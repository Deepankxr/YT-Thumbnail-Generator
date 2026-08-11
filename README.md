# YT Thumbnail Generator

A microservice that composites YouTube thumbnails in the visual language of
Nick Saraev, Nate Herk, Jack Roberts and Liam Ottley. FastAPI + Pillow,
Docker-ready for Coolify, same shape as `pptx-service`.

**~150–200 ms per render. $0 per render** unless you opt into AI hero art.

## The idea

Every thumbnail on those four channels decomposes into four layers:

| Layer | Content | Who makes it |
|---|---|---|
| 1. Background | Flat colour, gradient, glow, or a photo plate | CSS-ish / supplied |
| 2. Hero object | 3D icon, UI card, device mockup, generated scene | **AI (optional)** |
| 3. Creator cutout | Matted PNG of the creator | **Your photo library** |
| 4. Text, arrow, plate | Headline and emphasis marks | **Deterministic code** |

Only layer 2 ever touches an image model. Layers 3 and 4 are composited, which
is what keeps typography exact and the creator's face free of identity drift —
and it's why a re-render to fix a typo costs nothing instead of another API call.

## Quick start

```bash
pip install -r requirements.txt
```

Render the sample set without starting a server:

```bash
python3 render_local.py
```

Run the API:

```bash
uvicorn app.main:app --reload --port 8080
```

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness + version |
| GET | `/styles` | Presets, palettes, font and accent treatment |
| POST | `/generate` | Render a thumbnail |

Set `THUMB_API_KEY` to require an `x-api-key` header.

### POST /generate

```json
{
  "headline": "AI tools don't matter.",
  "style": "herk",
  "palette": "desk",
  "accent_words": ["matter."],
  "subject": "https://cdn.example.com/creator-cutout.png",
  "card_text": "The only kind of AI business that actually sells.",
  "output": "binary",
  "include_qa": true
}
```

`output: "binary"` returns raw PNG bytes — point an n8n HTTP Request node at it
with **Response Format: File** and it lands straight in `$binary`.
`output: "base64"` returns `{ filename, mimeType, data, qa }`.

Assets (`subject`, `hero`, `background`) accept an https URL, a `data:` URI,
raw base64, or a path on the server.

## Styles

| Style | Look | Type | Accent |
|---|---|---|---|
| `saraev` | Clean, premium, restrained. Flat palette, one hand-drawn arrow. | Poppins ExtraBold | Underline |
| `herk` | Photo plate, big face right, rendered UI card. | Inter Black | Cyan pill |
| `roberts` | High energy. Neon rim light, backlight glow, hard stroke. | Montserrat Black | Blue pill |
| `ottley` | Editorial and loud. Full-width band, floating 3D logos, group shots. | Archivo Black, compressed caps | Hard red plate + yellow swash |

Each carries its own palettes (`GET /styles`). Supply a light palette and the
type, arrow and scrim automatically flip to dark — there's a luminance test, not
a hardcoded list.

## Creative controls

The presets are a starting point, not a cage. Every knob below is per-request.

| Field | Does |
|---|---|
| `accent_words` | Words that get the style's accent treatment — rounded pill (`herk`, `roberts`) or hard plate (`ottley`) |
| `word_colors` | Per-word colour, e.g. `{"STOP": "#FFD400"}`. Beats accent treatment for that word, so one line can carry two colours |
| `text_position` | Move the headline band to `top` or `bottom`. The scrim and the QA probe follow it |
| `subjects` | Several cutouts for a group shot, overlapped left to right. A `null` slot renders the placeholder so layouts can be previewed before assets exist |
| `icons` | Floating 3D logos dropped into the style's icon slots |
| `subject_side` | Flip the cutout left or right |
| `palette` | Swap the background. Light palettes auto-flip type, arrow and scrim to dark via a luminance test |

Typography is driven off variable-font axes, so `ottley`'s compressed caps come
from Archivo's `wdth` axis at 72 rather than a second font file.

## Rendered props instead of generated ones

Nate's tweet cards and payment toasts are the elements diffusion models mangle
worst — small UI text comes out as gibberish. `app/cards.py` draws them:

- `card_text` → a social post card
- `toast_text` + `toast_amount` → a notification pill

Always legible, always free, and editable after the fact.

## Optional AI hero layer

Set `GEMINI_API_KEY` and pass `hero_prompt` to generate the hero object with
Nano Banana Pro (~$0.134/image at 1K–2K, 50% off via the Batch API). The prompt
is constrained to produce a compositable object — no text, no faces.

Without a key the service still renders everything else; `hero_prompt` returns
503 rather than failing the whole request.

## Feed-size QA

`include_qa: true` attaches a legibility report. It downsamples to 168px — the
width a thumbnail actually occupies in a browsing feed — and measures contrast
**inside the headline box**, which is the failure nobody catches while zoomed in
at 100%.

```json
{ "feed_width": 168, "headline_contrast": 81.2, "edge_energy": 65.2, "verdict": "ok" }
```

On binary responses the same result comes back as `x-qa-verdict` and
`x-qa-contrast` headers.

## Fonts

Bundled under `assets/fonts`, all SIL OFL (Montserrat, Inter, Archivo, Anton,
Poppins). Shipping them in the image means renders are byte-identical between a
laptop and the container.

The OFL permits commercial use and embedding but requires the licence to travel
with the files, so it lives at `assets/fonts/OFL.txt` and is copied into the
image. The fonts are third-party and are not covered by this repository's own
licence terms.

## Deploy

Coolify auto-detects the `Dockerfile`; it honours the injected `$PORT` and
defaults to 8080.

```bash
docker build -t thumbnail-service .
docker run -p 8080:8080 -e THUMB_API_KEY=... thumbnail-service
```

## Known gaps

- The default subject is a placeholder silhouette. Real output needs matted PNGs
  of the creator — shoot ~20 once (a few expressions, a few angles), matte with
  BiRefNet (MIT, commercially free), reuse forever.
- No auto-matting endpoint yet; cutouts are supplied pre-matted.
- Layouts are one canonical arrangement per style (plus the `text_position`
  override). Multi-variant layout search is the obvious next step, since it's
  what a selection loop would rank.
- Group shots space subjects evenly. Liam's real ones vary depth and scale per
  person; that needs per-slot scale/offset controls.
