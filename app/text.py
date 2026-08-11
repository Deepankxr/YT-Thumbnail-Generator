"""Headline typesetting: auto-fit wrapping, accent pills, stroke, shadow.

This is the layer that separates a designed thumbnail from a generated one, so
it stays deterministic — no model ever draws a glyph. We lay out positioned word
runs first, then paint, which is what makes per-word treatments (the cyan
highlight box behind one word) possible.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from PIL import Image, ImageDraw, ImageFilter

from .assets import load_font
from .shapes import rounded_rect

RGB = tuple[int, int, int]


@dataclass
class Run:
    """One word, positioned on a line."""

    word: str
    x: float
    y: float
    width: float
    accent: bool = False


@dataclass
class Layout:
    runs: list[Run] = field(default_factory=list)
    size: int = 0
    line_height: float = 0.0
    width: float = 0.0
    height: float = 0.0
    font_width: float | None = None


def _measure(draw: ImageDraw.ImageDraw, text: str, font) -> float:
    return draw.textlength(text, font=font)


def _accent_groups(runs: list[Run]) -> list[list[Run]]:
    """Consecutive accent words on the same line share one pill.

    Without this, "AI person" renders as two abutting boxes with a seam down
    the middle instead of a single highlight.
    """
    groups: list[list[Run]] = []
    current: list[Run] = []

    for run in runs:
        if not run.accent:
            if current:
                groups.append(current)
                current = []
            continue
        if current and abs(run.y - current[-1].y) > 0.5:
            groups.append(current)
            current = []
        current.append(run)

    if current:
        groups.append(current)
    return groups


def _wrap(draw, words: list[str], font, max_width: float) -> list[list[str]] | None:
    """Greedy wrap. None if any single word can't fit — caller shrinks and retries."""
    lines: list[list[str]] = []
    current: list[str] = []

    for word in words:
        if _measure(draw, word, font) > max_width:
            return None
        trial = current + [word]
        if _measure(draw, " ".join(trial), font) <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = [word]

    if current:
        lines.append(current)
    return lines


def layout_headline(
    text: str,
    box: tuple[float, float, float, float],
    family: str,
    weight: str,
    *,
    max_lines: int = 3,
    line_height: float = 0.94,
    align: str = "left",
    valign: str = "top",
    accent_words: set[str] | None = None,
    tracking: float = -0.01,
    max_size: int | None = None,
    accent_pad_x: float = 0.0,
    font_width: float | None = None,
) -> Layout:
    """Fit `text` into `box` at the largest size that respects `max_lines`.

    Binary search on font size. `line_height` under 1.0 gives the tight stacked
    look all three reference channels use; `tracking` is in em and typically
    slightly negative for heavy weights.

    `accent_pad_x` reserves room for highlight-pill padding so a pilled word at
    the start or end of a line can't bleed past the box.
    """
    bx, by, bw, bh = box
    accent_words = {w.lower().strip(".,!?") for w in (accent_words or set())}
    words = text.split()
    if not words:
        return Layout()

    if accent_words and accent_pad_x:
        # Two pads: a pilled word could land at both ends of the same line.
        bw = max(bw - accent_pad_x * 2, bw * 0.5)
        bx += accent_pad_x

    probe = Image.new("L", (8, 8))
    draw = ImageDraw.Draw(probe)

    lo, hi = 12, max_size or int(bh)
    best: tuple[int, list[list[str]]] | None = None

    while lo <= hi:
        mid = (lo + hi) // 2
        font = load_font(family, mid, weight, font_width)
        lines = _wrap(draw, words, font, bw)
        fits = lines is not None and len(lines) <= max_lines and len(lines) * mid * line_height <= bh
        if fits:
            best = (mid, lines)  # type: ignore[assignment]
            lo = mid + 1
        else:
            hi = mid - 1

    if best is None:
        # Degenerate box; fall back to the smallest legible size on one line.
        size = 12
        lines = [words]
    else:
        size, lines = best

    font = load_font(family, size, weight, font_width)
    track_px = tracking * size
    lh = size * line_height

    # Real ink height of the first line, so vertical centring isn't thrown off
    # by the font's internal leading.
    ascent_probe = draw.textbbox((0, 0), "Hxdp", font=font)
    block_h = (len(lines) - 1) * lh + (ascent_probe[3] - ascent_probe[1])

    if valign == "center":
        cursor_y = by + (bh - block_h) / 2
    elif valign == "bottom":
        cursor_y = by + bh - block_h
    else:
        cursor_y = by

    layout = Layout(size=size, line_height=lh, font_width=font_width)
    widest = 0.0

    space_w = _measure(draw, " ", font)
    # Breathing room where a pill starts or ends, so the highlight box doesn't
    # butt straight against the neighbouring word.
    boundary_gap = accent_pad_x * 0.6 if accent_words else 0.0

    def _is_accent(word: str) -> bool:
        return word.lower().strip(".,!?") in accent_words

    for line in lines:
        flags = [_is_accent(word) for word in line]
        boundaries = sum(1 for i in range(len(line) - 1) if flags[i] != flags[i + 1])

        # Width including tracking and pill boundaries, so alignment matches paint.
        line_w = sum(_measure(draw, w, font) for w in line) + track_px * max(len(line) - 1, 0)
        line_w += space_w * max(len(line) - 1, 0) + boundary_gap * boundaries
        widest = max(widest, line_w)

        if align == "center":
            cursor_x = bx + (bw - line_w) / 2
        elif align == "right":
            cursor_x = bx + bw - line_w
        else:
            cursor_x = bx

        for i, word in enumerate(line):
            w = _measure(draw, word, font)
            layout.runs.append(
                Run(word=word, x=cursor_x, y=cursor_y, width=w, accent=flags[i])
            )
            cursor_x += w + space_w + track_px
            if i < len(line) - 1 and flags[i] != flags[i + 1]:
                cursor_x += boundary_gap

        cursor_y += lh

    layout.width = widest
    layout.height = block_h
    return layout


def paint_headline(
    canvas: Image.Image,
    layout: Layout,
    family: str,
    weight: str,
    *,
    color: RGB = (255, 255, 255),
    accent_color: RGB | None = None,
    accent_fill: RGB | None = None,
    shadow: bool = True,
    shadow_opacity: float = 0.55,
    shadow_blur: int = 14,
    shadow_offset: tuple[int, int] = (0, 6),
    stroke_width: int = 0,
    stroke_color: RGB = (0, 0, 0),
    pill_pad: tuple[int, int] = (18, 8),
    pill_radius: int | None = None,
    word_colors: dict[str, RGB] | None = None,
) -> None:
    """Paint a laid-out headline onto `canvas` in place.

    Order matters: shadow, then accent boxes, then glyphs. `accent_fill` draws
    the highlight box behind accent words — rounded for Nate/Jack, square for
    Liam, controlled by `pill_radius`. `accent_color` alone just recolours.

    `word_colors` maps a lowercase word to an explicit colour and overrides
    everything else for that word, which is how a single line carries two
    colours ("STOP" yellow, "SELLING WORKFLOWS" white).
    """
    if not layout.runs:
        return

    font = load_font(family, layout.size, weight, layout.font_width)
    word_colors = {k.lower().strip(".,!?"): v for k, v in (word_colors or {}).items()}

    if shadow:
        shadow_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        sdraw = ImageDraw.Draw(shadow_layer)
        for run in layout.runs:
            sdraw.text((run.x, run.y), run.word, font=font,
                       fill=(0, 0, 0, int(255 * shadow_opacity)))
        shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(radius=shadow_blur))
        offset_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        offset_layer.paste(shadow_layer, shadow_offset)
        canvas.alpha_composite(offset_layer)

    if accent_fill:
        probe = ImageDraw.Draw(canvas)
        pad_x, pad_y = pill_pad

        # One reference measurement drives every pill's height, so "AI" and
        # "person" get identical boxes instead of tracking their own ink.
        ref = probe.textbbox((0, 0), "Hxpg", font=font)
        ref_top, ref_bottom = ref[1], ref[3]

        for group in _accent_groups(layout.runs):
            x0 = min(r.x for r in group)
            x1 = max(r.x + r.width for r in group)
            y = group[0].y

            pw = int(x1 - x0 + pad_x * 2)
            ph = int(ref_bottom - ref_top + pad_y * 2)
            radius = pill_radius if pill_radius is not None else int(ph * 0.22)
            pill = rounded_rect((pw, ph), radius, accent_fill + (255,))
            canvas.alpha_composite(pill, (int(x0 - pad_x), int(y + ref_top - pad_y)))

    draw = ImageDraw.Draw(canvas)
    for run in layout.runs:
        key = run.word.lower().strip(".,!?")
        if key in word_colors:
            fill = word_colors[key]
        elif run.accent and accent_color:
            fill = accent_color
        else:
            fill = color
        if stroke_width:
            draw.text((run.x, run.y), run.word, font=font, fill=fill + (255,),
                      stroke_width=stroke_width, stroke_fill=stroke_color + (255,))
        else:
            draw.text((run.x, run.y), run.word, font=font, fill=fill + (255,))


def underline(
    canvas: Image.Image,
    layout: Layout,
    color: RGB,
    family: str,
    weight: str,
    *,
    width: int = 10,
    gap: int = 10,
    line_index: int = -1,
    swash: bool = False,
) -> None:
    """Rule under one line — Nick's "No one is doing this." emphasis mark.

    Sits below the descender rather than the baseline, so the tail of a 'g' or
    'y' never collides with the rule. `swash` swaps the straight rule for a
    tapered marker curve, which is Liam's treatment.
    """
    if not layout.runs:
        return

    ys = sorted({round(r.y, 2) for r in layout.runs})
    target_y = ys[line_index]
    runs = [r for r in layout.runs if abs(r.y - target_y) < 0.5]
    if not runs:
        return

    # A swash under a colour plate reads as a mistake — the plate already
    # carries the emphasis. Skip rather than stack two treatments.
    if swash and any(r.accent for r in runs):
        return

    font = load_font(family, layout.size, weight, layout.font_width)
    draw = ImageDraw.Draw(canvas)
    # Deepest descender on this line, measured from the actual words drawn.
    bottom = max(draw.textbbox((r.x, r.y), r.word, font=font)[3] for r in runs)

    x0 = min(r.x for r in runs)
    x1 = max(r.x + r.width for r in runs)
    y = bottom + gap

    if not swash:
        draw.rounded_rectangle((x0, y, x1, y + width), radius=width // 2, fill=color + (255,))
        return

    # Marker-pen swash: a shallow bezier that dips in the middle and tapers at
    # both ends, so it reads as drawn rather than as a rule.
    span = x1 - x0
    ctrl = ((x0 + x1) / 2, y + span * 0.055)
    steps = 90
    pts = []
    for i in range(steps + 1):
        t = i / steps
        u = 1 - t
        pts.append((
            u * u * x0 + 2 * u * t * ctrl[0] + t * t * x1,
            u * u * y + 2 * u * t * ctrl[1] + t * t * y,
        ))

    for i in range(steps):
        t = i / steps
        # Thickest at the centre, thin at both tips.
        taper = 0.35 + 0.65 * (1 - abs(t - 0.5) * 2) ** 0.6
        w = max(2, int(width * taper))
        draw.line([pts[i], pts[i + 1]], fill=color + (255,), width=w)
