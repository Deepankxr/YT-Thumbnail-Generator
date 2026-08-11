"""Deterministically rendered UI props: social cards and notification toasts.

Nate Herk's thumbnails lean on pixel-perfect tweet cards and payment toasts.
Diffusion models mangle exactly this kind of small UI text, so we draw it — the
props cost nothing per render and are always legible.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from .assets import load_font
from .shapes import drop_shadow

RGB = tuple[int, int, int]


def _avatar(size: int, color: RGB) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((0, 0, size - 1, size - 1), fill=color + (255,))
    # Neutral head-and-shoulders mark; never a real avatar.
    draw.ellipse((size * 0.30, size * 0.22, size * 0.70, size * 0.62), fill=(255, 255, 255, 235))
    draw.ellipse((size * 0.18, size * 0.60, size * 0.82, size * 1.15), fill=(255, 255, 255, 235))
    return img


def social_card(
    width: int,
    text: str,
    *,
    display_name: str = "Your Name",
    handle: str = "@yourhandle",
    dark: bool = True,
    accent: RGB = (29, 155, 240),
    scale: float = 1.0,
) -> Image.Image:
    """A social post card. Height is derived from the wrapped body text."""
    pad = int(34 * scale)
    name_size = int(30 * scale)
    body_size = int(52 * scale)
    avatar_size = int(64 * scale)

    bg = (21, 24, 28) if dark else (255, 255, 255)
    fg = (231, 233, 234) if dark else (15, 20, 25)
    muted = (113, 118, 123)

    body_font = load_font("inter", body_size, "Bold")
    name_font = load_font("inter", name_size, "Bold")
    meta_font = load_font("inter", name_size, "Regular")

    probe = ImageDraw.Draw(Image.new("L", (8, 8)))
    max_text_w = width - pad * 2

    lines: list[str] = []
    current = ""
    for word in text.split():
        trial = f"{current} {word}".strip()
        if probe.textlength(trial, font=body_font) <= max_text_w or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)

    body_lh = int(body_size * 1.22)
    header_h = avatar_size + int(18 * scale)
    height = pad * 2 + header_h + len(lines) * body_lh + int(22 * scale)

    card = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(card)
    radius = int(28 * scale)
    draw.rounded_rectangle((0, 0, width - 1, height - 1), radius=radius, fill=bg + (255,))

    card.alpha_composite(_avatar(avatar_size, accent), (pad, pad))

    name_x = pad + avatar_size + int(18 * scale)
    draw.text((name_x, pad + int(4 * scale)), display_name, font=name_font, fill=fg + (255,))
    name_w = draw.textlength(display_name, font=name_font)

    # Verified tick, drawn rather than fetched.
    tick_r = int(11 * scale)
    tick_cx = name_x + name_w + int(14 * scale)
    tick_cy = pad + int(4 * scale) + name_size // 2
    draw.ellipse((tick_cx - tick_r, tick_cy - tick_r, tick_cx + tick_r, tick_cy + tick_r),
                 fill=accent + (255,))
    draw.line(
        [(tick_cx - tick_r * 0.45, tick_cy),
         (tick_cx - tick_r * 0.1, tick_cy + tick_r * 0.38),
         (tick_cx + tick_r * 0.5, tick_cy - tick_r * 0.4)],
        fill=(255, 255, 255, 255), width=max(2, int(3 * scale)),
    )

    draw.text((name_x, pad + int(4 * scale) + name_size + int(6 * scale)), handle,
              font=meta_font, fill=muted + (255,))

    y = pad + header_h + int(10 * scale)
    for line in lines:
        draw.text((pad, y), line, font=body_font, fill=fg + (255,))
        y += body_lh

    return card


def toast(
    width: int,
    title: str,
    amount: str,
    *,
    scale: float = 1.0,
    accent: RGB = (217, 119, 87),
    meta: str = "now",
) -> Image.Image:
    """A macOS-style notification pill — the "$17,532 Received" prop."""
    pad = int(22 * scale)
    icon = int(56 * scale)
    height = pad * 2 + icon

    card = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(card)
    draw.rounded_rectangle((0, 0, width - 1, height - 1), radius=int(20 * scale),
                           fill=(250, 250, 252, 252))

    draw.rounded_rectangle((pad, pad, pad + icon, pad + icon), radius=int(14 * scale),
                           fill=accent + (255,))
    draw.ellipse((pad + icon * 0.28, pad + icon * 0.28, pad + icon * 0.72, pad + icon * 0.72),
                 fill=(255, 255, 255, 255))

    tx = pad + icon + int(18 * scale)
    title_font = load_font("inter", int(26 * scale), "SemiBold")
    amount_font = load_font("inter", int(32 * scale), "Black")

    draw.text((tx, pad + int(2 * scale)), title, font=title_font, fill=(70, 74, 82, 255))
    draw.text((tx, pad + int(26 * scale)), amount, font=amount_font, fill=(12, 14, 18, 255))

    meta_font = load_font("inter", int(22 * scale), "Medium")
    meta_w = draw.textlength(meta, font=meta_font)
    draw.text((width - pad - meta_w, pad + int(4 * scale)), meta, font=meta_font,
              fill=(150, 155, 163, 255))

    return card


def with_shadow(card: Image.Image, blur: int = 28, offset: tuple[int, int] = (0, 14),
                opacity: float = 0.55) -> Image.Image:
    """Pad a card and lay its own drop shadow underneath."""
    pad = blur * 3
    canvas = Image.new("RGBA", (card.width + pad * 2, card.height + pad * 2), (0, 0, 0, 0))
    placed = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    placed.paste(card, (pad, pad))
    canvas.alpha_composite(drop_shadow(placed, offset, blur, opacity))
    canvas.alpha_composite(placed)
    return canvas
