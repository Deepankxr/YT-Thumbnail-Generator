"""Turn a YouTube URL into a starting spec by looking at its thumbnail.

A vision model reads the reference and answers with a ThumbnailRequest. It is
told the exact catalogue of styles, palettes and fields this renderer supports,
generated from the live presets rather than hardcoded, so it cannot invent a
style that does not exist.

The result is a *starting point*, not a copy. The renderer has no access to the
original's photography, background art or 3D props, so what transfers is the
structure — layout, type treatment, emphasis, depth — which is the reusable part
anyway. The person in the frame is deliberately never reproduced: `subject` comes
back empty for the caller to fill with their own cutout.
"""

from __future__ import annotations

import base64
import json
import re

import requests

from .openrouter import API_BASE, HEADERS_EXTRA, OpenRouterError
from .styles import STYLES, WORD_PALETTE

TIMEOUT = 120

# Curated vision models, cheapest last. All confirmed to accept image input and
# return text on OpenRouter.
VISION_MODELS = [
    ("anthropic/claude-sonnet-5", "Claude Sonnet 5", "Best structure and type reading. Default."),
    ("google/gemini-3.1-pro-preview", "Gemini 3.1 Pro", "Strong alternative, similar price."),
    ("openai/gpt-5.4-mini", "GPT-5.4 Mini", "Cheaper, usually good enough."),
    ("google/gemini-3.1-flash-lite", "Gemini 3.1 Flash Lite", "Cheapest."),
]

YT_PATTERNS = [
    re.compile(r"(?:youtube\.com/watch\?(?:.*&)?v=)([\w-]{11})"),
    re.compile(r"(?:youtu\.be/)([\w-]{11})"),
    re.compile(r"(?:youtube\.com/shorts/)([\w-]{11})"),
    re.compile(r"(?:youtube\.com/embed/)([\w-]{11})"),
    re.compile(r"^([\w-]{11})$"),
]


def video_id(url: str) -> str | None:
    """Pull the id out of any of YouTube's URL shapes, or a bare id."""
    url = (url or "").strip()
    for pattern in YT_PATTERNS:
        m = pattern.search(url)
        if m:
            return m.group(1)
    return None


def fetch_thumbnail(url: str) -> tuple[str, str]:
    """Return (base64 jpeg, resolved source url).

    Accepts a YouTube link or a direct image URL. maxres does not exist for
    every video, so fall back through the sizes YouTube always generates.
    """
    vid = video_id(url)
    candidates = (
        [f"https://i.ytimg.com/vi/{vid}/maxresdefault.jpg",
         f"https://i.ytimg.com/vi/{vid}/sddefault.jpg",
         f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"]
        if vid else
        ([url] if url.lower().startswith(("http://", "https://")) else [])
    )
    if not candidates:
        raise OpenRouterError(
            "Could not read a YouTube video id from that. Paste a watch/youtu.be/"
            "shorts link, a bare 11-character id, or a direct image URL.")

    last = ""
    for candidate in candidates:
        try:
            resp = requests.get(candidate, timeout=30)
            # YouTube serves a 120x90 grey placeholder rather than 404ing for a
            # missing size, so treat suspiciously small payloads as misses too.
            if resp.status_code == 200 and len(resp.content) > 6000:
                return base64.b64encode(resp.content).decode(), candidate
            last = f"{resp.status_code} ({len(resp.content)} bytes)"
        except requests.RequestException as exc:
            last = str(exc)
    raise OpenRouterError(f"Could not fetch a thumbnail for that link: {last}")


def _catalogue() -> str:
    """Describe what the renderer can actually do, from the live presets."""
    lines = []
    for s in STYLES.values():
        lines.append(f'- "{s.name}": {s.description} Palettes: '
                     f'{", ".join(sorted(s.palettes))}.')
    swatches = ", ".join(hexv for group in WORD_PALETTE.values() for _, hexv in group)
    return "STYLES:\n" + "\n".join(lines) + f"\n\nWORD COLOUR SWATCHES: {swatches}"


PROMPT = """You are looking at a YouTube thumbnail. Describe how to rebuild its
DESIGN using the renderer below, then return the settings as JSON.

{catalogue}

Return ONLY a JSON object with these keys (omit any that do not apply):
  headline        string, the main text, kept verbatim where legible
  style           one of the style names above — pick the closest visual match
  palette         one of that style's palettes
  accent_words    array of words from the headline that are highlighted,
                  boxed, underlined or a different colour
  word_colors     object mapping a lowercase word to a hex from the swatches,
                  only when a word is clearly its own colour
  text_position   "top" or "bottom" if the headline sits in a band there
  subject_side    "left" or "right" — which side the person occupies
  behind          array containing "headline" ONLY if text passes behind the person
  arrow           true only if a drawn arrow points at something
  labels          array of small standalone captions, each
                  {{text, x, y, size, arrow_to}} with x/y as 0-1 fractions of
                  width/height from the top-left
  diagram         {{nodes:[{{label}}], center_label}} if there is a hub-and-spoke
                  graph of labelled nodes
  card_text       the body text if a social-post card is shown
  toast_text, toast_amount   if a notification pill is shown
  notes           one sentence on anything the renderer cannot reproduce

Rules:
- Do NOT describe the person, their face, clothing or pose. The caller supplies
  their own photo. Never set "subject".
- Judge style by visual language, not subject matter: restrained and quiet ->
  enterprise or saraev; neon and glowing -> roberts; compressed caps with hard
  colour plates -> ottley; photo plate with a UI card -> herk.
- Positions are fractions between 0 and 1.
- Output raw JSON. No markdown fence, no commentary outside the object."""


def _extract_json(text: str) -> dict:
    """Models fence their JSON about half the time; take the object either way."""
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            text = text[start:end + 1]
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise OpenRouterError(f"Model did not return usable JSON: {exc}") from exc


# Anything outside this is either not ours to set or not the model's to guess.
ALLOWED = {
    "headline", "style", "palette", "accent_words", "word_colors", "text_position",
    "subject_side", "behind", "arrow", "labels", "diagram", "card_text",
    "toast_text", "toast_amount",
}


def clean_spec(raw: dict) -> tuple[dict, list[str]]:
    """Keep only fields we support and values the renderer will accept.

    A model will confidently name a style or palette that does not exist; better
    to drop it and say so than to 422 the whole analysis.
    """
    warnings: list[str] = []
    spec = {k: v for k, v in raw.items() if k in ALLOWED and v not in (None, "", [], {})}

    style = spec.get("style")
    if style not in STYLES:
        if style:
            warnings.append(f"unknown style '{style}', fell back to saraev")
        spec["style"] = "saraev"
    preset = STYLES[spec["style"]]

    if spec.get("palette") not in preset.palettes:
        if spec.get("palette"):
            warnings.append(f"palette '{spec['palette']}' is not in {spec['style']}, using default")
        spec.pop("palette", None)

    if not str(spec.get("headline", "")).strip():
        spec["headline"] = "Untitled"
        warnings.append("no headline was legible")
    spec["headline"] = str(spec["headline"])[:120]

    for key in ("accent_words", "behind"):
        if key in spec:
            spec[key] = [str(v) for v in spec[key] if isinstance(v, (str, int))][:8]

    if "labels" in spec:
        clean = []
        for lab in spec["labels"][:8]:
            if not isinstance(lab, dict) or not str(lab.get("text", "")).strip():
                continue
            item = {"text": str(lab["text"])[:60],
                    "x": min(1.0, max(0.0, float(lab.get("x", 0.08)))),
                    "y": min(1.0, max(0.0, float(lab.get("y", 0.08)))),
                    "size": min(0.4, max(0.02, float(lab.get("size", 0.055))))}
            tgt = lab.get("arrow_to")
            if isinstance(tgt, (list, tuple)) and len(tgt) == 2:
                item["arrow_to"] = [min(1.0, max(0.0, float(tgt[0]))),
                                    min(1.0, max(0.0, float(tgt[1])))]
            clean.append(item)
        spec["labels"] = clean

    if "diagram" in spec:
        nodes = (spec["diagram"] or {}).get("nodes") or []
        nodes = [{"label": str((n or {}).get("label", ""))[:40]} for n in nodes[:10]
                 if str((n or {}).get("label", "")).strip()]
        if nodes:
            spec["diagram"] = {"nodes": nodes}
            if (spec.get("diagram") or {}) and raw.get("diagram", {}).get("center_label"):
                spec["diagram"]["center_label"] = str(raw["diagram"]["center_label"])[:40]
        else:
            spec.pop("diagram")

    if "word_colors" in spec:
        valid = {h.lower() for g in WORD_PALETTE.values() for _, h in g}
        wc = {}
        for word, hexv in (spec["word_colors"] or {}).items():
            h = str(hexv).strip()
            if re.fullmatch(r"#[0-9a-fA-F]{6}", h):
                wc[str(word).lower()] = h
                if h.lower() not in valid:
                    warnings.append(f"'{word}' used a colour outside the palette ({h})")
        spec["word_colors"] = wc

    # The caller's own photo goes here; the reference's person never does.
    spec.pop("subject", None)
    return spec, warnings


def analyze(image_b64: str, api_key: str, model: str) -> tuple[dict, list[str], str]:
    """Return (spec, warnings, notes) for a thumbnail image."""
    if not api_key:
        raise OpenRouterError("no OpenRouter API key supplied")

    body = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": PROMPT.format(catalogue=_catalogue())},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
            ],
        }],
    }

    try:
        resp = requests.post(
            f"{API_BASE}/chat/completions", json=body,
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
    if resp.status_code >= 400:
        detail = ""
        try:
            detail = str((resp.json().get("error") or {}).get("message", ""))[:300]
        except Exception:
            pass
        raise OpenRouterError(f"OpenRouter error {resp.status_code}: {detail or 'unknown'}")

    payload = resp.json()
    try:
        text = payload["choices"][0]["message"]["content"]
        if isinstance(text, list):  # some providers return content parts
            text = "".join(p.get("text", "") for p in text if isinstance(p, dict))
    except (KeyError, IndexError) as exc:
        raise OpenRouterError(f"unexpected response shape: {str(payload)[:200]}") from exc

    raw = _extract_json(text)
    notes = str(raw.get("notes", ""))[:300]
    spec, warnings = clean_spec(raw)
    return spec, warnings, notes
