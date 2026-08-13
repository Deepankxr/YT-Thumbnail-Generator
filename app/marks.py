"""Pixel-art marks drawn from sprite grids.

Scaled up with NEAREST so the pixels stay hard-edged. A diffusion model asked
for "a pixel robot" produces something that is almost pixel-art — subtly wrong
grid, soft edges, inconsistent between generations — which is worse than useless
when three of them sit side by side in one frame.

A sprite is a list of equal-length strings, one character per pixel:
    "." transparent   "#" body   "o" dark detail   "*" highlight
"""

from __future__ import annotations

from PIL import Image

RGB = tuple[int, int, int]

# Chunky bot: detached motion dashes either side, two dark eyes, a bolt, feet.
ROBOT = [
    "......##########......",
    "......##########......",
    "....##############....",
    "....##oo######oo##....",
    "....##oo######oo##....",
    "....##############....",
    "##..##############..##",
    "....######**######....",
    "##..#####**#######..##",
    "....####*****#####....",
    "##..######**######..##",
    "....#####**#######....",
    "....##############....",
    "....###..####..###....",
    "....###..####..###....",
]

BOLT = [
    "......***.....",
    ".....***......",
    "....***.......",
    "...*******....",
    "......***.....",
    ".....***......",
    "....***.......",
]

PALETTE_KEYS = {"#": "body", "o": "dark", "*": "accent"}


def sprite(
    grid: list[str],
    pixel: int,
    *,
    body: RGB = (232, 86, 58),
    dark: RGB = (24, 24, 28),
    accent: RGB = (255, 205, 60),
) -> Image.Image:
    """Render a sprite grid at `pixel` px per cell."""
    if not grid:
        raise ValueError("sprite grid is empty")
    width = max(len(row) for row in grid)
    colours = {"body": body, "dark": dark, "accent": accent}

    small = Image.new("RGBA", (width, len(grid)), (0, 0, 0, 0))
    px = small.load()
    for y, row in enumerate(grid):
        for x, ch in enumerate(row.ljust(width, ".")):
            key = PALETTE_KEYS.get(ch)
            if key:
                px[x, y] = colours[key] + (255,)

    pixel = max(1, int(pixel))
    return small.resize((width * pixel, len(grid) * pixel), Image.NEAREST)


def robot(size: int, **colours) -> Image.Image:
    """A pixel robot sized to fit a `size` x `size` box."""
    pixel = max(1, size // max(len(ROBOT), max(len(r) for r in ROBOT)))
    img = sprite(ROBOT, pixel, **colours)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.alpha_composite(img, ((size - img.width) // 2, (size - img.height) // 2))
    return canvas


def bolt(size: int, colour: RGB = (255, 205, 60)) -> Image.Image:
    pixel = max(1, size // max(len(BOLT), max(len(r) for r in BOLT)))
    return sprite(BOLT, pixel, accent=colour)
