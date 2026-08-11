"""Font and image loading.

Fonts ship with the repo (SIL OFL) so rendering is byte-identical between a
laptop and the container. Images can arrive as a URL, a base64 blob, or a path
on disk — n8n tends to hand us base64, humans tend to hand us URLs.
"""

from __future__ import annotations

import base64
import binascii
import io
import os
from functools import lru_cache

import requests
from PIL import Image, ImageFont

FONT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "fonts")

# family -> filename. Variable fonts carry the whole weight axis in one file.
FONT_FILES = {
    "montserrat": "Montserrat[wght].ttf",
    "inter": "Inter[opsz,wght].ttf",
    "archivo": "Archivo[wdth,wght].ttf",
    "anton": "Anton-Regular.ttf",
    "poppins": "Poppins-ExtraBold.ttf",
    "poppins-bold": "Poppins-Bold.ttf",
}

# Anton and the static Poppins cuts have no variation axis to set.
STATIC_FONTS = {"anton", "poppins", "poppins-bold"}

# Named weights -> numeric, for families where we also drive the width axis and
# therefore have to set every axis by value rather than by instance name.
WEIGHT_VALUES = {
    "Thin": 100, "ExtraLight": 200, "Light": 300, "Regular": 400, "Medium": 500,
    "SemiBold": 600, "Bold": 700, "ExtraBold": 800, "Black": 900,
}

# Families exposing a wdth axis, in the order set_variation_by_axes expects.
VARIABLE_AXES = {"archivo": ("wght", "wdth")}

FETCH_TIMEOUT = 20
MAX_IMAGE_BYTES = 25 * 1024 * 1024


@lru_cache(maxsize=512)
def load_font(family: str, size: int, weight: str = "Black",
              width: float | None = None) -> ImageFont.FreeTypeFont:
    """Return a font at `size` px, set to `weight` (and `width` where supported).

    `width` drives the wdth axis — values near 70 give the compressed all-caps
    display face that carries Liam Ottley's headlines. Ignored by families with
    no width axis.

    Sizes are cached because the auto-fit search asks for dozens of sizes per
    render and FreeType face construction is not free.
    """
    family = family.lower()
    filename = FONT_FILES.get(family)
    if filename is None:
        raise ValueError(f"unknown font family '{family}'; have {sorted(FONT_FILES)}")

    path = os.path.join(FONT_DIR, filename)
    font = ImageFont.truetype(path, size)

    if family in STATIC_FONTS:
        return font

    if width is not None and family in VARIABLE_AXES:
        try:
            # Setting one axis by value means setting them all by value.
            font.set_variation_by_axes([float(WEIGHT_VALUES.get(weight, 900)), float(width)])
            return font
        except Exception:
            pass  # fall through to the named instance

    try:
        font.set_variation_by_name(weight)
    except Exception:
        # Older FreeType, or a weight name this family doesn't publish.
        # Regular is a survivable fallback; the layout still holds.
        pass
    return font


def load_image(ref: str | None) -> Image.Image | None:
    """Load an image from an http(s) URL, a data/base64 blob, or a local path."""
    if not ref:
        return None

    ref = ref.strip()

    if ref.startswith(("http://", "https://")):
        resp = requests.get(ref, timeout=FETCH_TIMEOUT, stream=True)
        resp.raise_for_status()
        raw = resp.raw.read(MAX_IMAGE_BYTES + 1, decode_content=True)
        if len(raw) > MAX_IMAGE_BYTES:
            raise ValueError(f"image at {ref[:80]} exceeds {MAX_IMAGE_BYTES} bytes")
        return Image.open(io.BytesIO(raw)).convert("RGBA")

    if ref.startswith("data:"):
        _, _, payload = ref.partition(",")
        ref = payload

    # A path is far more likely than base64 to be short and contain a dot.
    if os.path.exists(ref):
        return Image.open(ref).convert("RGBA")

    try:
        raw = base64.b64decode(ref, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("image ref is not a URL, an existing path, or valid base64") from exc
    return Image.open(io.BytesIO(raw)).convert("RGBA")
