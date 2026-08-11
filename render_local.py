"""Render sample thumbnails without starting the server.

    python3 render_local.py              # all presets -> out/
    python3 render_local.py --subject cutout.png
"""

from __future__ import annotations

import argparse
import os

from app.compositor import legibility_report, render

SAMPLES = [
    dict(name="saraev-violet", style_name="saraev", palette="violet",
         headline="This changes everything.", subject_side="right"),
    dict(name="saraev-cream", style_name="saraev", palette="cream",
         headline="No one is doing this.", subject_side="right"),
    dict(name="saraev-ink", style_name="saraev", palette="ink",
         headline="Agents can do it all.", subject_side="right"),
    dict(name="herk-card", style_name="herk", palette="desk",
         headline="AI tools don't matter.", accent_words=["matter."],
         card_text="The only kind of AI business that actually sells.",
         card_name="Your Name", card_handle="@yourhandle", arrow=False),
    dict(name="herk-toast", style_name="herk", palette="warm",
         headline="Become the AI person", accent_words=["AI", "person"],
         toast_text="Payment received", toast_amount="$17,532", arrow=False),
    dict(name="roberts-electric", style_name="roberts", palette="electric",
         headline="AI agents, zero code", accent_words=["zero", "code"]),
    dict(name="roberts-inferno", style_name="roberts", palette="inferno",
         headline="This destroys AI slop", accent_words=["AI", "slop"]),
    dict(name="ottley-plate", style_name="ottley", palette="studio",
         headline="Claude changes everything", accent_words=["everything"], arrow=False),
    dict(name="ottley-twotone", style_name="ottley", palette="studio",
         headline="Stop selling workflows",
         word_colors={"stop": "#FFD400"}, arrow=False),
    dict(name="ottley-paper", style_name="ottley", palette="paper",
         headline="Automate with AI agents", accent_words=["AI", "agents"], arrow=False,
         text_position="top"),
    dict(name="ottley-group", style_name="ottley", palette="ocean",
         headline="AI in paradise", accent_words=["paradise"], arrow=False,
         text_position="top", subjects=[None, None, None, None]),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--subject", help="Path to a matted PNG cutout of the creator")
    parser.add_argument("--out", default="out")
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)

    for sample in SAMPLES:
        name = sample.pop("name")
        img = render(subject=args.subject, **sample)
        path = os.path.join(args.out, f"{name}.png")
        img.save(path)
        qa = legibility_report(img, sample["style_name"], text_position=sample.get("text_position"))
        print(f"{path:36s} {qa['verdict']:5s} contrast={qa['headline_contrast']:6.2f} "
              f"edges={qa['edge_energy']:5.2f}")


if __name__ == "__main__":
    main()
