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
from fastapi.responses import JSONResponse

from . import __version__
from .compositor import legibility_report, render
from .hero import HeroUnavailable, generate_hero
from .schema import ThumbnailRequest
from .styles import STYLES

MIME = "image/png"
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
        img = render(
            headline=req.headline,
            style_name=req.style,
            palette=req.palette,
            accent_words=req.accent_words,
            subject=req.subject,
            subjects=req.subjects,
            icons=req.icons,
            word_colors=req.word_colors,
            hero=hero,
            background=req.background,
            arrow=req.arrow,
            card_text=req.card_text,
            card_name=req.card_name,
            card_handle=req.card_handle,
            toast_text=req.toast_text,
            toast_amount=req.toast_amount,
            subject_side=req.subject_side,
            text_position=req.text_position,
            width=req.width,
            height=req.height,
        )
    except ValueError as exc:
        # Bad palette / style / asset ref is the caller's problem, not a 500.
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"render failed: {exc}") from exc

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    data = buf.getvalue()

    qa = legibility_report(img, req.style, text_position=req.text_position) if req.include_qa else None
    filename = _filename(req)

    if req.output == "base64":
        return JSONResponse({
            "filename": filename,
            "mimeType": MIME,
            "data": base64.b64encode(data).decode(),
            "qa": qa,
        })

    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    if qa:
        headers["x-qa-verdict"] = qa["verdict"]
        headers["x-qa-contrast"] = str(qa["headline_contrast"])
    return Response(content=data, media_type=MIME, headers=headers)
