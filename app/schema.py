"""Request models for the thumbnail service."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class EditRequest(BaseModel):
    """Compose a thumbnail, have a model edit the artwork, then redraw the text.

    Carries a full ThumbnailRequest so the vector layer can be laid back down
    exactly as it was — the model never sees or regenerates the typography.
    """

    spec: "ThumbnailRequest"
    instruction: str = Field(..., min_length=3, max_length=1000,
                             description="What the model should change about the artwork.")
    model: str = Field("google/gemini-3-pro-image", description="OpenRouter model id.")
    redraw_text: bool = Field(
        True, description="Redraw headline and arrow over the edited artwork. "
                          "Turn off only if you want the model's raw output.")
    output: Literal["binary", "base64"] = "base64"
    include_qa: bool = False


class AnalyzeRequest(BaseModel):
    """Read a reference thumbnail and propose a spec that approximates it."""

    url: str = Field(..., min_length=5, max_length=500,
                     description="YouTube link, bare 11-char video id, or a direct image URL.")
    model: str = Field("anthropic/claude-sonnet-5", description="OpenRouter vision model id.")
    include_reference: bool = Field(
        True, description="Return the reference image too, for side-by-side comparison.")


class Label(BaseModel):
    """A free-standing caption, optionally pointing at something."""

    text: str = Field(..., min_length=1, max_length=60)
    x: float = Field(0.08, ge=-0.2, le=1.2, description="Left edge, fraction of width.")
    y: float = Field(0.08, ge=-0.2, le=1.2, description="Top edge, fraction of height.")
    size: float = Field(0.055, gt=0.005, le=0.4, description="Cap height as a fraction of height.")
    color: str | None = None
    arrow_to: tuple[float, float] | None = Field(None, description="Point an arrow at this spot.")
    arrow_color: str | None = None
    bow: float = Field(0.22, ge=-1.0, le=1.0, description="Arrow curvature; sign flips the bend.")
    shadow: bool = True


class DiagramNode(BaseModel):
    label: str = Field("", max_length=40)
    icon: str | None = Field(None, description="Optional icon for this node.")


class Diagram(BaseModel):
    """Hub-and-spoke node diagram, drawn deterministically."""

    nodes: list[DiagramNode] = Field(default_factory=list, max_length=10)
    center_icon: str | None = None
    center_label: str | None = Field(None, max_length=40)
    accent: str | None = Field(None, description="Node colour; defaults to the style accent.")
    layout: Literal["hub", "cycle"] = Field(
        "hub", description="hub = spokes from a centre; cycle = a loop of arrows.")
    frame: Literal["tablet"] | None = Field(
        None, description="Mount the diagram on a screen inside a device bezel.")
    frame_glow: str | None = Field(None, description="Halo colour around the device.")
    screen: str | None = Field(None, description="Screen fill; defaults to white.")
    line_color: str | None = Field(None, description="Connector/arrow colour.")


class Tile(BaseModel):
    """Repeating backdrop of marks, optionally struck through."""

    icons: list[str] = Field(default_factory=list,
                             description="Images to repeat; a generic mark is used if empty.")
    columns: int = Field(6, ge=1, le=20)
    opacity: float = Field(0.5, ge=0.0, le=1.0)
    cross: bool = Field(True, description="Strike tiles through.")
    cross_color: str | None = None
    cross_every: int = Field(1, ge=0, le=12, description="Strike every nth tile; 0 disables.")
    angle: float = Field(0.0, ge=-45.0, le=45.0)
    blur: float = Field(0.0, ge=0.0, le=40.0)
    accent: str | None = None


class ElementOverride(BaseModel):
    """A nudge applied on top of the preset's placement for one element."""

    dx: float = Field(0.0, ge=-1.0, le=1.0, description="Horizontal delta, fraction of width.")
    dy: float = Field(0.0, ge=-1.0, le=1.0, description="Vertical delta, fraction of height.")
    scale: float = Field(1.0, gt=0.05, le=8.0, description="Size multiplier.")
    # Arrows are positioned by their endpoints rather than a box.
    from_: tuple[float, float] | None = Field(None, alias="from")
    to: tuple[float, float] | None = None

    model_config = {"populate_by_name": True}


class ThumbnailRequest(BaseModel):
    headline: str = Field(..., min_length=1, max_length=120,
                          description="Thumbnail copy. 3-6 words performs best.")
    style: Literal["saraev", "herk", "roberts", "ottley", "enterprise"] = "saraev"
    palette: str | None = Field(None, description="Palette name from the style; see GET /styles.")
    accent_words: list[str] = Field(default_factory=list,
                                    description="Words to highlight (pill or colour, per style).")

    # Assets: URL, data URI, base64, or a server-side path.
    subject: str | None = Field(None, description="Matted PNG cutout of the creator.")
    subjects: list[str | None] = Field(
        default_factory=list,
        description="Several cutouts for a group shot; overlapped left to right. "
                    "Takes precedence over `subject`. A null slot renders the "
                    "placeholder, so a layout can be previewed before the real "
                    "cutouts exist.")
    icons: list[str] = Field(
        default_factory=list,
        description="Floating 3D logos dropped into the style's icon slots.")
    word_colors: dict[str, str] = Field(
        default_factory=dict,
        description='Per-word colour overrides, e.g. {"STOP": "#FFD400"}. '
                    "Wins over accent treatment for that word.")
    hero: str | None = Field(None, description="Hero visual (e.g. a generated scene or 3D icon).")
    hero_prompt: str | None = Field(
        None, description="Generate the hero layer with Nano Banana Pro instead of supplying one. "
                          "Requires GEMINI_API_KEY. ~$0.134/image.")
    background: str | None = Field(None, description="Full-bleed background plate.")

    # Rendered props, used when no hero image is supplied.
    labels: list[Label] = Field(default_factory=list, max_length=8,
                                description="Free-standing captions with optional arrows.")
    diagram: Diagram | None = Field(None, description="Hub-and-spoke node diagram.")
    tile: Tile | None = Field(None, description="Repeating backdrop of marks.")

    card_text: str | None = Field(None, description="Renders a social card prop.")
    card_name: str = "Your Name"
    card_handle: str = "@yourhandle"
    toast_text: str | None = Field(None, description="Renders a notification toast prop.")
    toast_amount: str | None = None

    arrow: bool = True
    subject_side: Literal["left", "right"] | None = None
    overrides: dict[str, ElementOverride] = Field(
        default_factory=dict,
        description="Per-element nudges from the preset, keyed by element id "
                    "(headline, subject, hero, arrow). Offsets are deltas so "
                    "the intent survives a style change.")
    hidden: list[str] = Field(
        default_factory=list,
        description="Element ids to drop (headline, subject, hero, arrow, icons, "
                    "label0...). This is how deletion works.")
    only: list[str] = Field(
        default_factory=list,
        description="Render only these ids, on transparency. With `hidden` this "
                    "splits a frame into backdrop + isolated layer, which is what "
                    "lets the studio drag real pixels without a round trip.")
    behind: list[str] = Field(
        default_factory=list,
        description="Vector ids to draw beneath the cutout (headline, arrow, "
                    "label0...), so text can pass behind the subject.")
    include_layout: bool = Field(
        False, description="Return where each element landed, for drawing "
                           "direct-manipulation handles.")
    text_position: Literal["top", "bottom"] | None = Field(
        None, description="Move the headline band; overrides the style default.")

    width: int = Field(1280, ge=320, le=2560)
    height: int = Field(720, ge=180, le=1440)

    output: Literal["binary", "base64"] = "binary"
    format: Literal["png", "jpeg"] = Field(
        "png", description="jpeg is ~6x faster to encode and less than half the "
                           "bytes — use it for live preview, png for the final file.")
    include_qa: bool = Field(False, description="Attach the feed-size legibility report.")
