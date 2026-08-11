"""Layer engine: background -> glow -> hero -> subject -> vignette -> arrow -> text.

Renders at 2x and downsamples, which is what keeps the arrow edges and cutout
shadows clean. The creator's face and every glyph are composited, never
generated, so identity and typography are exact on every run.
"""

from __future__ import annotations

import math

from PIL import Image, ImageDraw, ImageFilter

from . import cards
from .assets import load_image
from .shapes import (
    drop_shadow, hand_arrow, linear_gradient, radial_glow, rim_light, scrim, vignette,
)
from .styles import Style, get_style
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
                    w: int, h: int) -> None:
    """Composite one or more cutouts, splitting the box into overlapping columns.

    Liam's group shots (four people shoulder to shoulder) need the figures to
    overlap slightly, or the row reads as separate pasted stickers.
    """
    images = [load_image(r) if r else placeholder_subject() for r in refs]
    images = [im for im in images if im is not None]
    if not images:
        return

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
        placed = _pad_to(fitted, (w, h), origin)

        if style.subject_shadow:
            canvas.alpha_composite(drop_shadow(
                placed, (int(-10 * SCALE), int(16 * SCALE)), int(30 * SCALE),
                style.subject_shadow_opacity))
        if style.subject_rim:
            canvas.alpha_composite(
                rim_light(placed, style.subject_rim, style.subject_rim_width * SCALE, 0.85))
        canvas.alpha_composite(placed)


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


def render(
    *,
    headline: str,
    style_name: str = "saraev",
    palette: str | None = None,
    accent_words: list[str] | None = None,
    subject: str | None = None,
    subjects: list[str] | None = None,
    icons: list[str] | None = None,
    word_colors: dict[str, str] | None = None,
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
    width: int = BASE_W,
    height: int = BASE_H,
) -> Image.Image:
    """Compose one thumbnail and return it at `width` x `height`."""
    style: Style = get_style(style_name, palette)
    w, h = width * SCALE, height * SCALE

    # --- background -------------------------------------------------------
    if background:
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
    else:
        canvas = linear_gradient((w, h), style.bg_top, style.bg_bottom, style.bg_angle)

    # --- backlight --------------------------------------------------------
    if style.glow_color and style.glow_intensity > 0:
        gc = (style.glow_center[0] * w, style.glow_center[1] * h)
        canvas.alpha_composite(
            radial_glow((w, h), gc, style.glow_radius * w * 0.5, style.glow_color, style.glow_intensity)
        )

    # --- hero visual / rendered prop --------------------------------------
    hero_layer: Image.Image | None = None
    if hero:
        hero_img = load_image(hero)
        if hero_img is not None:
            hero_layer = hero_img
    elif card_text:
        hero_layer = cards.with_shadow(
            cards.social_card(int(w * 0.42), card_text, display_name=card_name,
                              handle=card_handle, scale=SCALE * 0.9)
        )
    elif toast_text and toast_amount:
        hero_layer = cards.with_shadow(
            cards.toast(int(w * 0.36), toast_text, toast_amount, scale=SCALE * 0.9)
        )

    if hero_layer is not None:
        box = _denorm(style.hero_box, w, h)
        fitted, origin = _fit(hero_layer, box, "center")
        if not card_text and not toast_text:
            canvas.alpha_composite(drop_shadow(
                _pad_to(fitted, (w, h), origin), (0, int(18 * SCALE)), int(26 * SCALE), 0.45))
        canvas.alpha_composite(fitted, origin)

    # --- subject cutout ---------------------------------------------------
    refs: list[str | None] = list(subjects) if subjects else [subject]
    box_rect = style.subject_box
    anchor = style.subject_anchor
    if subject_side == "left":
        box_rect = (0.02, box_rect[1], box_rect[2], box_rect[3])
        anchor = anchor.replace("right", "left")
    elif subject_side == "right":
        box_rect = (1.0 - box_rect[2] - 0.02, box_rect[1], box_rect[2], box_rect[3])
        anchor = anchor.replace("left", "right")

    _place_subjects(canvas, refs, style, box_rect, anchor, w, h)

    if icons:
        _place_icons(canvas, icons, style, w, h)

    # --- vignette ---------------------------------------------------------
    if style.vignette_strength > 0:
        canvas.alpha_composite(vignette((w, h), style.vignette_strength))

    # --- scrim behind the headline ----------------------------------------
    scrim_dir = style.scrim
    if text_position == "top":
        scrim_dir = "top"
    elif text_position == "bottom":
        scrim_dir = "bottom"
    if scrim_dir and style.scrim_opacity > 0:
        canvas.alpha_composite(scrim((w, h), scrim_dir, style.scrim_opacity))

    # --- arrow ------------------------------------------------------------
    if arrow:
        start = (style.arrow_from[0] * w, style.arrow_from[1] * h)
        end = (style.arrow_to[0] * w, style.arrow_to[1] * h)
        canvas.alpha_composite(hand_arrow(
            (w, h), start, end, style.arrow_color,
            width=style.arrow_width * SCALE, bow=style.arrow_bow,
            head_len=46.0 * SCALE,
        ))

    # --- headline ---------------------------------------------------------
    copy = _apply_case(headline, style.text_case)
    text_rect = style.text_box
    if text_position == "top":
        text_rect = (text_rect[0], 0.06, text_rect[2], text_rect[3])
    elif text_position == "bottom":
        text_rect = (text_rect[0], 1.0 - text_rect[3] - 0.06, text_rect[2], text_rect[3])
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

    return canvas.convert("RGB").resize((width, height), Image.LANCZOS)


def _pad_to(layer: Image.Image, size: tuple[int, int], origin: tuple[int, int]) -> Image.Image:
    """Place a smaller layer on a full-canvas transparent sheet."""
    sheet = Image.new("RGBA", size, (0, 0, 0, 0))
    sheet.paste(layer, origin)
    return sheet


def legibility_report(img: Image.Image, style_name: str = "saraev", feed_width: int = 168,
                      text_position: str | None = None) -> dict:
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
    if text_position == "top":
        box = (box[0], 0.06, box[2], box[3])
    elif text_position == "bottom":
        box = (box[0], 1.0 - box[3] - 0.06, box[2], box[3])

    x0, y0 = int(box[0] * small.width), int(box[1] * small.height)
    x1 = min(small.width, x0 + max(2, int(box[2] * small.width)))
    y1 = min(small.height, y0 + max(2, int(box[3] * small.height)))
    region = small.crop((x0, y0, x1, y1))

    px = list(region.getdata())
    mean = sum(px) / len(px)
    stdev = math.sqrt(sum((p - mean) ** 2 for p in px) / len(px))

    edge_px = list(region.filter(ImageFilter.FIND_EDGES).getdata())
    edge_energy = sum(edge_px) / len(edge_px)

    return {
        "feed_width": feed_width,
        "headline_contrast": round(stdev, 2),
        "edge_energy": round(edge_energy, 2),
        "verdict": "ok" if stdev > 40 and edge_energy > 10 else "weak",
    }
