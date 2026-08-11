"""Drawing primitives: gradients, glows, vignettes, rim light, hand-drawn arrows.

Everything here works on RGBA layers at render scale and is composited by
`compositor`. Nothing draws text — that lives in `text.py`.
"""

from __future__ import annotations

import math

from PIL import Image, ImageDraw, ImageFilter

RGBA = tuple[int, int, int, int]
RGB = tuple[int, int, int]


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def linear_gradient(size: tuple[int, int], top: RGB, bottom: RGB, angle: float = 90.0) -> Image.Image:
    """Vertical (default) or angled two-stop gradient.

    Built as a 1px-wide strip and stretched, which is ~100x faster than
    per-pixel work and visually identical after the rotate/crop.
    """
    w, h = size
    if abs(angle - 90.0) < 0.01:
        strip = Image.new("RGB", (1, h))
        px = strip.load()
        for y in range(h):
            t = y / max(h - 1, 1)
            px[0, y] = (
                int(_lerp(top[0], bottom[0], t)),
                int(_lerp(top[1], bottom[1], t)),
                int(_lerp(top[2], bottom[2], t)),
            )
        return strip.resize((w, h), Image.BILINEAR).convert("RGBA")

    # Oversize so the rotation's corners still cover the canvas.
    diag = int(math.hypot(w, h)) + 2
    strip = linear_gradient((diag, diag), top, bottom, 90.0)
    rotated = strip.rotate(angle - 90.0, resample=Image.BILINEAR, expand=False)
    left, upper = (diag - w) // 2, (diag - h) // 2
    return rotated.crop((left, upper, left + w, upper + h))


def radial_glow(
    size: tuple[int, int],
    center: tuple[float, float],
    radius: float,
    color: RGB,
    intensity: float = 1.0,
) -> Image.Image:
    """Soft radial falloff used for Jack-style backlighting behind the subject.

    Drawn small and upscaled: the blur we'd need at full res is the single most
    expensive op in the pipeline, and the falloff is smooth enough to survive.
    """
    w, h = size
    small_w, small_h = max(w // 8, 8), max(h // 8, 8)
    layer = Image.new("L", (small_w, small_h), 0)
    draw = ImageDraw.Draw(layer)

    cx, cy = center[0] / 8, center[1] / 8
    r = max(radius / 8, 1)
    steps = 48
    for i in range(steps, 0, -1):
        t = i / steps
        rr = r * t
        # Quadratic falloff reads closer to a real light than a linear ramp.
        alpha = int(255 * intensity * (1 - t) ** 2)
        draw.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=alpha)

    layer = layer.resize((w, h), Image.BICUBIC).filter(ImageFilter.GaussianBlur(radius=max(w // 120, 2)))
    out = Image.new("RGBA", (w, h), color + (0,))
    out.putalpha(layer)
    return out


def vignette(size: tuple[int, int], strength: float = 0.55) -> Image.Image:
    """Darkened edges. Keeps the eye on the subject and lifts text contrast."""
    w, h = size
    small_w, small_h = max(w // 8, 8), max(h // 8, 8)

    # One oversized inverted ellipse, heavily blurred: opaque at the corners,
    # clear through the middle.
    mask = Image.new("L", (small_w, small_h), int(255 * strength))
    draw = ImageDraw.Draw(mask)
    draw.ellipse((-small_w * 0.15, -small_h * 0.15, small_w * 1.15, small_h * 1.15), fill=0)
    mask = mask.resize((w, h), Image.BICUBIC).filter(ImageFilter.GaussianBlur(radius=max(w // 40, 4)))

    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    out.putalpha(mask)
    return out


def scrim(size: tuple[int, int], direction: str, opacity: float, extent: float = 0.62,
          color: RGB = (0, 0, 0)) -> Image.Image:
    """One-sided darkening ramp behind the headline.

    Without this, white type over a supplied photo backplate is a coin flip.
    The ramp is eased (cubic) so it never shows a visible edge.
    """
    w, h = size
    horizontal = direction in ("left", "right")
    span = max(1, int((w if horizontal else h) * extent))

    # Build the ramp once as a 1px line, then stretch — a per-pixel loop here
    # costs ~4M Python iterations at 2x render scale.
    line = Image.new("L", (span, 1))
    line.putdata([int(255 * opacity * (1 - i / span) ** 3) for i in range(span)])

    if direction in ("right", "bottom"):
        line = line.transpose(Image.FLIP_LEFT_RIGHT)

    mask = Image.new("L", (w, h), 0)
    if horizontal:
        band = line.resize((span, h), Image.BILINEAR)
        mask.paste(band, (0 if direction == "left" else w - span, 0))
    else:
        band = line.transpose(Image.ROTATE_270).resize((w, span), Image.BILINEAR)
        mask.paste(band, (0, 0 if direction == "top" else h - span))

    out = Image.new("RGBA", (w, h), color + (0,))
    out.putalpha(mask)
    return out


def drop_shadow(layer: Image.Image, offset: tuple[int, int], blur: int, opacity: float = 0.5) -> Image.Image:
    """Shadow cast by a layer's own alpha. Returned same-size, to paste under it."""
    alpha = layer.getchannel("A")
    shadow = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    shadow.putalpha(alpha.point(lambda a: int(a * opacity)))
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=blur))

    shifted = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    shifted.paste(shadow, offset)
    return shifted


def rim_light(layer: Image.Image, color: RGB, width: int, opacity: float = 0.9) -> Image.Image:
    """Coloured edge glow hugging a cutout — the Jack Roberts neon separation.

    Dilate the alpha, subtract the original, blur what's left.

    The dilation runs at quarter resolution: MaxFilter is O(pixels x kernel^2),
    and at 2x render scale a full-res pass costs ~2s on its own. The ring gets
    blurred anyway, so the downsample is invisible in the output.
    """
    alpha = layer.getchannel("A")
    w, h = layer.size
    small = (max(w // 4, 1), max(h // 4, 1))

    small_alpha = alpha.resize(small, Image.BILINEAR)
    kernel = max(3, (width // 4) * 2 + 1)
    grown = small_alpha.filter(ImageFilter.MaxFilter(size=kernel)).resize((w, h), Image.BILINEAR)

    # Knock the subject back out so only the ring survives.
    solid = alpha.point(lambda a: 255 if a > 128 else 0)
    ring = Image.composite(Image.new("L", layer.size, 0), grown, solid)
    ring = ring.filter(ImageFilter.GaussianBlur(radius=max(width, 2)))
    ring = ring.point(lambda a: int(min(255, a * opacity * 1.6)))

    out = Image.new("RGBA", layer.size, color + (0,))
    out.putalpha(ring)
    return out


def rounded_rect(size: tuple[int, int], radius: int, fill: RGBA) -> Image.Image:
    """Standalone rounded rectangle — the highlight pill behind an accent word."""
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=radius, fill=fill)
    return img


def _quad_bezier(p0, p1, p2, t: float) -> tuple[float, float]:
    u = 1 - t
    return (
        u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
        u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1],
    )


def hand_arrow(
    size: tuple[int, int],
    start: tuple[float, float],
    end: tuple[float, float],
    color: RGB,
    width: int = 8,
    bow: float = 0.28,
    head_len: float = 46.0,
    opacity: int = 255,
) -> Image.Image:
    """Curved marker-pen arrow, the connective tissue in all three channels' work.

    `bow` bends the curve perpendicular to the start→end line; positive bows one
    way, negative the other. The stroke tapers slightly toward the head so it
    reads as drawn rather than as a CAD spline.
    """
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)

    dx, dy = end[0] - start[0], end[1] - start[1]
    # Control point: midpoint pushed along the perpendicular.
    mx, my = (start[0] + end[0]) / 2, (start[1] + end[1]) / 2
    ctrl = (mx - dy * bow, my + dx * bow)

    # Stop the shaft short so the head sits at the tip cleanly.
    steps = 120
    pts = [_quad_bezier(start, ctrl, end, i / steps) for i in range(steps + 1)]

    shaft_end = steps
    for i in range(steps, 0, -1):
        if math.hypot(pts[i][0] - end[0], pts[i][1] - end[1]) >= head_len * 0.72:
            shaft_end = i
            break

    for i in range(shaft_end):
        t = i / max(shaft_end, 1)
        w = max(2, int(width * (1.0 - 0.35 * t)))
        draw.line([pts[i], pts[i + 1]], fill=color + (opacity,), width=w)
        draw.ellipse((pts[i][0] - w / 2, pts[i][1] - w / 2, pts[i][0] + w / 2, pts[i][1] + w / 2),
                     fill=color + (opacity,))

    # Head oriented along the curve's final tangent.
    tip = pts[-1]
    prev = pts[max(shaft_end - 6, 0)]
    ang = math.atan2(tip[1] - prev[1], tip[0] - prev[0])
    spread = math.radians(26)
    left = (tip[0] - head_len * math.cos(ang - spread), tip[1] - head_len * math.sin(ang - spread))
    right = (tip[0] - head_len * math.cos(ang + spread), tip[1] - head_len * math.sin(ang + spread))
    draw.polygon([tip, left, right], fill=color + (opacity,))

    return layer
