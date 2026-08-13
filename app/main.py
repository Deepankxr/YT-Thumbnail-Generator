"""FastAPI surface for the thumbnail generation service.

Endpoints
    GET  /health      -> liveness + version
    GET  /styles      -> presets and their palettes (handy for the agent prompt)
    POST /generate    -> thumbnail bytes. Response shape controlled by `output`:
                           - "binary" (default): raw PNG, so an n8n HTTP Request
                             node with "Response Format: File" captures it
                             straight into $binary.
                           - "base64": JSON { filename, mimeType, data, qa }.

Auth: if env THUMB_API_KEY is set, requests must send it as `x-api-key`.
"""

from __future__ import annotations

import base64
import io
import os
import re

from fastapi import FastAPI, Header, HTTPException, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse

from PIL import Image

from . import __version__
from .analyze import VISION_MODELS, analyze, fetch_thumbnail, video_id
from .assets import FONT_DIR, FONT_FILES
from .avatar import POSES, generate_avatar
from .assets import load_image
from .compositor import compose, legibility_report
from .openrouter import OpenRouterError, edit_image, list_models
from .preview import PREVIEW_HTML
from .hero import HeroUnavailable, generate_hero
from .schema import AnalyzeRequest, AvatarRequest, EditRequest, ThumbnailRequest
from .styles import STYLES, WORD_PALETTE

MIME = "image/png"
MIME_BY_FORMAT = {"png": "image/png", "jpeg": "image/jpeg"}
API_KEY = os.environ.get("THUMB_API_KEY", "").strip()

app = FastAPI(title="Thumbnail Service", version=__version__)


def _check_key(x_api_key: str | None):
    if API_KEY and (x_api_key or "").strip() != API_KEY:
        raise HTTPException(status_code=401, detail="invalid or missing x-api-key")


def _filename(req: ThumbnailRequest) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", req.headline.lower()).strip("-")[:48] or "thumbnail"
    return f"{slug}-{req.style}.png"


def _accent_kind(style) -> str:
    """How this style emphasises accent words — surfaced so the calling agent
    can pick sensible copy (a plate wants one short word, not a clause)."""
    if style.accent_fill:
        return "plate" if style.accent_radius == 0 else "pill"
    if style.underline_color:
        return "swash" if style.underline_swash else "underline"
    return "none"


@app.get("/fonts/{family}", include_in_schema=False)
def font(family: str):
    """Serve a bundled TTF so the studio's inline text editor uses the same
    typeface the renderer does — otherwise editing shows one font and the
    render comes back in another."""
    filename = FONT_FILES.get(family.lower())
    if not filename:
        raise HTTPException(status_code=404, detail=f"unknown font '{family}'")
    return FileResponse(os.path.join(FONT_DIR, filename), media_type="font/ttf",
                        headers={"Cache-Control": "public, max-age=31536000"})


@app.get("/", include_in_schema=False)
def root():
    """Opening the bare host should land on the studio, not a 404."""
    return RedirectResponse(url="/preview")


@app.get("/preview", response_class=HTMLResponse)
def preview():
    """Browser UI for editing thumbnails. Unauthenticated by design: it is a
    local design tool, and the endpoints it calls enforce the key themselves."""
    return PREVIEW_HTML


@app.get("/health")
def health():
    return {"status": "ok", "version": __version__}


@app.get("/styles")
def styles():
    return {
        "styles": [
            {
                "name": s.name,
                "description": s.description,
                "palettes": sorted(s.palettes.keys()),
                "font": f"{s.font_family} {s.font_weight}",
                "accent": _accent_kind(s),
            }
            for s in STYLES.values()
        ]
    }


@app.get("/palette")
def palette():
    """Curated word-colour swatches, grouped. Shared by the studio and any
    caller picking colours programmatically, so both stay on the same set."""
    return {
        "groups": [
            {"name": group, "swatches": [{"name": n, "hex": h} for n, h in swatches]}
            for group, swatches in WORD_PALETTE.items()
        ],
        "accents": {s.name: "#%02x%02x%02x" % s.accent_fill
                    for s in STYLES.values() if s.accent_fill},
    }


@app.get("/cards")
def card_types():
    """Prop types the renderer can draw, with the fields each one uses."""
    return {"cards": [
        {"type": "tweet", "label": "Social post",
         "fields": ["text", "name", "handle", "metrics"],
         "note": "Avatar, name, body and optional engagement counts."},
        {"type": "toast", "label": "Notification",
         "fields": ["text", "sublabel"],
         "note": 'Pill with an icon, e.g. "Payment received / $17,532".'},
        {"type": "stat", "label": "Stat + chart",
         "fields": ["text", "sublabel"],
         "note": 'A big figure over a rising sparkline, e.g. "$45,208 / last 30 days".'},
        {"type": "checklist", "label": "Checklist note",
         "fields": ["text", "items"],
         "note": "Sticky note of ticked-off tasks."},
        {"type": "prompt", "label": "Prompt input",
         "fields": ["text"],
         "note": 'An empty input bar, e.g. "Describe a task or ask a question".'},
        {"type": "chat", "label": "Chat bubbles",
         "fields": ["items"],
         "note": "Alternating messages; every second line is the reply."},
        {"type": "terminal", "label": "Terminal",
         "fields": ["items"],
         "note": "Dark window of output; lines starting $ > or a tick are highlighted."},
    ]}


@app.get("/edit/models")
def edit_models():
    """Image-editing models available on OpenRouter. No key needed — the list is
    public, so the picker can populate before the user has pasted anything."""
    try:
        return {"models": list_models()}
    except OpenRouterError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/analyze/models")
def analyze_models():
    """Vision models offered for reading a reference thumbnail."""
    return {"models": [{"id": i, "label": l, "note": n} for i, l, n in VISION_MODELS]}


@app.get("/avatar/poses")
def avatar_poses():
    """Poses the avatar generator understands."""
    return {"poses": [{"id": k, "description": v} for k, v in POSES.items()]}


@app.post("/avatar")
def avatar(
    req: AvatarRequest,
    x_api_key: str | None = Header(default=None),
    x_openrouter_key: str | None = Header(default=None),
):
    """Generate a presenter cutout from a reference photo, matted and trimmed.

    A real photograph beats this on likeness, cost and consistency — generated
    faces drift between runs, so a channel built on them slowly stops looking
    like one person. Use it for poses you have not shot, or for a deliberately
    stylised look.
    """
    _check_key(x_api_key)
    key = (x_openrouter_key or "").strip()
    if not key:
        raise HTTPException(
            status_code=401,
            detail="Missing x-openrouter-key header. Avatar generation bills to "
                   "your own OpenRouter key; this service never stores it.")

    if req.pose not in POSES and not req.extra:
        raise HTTPException(
            status_code=422,
            detail=f"unknown pose '{req.pose}'; choose one of {sorted(POSES)} "
                   "or supply `extra` to describe your own")

    try:
        ref = load_image(req.reference)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"could not read the reference: {exc}") from exc
    if ref is None:
        raise HTTPException(status_code=422, detail="no reference image supplied")

    buf = io.BytesIO()
    ref.convert("RGB").save(buf, format="PNG")
    ref_b64 = base64.b64encode(buf.getvalue()).decode()

    try:
        data, report = generate_avatar(ref_b64, key, pose=req.pose, model=req.model,
                                       extra=req.extra, height=req.height)
    except OpenRouterError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {"data": data, "mimeType": "image/png", "report": report}


@app.post("/analyze")
def analyze_url(
    req: AnalyzeRequest,
    x_api_key: str | None = Header(default=None),
    x_openrouter_key: str | None = Header(default=None),
):
    """Read a reference thumbnail and return a spec that approximates its design.

    What comes back is a starting point, not a copy: the renderer has no access
    to the original's photography or artwork, so the transferable part is the
    structure. `subject` is deliberately never set — the caller supplies their
    own cutout.
    """
    _check_key(x_api_key)

    key = (x_openrouter_key or "").strip()
    if not key:
        raise HTTPException(
            status_code=401,
            detail="Missing x-openrouter-key header. Analysis bills to your own "
                   "OpenRouter key; this service never stores it.")

    try:
        image_b64, source = fetch_thumbnail(req.url)
        spec, warnings, notes = analyze(image_b64, key, req.model)
    except OpenRouterError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    # Fail here rather than letting a bad spec surface as a render error later.
    try:
        ThumbnailRequest(**spec)
    except Exception as exc:
        raise HTTPException(status_code=502,
                            detail=f"model returned a spec the renderer rejects: {exc}") from exc

    return {
        "spec": spec,
        "warnings": warnings,
        "notes": notes,
        "reference": {"url": source, "video_id": video_id(req.url),
                      "data": image_b64 if req.include_reference else None},
        "model": req.model,
    }


@app.post("/edit")
def edit(
    req: EditRequest,
    x_api_key: str | None = Header(default=None),
    x_openrouter_key: str | None = Header(default=None),
):
    """Edit the artwork with a model, then lay the exact typography back on top.

    Three passes: compose the plate without the vector layer, send that to
    OpenRouter, then compose the vector layer over whatever comes back. The
    model never touches a glyph, so the headline cannot come back mangled and
    fixing copy afterwards is still free.

    The OpenRouter key comes from the `x-openrouter-key` header and is used for
    this request only — never logged, never stored.
    """
    _check_key(x_api_key)

    key = (x_openrouter_key or "").strip()
    if not key:
        raise HTTPException(
            status_code=401,
            detail="Missing x-openrouter-key header. Editing bills to your own "
                   "OpenRouter key; this service never stores it.")

    spec = req.spec
    common = dict(
        headline=spec.headline, style_name=spec.style, palette=spec.palette,
        accent_words=spec.accent_words, word_colors=spec.word_colors,
        labels=[l.model_dump() for l in spec.labels],
        arrow=spec.arrow, subject_side=spec.subject_side,
        text_position=spec.text_position,
        overrides={k: v.model_dump(by_alias=True, exclude_none=True)
                   for k, v in spec.overrides.items()},
        width=spec.width, height=spec.height,
    )

    # Edit the backdrop alone by default. Sending the whole composite back
    # bakes the cutout and props into pixels, which is exactly what left the
    # studio unable to select anything after an edit.
    art_ids = ["subject", "hero", "icons"]
    vector_ids = ["headline", "arrow"] + [f"label{i}" for i in range(len(spec.labels))]
    hidden = list(spec.hidden) + vector_ids + ([] if req.include_subject else art_ids)

    try:
        plate, _ = compose(
            subject=spec.subject, subjects=spec.subjects, icons=spec.icons,
            hero=spec.hero, background=spec.background,
            diagram=spec.diagram.model_dump() if spec.diagram else None,
            tile=spec.tile.model_dump() if spec.tile else None,
            card=spec.card.model_dump() if spec.card else None,
            card_text=spec.card_text, card_name=spec.card_name,
            card_handle=spec.card_handle, toast_text=spec.toast_text,
            toast_amount=spec.toast_amount,
            hidden=hidden, draw_vector=False, **common,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    buf = io.BytesIO()
    plate.save(buf, format="PNG")
    plate_b64 = base64.b64encode(buf.getvalue()).decode()

    try:
        edited_b64 = edit_image(plate_b64, req.instruction, req.model, key)
    except OpenRouterError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    # Compose the full frame over the edited backdrop so the caller sees the
    # finished thumbnail, and hand back the backdrop so the studio can keep
    # rendering over it with everything still editable.
    layout: list[dict] = []
    if req.redraw_text:
        try:
            img, layout = compose(
                background=edited_b64,
                subject=spec.subject, subjects=spec.subjects, icons=spec.icons,
                hero=spec.hero,
                diagram=spec.diagram.model_dump() if spec.diagram else None,
                card=spec.card.model_dump() if spec.card else None,
            card_text=spec.card_text, card_name=spec.card_name,
                card_handle=spec.card_handle, toast_text=spec.toast_text,
                toast_amount=spec.toast_amount,
                hidden=list(spec.hidden), behind=spec.behind, **common,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        data = buf.getvalue()
    else:
        data = base64.b64decode(edited_b64)
        img = Image.open(io.BytesIO(data)).convert("RGB")

    qa = legibility_report(img, spec.style, text_position=spec.text_position) if req.include_qa else None
    filename = _filename(spec).replace(".png", "-edited.png")

    if req.output == "base64":
        return JSONResponse({"filename": filename, "mimeType": MIME,
                             "data": base64.b64encode(data).decode(),
                             "backdrop": edited_b64, "layout": layout,
                             "qa": qa, "model": req.model})

    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    if qa:
        headers["x-qa-verdict"] = qa["verdict"]
    return Response(content=data, media_type=MIME, headers=headers)


@app.post("/generate")
def generate(req: ThumbnailRequest, x_api_key: str | None = Header(default=None)):
    _check_key(x_api_key)

    hero = req.hero
    if not hero and req.hero_prompt:
        try:
            hero = generate_hero(req.hero_prompt)
        except HeroUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"hero generation failed: {exc}") from exc

    try:
        img, layout = compose(
            headline=req.headline,
            style_name=req.style,
            palette=req.palette,
            accent_words=req.accent_words,
            subject=req.subject,
            subjects=req.subjects,
            icons=req.icons,
            word_colors=req.word_colors,
            labels=[l.model_dump() for l in req.labels],
            diagram=req.diagram.model_dump() if req.diagram else None,
            tile=req.tile.model_dump() if req.tile else None,
            hero=hero,
            background=req.background,
            arrow=req.arrow,
            card=req.card.model_dump() if req.card else None,
            card_text=req.card_text,
            card_name=req.card_name,
            card_handle=req.card_handle,
            toast_text=req.toast_text,
            toast_amount=req.toast_amount,
            subject_side=req.subject_side,
            text_position=req.text_position,
            overrides={k: v.model_dump(by_alias=True, exclude_none=True)
                       for k, v in req.overrides.items()},
            hidden=req.hidden,
            only=req.only,
            behind=req.behind,
            width=req.width,
            height=req.height,
        )
    except ValueError as exc:
        # Bad palette / style / asset ref is the caller's problem, not a 500.
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"render failed: {exc}") from exc

    buf = io.BytesIO()
    # optimize=True costs ~70ms to save ~4% — a bad trade for an interactive
    # canvas, and not worth it for the final file either.
    fmt = "png" if req.only else req.format
    if fmt == "jpeg":
        img.save(buf, format="JPEG", quality=88)
    else:
        img.save(buf, format="PNG")
    data = buf.getvalue()
    mime = MIME_BY_FORMAT[fmt]

    qa = (legibility_report(img, req.style, text_position=req.text_position,
                            has_diagram=bool(req.diagram and req.diagram.nodes))
          if req.include_qa else None)
    filename = _filename(req)
    if fmt == "jpeg":
        filename = filename.rsplit(".", 1)[0] + ".jpg"

    if req.output == "base64":
        return JSONResponse({
            "filename": filename,
            "mimeType": mime,
            "data": base64.b64encode(data).decode(),
            "qa": qa,
            "layout": layout if req.include_layout else None,
        })

    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    if qa:
        headers["x-qa-verdict"] = qa["verdict"]
        headers["x-qa-contrast"] = str(qa["headline_contrast"])
    return Response(content=data, media_type=mime, headers=headers)
