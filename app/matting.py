"""Background removal backends, cheapest and most available first.

macOS ships the same subject-lifting model Preview and Photos use, reachable
through Vision. On a Mac it is instant, free, needs no download, and mattes hair
better than u2net — which matters here because rembg's model fetch is a ~200MB
download that fails often enough to be unreliable as the only path.

Order: Vision (macOS) -> rembg (anywhere, if installed) -> a clear error telling
the caller to cut it out by hand.
"""

from __future__ import annotations

import io
import platform

from PIL import Image


class MattingUnavailable(RuntimeError):
    """No backend could run — the message says what to do instead."""


def vision_available() -> bool:
    if platform.system() != "Darwin":
        return False
    try:
        import Vision  # noqa: F401
        return True
    except ImportError:
        return False


def _cut_with_vision(img: Image.Image) -> Image.Image:
    """Foreground instance mask via Vision, composited onto transparency."""
    import Quartz
    import Vision
    from CoreFoundation import CFDataCreate

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    data = CFDataCreate(None, buf.getvalue(), len(buf.getvalue()))
    source = Quartz.CGImageSourceCreateWithData(data, None)
    if source is None or Quartz.CGImageSourceGetCount(source) == 0:
        raise MattingUnavailable("Vision could not decode the image")
    cg = Quartz.CGImageSourceCreateImageAtIndex(source, 0, None)

    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(cg, None)
    request = Vision.VNGenerateForegroundInstanceMaskRequest.alloc().init()
    ok, err = handler.performRequests_error_([request], None)
    if not ok:
        raise MattingUnavailable(f"Vision request failed: {err}")

    results = request.results()
    if not results:
        raise MattingUnavailable(
            "Vision found no foreground subject. Try a photo where the person is "
            "clearly separated from the background.")

    observation = results[0]
    mask_buf, err = observation.generateScaledMaskForImageForInstances_fromRequestHandler_error_(
        observation.allInstances(), handler, None)
    if mask_buf is None:
        raise MattingUnavailable(f"Vision could not build a mask: {err}")

    # The mask comes back as a one-channel float/8-bit CVPixelBuffer.
    Quartz.CVPixelBufferLockBaseAddress(mask_buf, 1)
    try:
        width = Quartz.CVPixelBufferGetWidth(mask_buf)
        height = Quartz.CVPixelBufferGetHeight(mask_buf)
        stride = Quartz.CVPixelBufferGetBytesPerRow(mask_buf)
        base = Quartz.CVPixelBufferGetBaseAddress(mask_buf)
        raw = bytes(base.as_buffer(stride * height))
    finally:
        Quartz.CVPixelBufferUnlockBaseAddress(mask_buf, 1)

    fmt = Quartz.CVPixelBufferGetPixelFormatType(mask_buf)
    if stride >= width * 4:                      # 32-bit float grayscale
        mask = Image.frombuffer("F", (width, height), raw, "raw", "F", stride, 1)
        mask = mask.point(lambda v: v * 255).convert("L")
    else:                                        # 8-bit grayscale
        mask = Image.frombuffer("L", (width, height), raw, "raw", "L", stride, 1)
    _ = fmt

    mask = mask.resize(img.size, Image.LANCZOS)
    out = img.convert("RGBA")
    out.putalpha(mask)
    return out


def _cut_with_rembg(img: Image.Image, model: str) -> Image.Image:
    try:
        from rembg import new_session, remove
    except ImportError as exc:
        raise MattingUnavailable("rembg is not installed") from exc
    return remove(img, session=new_session(model))


def cut_out(img: Image.Image, model: str = "u2net", prefer: str = "auto") -> tuple[Image.Image, str]:
    """Return (rgba, backend name). Images that already carry alpha pass through."""
    if img.mode == "RGBA" and img.getchannel("A").getextrema()[0] < 250:
        return img, "already-transparent"

    order = ["vision", "rembg"] if prefer in ("auto", "vision") else ["rembg", "vision"]
    problems = []
    for backend in order:
        try:
            if backend == "vision" and vision_available():
                return _cut_with_vision(img), "vision"
            if backend == "rembg":
                return _cut_with_rembg(img, model), f"rembg:{model}"
        except MattingUnavailable as exc:
            problems.append(f"{backend}: {exc}")
        except Exception as exc:
            problems.append(f"{backend}: {type(exc).__name__}: {exc}")

    raise MattingUnavailable(
        "No background remover succeeded.\n  " + "\n  ".join(problems) +
        "\n\nCut it out by hand instead — macOS Preview > Markup > Remove "
        "Background, Photoroom, or Photoshop — and re-run on the resulting PNG.")
