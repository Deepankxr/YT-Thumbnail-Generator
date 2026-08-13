"""Tiled backdrop: a repeating field of marks, optionally struck through.

Nate's "AI Tools don't matter." sits on a grid of app icons with red crosses
over them — the backdrop states the premise so the headline doesn't have to.
Drawn rather than generated: a diffusion model asked for "a grid of logos" will
warp the spacing and invent glyphs, and the regularity is the whole effect.
"""

from __future__ import annotations

import math

from PIL import Image, ImageDraw, ImageFilter

from .assets import load_image
from .shapes import rounded_rect

RGB = tuple[int, int, int]


def _placeholder_mark(size: int, color: RGB) -> Image.Image:
    """A generic rounded app-tile, so a tiled backdrop reads before real icons."""
    tile = rounded_rect((size, size), int(size * 0.24), color + (255,))
    d = ImageDraw.Draw(tile)
    c, r = size / 2, size * 0.30
    for k in range(8):
        a = math.pi * k / 4
        d.line([(c, c), (c + math.cos(a) * r, c + math.sin(a) * r)],
               fill=(255, 255, 255, 235), width=max(2, int(size * 0.075)))
    return tile


def _cross(size: int, color: RGB, width: int) -> Image.Image:
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    pad = size * 0.18
    d.line([(pad, pad), (size - pad, size - pad)], fill=color + (255,), width=width)
    d.line([(size - pad, pad), (pad, size - pad)], fill=color + (255,), width=width)
    return layer


def tiled_backdrop(
    size: tuple[int, int],
    icons: list[str] | None = None,
    *,
    columns: int = 6,
    opacity: float = 0.5,
    cross: bool = True,
    cross_color: RGB = (232, 62, 40),
    cross_every: int = 1,
    angle: float = 0.0,
    blur: float = 0.0,
    stagger: bool = True,
    accent: RGB = (217, 119, 87),
) -> Image.Image:
    """A full-bleed grid of marks.

    `cross_every` strikes through every nth tile, so a backdrop can read as
    "all of these are wrong" or just "some of these are". Rows are staggered by
    half a tile, which stops the grid looking like a spreadsheet.
    """
    w, h = size
    columns = max(1, min(columns, 20))
    step = w / columns
    tile_px = int(step * 0.62)
    if tile_px < 4:
        return Image.new("RGBA", size, (0, 0, 0, 0))

    # Oversize the field so a rotation can't expose bare corners.
    pad = int(max(w, h) * (0.35 if angle else 0.08))
    fw, fh = w + pad * 2, h + pad * 2
    field = Image.new("RGBA", (fw, fh), (0, 0, 0, 0))

    marks: list[Image.Image] = []
    for ref in (icons or []):
        img = load_image(ref)
        if img is None:
            continue
        ratio = tile_px / max(img.width, img.height)
        marks.append(img.resize((max(1, int(img.width * ratio)),
                                 max(1, int(img.height * ratio))), Image.LANCZOS))
    if not marks:
        marks = [_placeholder_mark(tile_px, accent)]

    x_mark = _cross(tile_px, cross_color, max(2, int(tile_px * 0.11))) if cross else None

    rows = int(fh / step) + 2
    cols = int(fw / step) + 2
    n = 0
    for row in range(rows):
        offset = (step / 2) if (stagger and row % 2) else 0
        for col in range(cols):
            mark = marks[n % len(marks)]
            x = int(col * step + offset + (step - mark.width) / 2)
            y = int(row * step + (step - mark.height) / 2)
            field.alpha_composite(mark, (x, y))
            if x_mark is not None and cross_every > 0 and n % cross_every == 0:
                field.alpha_composite(x_mark, (int(col * step + offset + (step - tile_px) / 2),
                                               int(row * step + (step - tile_px) / 2)))
            n += 1

    if angle:
        field = field.rotate(angle, resample=Image.BICUBIC, center=(fw / 2, fh / 2))
    if blur:
        field = field.filter(ImageFilter.GaussianBlur(radius=blur))

    out = field.crop((pad, pad, pad + w, pad + h))
    if opacity < 1.0:
        alpha = out.getchannel("A").point(lambda a: int(a * max(0.0, min(1.0, opacity))))
        out.putalpha(alpha)
    return out
