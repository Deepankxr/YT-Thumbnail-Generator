"""Optional AI hero-visual generation (the only layer a model should touch).

The compositor works fully offline; this module is what you reach for when the
thumbnail needs generated art — Jack-style chrome robots, a 3D glossy icon, a
lit product scene. Text and the creator's face deliberately never go through
here: those are composited so typography stays exact and identity never drifts.

Set GEMINI_API_KEY to enable. Nano Banana Pro is ~$0.134/image at 1K-2K, so a
three-variant run costs about $0.40.
"""

from __future__ import annotations

import base64
import os

import requests

MODEL = os.environ.get("THUMB_HERO_MODEL", "gemini-3-pro-image-preview")
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
TIMEOUT = 120

# Steers the model toward a compositable prop rather than a finished thumbnail.
HERO_SYSTEM = (
    "Generate a single hero object or scene for a YouTube thumbnail. "
    "No text, no words, no letters, no watermarks, no human faces. "
    "Centred subject, dramatic studio lighting, high contrast, clean separation "
    "from the background so it can be cut out and composited."
)


class HeroUnavailable(RuntimeError):
    """Raised when no API key is configured."""


def generate_hero(prompt: str, *, aspect: str = "1:1", api_key: str | None = None) -> str:
    """Generate one hero image and return it base64-encoded.

    The return value drops straight into `ThumbnailRequest.hero`.
    """
    key = api_key or os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise HeroUnavailable(
            "GEMINI_API_KEY is not set; supply `hero` as a URL/base64 instead, "
            "or run without a hero layer"
        )

    body = {
        "contents": [{"parts": [{"text": f"{HERO_SYSTEM}\n\nSubject: {prompt}"}]}],
        "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": aspect}},
    }

    resp = requests.post(
        ENDPOINT.format(model=MODEL),
        json=body,
        headers={"x-goog-api-key": key, "Content-Type": "application/json"},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    payload = resp.json()

    for candidate in payload.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            data = part.get("inlineData", {}).get("data")
            if data:
                # Validate before handing it to the compositor, so a malformed
                # response fails here rather than deep inside PIL.
                base64.b64decode(data, validate=True)
                return data

    raise RuntimeError(f"no image in response from {MODEL}: {str(payload)[:300]}")
