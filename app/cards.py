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
    metrics: list[str] | None = None,
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
    metric_h = int(58 * scale) if metrics else 0
    height = pad * 2 + header_h + len(lines) * body_lh + int(22 * scale) + metric_h

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

    if metrics:
        m_size = int(30 * scale)
        metrics_row(draw, pad, y + int(14 * scale), [str(m) for m in metrics],
                    load_font("inter", m_size, "Medium"), muted,
                    gap=(width - pad * 2) / max(len(metrics), 1),
                    glyph=int(m_size * 0.95))

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


# --------------------------------------------------------------------------- #
# Further card types, each taken from a prop the reference channels actually use
# --------------------------------------------------------------------------- #

def metrics_row(draw, x: float, y: float, counts: list[str], font, muted: RGB,
                gap: float, glyph: int) -> None:
    """Reply / repost / like counts under a post body.

    The glyph is sized off the font rather than fixed: at thumbnail scale a
    13px circle renders as a speck next to 24px numerals.
    """
    for i, value in enumerate(counts[:4]):
        cx = x + i * gap
        draw.ellipse((cx, y, cx + glyph, y + glyph), outline=muted + (255,),
                     width=max(2, glyph // 8))
        draw.text((cx + glyph * 1.45, y - glyph * 0.05), value, font=font,
                  fill=muted + (255,))


def stat_card(width: int, amount: str, sublabel: str, *, scale: float = 1.0,
              dark: bool = True, accent: RGB = (34, 197, 94),
              spark: bool = True) -> Image.Image:
    """A big figure over a rising sparkline — Liam's "$45,208 LAST 30 DAYS"."""
    pad = int(30 * scale)
    fig_size = int(74 * scale)
    sub_size = int(22 * scale)
    height = pad * 2 + fig_size + sub_size + (int(90 * scale) if spark else 0)

    bg = (18, 20, 24) if dark else (255, 255, 255)
    fg = (245, 246, 248) if dark else (16, 18, 22)
    muted = (150, 155, 165)

    card = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(card)
    d.rounded_rectangle((0, 0, width - 1, height - 1), radius=int(22 * scale), fill=bg + (255,))

    d.text((pad, pad), amount, font=load_font("inter", fig_size, "Black"), fill=fg + (255,))
    d.text((pad, pad + fig_size + int(6 * scale)), sublabel.upper(),
           font=load_font("inter", sub_size, "SemiBold"), fill=muted + (255,))

    if spark:
        top = pad + fig_size + sub_size + int(26 * scale)
        bottom = height - pad
        left, right = pad, width - pad
        # A gently accelerating curve reads as growth without implying real data.
        points = []
        steps = 24
        for i in range(steps + 1):
            t = i / steps
            px = left + (right - left) * t
            py = bottom - (bottom - top) * (t ** 1.7) * 0.92
            points.append((px, py))
        d.polygon(points + [(right, bottom), (left, bottom)], fill=accent + (48,))
        d.line(points, fill=accent + (255,), width=max(3, int(5 * scale)))
        d.ellipse((points[-1][0] - 7 * scale, points[-1][1] - 7 * scale,
                   points[-1][0] + 7 * scale, points[-1][1] + 7 * scale), fill=accent + (255,))
    return card


def checklist_card(width: int, items: list[str], *, title: str = "",
                   scale: float = 1.0, tick: RGB = (220, 38, 38),
                   paper: RGB = (253, 224, 71)) -> Image.Image:
    """A sticky note of ticked-off tasks — Liam's "Respond To Emails ✓" note."""
    items = [i for i in items if str(i).strip()][:7] or ["Item one"]
    pad = int(28 * scale)
    row = int(42 * scale)
    title_size = int(28 * scale)
    body_size = int(26 * scale)
    head = (title_size + int(14 * scale)) if title else 0
    height = pad * 2 + head + row * len(items)

    card = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(card)
    d.rounded_rectangle((0, 0, width - 1, height - 1), radius=int(10 * scale),
                        fill=paper + (255,))

    ink = (32, 28, 12)
    y = pad
    if title:
        d.text((pad, y), title, font=load_font("inter", title_size, "Black"), fill=ink + (255,))
        y += head

    font = load_font("inter", body_size, "SemiBold")
    for item in items:
        box = int(24 * scale)
        d.rounded_rectangle((pad, y + 4, pad + box, y + 4 + box), radius=int(4 * scale),
                            outline=ink + (200,), width=max(2, int(2 * scale)))
        # Hand-drawn tick, deliberately overshooting the box like a real one.
        d.line([(pad + box * 0.18, y + 4 + box * 0.55),
                (pad + box * 0.45, y + 4 + box * 0.82),
                (pad + box * 1.05, y + 4 - box * 0.12)],
               fill=tick + (255,), width=max(3, int(4 * scale)))
        d.text((pad + box + int(18 * scale), y), str(item), font=font, fill=ink + (255,))
        y += row
    return card


def prompt_card(width: int, placeholder: str, *, scale: float = 1.0,
                dark: bool = True, accent: RGB = (217, 119, 87)) -> Image.Image:
    """An empty prompt input — Nate's "Describe a task or ask a question"."""
    pad = int(26 * scale)
    size = int(30 * scale)
    height = pad * 2 + size + int(10 * scale)
    bg = (26, 28, 33) if dark else (255, 255, 255)
    fg = (140, 146, 156)

    card = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(card)
    d.rounded_rectangle((0, 0, width - 1, height - 1), radius=int(16 * scale),
                        fill=bg + (255,), outline=(70, 74, 82, 255), width=max(1, int(2 * scale)))
    d.text((pad, pad), placeholder, font=load_font("inter", size, "Medium"), fill=fg + (255,))
    caret = pad + d.textlength(placeholder, font=load_font("inter", size, "Medium")) + int(6 * scale)
    d.rectangle((caret, pad - 2, caret + max(2, int(3 * scale)), pad + size), fill=accent + (255,))
    return card


def chat_card(width: int, lines: list[str], *, scale: float = 1.0, dark: bool = True,
              accent: RGB = (37, 99, 235)) -> Image.Image:
    """Alternating message bubbles; odd lines are the reply."""
    lines = [str(l) for l in lines if str(l).strip()][:4] or ["Hello"]
    pad = int(22 * scale)
    size = int(27 * scale)
    font = load_font("inter", size, "Medium")
    probe = ImageDraw.Draw(Image.new("L", (8, 8)))
    bubble_pad = int(18 * scale)
    gap = int(14 * scale)

    heights, widths = [], []
    for line in lines:
        widths.append(min(width - pad * 2, probe.textlength(line, font=font) + bubble_pad * 2))
        heights.append(size + bubble_pad * 2)
    height = pad * 2 + sum(heights) + gap * (len(lines) - 1)

    card = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(card)
    y = pad
    for i, line in enumerate(lines):
        mine = i % 2 == 1
        w = int(widths[i])
        x = width - pad - w if mine else pad
        fill = accent if mine else ((44, 47, 54) if dark else (232, 234, 238))
        text = (255, 255, 255) if mine or dark else (16, 18, 22)
        d.rounded_rectangle((x, y, x + w, y + heights[i]), radius=int(18 * scale),
                            fill=fill + (255,))
        d.text((x + bubble_pad, y + bubble_pad), line, font=font, fill=text + (255,))
        y += heights[i] + gap
    return card


def terminal_card(width: int, lines: list[str], *, scale: float = 1.0,
                  accent: RGB = (34, 197, 94)) -> Image.Image:
    """A dark window of monospaced-looking output, with traffic-light dots."""
    lines = [str(l) for l in lines if str(l).strip()][:8] or ["$ run"]
    pad = int(26 * scale)
    bar = int(40 * scale)
    size = int(34 * scale)
    row = int(size * 1.45)
    height = bar + pad * 2 + row * len(lines)

    card = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(card)
    d.rounded_rectangle((0, 0, width - 1, height - 1), radius=int(14 * scale),
                        fill=(16, 18, 22, 255))
    d.rectangle((0, bar - 1, width, bar), fill=(44, 48, 56, 255))
    for i, dot in enumerate(((255, 95, 87), (255, 189, 46), (39, 201, 63))):
        cx = pad + i * int(20 * scale)
        r = int(6 * scale)
        d.ellipse((cx, bar / 2 - r, cx + r * 2, bar / 2 + r), fill=dot + (255,))

    font = load_font("inter", size, "Medium")
    y = bar + pad
    for line in lines:
        colour = accent if line.strip().startswith(("$", ">", "✓")) else (198, 203, 212)
        d.text((pad, y), line, font=font, fill=colour + (255,))
        y += row
    return card
