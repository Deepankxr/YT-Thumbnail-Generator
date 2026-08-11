"""Request models for the thumbnail service."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ThumbnailRequest(BaseModel):
    headline: str = Field(..., min_length=1, max_length=120,
                          description="Thumbnail copy. 3-6 words performs best.")
    style: Literal["saraev", "herk", "roberts", "ottley"] = "saraev"
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
    card_text: str | None = Field(None, description="Renders a social card prop.")
    card_name: str = "Your Name"
    card_handle: str = "@yourhandle"
    toast_text: str | None = Field(None, description="Renders a notification toast prop.")
    toast_amount: str | None = None

    arrow: bool = True
    subject_side: Literal["left", "right"] | None = None
    text_position: Literal["top", "bottom"] | None = Field(
        None, description="Move the headline band; overrides the style default.")

    width: int = Field(1280, ge=320, le=2560)
    height: int = Field(720, ge=180, le=1440)

    output: Literal["binary", "base64"] = "binary"
    include_qa: bool = Field(False, description="Attach the feed-size legibility report.")
