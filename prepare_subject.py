"""Turn a raw photo of a person into a cutout the compositor can use.

    python3 prepare_subject.py photo.jpg -o assets/subjects/deepankar-01.png
    python3 prepare_subject.py shoot/*.jpg -o assets/subjects/     # batch

Removes the background, trims to the subject, normalises the size, and reports
whether the result is actually good enough to use. Run it once per photo; the
cutouts are then reused forever at zero cost.

Background removal is tried in order:

  1. macOS Vision — the same subject-lifting model Preview uses. Instant, free,
     no download. Needs `pip install pyobjc-framework-Vision pyobjc-framework-Quartz`.
  2. rembg — anywhere, if installed. Downloads a ~175MB model on first run.
  3. Neither: the script tells you to cut it out by hand and re-run on the PNG.

Images that already carry transparency skip straight to trim and QC.
"""

from __future__ import annotations

import argparse
import glob
import os
import sys

from PIL import Image

TARGET_HEIGHT = 1400  # generous for a 1280x720 canvas rendered at 2x
MIN_SOURCE_PX = 900   # below this the cutout goes soft once scaled up


def cutout(img: Image.Image, model: str = "u2net") -> tuple[Image.Image, bool]:  # noqa: D401
    """Return (rgba, removed_here). Passes through images that already have alpha.

    `u2net` is the default deliberately: ~175MB and fast, and for a well-lit
    photo shot against a plain wall the result is indistinguishable from the
    heavier model once composited. `birefnet-general` mattes hair noticeably
    better but is a ~900MB download, so it's opt-in via --model rather than
    something every first run has to wait for.
    """
    from app.matting import MattingUnavailable, cut_out
    try:
        out, backend = cut_out(img, model=model)
    except MattingUnavailable as exc:
        raise SystemExit(str(exc))
    return out, backend != "already-transparent"


def trim(img: Image.Image, pad: int = 8) -> Image.Image:
    """Crop to the subject's alpha bounding box, with a little breathing room."""
    bbox = img.getchannel("A").getbbox()
    if not bbox:
        raise SystemExit("image is fully transparent — nothing to cut out")
    left, top, right, bottom = bbox
    return img.crop((max(0, left - pad), max(0, top - pad),
                     min(img.width, right + pad), min(img.height, bottom + pad)))


def quality_report(original: Image.Image, result: Image.Image) -> dict:
    """Flag the problems that only show up after compositing."""
    alpha = result.getchannel("A")
    # Histogram rather than getdata(): C-speed, and it avoids materialising a
    # multi-million-element Python list for every photo.
    hist = alpha.histogram()
    total = result.width * result.height
    soft = sum(hist[17:240])
    coverage = sum(hist[241:]) / total

    notes = []
    if min(original.size) < MIN_SOURCE_PX:
        notes.append(f"source is small ({original.width}x{original.height}); "
                     f"aim for {MIN_SOURCE_PX}px+ on the short edge")
    # A believable matte has a thin antialiased fringe. Almost none means a
    # hard, pasted-looking edge; too much means a grey halo.
    soft_ratio = soft / total
    if soft_ratio < 0.002:
        notes.append("edge looks hard/jagged — hair will read as cut with scissors")
    elif soft_ratio > 0.09:
        notes.append("large semi-transparent halo — background may be bleeding in")
    if coverage < 0.10:
        notes.append("subject occupies very little of the frame; crop tighter before matting")

    # Touching the top edge usually means the head is clipped.
    top_row = [alpha.getpixel((x, 0)) for x in range(0, alpha.width, max(1, alpha.width // 60))]
    if sum(1 for a in top_row if a > 128) > len(top_row) * 0.25:
        notes.append("subject touches the top edge — head may be cropped")

    return {
        "size": f"{result.width}x{result.height}",
        "coverage": round(coverage, 3),
        "soft_edge_ratio": round(soft_ratio, 4),
        "verdict": "ok" if not notes else "check",
        "notes": notes,
    }


def process(path: str, out_path: str, height: int, model: str) -> dict:
    src = Image.open(path)
    original = src.copy()
    rgba, removed = cutout(src.convert("RGBA"), model)
    trimmed = trim(rgba)

    ratio = height / trimmed.height
    final = trimmed.resize((max(1, int(trimmed.width * ratio)), height), Image.LANCZOS)

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    final.save(out_path)

    report = quality_report(original, final)
    report["matted_here"] = removed
    report["out"] = out_path
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("images", nargs="+", help="Source photo(s); globs are fine")
    parser.add_argument("-o", "--out", required=True,
                        help="Output PNG, or a directory when passing several images")
    parser.add_argument("--height", type=int, default=TARGET_HEIGHT)
    parser.add_argument("--model", default="u2net",
                        choices=["u2net", "birefnet-general", "isnet-general-use"],
                        help="Matting model. u2net (~175MB) is the fast default; "
                             "birefnet-general (~900MB) mattes hair better.")
    args = parser.parse_args()

    paths = [p for pattern in args.images for p in sorted(glob.glob(pattern))] or args.images
    batch = len(paths) > 1 or args.out.endswith("/") or os.path.isdir(args.out)

    failures = 0
    for path in paths:
        if batch:
            stem = os.path.splitext(os.path.basename(path))[0]
            out_path = os.path.join(args.out, f"{stem}.png")
        else:
            out_path = args.out

        try:
            r = process(path, out_path, args.height, args.model)
        except SystemExit as exc:
            print(f"{path}: {exc}", file=sys.stderr)
            failures += 1
            continue

        flag = "OK   " if r["verdict"] == "ok" else "CHECK"
        print(f"{flag} {r['out']}  {r['size']}  coverage={r['coverage']}  "
              f"edge={r['soft_edge_ratio']}")
        for note in r["notes"]:
            print(f"      - {note}")

    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
