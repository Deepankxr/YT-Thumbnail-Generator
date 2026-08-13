"""Style presets reverse-engineered from the three reference channels.

Each preset encodes a palette, a type treatment, a layout, and a set of effects.
They are deliberately opinionated — the point is that a caller supplies only a
headline and a cutout and still lands inside a coherent design system.

Rects are normalised (x, y, w, h) against the canvas, so the same preset renders
correctly at 1280x720 or 2560x1440.
"""

from __future__ import annotations

from dataclasses import dataclass, field

RGB = tuple[int, int, int]


@dataclass
class Style:
    name: str
    description: str

    # Background
    bg_top: RGB
    bg_bottom: RGB
    bg_angle: float = 90.0
    glow_color: RGB | None = None
    glow_intensity: float = 0.0
    glow_center: tuple[float, float] = (0.5, 0.55)
    glow_radius: float = 0.75
    vignette_strength: float = 0.0

    # Type
    font_family: str = "montserrat"
    font_weight: str = "Black"
    # wdth axis, where the family has one. ~70 is a compressed display cut.
    font_width: float | None = None
    text_color: RGB = (255, 255, 255)
    text_case: str = "none"  # none | upper | title
    tracking: float = -0.015
    line_height: float = 0.94
    max_lines: int = 3
    text_align: str = "left"
    shadow: bool = True
    shadow_opacity: float = 0.5
    shadow_blur: int = 16
    stroke_width: int = 0
    stroke_color: RGB = (0, 0, 0)
    # Darkening ramp behind the headline: None | left | right | top | bottom.
    scrim: str | None = None
    scrim_opacity: float = 0.0

    # Accent word treatment
    accent_fill: RGB | None = None
    accent_color: RGB | None = None
    # Corner radius of the accent box: None = auto-rounded pill, 0 = hard plate.
    accent_radius: int | None = None
    accent_pad: tuple[int, int] = (18, 8)
    underline_color: RGB | None = None
    underline_swash: bool = False

    # Layout (normalised)
    text_box: tuple[float, float, float, float] = (0.05, 0.07, 0.60, 0.32)
    text_valign: str = "top"
    subject_box: tuple[float, float, float, float] = (0.52, 0.06, 0.46, 0.94)
    subject_anchor: str = "bottom-right"
    hero_box: tuple[float, float, float, float] = (0.05, 0.42, 0.44, 0.50)
    # Diagrams need far more room than an icon or card, and their labels need
    # space around them, so they get their own box rather than reusing hero_box.
    diagram_box: tuple[float, float, float, float] = (0.01, 0.26, 0.53, 0.66)

    # Icon slots: normalised (x, y, size) for floating 3D logos.
    icon_slots: list[tuple[float, float, float]] = field(default_factory=list)

    # Subject treatment
    subject_shadow: bool = True
    subject_shadow_opacity: float = 0.45
    subject_rim: RGB | None = None
    subject_rim_width: int = 6

    # Arrow
    arrow_color: RGB = (255, 255, 255)
    arrow_width: int = 9
    arrow_bow: float = 0.30
    arrow_from: tuple[float, float] = (0.30, 0.40)
    arrow_to: tuple[float, float] = (0.44, 0.60)

    palettes: dict[str, tuple[RGB, RGB]] = field(default_factory=dict)


SARAEV = Style(
    name="saraev",
    description="Clean, premium, restrained. Geometric heavy sans, 2-3 colours, "
                "one hand-drawn arrow, studio cutout on the right.",
    bg_top=(109, 40, 217),
    bg_bottom=(76, 29, 149),
    font_family="poppins",
    font_weight="ExtraBold",
    text_color=(255, 255, 255),
    text_case="none",
    tracking=-0.02,
    line_height=0.96,
    max_lines=2,
    shadow=True,
    shadow_opacity=0.28,
    shadow_blur=22,
    scrim="left",
    scrim_opacity=0.22,
    underline_color=(255, 255, 255),
    text_box=(0.055, 0.09, 0.58, 0.26),
    subject_box=(0.54, 0.04, 0.44, 0.96),
    hero_box=(0.07, 0.42, 0.42, 0.48),
    subject_shadow=True,
    subject_shadow_opacity=0.35,
    arrow_color=(255, 255, 255),
    arrow_width=9,
    arrow_bow=0.34,
    arrow_from=(0.34, 0.36),
    arrow_to=(0.46, 0.60),
    palettes={
        "violet": ((124, 58, 237), (67, 26, 133)),
        "cream": ((242, 237, 228), (232, 226, 214)),
        "ink": ((22, 22, 24), (12, 12, 14)),
        "bone": ((248, 246, 241), (238, 235, 228)),
    },
)

HERK = Style(
    name="herk",
    description="Photo-real base plate, big face right, rendered UI card, "
                "white Inter Black with a cyan highlight box.",
    bg_top=(28, 32, 40),
    bg_bottom=(12, 14, 18),
    glow_color=(56, 78, 120),
    glow_intensity=0.55,
    glow_center=(0.62, 0.45),
    glow_radius=0.80,
    vignette_strength=0.50,
    font_family="inter",
    font_weight="Black",
    text_color=(255, 255, 255),
    tracking=-0.02,
    line_height=0.98,
    max_lines=2,
    shadow=True,
    shadow_opacity=0.65,
    shadow_blur=18,
    scrim="left",
    scrim_opacity=0.55,
    accent_fill=(34, 211, 238),
    accent_color=(8, 12, 20),
    text_box=(0.045, 0.08, 0.56, 0.28),
    subject_box=(0.55, 0.05, 0.45, 0.95),
    hero_box=(0.03, 0.34, 0.50, 0.56),
    subject_shadow=True,
    subject_shadow_opacity=0.55,
    arrow_color=(255, 255, 255),
    arrow_width=8,
    arrow_bow=0.28,
    arrow_from=(0.30, 0.38),
    arrow_to=(0.44, 0.58),
    palettes={
        "desk": ((28, 32, 40), (12, 14, 18)),
        "studio": ((38, 40, 48), (16, 17, 22)),
        "warm": ((48, 34, 24), (18, 13, 10)),
    },
)

ROBERTS = Style(
    name="roberts",
    description="High energy. Neon rim light, strong backlight glow, saturated "
                "palette, Montserrat Black with a hard stroke and blue pill.",
    bg_top=(10, 22, 58),
    bg_bottom=(4, 6, 16),
    glow_color=(37, 99, 235),
    glow_intensity=0.95,
    glow_center=(0.50, 0.52),
    glow_radius=0.85,
    vignette_strength=0.62,
    font_family="montserrat",
    font_weight="Black",
    text_color=(255, 255, 255),
    text_case="title",
    tracking=-0.015,
    line_height=0.92,
    max_lines=2,
    shadow=True,
    shadow_opacity=0.75,
    shadow_blur=20,
    stroke_width=7,
    stroke_color=(6, 8, 18),
    scrim="bottom",
    scrim_opacity=0.60,
    accent_fill=(37, 99, 235),
    accent_color=(255, 255, 255),
    text_box=(0.06, 0.62, 0.88, 0.26),
    text_valign="center",
    text_align="left",
    subject_box=(0.28, 0.02, 0.42, 0.92),
    subject_anchor="bottom-center",
    hero_box=(0.62, 0.08, 0.34, 0.46),
    subject_shadow=True,
    subject_shadow_opacity=0.6,
    subject_rim=(96, 176, 255),
    subject_rim_width=7,
    arrow_color=(255, 255, 255),
    arrow_width=10,
    arrow_bow=-0.30,
    arrow_from=(0.55, 0.42),
    arrow_to=(0.68, 0.28),
    palettes={
        "electric": ((10, 22, 58), (4, 6, 16)),
        "inferno": ((58, 18, 6), (14, 5, 3)),
        "toxic": ((6, 40, 30), (3, 12, 10)),
        "void": ((16, 16, 20), (3, 3, 5)),
    },
)


OTTLEY = Style(
    name="ottley",
    description="Editorial and loud. Compressed all-caps Archivo, hard-edged "
                "colour plates, full-width band, photoreal subject, floating "
                "3D logos.",
    bg_top=(18, 18, 20),
    bg_bottom=(6, 6, 8),
    glow_color=(70, 70, 84),
    glow_intensity=0.40,
    glow_center=(0.50, 0.42),
    glow_radius=0.90,
    vignette_strength=0.55,
    font_family="archivo",
    font_weight="Black",
    font_width=72,
    text_color=(255, 255, 255),
    text_case="upper",
    tracking=-0.005,
    line_height=0.92,
    max_lines=2,
    text_align="center",
    shadow=True,
    shadow_opacity=0.70,
    shadow_blur=18,
    stroke_width=0,
    scrim="bottom",
    scrim_opacity=0.66,
    # Hard rectangular plate, not a rounded pill — the signature move.
    accent_fill=(232, 62, 40),
    accent_color=(255, 255, 255),
    accent_radius=0,
    accent_pad=(20, 10),
    underline_color=(255, 212, 0),
    underline_swash=True,
    text_box=(0.04, 0.70, 0.92, 0.22),
    text_valign="center",
    subject_box=(0.30, 0.04, 0.44, 0.94),
    subject_anchor="bottom-center",
    hero_box=(0.04, 0.10, 0.30, 0.42),
    icon_slots=[(0.08, 0.16, 0.20), (0.74, 0.16, 0.20)],
    subject_shadow=True,
    subject_shadow_opacity=0.55,
    arrow_color=(255, 212, 0),
    arrow_width=10,
    arrow_bow=0.30,
    arrow_from=(0.24, 0.40),
    arrow_to=(0.38, 0.56),
    palettes={
        "studio": ((18, 18, 20), (6, 6, 8)),
        "paper": ((246, 244, 238), (228, 224, 214)),
        "ocean": ((22, 58, 82), (6, 18, 30)),
        "sunset": ((70, 26, 16), (14, 6, 6)),
    },
)


ENTERPRISE = Style(
    name="enterprise",
    description="Restrained and credible. Built for a senior operator scrolling "
                "with no patience: sentence case, two colours, generous negative "
                "space, no glow or stroke. The visual carries substance rather "
                "than a reaction.",
    bg_top=(247, 246, 243),
    bg_bottom=(238, 236, 231),
    # No glow, no vignette. Both read as 'video thumbnail' rather than
    # 'business publication', which is exactly the wrong signal here.
    glow_intensity=0.0,
    vignette_strength=0.0,
    font_family="inter",
    font_weight="SemiBold",
    text_color=(20, 22, 26),
    text_case="none",
    tracking=-0.018,
    line_height=1.02,
    max_lines=3,
    text_align="left",
    # A whisper of shadow for photo backplates; invisible on flat colour.
    shadow=True,
    shadow_opacity=0.10,
    shadow_blur=18,
    stroke_width=0,
    scrim=None,
    scrim_opacity=0.0,
    # Emphasis is a thin rule under one phrase, not a highlighter pen.
    accent_fill=None,
    accent_color=(11, 87, 164),
    underline_color=(11, 87, 164),
    underline_swash=False,
    text_box=(0.055, 0.15, 0.52, 0.34),
    text_valign="center",
    subject_box=(0.60, 0.06, 0.38, 0.94),
    subject_anchor="bottom-right",
    hero_box=(0.06, 0.60, 0.44, 0.34),
    # Sits below the headline band rather than behind it.
    diagram_box=(0.04, 0.44, 0.50, 0.50),
    icon_slots=[(0.06, 0.72, 0.10), (0.19, 0.72, 0.10), (0.32, 0.72, 0.10)],
    subject_shadow=True,
    subject_shadow_opacity=0.22,
    subject_rim=None,
    # An arrow is a creator-economy tell. Off by default; still available.
    arrow_color=(11, 87, 164),
    arrow_width=6,
    arrow_bow=0.22,
    arrow_from=(0.30, 0.34),
    arrow_to=(0.42, 0.52),
    palettes={
        "paper": ((247, 246, 243), (238, 236, 231)),
        "slate": ((30, 36, 46), (18, 22, 30)),
        "navy": ((17, 34, 64), (10, 20, 40)),
        "graphite": ((38, 40, 44), (24, 26, 30)),
    },
)

STYLES: dict[str, Style] = {s.name: s for s in (SARAEV, HERK, ROBERTS, OTTLEY, ENTERPRISE)}


# Curated word-colour palette. Every swatch was picked to survive the two things
# that kill thumbnail text: sitting on a busy photo, and being scaled to 168px
# in the feed. Mid-tone muddy colours are deliberately absent — they vanish.
WORD_PALETTE: dict[str, list[tuple[str, str]]] = {
    "Highlight": [
        ("Signal yellow", "#FFD400"),
        ("Amber", "#FFB020"),
        ("Orange", "#FF5C2B"),
        ("Alert red", "#E83E28"),
    ],
    "Cool": [
        ("Cyan", "#22D3EE"),
        ("Sky", "#38BDF8"),
        ("Electric blue", "#2563EB"),
        ("Violet", "#8B5CF6"),
    ],
    "Signal": [
        ("Green", "#22C55E"),
        ("Lime", "#A3E635"),
        ("Pink", "#EC4899"),
        ("Magenta", "#D946EF"),
    ],
    "Neutral": [
        ("White", "#FFFFFF"),
        ("Bone", "#F2EDE4"),
        ("Slate", "#94A3B8"),
        ("Ink", "#111114"),
    ],
}


def get_style(name: str, palette: str | None = None) -> Style:
    """Fetch a preset, optionally swapping its background palette."""
    from dataclasses import replace

    key = (name or "saraev").lower()
    if key not in STYLES:
        raise ValueError(f"unknown style '{name}'; have {sorted(STYLES)}")

    style = STYLES[key]
    if palette:
        if palette not in style.palettes:
            raise ValueError(
                f"style '{key}' has no palette '{palette}'; have {sorted(style.palettes)}"
            )
        top, bottom = style.palettes[palette]
        style = replace(style, bg_top=top, bg_bottom=bottom)
        # Light backgrounds need dark type and a dark arrow, or the whole thing
        # disappears. Luminance test rather than a hardcoded palette list.
        if _luminance(top) > 0.6:
            style = replace(
                style,
                text_color=(16, 16, 18),
                arrow_color=(16, 16, 18),
                underline_color=style.underline_color or (16, 16, 18),
                shadow_opacity=min(style.shadow_opacity, 0.14),
                stroke_width=0,
                # A dark ramp under dark type would only muddy a light plate.
                scrim_opacity=0.0,
            )
        elif _luminance(style.text_color) < 0.4:
            # Dark type was chosen for this style's default light plate; a dark
            # palette needs it flipped back or the headline disappears.
            style = replace(
                style,
                text_color=(245, 246, 248),
                arrow_color=(120, 170, 235),
                underline_color=(120, 170, 235) if style.underline_color else None,
            )
    return style


def _luminance(rgb: RGB) -> float:
    r, g, b = (c / 255 for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b
