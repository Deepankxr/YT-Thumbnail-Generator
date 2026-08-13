"""Generate a presenter cutout from a reference photo of the same person.

An image model is given the caller's own photograph and asked for a studio
portrait of that person in a chosen pose, which is then matted and trimmed into
a `subject` cutout.

Worth knowing before reaching for this: a real photograph is better on every
axis that matters. The likeness is exact rather than approximate, it costs
nothing, and it does not drift — two generations of the same prompt produce
subtly different faces, so a channel built on generated avatars slowly stops
looking like one person. The reference channels this service imitates all use
real photography. Generation earns its place when a pose is needed that has not
been shot, or when a deliberately stylised look is wanted.
"""

from __future__ import annotations

import base64
import io

from PIL import Image

from .matting import MattingUnavailable, cut_out
from .openrouter import OpenRouterError, edit_image

# Poses worth having, phrased as instructions rather than labels. "Their right"
# is the viewer's left, which is where a left-hand screen or prop sits.
POSES = {
    "point-left": "pointing with one hand toward their own right, "
                  "arm raised to chest height, looking at the camera and smiling",
    "point-right": "pointing with one hand toward their own left, "
                   "arm raised to chest height, looking at the camera and smiling",
    "neutral": "facing the camera with a relaxed, friendly expression, arms down",
    "surprised": "eyes wide and mouth slightly open in genuine surprise, "
                 "hands raised near the shoulders",
    "arms-crossed": "arms crossed, confident and composed, looking at the camera",
    "thumbs-up": "giving a thumbs up with one hand, smiling at the camera",
}

PROMPT = (
    "Use the supplied photograph as the reference for this person's face, hair, "
    "glasses and skin tone. Generate a photographic studio portrait of the SAME "
    "person, {pose}.\n"
    "Requirements: even neutral studio lighting with no coloured cast; plain "
    "flat mid-grey background; head and upper body only, framed from the waist "
    "up; sharp focus; photographic realism, not an illustration or 3D render.\n"
    "The face must remain clearly recognisable as the person in the reference. "
    "Do not add text, logos or borders."
)


def generate_avatar(
    reference_b64: str,
    api_key: str,
    *,
    pose: str = "point-left",
    model: str = "google/gemini-3-pro-image",
    extra: str = "",
    height: int = 1400,
) -> tuple[str, dict]:
    """Return (cutout png base64, quality report).

    The generated frame is matted here rather than by the caller, because a
    portrait on a plain background is exactly the case local matting handles
    well — and it keeps the whole thing to one round trip.
    """
    if pose not in POSES and not extra:
        raise OpenRouterError(
            f"unknown pose '{pose}'; choose one of {sorted(POSES)} or pass `extra`")

    instruction = PROMPT.format(pose=POSES.get(pose, POSES["neutral"]))
    if extra:
        instruction += "\n" + extra.strip()

    generated = edit_image(reference_b64, instruction, model, api_key)

    img = Image.open(io.BytesIO(base64.b64decode(generated))).convert("RGB")
    try:
        cut, backend = cut_out(img)
    except MattingUnavailable as exc:
        raise OpenRouterError(
            f"the avatar was generated but could not be cut out: {exc}") from exc

    bbox = cut.getchannel("A").getbbox()
    if bbox:
        cut = cut.crop(bbox)
    ratio = height / cut.height
    cut = cut.resize((max(1, int(cut.width * ratio)), height), Image.LANCZOS)

    alpha = cut.getchannel("A")
    hist = alpha.histogram()
    total = cut.width * cut.height
    report = {
        "size": f"{cut.width}x{cut.height}",
        "matted_with": backend,
        "coverage": round(sum(hist[241:]) / total, 3),
        "soft_edge_ratio": round(sum(hist[17:240]) / total, 4),
        "pose": pose,
        "model": model,
    }
    report["verdict"] = "ok" if report["coverage"] > 0.12 else "check"

    buf = io.BytesIO()
    cut.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode(), report
