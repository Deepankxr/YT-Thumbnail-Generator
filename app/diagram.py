"""Node diagrams: a central icon with labelled spokes radiating out.

This is the "1 Person Business" element — a hub icon, dashed connectors, and a
ring of labelled nodes. It belongs here rather than in a prompt because small
labels and precise connectors are exactly what diffusion models turn to mush,
and because the labels are usually the whole point of the thumbnail.
"""

from __future__ import annotations

import json
import math
from collections import OrderedDict

from PIL import Image, ImageDraw, ImageFilter

from .assets import load_font, load_image
from .shapes import drop_shadow, hand_arrow, rounded_rect

RGB = tuple[int, int, int]


def _dashed_line(draw: ImageDraw.ImageDraw, start, end, color: RGB,
                 width: int, dash: int, gap: int, opacity: int = 255) -> None:
    """Dashes along a straight run. Pillow has no dash support of its own."""
    dx, dy = end[0] - start[0], end[1] - start[1]
    dist = math.hypot(dx, dy)
    if dist < 1:
        return
    ux, uy = dx / dist, dy / dist

    pos = 0.0
    while pos < dist:
        seg = min(dash, dist - pos)
        draw.line(
            [(start[0] + ux * pos, start[1] + uy * pos),
             (start[0] + ux * (pos + seg), start[1] + uy * (pos + seg))],
            fill=color + (opacity,), width=width,
        )
        pos += dash + gap


def _node_tile(size: int, accent: RGB, icon_ref: str | None, dark: bool) -> Image.Image:
    """One spoke node: a rounded tile with either a supplied icon or a glyph."""
    tile = rounded_rect((size, size), int(size * 0.24),
                        (accent + (255,)) if icon_ref is None else (0, 0, 0, 0))

    if icon_ref:
        icon = load_image(icon_ref)
        if icon is not None:
            ratio = size / max(icon.width, icon.height)
            icon = icon.resize((max(1, int(icon.width * ratio)), max(1, int(icon.height * ratio))),
                               Image.LANCZOS)
            sheet = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            sheet.paste(icon, ((size - icon.width) // 2, (size - icon.height) // 2))
            return sheet

    # Generic bot mark, so a diagram still reads before real icons exist.
    d = ImageDraw.Draw(tile)
    fg = (255, 255, 255, 235) if not dark else (16, 16, 20, 235)
    d.rounded_rectangle((size * 0.24, size * 0.28, size * 0.76, size * 0.72),
                        radius=int(size * 0.12), outline=fg, width=max(2, size // 22))
    r = size * 0.055
    for cx in (size * 0.40, size * 0.60):
        d.ellipse((cx - r, size * 0.44 - r, cx + r, size * 0.44 + r), fill=fg)
    d.line([(size * 0.38, size * 0.60), (size * 0.62, size * 0.60)], fill=fg,
           width=max(2, size // 26))
    d.line([(size * 0.5, size * 0.28), (size * 0.5, size * 0.19)], fill=fg,
           width=max(2, size // 26))
    d.ellipse((size * 0.5 - r * 0.8, size * 0.19 - r * 1.6,
               size * 0.5 + r * 0.8, size * 0.19), fill=fg)
    return tile


# A diagram is fully determined by its arguments, and redrawing one costs
# ~170ms — which is paid on every drag of an unrelated element. Memoise the
# last few so moving the headline doesn't re-render the whole graph.
_CACHE: OrderedDict[str, Image.Image] = OrderedDict()
_CACHE_MAX = 12


def node_diagram(
    width: int,
    nodes: list[dict],
    *,
    center_icon: str | None = None,
    center_label: str | None = None,
    accent: RGB = (217, 119, 87),
    text_color: RGB = (255, 255, 255),
    line_color: RGB | None = None,
    dark: bool = True,
    scale: float = 1.0,
    layout: str = "hub",
    frame: str | None = None,
    frame_glow: RGB | None = None,
    screen: RGB = (255, 255, 255),
) -> Image.Image:
    """Node diagram, `width` px wide, height derived from the layout.

    `layout="hub"` is spokes radiating from a centre; `layout="cycle"` drops the
    hub and curves an arrow from each node to the next, which is how a loop or
    a repeating process reads.

    `frame="tablet"` mounts the whole thing on a lit screen inside a device
    bezel — the shape a lot of product thumbnails use to say "this is software".

    Nodes are distributed around an ellipse rather than a circle: thumbnails are
    16:9, and a true circle wastes the horizontal space that matters.
    """
    if not nodes:
        raise ValueError("node_diagram needs at least one node")

    key = json.dumps([width, nodes, center_icon, center_label, accent, text_color,
                      line_color, dark, round(scale, 4), layout, frame, frame_glow,
                      screen], sort_keys=True, default=str)
    hit = _CACHE.get(key)
    if hit is not None:
        _CACHE.move_to_end(key)
        return hit.copy()

    # A cycle has no hub and reads better squarer; a hub layout needs the
    # width for its labels.
    height = int(width * (0.84 if layout == "cycle" else 0.72))
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    cx, cy = width / 2, height / 2
    hub = int(width * 0.155 * scale)
    tile = int(width * 0.098 * scale)
    label_px = max(11, int(width * 0.032 * scale))
    font = load_font("inter", label_px, "SemiBold")

    rx, ry = width * 0.375, height * 0.355
    line = line_color or (text_color if dark else (60, 60, 70))

    n = len(nodes)
    # Start at the top and walk clockwise, so reading order matches the list.
    positions = []
    for i in range(n):
        angle = -math.pi / 2 + (2 * math.pi * i / n)
        positions.append((cx + rx * math.cos(angle), cy + ry * math.sin(angle)))

    if layout == "cycle":
        # Arrow from each node to the next, stopping clear of both tiles so the
        # heads read as pointing at something rather than into it.
        for i, (px, py) in enumerate(positions):
            qx, qy = positions[(i + 1) % n]
            vx, vy = qx - px, qy - py
            dist = math.hypot(vx, vy) or 1
            ux, uy = vx / dist, vy / dist
            gap = tile * 0.78
            canvas.alpha_composite(hand_arrow(
                (width, height),
                (px + ux * gap, py + uy * gap),
                (qx - ux * gap, qy - uy * gap),
                line, width=max(2, int(width * 0.008)), bow=0.30,
                head_len=width * 0.035, opacity=235,
            ))
        draw = ImageDraw.Draw(canvas)

    # Connectors first, so tiles sit on top of the line ends.
    for px, py in positions if layout != "cycle" else []:
        vx, vy = px - cx, py - cy
        dist = math.hypot(vx, vy) or 1
        ux, uy = vx / dist, vy / dist
        _dashed_line(
            draw,
            (cx + ux * hub * 0.62, cy + uy * hub * 0.62),
            (px - ux * tile * 0.62, py - uy * tile * 0.62),
            line, max(2, int(width * 0.005)), int(width * 0.022), int(width * 0.016),
            opacity=150,
        )

    # Hub
    if layout == "cycle":
        pass
    elif center_icon:
        icon = load_image(center_icon)
        if icon is not None:
            ratio = hub / max(icon.width, icon.height)
            icon = icon.resize((max(1, int(icon.width * ratio)), max(1, int(icon.height * ratio))),
                               Image.LANCZOS)
            sheet = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
            sheet.paste(icon, (int(cx - icon.width / 2), int(cy - icon.height / 2)))
            canvas.alpha_composite(drop_shadow(sheet, (0, int(6 * scale)), int(14 * scale), 0.5))
            canvas.alpha_composite(sheet)
    else:
        hub_tile = rounded_rect((hub, hub), int(hub * 0.26), accent + (255,))
        sheet = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        sheet.paste(hub_tile, (int(cx - hub / 2), int(cy - hub / 2)))
        canvas.alpha_composite(drop_shadow(sheet, (0, int(6 * scale)), int(14 * scale), 0.5))
        canvas.alpha_composite(sheet)
        # Asterisk mark, evocative without copying any real product logo.
        d2 = ImageDraw.Draw(canvas)
        for k in range(8):
            a = math.pi * k / 4
            d2.line([(cx, cy), (cx + math.cos(a) * hub * 0.32, cy + math.sin(a) * hub * 0.32)],
                    fill=(255, 255, 255, 240), width=max(3, int(hub * 0.07)))

    if center_label and layout != "cycle":
        cw = draw.textlength(center_label, font=font)
        draw.text((cx - cw / 2, cy + hub * 0.62), center_label, font=font,
                  fill=text_color + (255,))

    # Nodes and their labels
    for (px, py), node in zip(positions, nodes):
        t = _node_tile(tile, accent, node.get("icon"), dark)
        sheet = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        sheet.paste(t, (int(px - tile / 2), int(py - tile / 2)))
        canvas.alpha_composite(drop_shadow(sheet, (0, int(4 * scale)), int(10 * scale), 0.45))
        canvas.alpha_composite(sheet)

        label = str(node.get("label", "")).strip()
        if not label:
            continue
        lw = draw.textlength(label, font=font)
        lx = px - lw / 2
        # Labels sit outward from the hub: above for the top half, below for the
        # bottom half. Always placing them below buries the top row's captions
        # in the hub.
        above = py < cy - tile * 0.2
        ly = (py - tile * 0.62 - label_px * 1.15) if above else (py + tile * 0.62)
        # Nudge back inside the frame rather than letting them clip.
        lx = max(2, min(lx, width - lw - 2))
        ly = max(2, min(ly, height - label_px - 2))
        draw.text((lx, ly), label, font=font, fill=text_color + (255,))

    if frame:
        canvas = _mount_in_device(canvas, screen, frame_glow, scale)

    _CACHE[key] = canvas
    if len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)
    return canvas.copy()


def _mount_in_device(content: Image.Image, screen: RGB, glow: RGB | None,
                     scale: float) -> Image.Image:
    """Put the diagram on a lit screen inside a rounded bezel."""
    cw, ch = content.size
    bezel = max(8, int(cw * 0.035))
    pad = int(cw * 0.10)
    sw, sh = cw + bezel * 2, ch + bezel * 2
    out = Image.new("RGBA", (sw + pad * 2, sh + pad * 2), (0, 0, 0, 0))

    if glow:
        # Two passes: a tight bright core plus a wide soft bloom. One blurred
        # rectangle reads as a drop shadow rather than an emitting screen.
        for spread, alpha in ((0.22, 235), (0.55, 150)):
            halo = rounded_rect((sw, sh), int(bezel * 1.6), glow + (alpha,))
            sheet = Image.new("RGBA", out.size, (0, 0, 0, 0))
            sheet.paste(halo, (pad, pad))
            out.alpha_composite(sheet.filter(ImageFilter.GaussianBlur(radius=pad * spread)))

    body = rounded_rect((sw, sh), int(bezel * 1.6), (24, 27, 33, 255))
    out.alpha_composite(body, (pad, pad))
    out.alpha_composite(rounded_rect((cw, ch), int(bezel * 0.7), screen + (255,)),
                        (pad + bezel, pad + bezel))
    out.alpha_composite(content, (pad + bezel, pad + bezel))
    return out
