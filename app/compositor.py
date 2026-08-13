"""Layer engine: background -> glow -> hero -> subject -> vignette -> arrow -> text.

Renders at 2x and downsamples, which is what keeps the arrow edges and cutout
shadows clean. The creator's face and every glyph are composited, never
generated, so identity and typography are exact on every run.
"""

from __future__ import annotations

import math

from PIL import Image, ImageDraw, ImageFilter

from . import cards
from .diagram import node_diagram
from .assets import load_image
from .shapes import (
    drop_shadow, hand_arrow, linear_gradient, radial_glow, rim_light, scrim, vignette,
)
from .styles import Style, get_style
from .tiles import tiled_backdrop
from .assets import load_font
from .text import layout_headline, paint_headline, underline

SCALE = 2
BASE_W, BASE_H = 1280, 720


def _apply_case(text: str, mode: str) -> str:
    if mode == "upper":
        return text.upper()
    if mode == "title":
        # Title-case without destroying ALL-CAPS product names.
        return " ".join(w if w.isupper() and len(w) > 1 else w.capitalize() for w in text.split())
    return text


def _fit(img: Image.Image, box: tuple[int, int, int, int], anchor: str) -> tuple[Image.Image, tuple[int, int]]:
    """Scale `img` to fit inside `box` (contain) and return it with a paste origin."""
    bx, by, bw, bh = box
    ratio = min(bw / img.width, bh / img.height)
    new_size = (max(1, int(img.width * ratio)), max(1, int(img.height * ratio)))
    resized = img.resize(new_size, Image.LANCZOS)

    if "left" in anchor:
        x = bx
    elif "right" in anchor:
        x = bx + bw - new_size[0]
    else:
        x = bx + (bw - new_size[0]) // 2

    if "top" in anchor:
        y = by
    elif "bottom" in anchor:
        y = by + bh - new_size[1]
    else:
        y = by + (bh - new_size[1]) // 2

    return resized, (x, y)


def _denorm(rect: tuple[float, float, float, float], w: int, h: int) -> tuple[int, int, int, int]:
    return (int(rect[0] * w), int(rect[1] * h), int(rect[2] * w), int(rect[3] * h))


CARD_WIDTHS = {"tweet": 0.42, "toast": 0.36, "stat": 0.34, "checklist": 0.34,
               "prompt": 0.44, "chat": 0.40, "terminal": 0.44}


def _render_card(spec: dict, w: int, style: Style) -> Image.Image | None:
    """Build whichever prop `spec["type"]` names, already drop-shadowed."""
    kind = spec.get("type")
    width = int(w * CARD_WIDTHS.get(kind, 0.40))
    scale = SCALE * 0.9
    accent = parse_color(spec.get("accent"))
    dark = bool(spec.get("dark", True))
    text = str(spec.get("text", ""))
    items = [str(i) for i in (spec.get("items") or [])]

    if kind == "tweet":
        built = cards.social_card(width, text or "Your post text here.",
                                  display_name=spec.get("name", "Your Name"),
                                  handle=spec.get("handle", "@yourhandle"),
                                  dark=dark, scale=scale,
                                  metrics=[str(m) for m in (spec.get("metrics") or [])],
                                  **({"accent": accent} if accent else {}))
    elif kind == "toast":
        built = cards.toast(width, text or "Payment received",
                            str(spec.get("sublabel") or "$0"), scale=scale,
                            **({"accent": accent} if accent else {}))
    elif kind == "stat":
        built = cards.stat_card(width, text or "$0", str(spec.get("sublabel") or "last 30 days"),
                                scale=scale, dark=dark,
                                **({"accent": accent} if accent else {}))
    elif kind == "checklist":
        built = cards.checklist_card(width, items, title=text, scale=scale)
    elif kind == "prompt":
        built = cards.prompt_card(width, text or "Describe a task or ask a question",
                                  scale=scale, dark=dark,
                                  **({"accent": accent} if accent else {}))
    elif kind == "chat":
        built = cards.chat_card(width, items or [text or "Hello"], scale=scale, dark=dark,
                                **({"accent": accent} if accent else {}))
    elif kind == "terminal":
        built = cards.terminal_card(width, items or [text or "$ run"], scale=scale,
                                    **({"accent": accent} if accent else {}))
    else:
        return None
    return cards.with_shadow(built)


def _luma(rgb: tuple[int, int, int]) -> float:
    r, g, b = (c / 255 for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def parse_color(value: str | tuple | None) -> tuple[int, int, int] | None:
    """Accept "#RRGGBB", "RRGGBB", or an (r, g, b) tuple."""
    if value is None or isinstance(value, tuple):
        return value
    text = str(value).strip().lstrip("#")
    if len(text) == 3:
        text = "".join(c * 2 for c in text)
    if len(text) != 6:
        raise ValueError(f"colour '{value}' is not a 3- or 6-digit hex value")
    try:
        return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
    except ValueError as exc:
        raise ValueError(f"colour '{value}' is not valid hex") from exc


def _place_subjects(canvas: Image.Image, refs: list[str | None], style: Style,
                    box_rect: tuple[float, float, float, float], anchor: str,
                    w: int, h: int, rotate: float = 0.0
                    ) -> tuple[tuple[int, int], tuple[int, int]] | None:
    """Composite one or more cutouts, splitting the box into overlapping columns.

    Liam's group shots (four people shoulder to shoulder) need the figures to
    overlap slightly, or the row reads as separate pasted stickers.

    Returns (origin, size) covering everything placed, so the studio can draw a
    selection box around it.
    """
    images = [load_image(r) if r else placeholder_subject() for r in refs]
    images = [im for im in images if im is not None]
    if not images:
        return None

    placed_boxes: list[tuple[int, int, int, int]] = []

    bx, by, bw, bh = box_rect
    n = len(images)
    if n > 1:
        # Widen the band for groups and overlap the columns by ~12%.
        bx = max(0.0, bx - 0.16)
        bw = min(1.0 - bx, bw + 0.32)
        col_w = bw / (n - (n - 1) * 0.12)

    for i, img in enumerate(images):
        if n == 1:
            box = _denorm((bx, by, bw, bh), w, h)
            fitted, origin = _fit(img, box, anchor)
        else:
            # Scale to the band's height rather than the column's width, or four
            # narrow columns shrink everyone to postage stamps.
            band_h = int(bh * h)
            ratio = band_h / img.height
            fitted = img.resize((max(1, int(img.width * ratio)), band_h), Image.LANCZOS)
            centre_x = (bx + i * col_w * 0.88 + col_w / 2) * w
            origin = (int(centre_x - fitted.width / 2), int((by + bh) * h - fitted.height))
        if rotate:
            before = fitted.size
            fitted = _rotate_layer(fitted, rotate)
            origin = (origin[0] - (fitted.width - before[0]) // 2,
                      origin[1] - (fitted.height - before[1]) // 2)
        placed = _pad_to(fitted, (w, h), origin)

        if style.subject_shadow:
            canvas.alpha_composite(drop_shadow(
                placed, (int(-10 * SCALE), int(16 * SCALE)), int(30 * SCALE),
                style.subject_shadow_opacity))
        if style.subject_rim:
            canvas.alpha_composite(
                rim_light(placed, style.subject_rim, style.subject_rim_width * SCALE, 0.85))
        canvas.alpha_composite(placed)
        placed_boxes.append((origin[0], origin[1], fitted.width, fitted.height))

    left = min(b[0] for b in placed_boxes)
    top = min(b[1] for b in placed_boxes)
    right = max(b[0] + b[2] for b in placed_boxes)
    bottom = max(b[1] + b[3] for b in placed_boxes)
    return ((left, top), (right - left, bottom - top))


def _place_icons(canvas: Image.Image, refs: list[str], style: Style, w: int, h: int) -> None:
    """Drop floating 3D logos into the preset's icon slots."""
    for ref, slot in zip(refs, style.icon_slots):
        icon = load_image(ref)
        if icon is None:
            continue
        size = int(slot[2] * w)
        box = (int(slot[0] * w), int(slot[1] * h), size, size)
        fitted, origin = _fit(icon, box, "center")
        placed = _pad_to(fitted, (w, h), origin)
        canvas.alpha_composite(drop_shadow(
            placed, (0, int(14 * SCALE)), int(24 * SCALE), 0.5))
        canvas.alpha_composite(placed)


def placeholder_subject(size: tuple[int, int] = (900, 1200)) -> Image.Image:
    """A neutral stand-in cutout so the service renders with no assets supplied.

    Deliberately a silhouette, not a face: the real input is a matted PNG of the
    actual creator. This exists to prove out placement, shadow and rim light.
    """
    w, h = size
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    body = (86, 96, 118, 255)
    head_r = w * 0.22
    cx = w * 0.5
    head_cy = h * 0.26

    draw.ellipse((cx - head_r, head_cy - head_r, cx + head_r, head_cy + head_r), fill=body)
    # Shoulders: a wide rounded slab that runs off the bottom edge.
    draw.rounded_rectangle(
        (cx - w * 0.42, head_cy + head_r * 0.72, cx + w * 0.42, h + h * 0.2),
        radius=int(w * 0.30), fill=body,
    )

    # Light from the upper left so the rim-light pass has something to sit on.
    shading = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shading)
    sdraw.ellipse((cx - head_r * 1.6, head_cy - head_r * 1.9, cx + head_r * 0.3, head_cy + head_r * 0.6),
                  fill=(255, 255, 255, 46))
    shading = shading.filter(ImageFilter.GaussianBlur(radius=w * 0.05))
    shading.putalpha(Image.composite(shading.getchannel("A"),
                                     Image.new("L", (w, h), 0),
                                     img.getchannel("A").point(lambda a: 255 if a > 8 else 0)))
    img.alpha_composite(shading)
    return img


def compose(
    *,
    headline: str,
    style_name: str = "saraev",
    palette: str | None = None,
    accent_words: list[str] | None = None,
    subject: str | None = None,
    subjects: list[str] | None = None,
    icons: list[str] | None = None,
    word_colors: dict[str, str] | None = None,
    labels: list[dict] | None = None,
    card: dict | None = None,
    diagram: dict | None = None,
    tile: dict | None = None,
    hero: str | None = None,
    background: str | None = None,
    arrow: bool = True,
    card_text: str | None = None,
    card_name: str = "Your Name",
    card_handle: str = "@yourhandle",
    toast_text: str | None = None,
    toast_amount: str | None = None,
    subject_side: str | None = None,
    text_position: str | None = None,
    overrides: dict | None = None,
    hidden: list[str] | None = None,
    only: list[str] | None = None,
    behind: list[str] | None = None,
    draw_art: bool = True,
    draw_vector: bool = True,
    width: int = BASE_W,
    height: int = BASE_H,
) -> tuple[Image.Image, list[dict]]:
    """Compose one thumbnail, returning it with a manifest of where things landed.

    The manifest is what makes direct manipulation possible: the studio draws
    interactive handles over the image using these boxes, so the browser never
    needs its own copy of the layout engine and cannot drift from what the
    server actually renders.

    `overrides` nudges elements away from their preset positions:
        {"subject": {"dx": 0.05, "dy": -0.02, "scale": 1.2},
         "headline": {"dx": 0, "dy": 0.1, "scale": 0.9},
         "arrow": {"from": [0.3, 0.4], "to": [0.5, 0.6]}}
    Offsets are deltas rather than absolutes so that switching style keeps the
    user's intent ("a bit left of wherever this preset puts it").

    `draw_art` and `draw_vector` split the render in two so an AI edit can touch
    the artwork without touching the typography: compose the plate with
    draw_vector=False, send that to a model, then compose again over the result
    with draw_art=False to lay exact text back on top.

    `hidden` drops elements by id — that is how deletion works.

    `only` renders just the named elements on transparency. Paired with
    `hidden`, it splits a frame into "everything except X" and "X alone", which
    is what lets the studio drag real pixels at 60fps instead of dragging an
    empty outline and waiting for a round trip.

    `behind` moves vector elements underneath the cutout — Nate's "4:30am",
    where huge numerals pass behind the presenter. The scrim follows the
    headline, since its whole job is to sit under it.
    """
    style: Style = get_style(style_name, palette)
    w, h = width * SCALE, height * SCALE
    ov = overrides or {}
    hide = set(hidden or [])
    solo = set(only or [])
    back = set(behind or [])
    manifest: list[dict] = []

    def want(elid: str) -> bool:
        return (elid in solo) if solo else (elid not in hide)

    def _norm_box(origin: tuple[int, int], size: tuple[int, int]) -> dict:
        return {"x": origin[0] / w, "y": origin[1] / h,
                "w": size[0] / w, "h": size[1] / h}

    def _shift(rect: tuple[float, float, float, float], key: str
               ) -> tuple[float, float, float, float]:
        """Apply this element's dx/dy/scale to a normalised rect."""
        o = ov.get(key) or {}
        x, y, bw, bh = rect
        scale = float(o.get("scale") or 1.0)
        if scale != 1.0:
            # Grow about the rect's centre so centred layouts stay centred.
            x -= bw * (scale - 1) / 2
            y -= bh * (scale - 1) / 2
            bw *= scale
            bh *= scale
        return (x + float(o.get("dx") or 0.0), y + float(o.get("dy") or 0.0), bw, bh)

    # --- background -------------------------------------------------------
    if not want("backdrop"):
        canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    elif background:
        plate = load_image(background)
        assert plate is not None
        plate, origin = _fit(plate, (0, 0, w, h), "center")
        canvas = Image.new("RGBA", (w, h), style.bg_bottom + (255,))
        # Cover rather than contain for a backplate: fill the frame, crop the rest.
        cover = min(plate.width / w, plate.height / h)
        if cover < 1:
            scale_up = max(w / plate.width, h / plate.height)
            plate = plate.resize((int(plate.width * scale_up) + 1, int(plate.height * scale_up) + 1),
                                 Image.LANCZOS)
        left = max(0, (plate.width - w) // 2)
        top = max(0, (plate.height - h) // 2)
        canvas.paste(plate.crop((left, top, left + w, top + h)), (0, 0))
        _ = origin
    elif draw_art:
        canvas = linear_gradient((w, h), style.bg_top, style.bg_bottom, style.bg_angle)
    else:
        # Vector-only pass with no plate supplied: transparent, nothing to cover.
        canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))

    # --- tiled backdrop ---------------------------------------------------
    if tile and draw_art and want("backdrop"):
        canvas.alpha_composite(tiled_backdrop(
            (w, h),
            tile.get("icons") or [],
            columns=int(tile.get("columns", 6)),
            opacity=float(tile.get("opacity", 0.5)),
            cross=bool(tile.get("cross", True)),
            cross_color=parse_color(tile.get("cross_color")) or (232, 62, 40),
            cross_every=int(tile.get("cross_every", 1)),
            angle=float(tile.get("angle", 0.0)),
            blur=float(tile.get("blur", 0.0)) * SCALE,
            accent=(parse_color(tile.get("accent"))
                    or style.accent_fill or style.accent_color or (217, 119, 87)),
        ))

    # --- backlight --------------------------------------------------------
    if (draw_art and want("backdrop") and not background
            and style.glow_color and style.glow_intensity > 0):
        gc = (style.glow_center[0] * w, style.glow_center[1] * h)
        canvas.alpha_composite(
            radial_glow((w, h), gc, style.glow_radius * w * 0.5, style.glow_color, style.glow_intensity)
        )

    # --- hero visual / rendered prop --------------------------------------
    hero_layer: Image.Image | None = None
    card_spec = dict(card or {})
    if not card_spec and card_text:
        card_spec = {"type": "tweet", "text": card_text,
                     "name": card_name, "handle": card_handle}
    elif not card_spec and toast_text and toast_amount:
        card_spec = {"type": "toast", "text": toast_text, "sublabel": toast_amount}

    if not draw_art or not want("hero"):
        hero_layer = None
    elif hero:
        hero_img = load_image(hero)
        if hero_img is not None:
            hero_layer = hero_img
    elif card_spec.get("type"):
        hero_layer = _render_card(card_spec, w, style)
    elif diagram and diagram.get("nodes"):
        light_plate = _luma(style.bg_top) > 0.6
        hero_layer = node_diagram(
            # Size to the box it will occupy. A frame adds bezel and glow
            # padding on both sides — about 27% — so the inner diagram has to
            # be that much narrower or _fit shrinks the whole thing to fit.
            max(200, int(style.diagram_box[2] * w
                         / (1.27 if diagram.get("frame") else 1.0))),
            diagram["nodes"],
            center_icon=diagram.get("center_icon"),
            center_label=diagram.get("center_label"),
            accent=(parse_color(diagram.get("accent"))
                    or style.accent_fill or style.accent_color or (217, 119, 87)),
            text_color=style.text_color,
            dark=not light_plate,
            scale=SCALE * 0.9,
            layout=str(diagram.get("layout", "hub")),
            mark=str(diagram.get("mark", "tile")),
            frame=diagram.get("frame"),
            frame_glow=parse_color(diagram.get("frame_glow")),
            screen=parse_color(diagram.get("screen")) or (255, 255, 255),
            line_color=parse_color(diagram.get("line_color")),
        )

    if hero_layer is not None:
        base_box = style.diagram_box if (diagram and diagram.get("nodes") and not hero
                                         and not card_text and not toast_text) else style.hero_box
        box = _denorm(_shift(base_box, "hero"), w, h)
        fitted, origin = _fit(hero_layer, box, "center")
        hero_rot = float((ov.get("hero") or {}).get("rotate", 0.0))
        if hero_rot:
            before = fitted.size
            fitted = _rotate_layer(fitted, hero_rot)
            origin = (origin[0] - (fitted.width - before[0]) // 2,
                      origin[1] - (fitted.height - before[1]) // 2)
        if not card_spec.get("type"):
            canvas.alpha_composite(drop_shadow(
                _pad_to(fitted, (w, h), origin), (0, int(18 * SCALE)), int(26 * SCALE), 0.45))
        canvas.alpha_composite(fitted, origin)
        manifest.append({"id": "hero", "type": "image", "label": "Hero / card",
                         **_norm_box(origin, fitted.size)})

    # --- vector layers -----------------------------------------------------
    # Arrow, callouts and headline are painted through one function so they can
    # run either before the cutout (Nate's "4:30am" numerals passing behind the
    # presenter) or after it, without duplicating the drawing code.
    if text_position is None and diagram and diagram.get("nodes"):
        # A diagram owns the centre, so the headline goes to the top band.
        text_position = "top"

    scrim_dir = style.scrim
    if text_position == "top":
        scrim_dir = "top"
    elif text_position == "bottom":
        scrim_dir = "bottom"

    painted: set[str] = set()

    def paint_vectors(phase: str) -> None:
        """phase is "behind" (under the cutout) or "front" (over it)."""
        if not draw_vector:
            return
        in_phase = lambda elid: (elid in back) == (phase == "behind")

        # The scrim exists to sit under the headline, so it follows it.
        if (in_phase("headline") and want("backdrop") and scrim_dir
                and style.scrim_opacity > 0 and "scrim" not in painted):
            painted.add("scrim")
            canvas.alpha_composite(scrim((w, h), scrim_dir, style.scrim_opacity))

        if arrow and want("arrow") and in_phase("arrow") and "arrow" not in painted:
            painted.add("arrow")
            a_ov = ov.get("arrow") or {}
            n_from = tuple(a_ov.get("from") or style.arrow_from)
            n_to = tuple(a_ov.get("to") or style.arrow_to)
            canvas.alpha_composite(hand_arrow(
                (w, h), (n_from[0] * w, n_from[1] * h), (n_to[0] * w, n_to[1] * h),
                style.arrow_color, width=style.arrow_width * SCALE,
                bow=style.arrow_bow, head_len=46.0 * SCALE,
            ))
            # Endpoints rather than a box: an arrow is dragged by its tips.
            manifest.append({"id": "arrow", "type": "arrow", "label": "Arrow",
                             "from": [n_from[0], n_from[1]], "to": [n_to[0], n_to[1]],
                             "x": min(n_from[0], n_to[0]), "y": min(n_from[1], n_to[1]),
                             "w": abs(n_to[0] - n_from[0]), "h": abs(n_to[1] - n_from[1])})

        # Free-standing callouts: small text anywhere, each able to point at
        # something with its own arrow.
        for i, lab in enumerate(labels or []):
            elid = f"label{i}"
            text = str(lab.get("text", "")).strip()
            if (not text or not want(elid) or not in_phase(elid) or elid in painted):
                continue
            painted.add(elid)
            lx = float(lab.get("x", 0.1)) + float((ov.get(elid) or {}).get("dx", 0.0))
            ly = float(lab.get("y", 0.1)) + float((ov.get(elid) or {}).get("dy", 0.0))
            lscale = float((ov.get(elid) or {}).get("scale", 1.0))
            size = max(10, int(float(lab.get("size", 0.055)) * h * lscale))
            colour = parse_color(lab.get("color")) or style.text_color
            lfont = load_font(style.font_family, size, style.font_weight, style.font_width)

            lrot = float((ov.get(elid) or {}).get("rotate", 0.0))
            ltarget = Image.new("RGBA", canvas.size, (0, 0, 0, 0)) if lrot else canvas
            ldraw = ImageDraw.Draw(ltarget)
            tw = ldraw.textlength(text, font=lfont)
            ox, oy = lx * w, ly * h

            if lab.get("shadow", True):
                shade = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
                ImageDraw.Draw(shade).text((ox, oy), text, font=lfont, fill=(0, 0, 0, 150))
                ltarget.alpha_composite(shade.filter(ImageFilter.GaussianBlur(radius=int(8 * SCALE))))
            ldraw.text((ox, oy), text, font=lfont, fill=colour + (255,))

            arrow_target = lab.get("arrow_to")
            if arrow_target:
                ltarget.alpha_composite(hand_arrow(
                    (w, h), (ox + tw / 2, oy + size * 1.25),
                    (float(arrow_target[0]) * w, float(arrow_target[1]) * h),
                    parse_color(lab.get("arrow_color")) or colour,
                    width=max(3, int(5 * SCALE)), bow=float(lab.get("bow", 0.22)),
                    head_len=30.0 * SCALE,
                ))

            lx0, ly0, lx1, ly1 = ox, oy, ox + tw, oy + size * 1.25
            if lrot:
                canvas.alpha_composite(ltarget.rotate(
                    lrot, resample=Image.BICUBIC,
                    center=((lx0 + lx1) / 2, (ly0 + ly1) / 2)))
                lx0, ly0, lx1, ly1 = _rotated_bounds(lx0, ly0, lx1, ly1, lrot)

            manifest.append({
                "id": elid, "type": "label", "label": text[:18],
                "x": lx0 / w, "y": ly0 / h,
                "w": (lx1 - lx0) / w, "h": (ly1 - ly0) / h,
                "font_px": size / SCALE,
            })

        if not want("headline") or not in_phase("headline") or "headline" in painted:
            return
        painted.add("headline")

        copy = _apply_case(headline, style.text_case)
        text_rect = style.text_box
        if text_position == "top":
            text_rect = (text_rect[0], 0.06, text_rect[2], text_rect[3])
        elif text_position == "bottom":
            text_rect = (text_rect[0], 1.0 - text_rect[3] - 0.06, text_rect[2], text_rect[3])
        text_rect = _shift(text_rect, "headline")
        box = _denorm(text_rect, w, h)
        pill_pad_x = int(style.accent_pad[0] * SCALE)
        layout = layout_headline(
            copy, box, style.font_family, style.font_weight,
            max_lines=style.max_lines, line_height=style.line_height,
            align=style.text_align, valign=style.text_valign,
            accent_words=set(accent_words or []), tracking=style.tracking,
            accent_pad_x=pill_pad_x if style.accent_fill else 0.0,
            font_width=style.font_width,
        )
        head_rot = float((ov.get("headline") or {}).get("rotate", 0.0))
        target = Image.new("RGBA", canvas.size, (0, 0, 0, 0)) if head_rot else canvas

        if style.underline_color:
            underline(target, layout, style.underline_color, style.font_family,
                      style.font_weight,
                      width=int((14 if style.underline_swash else 8) * SCALE),
                      gap=int(7 * SCALE), swash=style.underline_swash)
        paint_headline(
            target, layout, style.font_family, style.font_weight,
            color=style.text_color, accent_color=style.accent_color,
            accent_fill=style.accent_fill, shadow=style.shadow,
            shadow_opacity=style.shadow_opacity,
            shadow_blur=int(style.shadow_blur * SCALE / 2),
            shadow_offset=(0, int(6 * SCALE)),
            stroke_width=style.stroke_width * SCALE // 2,
            stroke_color=style.stroke_color,
            pill_pad=(pill_pad_x, int(style.accent_pad[1] * SCALE)),
            pill_radius=(style.accent_radius * SCALE if style.accent_radius is not None else None),
            word_colors={k: parse_color(v) for k, v in (word_colors or {}).items()},
        )

        if layout.runs:
            # The painted ink, not the layout box — a selection rectangle around
            # empty space above the text would feel broken to drag.
            left = min(r.x for r in layout.runs)
            right = max(r.x + r.width for r in layout.runs)
            top = min(r.y for r in layout.runs)
            bottom = max(r.y for r in layout.runs) + layout.size

            if head_rot:
                # Spin about the text's own centre, not the canvas centre, or a
                # headline in the corner swings out of frame.
                canvas.alpha_composite(target.rotate(
                    head_rot, resample=Image.BICUBIC,
                    center=((left + right) / 2, (top + bottom) / 2)))
                left, top, right, bottom = _rotated_bounds(
                    left, top, right, bottom, head_rot)
            manifest.append({
                "id": "headline", "type": "text", "label": "Headline",
                "x": left / w, "y": top / h,
                "w": (right - left) / w, "h": (bottom - top) / h,
                "font_px": layout.size / SCALE,
                "align": style.text_align,
                "color": "#%02x%02x%02x" % style.text_color,
            })

    paint_vectors("behind")

    # --- subject cutout ---------------------------------------------------
    refs: list[str | None] = list(subjects) if subjects else [subject]
    box_rect = style.subject_box
    anchor = style.subject_anchor
    if subject_side is None and diagram and diagram.get("nodes"):
        # A diagram occupies the left half; centring the subject would bury it.
        subject_side = "right"
    if subject_side == "left":
        box_rect = (0.02, box_rect[1], box_rect[2], box_rect[3])
        anchor = anchor.replace("right", "left")
    elif subject_side == "right":
        box_rect = (1.0 - box_rect[2] - 0.02, box_rect[1], box_rect[2], box_rect[3])
        anchor = anchor.replace("left", "right")

    subject_bbox = _place_subjects(
        canvas, refs, style, _shift(box_rect, "subject"), anchor, w, h,
        rotate=float((ov.get("subject") or {}).get("rotate", 0.0)),
    ) if (draw_art and want("subject")) else None
    if subject_bbox:
        manifest.append({"id": "subject", "type": "image", "label": "Photo",
                         **_norm_box(subject_bbox[0], subject_bbox[1])})

    if icons and draw_art and want("icons"):
        _place_icons(canvas, icons, style, w, h)

    # --- vignette ---------------------------------------------------------
    if draw_art and want("backdrop") and not background and style.vignette_strength > 0:
        canvas.alpha_composite(vignette((w, h), style.vignette_strength))

    paint_vectors("front")

    return _finish(canvas, width, height, bool(solo)), manifest

    copy = _apply_case(headline, style.text_case)
    text_rect = style.text_box
    if text_position is None and diagram and diagram.get("nodes"):
        # Same reasoning as the subject: the diagram owns the centre, so the
        # headline goes to the top band rather than sitting on top of it.
        text_position = "top"
    if text_position == "top":
        text_rect = (text_rect[0], 0.06, text_rect[2], text_rect[3])
    elif text_position == "bottom":
        text_rect = (text_rect[0], 1.0 - text_rect[3] - 0.06, text_rect[2], text_rect[3])
    text_rect = _shift(text_rect, "headline")
    box = _denorm(text_rect, w, h)
    pill_pad_x = int(style.accent_pad[0] * SCALE)
    layout = layout_headline(
        copy, box, style.font_family, style.font_weight,
        max_lines=style.max_lines,
        line_height=style.line_height,
        align=style.text_align,
        valign=style.text_valign,
        accent_words=set(accent_words or []),
        tracking=style.tracking,
        accent_pad_x=pill_pad_x if style.accent_fill else 0.0,
        font_width=style.font_width,
    )
    if style.underline_color:
        underline(canvas, layout, style.underline_color, style.font_family, style.font_weight,
                  width=int((14 if style.underline_swash else 8) * SCALE),
                  gap=int(7 * SCALE), swash=style.underline_swash)
    paint_headline(
        canvas, layout, style.font_family, style.font_weight,
        color=style.text_color,
        accent_color=style.accent_color,
        accent_fill=style.accent_fill,
        shadow=style.shadow,
        shadow_opacity=style.shadow_opacity,
        shadow_blur=int(style.shadow_blur * SCALE / 2),
        shadow_offset=(0, int(6 * SCALE)),
        stroke_width=style.stroke_width * SCALE // 2,
        stroke_color=style.stroke_color,
        pill_pad=(pill_pad_x, int(style.accent_pad[1] * SCALE)),
        pill_radius=(style.accent_radius * SCALE if style.accent_radius is not None else None),
        word_colors={k: parse_color(v) for k, v in (word_colors or {}).items()},
    )

    if layout.runs:
        # The painted ink, not the layout box — a selection rectangle around
        # empty space above the text would feel broken to drag.
        left = min(r.x for r in layout.runs)
        right = max(r.x + r.width for r in layout.runs)
        top = min(r.y for r in layout.runs)
        bottom = max(r.y for r in layout.runs) + layout.size
        manifest.append({
            "id": "headline", "type": "text", "label": "Headline",
            "x": left / w, "y": top / h,
            "w": (right - left) / w, "h": (bottom - top) / h,
            "font_px": layout.size / SCALE,
            "align": style.text_align,
            "color": "#%02x%02x%02x" % style.text_color,
        })

    return _finish(canvas, width, height, bool(solo)), manifest


def _finish(canvas: Image.Image, width: int, height: int, keep_alpha: bool) -> Image.Image:
    """Downsample to output size. Isolated layers keep alpha so they can be
    composited over the backdrop in the browser."""
    out = canvas.resize((width, height), Image.LANCZOS)
    return out if keep_alpha else out.convert("RGB")


def render(**kwargs) -> Image.Image:
    """Compose and return just the image — the shape most callers want."""
    return compose(**kwargs)[0]


def _rotated_bounds(x0: float, y0: float, x1: float, y1: float,
                    degrees: float) -> tuple[float, float, float, float]:
    """Axis-aligned bounds of a rectangle after rotating about its own centre.

    The selection box has to grow with the rotation or the handles stop lining
    up with the pixels the user can see.
    """
    rad = math.radians(-degrees)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    spun = [((px - cx) * math.cos(rad) - (py - cy) * math.sin(rad) + cx,
             (px - cx) * math.sin(rad) + (py - cy) * math.cos(rad) + cy)
            for px, py in corners]
    xs = [p[0] for p in spun]
    ys = [p[1] for p in spun]
    return min(xs), min(ys), max(xs), max(ys)


def _rotate_layer(layer: Image.Image, degrees: float) -> Image.Image:
    """Rotate about the layer's own centre, expanding so corners aren't clipped."""
    if not degrees:
        return layer
    return layer.rotate(degrees, resample=Image.BICUBIC, expand=True)


def _pad_to(layer: Image.Image, size: tuple[int, int], origin: tuple[int, int]) -> Image.Image:
    """Place a smaller layer on a full-canvas transparent sheet."""
    sheet = Image.new("RGBA", size, (0, 0, 0, 0))
    sheet.paste(layer, origin)
    return sheet


def legibility_report(img: Image.Image, style_name: str = "saraev", feed_width: int = 168,
                      text_position: str | None = None, has_diagram: bool = False) -> dict:
    """Check the headline still reads at YouTube feed size.

    Downsamples to the width a thumbnail actually occupies in a browsing feed,
    then measures contrast *inside the headline box only*. Measuring the whole
    frame just reports how busy the artwork is — a flat background would fail a
    perfectly legible title, and a noisy one would pass an illegible one.
    """
    small = img.convert("L").resize(
        (feed_width, int(feed_width * img.height / img.width)), Image.LANCZOS
    )

    try:
        box = get_style(style_name).text_box
    except ValueError:
        box = (0.05, 0.07, 0.60, 0.32)

    # Must mirror render()'s override, or we measure an empty strip.
    if text_position is None and has_diagram:
        text_position = "top"
    if text_position == "top":
        box = (box[0], 0.06, box[2], box[3])
    elif text_position == "bottom":
        box = (box[0], 1.0 - box[3] - 0.06, box[2], box[3])

    x0, y0 = int(box[0] * small.width), int(box[1] * small.height)
    x1 = min(small.width, x0 + max(2, int(box[2] * small.width)))
    y1 = min(small.height, y0 + max(2, int(box[3] * small.height)))
    region = small.crop((x0, y0, x1, y1))

    # Histograms keep this O(256) in Python instead of O(pixels).
    hist = region.histogram()
    n = max(1, region.width * region.height)
    mean = sum(i * c for i, c in enumerate(hist)) / n
    stdev = math.sqrt(sum(c * (i - mean) ** 2 for i, c in enumerate(hist)) / n)

    edge_hist = region.filter(ImageFilter.FIND_EDGES).histogram()
    edge_energy = sum(i * c for i, c in enumerate(edge_hist)) / n

    return {
        "feed_width": feed_width,
        "headline_contrast": round(stdev, 2),
        "edge_energy": round(edge_energy, 2),
        "verdict": "ok" if stdev > 40 and edge_energy > 10 else "weak",
    }
