"""OpenRouter client for AI image editing, using the caller's own API key.

The key is never stored, never logged, and never written to disk. It arrives on
a request header (not the JSON body) specifically because n8n persists full
request bodies in its execution history — a key in the body would sit in that
history indefinitely.

Only Google and OpenAI publish image-output models on OpenRouter; there is no
FLUX, Seedream or Stable Diffusion there. The curated ordering below reflects
what is actually good at *editing an existing thumbnail*, which is a narrower
question than raw image quality.
"""

from __future__ import annotations

import base64
import re

import requests

API_BASE = "https://openrouter.ai/api/v1"
TIMEOUT = 180

# Referer/title show up in the caller's OpenRouter dashboard, which makes spend
# attributable per app rather than an unlabelled lump.
HEADERS_EXTRA = {
    "HTTP-Referer": "https://github.com/Deepankxr/YT-Thumbnail-Generator",
    "X-Title": "YT Thumbnail Generator",
}

# Ranked for thumbnail editing. Prices are per output-image token; the per-image
# estimate assumes ~1120 tokens for a 1-2K image, which is what Google documents.
CURATED = [
    ("google/gemini-3-pro-image", "Nano Banana Pro", "Best quality and text handling. Default.", 0.134),
    ("google/gemini-3.1-flash-image", "Nano Banana 2", "Roughly half the price, close quality.", 0.067),
    ("google/gemini-2.5-flash-image", "Nano Banana", "Cheapest Google option, good for iterating.", 0.039),
    ("google/gemini-3.1-flash-lite-image", "Nano Banana 2 Lite", "Fastest and cheapest.", None),
    ("openai/gpt-5-image", "GPT-5 Image", "Different look; useful as a second opinion.", None),
    ("openai/gpt-5-image-mini", "GPT-5 Image Mini", "Cheaper OpenAI option.", None),
]

DATA_URI = re.compile(r"^data:image/[a-zA-Z.+-]+;base64,")


class OpenRouterError(RuntimeError):
    """Anything the caller can act on: bad key, no credit, model refused."""


def list_models() -> list[dict]:
    """Image-editing models available on OpenRouter, curated order first.

    Needs no key — the model list is public, so the studio can populate its
    picker before the user has pasted anything.
    """
    try:
        resp = requests.get(f"{API_BASE}/models", timeout=30)
        resp.raise_for_status()
        live = {m["id"]: m for m in resp.json().get("data", [])}
    except Exception as exc:
        raise OpenRouterError(f"could not reach OpenRouter: {exc}") from exc

    out = []
    for model_id, label, note, est in CURATED:
        m = live.get(model_id)
        if not m:
            continue  # retired upstream; don't offer something that will 404
        arch = m.get("architecture") or {}
        if "image" not in arch.get("output_modalities", []):
            continue
        out.append({
            "id": model_id,
            "label": label,
            "note": note,
            "accepts_image_input": "image" in arch.get("input_modalities", []),
            "estimated_cost_per_image": est,
            "price_per_output_image_token": (m.get("pricing") or {}).get("image_output"),
        })
    return out


def _extract_image(payload: dict) -> str:
    """Pull the returned image out of a chat completion, as bare base64."""
    for choice in payload.get("choices", []):
        message = choice.get("message") or {}
        for img in message.get("images") or []:
            url = (img.get("image_url") or {}).get("url", "")
            if DATA_URI.match(url):
                return DATA_URI.sub("", url)
        # Some providers inline the image in the content array instead.
        content = message.get("content")
        if isinstance(content, list):
            for part in content:
                url = ((part or {}).get("image_url") or {}).get("url", "")
                if DATA_URI.match(url):
                    return DATA_URI.sub("", url)

    # A refusal or a text-only reply is the common failure; surface what it said.
    text = ""
    for choice in payload.get("choices", []):
        c = (choice.get("message") or {}).get("content")
        if isinstance(c, str):
            text = c
            break
    raise OpenRouterError(
        f"model returned no image{': ' + text[:300] if text else ''}. "
        "Some models refuse edits to photos of real people; try a different "
        "instruction or model."
    )


def edit_image(image_b64: str, instruction: str, model: str, api_key: str) -> str:
    """Send an image plus an instruction, return the edited image as base64."""
    if not api_key:
        raise OpenRouterError("no OpenRouter API key supplied")

    body = {
        "model": model,
        "modalities": ["image", "text"],
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": instruction},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
            ],
        }],
    }

    try:
        resp = requests.post(
            f"{API_BASE}/chat/completions",
            json=body,
            headers={"Authorization": f"Bearer {api_key}",
                     "Content-Type": "application/json", **HEADERS_EXTRA},
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        raise OpenRouterError(f"request to OpenRouter failed: {exc}") from exc

    if resp.status_code == 401:
        raise OpenRouterError("OpenRouter rejected the API key (401).")
    if resp.status_code == 402:
        raise OpenRouterError("OpenRouter reports insufficient credit (402).")
    if resp.status_code == 429:
        raise OpenRouterError("Rate limited by OpenRouter (429). Try again shortly.")
    if resp.status_code >= 400:
        # Never echo the whole response — it can contain the request we sent.
        detail = ""
        try:
            detail = str((resp.json().get("error") or {}).get("message", ""))[:300]
        except Exception:
            pass
        raise OpenRouterError(f"OpenRouter error {resp.status_code}: {detail or 'unknown'}")

    data = _extract_image(resp.json())
    base64.b64decode(data, validate=True)  # fail here rather than inside PIL
    return data
