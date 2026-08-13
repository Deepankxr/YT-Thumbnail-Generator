"""Regression suite for the thumbnail service.

Written after a run of bugs that shared a shape: a change looked fine in one
render and silently broke another path. The cases here are the invariants that
must hold as presets and features are added — element identity, layer order,
input validation, and the escaping of the studio page, which has broken twice.

    pip install pytest
    python3 -m pytest -q
"""

from __future__ import annotations

import base64
import io
import json
import re
import subprocess
import shutil

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.analyze import clean_spec, video_id
from app.compositor import compose, legibility_report, parse_color
from app.main import app
from app.preview import PREVIEW_HTML
from app.styles import STYLES, WORD_PALETTE, get_style

client = TestClient(app)

ALL_STYLES = sorted(STYLES)
STYLE_PALETTES = [(s, p) for s in ALL_STYLES for p in sorted(STYLES[s].palettes)]


def png(resp) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(resp.json()["data"])))


# --------------------------------------------------------------------------- #
# API surface
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("path", ["/health", "/styles", "/palette", "/preview",
                                  "/analyze/models", "/fonts/inter"])
def test_get_endpoints_ok(path):
    assert client.get(path).status_code == 200


def test_root_redirects_to_studio():
    r = client.get("/", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert r.headers["location"] == "/preview"


def test_unknown_font_404s():
    assert client.get("/fonts/comic-sans").status_code == 404


def test_styles_endpoint_matches_presets():
    listed = {s["name"] for s in client.get("/styles").json()["styles"]}
    assert listed == set(ALL_STYLES)


def test_palette_swatches_are_hex():
    for group in client.get("/palette").json()["groups"]:
        for sw in group["swatches"]:
            assert re.fullmatch(r"#[0-9A-Fa-f]{6}", sw["hex"]), sw


# --------------------------------------------------------------------------- #
# Rendering — every preset must survive every one of its palettes
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("style,palette", STYLE_PALETTES)
def test_every_style_palette_renders_and_is_legible(style, palette):
    img, manifest = compose(headline="This changes everything.",
                            style_name=style, palette=palette)
    assert img.size == (1280, 720)
    assert any(m["id"] == "headline" for m in manifest)
    assert legibility_report(img, style)["verdict"] == "ok", f"{style}/{palette} illegible"


@pytest.mark.parametrize("style,palette", STYLE_PALETTES)
def test_headline_contrasts_with_its_plate(style, palette):
    """A light palette must not leave light type, and vice versa."""
    st = get_style(style, palette)
    lum = lambda c: 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
    assert abs(lum(st.text_color) - lum(st.bg_top)) > 60, f"{style}/{palette} too close"


def test_light_palette_never_invents_an_underline(monkeypatch):
    """`or` in the luminance flip once gave underline-less styles a black rule.

    No shipped preset currently pairs "no underline" with a light palette, so
    checking the presets as they stand proves nothing. Construct the pairing
    instead, which is exactly the case a future light palette would create.
    """
    from dataclasses import replace

    base = STYLES["roberts"]
    assert base.underline_color is None, "fixture assumes roberts has no underline"
    probe = replace(base, name="probe",
                    palettes={**base.palettes, "chalk": ((246, 245, 242), (238, 236, 231))})
    monkeypatch.setitem(STYLES, "probe", probe)

    got = get_style("probe", "chalk")
    assert got.underline_color is None, "a light palette invented an underline"
    assert got.text_color[0] < 60, "light palette must darken the type"


def test_light_palette_keeps_a_dark_accent_underline():
    """Enterprise's blue rule reads fine on paper and must not be flattened."""
    assert get_style("enterprise", "paper").underline_color == (11, 87, 164)


def test_render_is_deterministic():
    spec = dict(headline="Same every time", style_name="ottley", palette="studio",
                accent_words=["time"])
    a, _ = compose(**spec)
    b, _ = compose(**spec)
    assert a.tobytes() == b.tobytes()


# --------------------------------------------------------------------------- #
# Element identity, visibility and depth
# --------------------------------------------------------------------------- #

def ids_for(**kw):
    return [m["id"] for m in compose(headline="Hello there", **kw)[1]]


def test_hidden_removes_the_element():
    assert "arrow" in ids_for(style_name="saraev")
    assert "arrow" not in ids_for(style_name="saraev", hidden=["arrow"])


def test_hiding_everything_is_not_an_error():
    img, manifest = compose(headline="x", style_name="saraev",
                            hidden=["headline", "arrow", "subject"])
    assert manifest == []
    assert img.size == (1280, 720)


def test_only_returns_an_isolated_layer_with_alpha():
    solo, _ = compose(headline="x", style_name="saraev", only=["subject"])
    assert solo.mode == "RGBA"
    lo, hi = solo.getchannel("A").getextrema()
    assert lo == 0 and hi == 255, "isolated layer should be partly transparent"


def test_backdrop_and_isolate_are_complementary():
    """The drag proxy relies on these two covering the frame between them."""
    back = ids_for(style_name="saraev", hidden=["subject"])
    solo = ids_for(style_name="saraev", only=["subject"])
    assert "subject" not in back
    assert solo == ["subject"]


def test_behind_puts_the_headline_under_the_subject():
    order = ids_for(style_name="herk", arrow=False, behind=["headline"])
    assert order.index("headline") < order.index("subject")


def test_default_order_puts_the_headline_over_the_subject():
    order = ids_for(style_name="herk", arrow=False)
    assert order.index("headline") > order.index("subject")


def test_elements_are_emitted_exactly_once():
    manifest = compose(headline="Once only", style_name="herk", arrow=True,
                       behind=["arrow"],
                       labels=[{"text": "a", "x": .1, "y": .1},
                               {"text": "b", "x": .2, "y": .2}])[1]
    ids = [m["id"] for m in manifest]
    assert len(ids) == len(set(ids)), f"duplicate element: {ids}"


def test_manifest_boxes_are_normalised():
    for m in compose(headline="Bounds check", style_name="ottley")[1]:
        for key in ("x", "y", "w", "h"):
            assert -1.0 <= m[key] <= 2.0, f"{m['id']}.{key} out of range: {m[key]}"


# --------------------------------------------------------------------------- #
# Props
# --------------------------------------------------------------------------- #

def test_diagram_pushes_subject_right_and_headline_up():
    manifest = compose(headline="Roadmap", style_name="ottley", arrow=False,
                       diagram={"nodes": [{"label": f"n{i}"} for i in range(5)]})[1]
    hero = next(m for m in manifest if m["id"] == "hero")
    subject = next(m for m in manifest if m["id"] == "subject")
    headline = next(m for m in manifest if m["id"] == "headline")
    assert hero["x"] < subject["x"], "diagram should sit left of the subject"
    assert headline["y"] < 0.35, "headline should move to the top band"


def test_diagram_cache_returns_equal_but_distinct_images():
    from app.diagram import node_diagram
    nodes = [{"label": "a"}, {"label": "b"}]
    first = node_diagram(400, nodes)
    second = node_diagram(400, nodes)
    assert first.tobytes() == second.tobytes()
    assert first is not second, "cache must hand out copies, not the stored image"


def test_tiled_backdrop_actually_paints():
    plain, _ = compose(headline="x", style_name="herk", palette="desk", arrow=False)
    tiled, _ = compose(headline="x", style_name="herk", palette="desk", arrow=False,
                       tile={"columns": 6, "opacity": 0.6})
    assert plain.tobytes() != tiled.tobytes()


def test_tiled_backdrop_survives_extreme_settings():
    for kw in ({"columns": 1}, {"columns": 20}, {"opacity": 0.0},
               {"angle": -45.0}, {"blur": 20.0}, {"cross_every": 0}):
        img, _ = compose(headline="x", style_name="herk", tile=kw)
        assert img.size == (1280, 720)


def test_labels_and_card_identity_render():
    manifest = compose(headline="x", style_name="herk", arrow=False,
                       card_text="Body", card_name="Deepankar",
                       card_handle="@deepankxr",
                       labels=[{"text": "opus", "x": .05, "y": .3,
                                "arrow_to": [.2, .5]}])[1]
    assert any(m["id"] == "label0" for m in manifest)
    assert any(m["id"] == "hero" for m in manifest)


# --------------------------------------------------------------------------- #
# Request validation — bad input must 422, never 500
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("body", [
    {"headline": "x", "style": "nope"},
    {"headline": "x", "palette": "not-a-palette"},
    {"headline": ""},
    {"headline": "x", "overrides": {"subject": {"scale": 99}}},
    {"headline": "x", "overrides": {"subject": {"dx": 5}}},
    {"headline": "x", "labels": [{"text": "a", "x": 5}]},
    {"headline": "x", "labels": [{"text": ""}]},
    {"headline": "x", "diagram": {"nodes": [{"label": "a"}] * 12}},
    {"headline": "x", "tile": {"columns": 99}},
    {"headline": "x", "tile": {"opacity": 5}},
    {"headline": "x", "width": 99},
])
def test_invalid_requests_are_rejected_cleanly(body):
    assert client.post("/generate", json=body).status_code == 422


def test_word_colour_rejects_bad_hex():
    r = client.post("/generate", json={"headline": "x", "word_colors": {"x": "nothex"}})
    assert r.status_code == 422


@pytest.mark.parametrize("value,expected", [
    ("#FFD400", (255, 212, 0)), ("FFD400", (255, 212, 0)), ("#fff", (255, 255, 255)),
])
def test_parse_color_accepts_common_forms(value, expected):
    assert parse_color(value) == expected


@pytest.mark.parametrize("value", ["", "#12", "#GGGGGG", "12345"])
def test_parse_color_rejects_junk(value):
    with pytest.raises(ValueError):
        parse_color(value)


# --------------------------------------------------------------------------- #
# Output shape
# --------------------------------------------------------------------------- #

def test_jpeg_is_smaller_and_labelled_correctly():
    body = {"headline": "Format check", "output": "base64"}
    p = client.post("/generate", json={**body, "format": "png"}).json()
    j = client.post("/generate", json={**body, "format": "jpeg"}).json()
    assert p["mimeType"] == "image/png" and j["mimeType"] == "image/jpeg"
    assert j["filename"].endswith(".jpg")
    assert len(j["data"]) < len(p["data"])


def test_isolated_layer_forces_png_even_when_jpeg_asked():
    """JPEG has no alpha; honouring the ask would silently break the drag proxy."""
    r = client.post("/generate", json={"headline": "x", "only": ["subject"],
                                       "format": "jpeg", "output": "base64"})
    assert r.json()["mimeType"] == "image/png"
    assert png(r).mode == "RGBA"


def test_binary_output_returns_image_bytes():
    r = client.post("/generate", json={"headline": "x"})
    assert r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_qa_and_layout_are_opt_in():
    r = client.post("/generate", json={"headline": "x", "output": "base64"}).json()
    assert r["qa"] is None and r["layout"] is None
    r = client.post("/generate", json={"headline": "x", "output": "base64",
                                       "include_qa": True, "include_layout": True}).json()
    assert r["qa"]["verdict"] in ("ok", "weak") and isinstance(r["layout"], list)


def test_custom_size_is_honoured():
    r = client.post("/generate", json={"headline": "x", "width": 854, "height": 480,
                                       "output": "base64"})
    assert png(r).size == (854, 480)


# --------------------------------------------------------------------------- #
# Keys are required and never echoed
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("path,body", [
    ("/edit", {"spec": {"headline": "x"}, "instruction": "make it blue"}),
    ("/analyze", {"url": "https://youtu.be/vY0EzTP-7EA"}),
])
def test_openrouter_routes_require_a_key(path, body):
    r = client.post(path, json=body)
    assert r.status_code == 401
    assert "x-openrouter-key" in r.json()["detail"]


def test_a_rejected_key_is_not_echoed_back():
    secret = "sk-or-v1-do-not-leak-me"
    r = client.post("/analyze", json={"url": "https://youtu.be/vY0EzTP-7EA"},
                    headers={"x-openrouter-key": secret})
    assert secret not in r.text


# --------------------------------------------------------------------------- #
# Reference analysis
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("url", [
    "https://www.youtube.com/watch?v=vY0EzTP-7EA",
    "https://youtu.be/vY0EzTP-7EA",
    "https://www.youtube.com/shorts/vY0EzTP-7EA",
    "https://www.youtube.com/embed/vY0EzTP-7EA",
    "https://www.youtube.com/watch?list=PL1&v=vY0EzTP-7EA",
    "vY0EzTP-7EA",
])
def test_video_id_parsing(url):
    assert video_id(url) == "vY0EzTP-7EA"


@pytest.mark.parametrize("url", ["", "https://example.com/page", "not a url"])
def test_video_id_rejects_non_youtube(url):
    assert video_id(url) is None


def test_clean_spec_drops_everything_a_model_might_invent():
    spec, warnings = clean_spec({
        "headline": "Test", "style": "nateherk", "palette": "neon",
        "word_colors": {"A": "#FFD400", "B": "not-hex"},
        "labels": [{"text": "ok", "x": 5, "y": -2}, {"text": ""}, {"x": 0.2}],
        "diagram": {"nodes": [{"label": "A"}, {"label": ""}]},
        "subject": "someone else's face", "bogus": 1,
    })
    assert spec["style"] == "saraev"          # unknown style falls back
    assert "palette" not in spec              # palette did not belong to it
    assert "subject" not in spec              # never carried over
    assert "bogus" not in spec
    assert spec["word_colors"] == {"a": "#FFD400"}
    assert len(spec["labels"]) == 1 and 0.0 <= spec["labels"][0]["x"] <= 1.0
    assert spec["diagram"]["nodes"] == [{"label": "A"}]
    assert warnings


def test_clean_spec_output_is_renderable():
    """Whatever survives cleaning must satisfy the renderer's own schema."""
    from app.schema import ThumbnailRequest
    spec, _ = clean_spec({"headline": "Round trip", "style": "ottley",
                          "palette": "studio", "accent_words": ["trip"],
                          "behind": ["headline"]})
    ThumbnailRequest(**spec)
    compose(**{"headline": spec["headline"], "style_name": spec["style"],
               "palette": spec["palette"], "accent_words": spec["accent_words"],
               "behind": spec["behind"]})


# --------------------------------------------------------------------------- #
# The studio page — it has broken twice on string escaping
# --------------------------------------------------------------------------- #

@pytest.mark.skipif(not shutil.which("node"), reason="node not available")
def test_studio_javascript_parses():
    """A stray newline inside a JS string literal killed the whole page once."""
    body = PREVIEW_HTML[PREVIEW_HTML.index("<script>") + 8: PREVIEW_HTML.rindex("</script>")]
    proc = subprocess.run(["node", "--check", "-"], input=body, text=True,
                          capture_output=True)
    assert proc.returncode == 0, proc.stderr


def test_studio_html_is_balanced():
    assert PREVIEW_HTML.count("<script>") == PREVIEW_HTML.count("</script>") == 1
    assert PREVIEW_HTML.count("<style>") == PREVIEW_HTML.count("</style>") == 1


def test_studio_references_only_real_endpoints():
    """Relative fetches in the page must resolve against mounted routes."""
    mounted = {r.path for r in app.routes if hasattr(r, "path")}
    for call in set(re.findall(r"fetch\('([a-z/]+)'", PREVIEW_HTML)):
        assert f"/{call}" in mounted, f"studio fetches unmounted /{call}"


def test_studio_builds_its_pickers_from_the_api():
    """A hardcoded list silently goes stale the moment a preset is added.

    One swatch may legitimately appear as a placeholder example, so the check is
    that the page does not embed the palette, not that no hex exists anywhere.
    """
    for style in ALL_STYLES:
        assert f'"{style}"' not in PREVIEW_HTML, f"{style} is hardcoded in the studio"

    swatches = [hexv for group in WORD_PALETTE.values() for _, hexv in group]
    embedded = [h for h in swatches if h in PREVIEW_HTML]
    assert len(embedded) <= 1, f"studio embeds the palette: {embedded}"
    assert "fetch('palette')" in PREVIEW_HTML
    assert "fetch('styles')" in PREVIEW_HTML


# --------------------------------------------------------------------------- #
# Feed-size QA
# --------------------------------------------------------------------------- #

def test_qa_follows_the_headline_when_it_moves():
    img, _ = compose(headline="Top band copy", style_name="ottley",
                     palette="studio", text_position="top")
    assert legibility_report(img, "ottley", text_position="top")["verdict"] == "ok"


def test_qa_flags_an_illegible_headline():
    """Near-invisible type must not be reported as fine."""
    img, _ = compose(headline="Barely there", style_name="saraev", palette="bone",
                     word_colors={"barely": "#F7F6F3", "there": "#F7F6F3"},
                     hidden=["subject", "arrow"])
    assert legibility_report(img, "saraev")["verdict"] == "weak"


# --------------------------------------------------------------------------- #
# Tiled backdrop
# --------------------------------------------------------------------------- #

def test_tile_survives_the_api_round_trip():
    r = client.post("/generate", json={"headline": "x", "style": "herk",
                                       "tile": {"columns": 8, "opacity": 0.6, "cross": True},
                                       "output": "base64", "include_layout": True})
    assert r.status_code == 200


def test_tile_is_part_of_the_backdrop():
    """It must vanish with the backdrop when an element is isolated."""
    solo, _ = compose(headline="x", style_name="herk", only=["subject"],
                      tile={"columns": 6, "opacity": 1.0})
    plain, _ = compose(headline="x", style_name="herk", only=["subject"])
    assert solo.tobytes() == plain.tobytes(), "tile leaked into an isolated layer"


def test_tile_opacity_zero_changes_nothing():
    off, _ = compose(headline="x", style_name="herk", palette="desk", arrow=False)
    zero, _ = compose(headline="x", style_name="herk", palette="desk", arrow=False,
                      tile={"columns": 6, "opacity": 0.0})
    assert off.tobytes() == zero.tobytes()


def test_analyzer_cleans_a_tile_spec():
    spec, _ = clean_spec({"headline": "x", "style": "herk",
                          "tile": {"columns": 99, "opacity": 7, "cross": "yes"}})
    assert spec["tile"]["columns"] == 20
    assert spec["tile"]["opacity"] == 1.0
    from app.schema import ThumbnailRequest
    ThumbnailRequest(**spec)


# --------------------------------------------------------------------------- #
# Cycle layout and device frame
# --------------------------------------------------------------------------- #

def test_cycle_layout_drops_the_hub():
    from app.diagram import node_diagram
    nodes = [{"label": ""}] * 3
    hub = node_diagram(400, nodes, layout="hub")
    cycle = node_diagram(400, nodes, layout="cycle")
    assert hub.tobytes() != cycle.tobytes()
    assert cycle.height > hub.height, "a cycle is rendered squarer than a hub"


def test_framed_diagram_is_larger_than_its_content():
    from app.diagram import node_diagram
    nodes = [{"label": ""}] * 3
    bare = node_diagram(400, nodes, layout="cycle")
    framed = node_diagram(400, nodes, layout="cycle", frame="tablet",
                          frame_glow=(34, 211, 238))
    assert framed.width > bare.width and framed.height > bare.height


def test_framed_diagram_is_sized_to_its_box_before_fitting():
    """Frame padding once ate ~27% of the box, silently shrinking the device.

    Checking the *fitted* result proves nothing: `contain` always fills the
    limiting dimension, so any fill ratio measured after fitting is ~1.0 no
    matter how badly the layer was sized. The real invariant is upstream — the
    layer must be built at roughly the box's own width so fitting has nothing
    left to shrink.
    """
    from app.compositor import SCALE
    from app.diagram import node_diagram

    style = get_style("herk")
    box_px = style.diagram_box[2] * 1280 * SCALE
    rendered = node_diagram(
        max(200, int(box_px / 1.27)), [{"label": ""}] * 3,
        layout="cycle", frame="tablet", frame_glow=(34, 211, 238))
    overshoot = rendered.width / box_px
    assert 0.95 < overshoot < 1.05, (
        f"framed layer is {overshoot:.2f}x its box, so fitting rescales it")


def test_matting_backends_report_which_ran():
    """Vision and rembg are both optional; the caller must know what was used."""
    from app.matting import cut_out
    transparent = Image.new("RGBA", (40, 40), (255, 0, 0, 0))
    out, backend = cut_out(transparent)
    assert backend == "already-transparent"
    assert out.mode == "RGBA"


# --------------------------------------------------------------------------- #
# Pixel marks and avatar generation
# --------------------------------------------------------------------------- #

def test_pixel_sprite_has_hard_edges():
    """NEAREST scaling is the point; a smooth ramp means it got resampled."""
    from app.marks import robot
    r = robot(320)
    hist = r.getchannel("A").histogram()
    levels = [i for i, count in enumerate(hist) if count]
    assert levels == [0, 255], f"sprite alpha should be binary, got {levels[:8]}"


def test_pixel_marks_change_the_diagram():
    from app.diagram import node_diagram
    nodes = [{"label": ""}] * 3
    tiles = node_diagram(400, nodes, layout="cycle", mark="tile")
    pixels = node_diagram(400, nodes, layout="cycle", mark="pixel")
    assert tiles.tobytes() != pixels.tobytes()


def test_avatar_poses_are_listed():
    poses = {p["id"] for p in client.get("/avatar/poses").json()["poses"]}
    assert {"point-left", "point-right", "neutral"} <= poses


def test_avatar_requires_a_key_and_a_known_pose():
    ref = {"reference": "assets/fonts/OFL.txt"}
    assert client.post("/avatar", json=ref).status_code == 401
    r = client.post("/avatar", json={"reference": "x", "pose": "moonwalk"},
                    headers={"x-openrouter-key": "k"})
    assert r.status_code == 422 and "moonwalk" in r.json()["detail"]


def test_avatar_rejects_an_unreadable_reference():
    r = client.post("/avatar", json={"reference": "/does/not/exist.png"},
                    headers={"x-openrouter-key": "k"})
    assert r.status_code == 422


# --------------------------------------------------------------------------- #
# Rotation
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("element", ["subject", "headline"])
def test_rotation_changes_the_render(element):
    plain, _ = compose(headline="Tilt", style_name="saraev", palette="ink")
    spun, _ = compose(headline="Tilt", style_name="saraev", palette="ink",
                      overrides={element: {"rotate": 20}})
    assert plain.tobytes() != spun.tobytes()


@pytest.mark.parametrize("element", ["subject", "headline"])
def test_rotated_boxes_stay_positive_and_grow(element):
    """Unpacking the bounds helper wrongly once produced a negative height,
    which silently inverted the selection box in the studio."""
    flat = {m["id"]: m for m in compose(headline="Tilt", style_name="saraev",
                                        palette="ink")[1]}[element]
    spun = {m["id"]: m for m in compose(headline="Tilt", style_name="saraev", palette="ink",
                                        overrides={element: {"rotate": 25}})[1]}[element]
    assert spun["w"] > 0 and spun["h"] > 0, f"{element} box inverted: {spun}"
    assert spun["w"] >= flat["w"] and spun["h"] >= flat["h"], "rotated box should grow"


def test_rotation_is_symmetric():
    a = {m["id"]: m for m in compose(headline="Tilt", style_name="saraev",
                                     overrides={"subject": {"rotate": 30}})[1]}["subject"]
    b = {m["id"]: m for m in compose(headline="Tilt", style_name="saraev",
                                     overrides={"subject": {"rotate": -30}})[1]}["subject"]
    assert abs(a["w"] - b["w"]) < 0.01 and abs(a["h"] - b["h"]) < 0.01


def test_rotation_is_validated():
    assert client.post("/generate", json={"headline": "x",
                                          "overrides": {"subject": {"rotate": 400}}}).status_code == 422


# --------------------------------------------------------------------------- #
# AI edits must stay composable
# --------------------------------------------------------------------------- #

def test_supplied_background_suppresses_style_backdrop_effects(monkeypatch):
    """An edited backdrop already carries its lighting; re-applying glow and
    vignette on top darkens it twice and made AI edits look muddy.

    Asserted on the call path rather than on pixels: on a dark preset the
    corners are already near-black, so doubling the vignette moves the mean by
    under one level and any pixel threshold that catches it also catches
    ordinary resampling noise.
    """
    import base64 as b64, io as _io
    from app import compositor

    calls = []
    for name in ("vignette", "radial_glow"):
        real = getattr(compositor, name)
        monkeypatch.setattr(compositor, name,
                            lambda *a, _n=name, _r=real, **k: (calls.append(_n), _r(*a, **k))[1])

    compose(headline="x", style_name="roberts", palette="electric")
    assert "vignette" in calls and "radial_glow" in calls, "preset should light its own backdrop"

    plate, _ = compose(headline="x", style_name="roberts", palette="electric",
                       hidden=["subject", "headline", "arrow"])
    buf = _io.BytesIO(); plate.save(buf, format="PNG")
    as_bg = b64.b64encode(buf.getvalue()).decode()

    calls.clear()
    compose(headline="x", style_name="roberts", palette="electric", background=as_bg)
    assert calls == [], f"backdrop effects re-applied over a supplied plate: {calls}"


# --------------------------------------------------------------------------- #
# Avatar panel, versions and the post-edit lockout
# --------------------------------------------------------------------------- #

def test_edit_sends_only_the_backdrop_by_default():
    """Including the cutout bakes it into pixels, which is what left the studio
    with nothing selectable after an AI edit."""
    from app.schema import EditRequest
    req = EditRequest(spec={"headline": "x"}, instruction="cinematic grade")
    assert req.include_subject is False


def test_studio_carries_the_edited_backdrop_forward():
    """The page must re-render over the edit rather than freezing the image."""
    assert "EDITED_BG" in PREVIEW_HTML
    assert "body.background=EDITED_BG" in PREVIEW_HTML
    assert "j.backdrop" in PREVIEW_HTML


def test_studio_has_rotation_and_version_controls():
    for hook in ("startRotate", "saveVersion", "restoreVersion", "runAvatar"):
        assert hook in PREVIEW_HTML, f"{hook} missing from the studio"


def test_rotation_survives_the_api():
    r = client.post("/generate", json={"headline": "x", "output": "base64",
                                       "include_layout": True,
                                       "overrides": {"subject": {"rotate": -20}}})
    assert r.status_code == 200
    assert any(m["id"] == "subject" for m in r.json()["layout"])


# --------------------------------------------------------------------------- #
# Card props
# --------------------------------------------------------------------------- #

CARD_TYPES = [c["type"] for c in client.get("/cards").json()["cards"]]


@pytest.mark.parametrize("kind", CARD_TYPES)
def test_every_card_type_renders(kind):
    card = {"type": kind, "text": "$45,208", "sublabel": "last 30 days",
            "items": ["one", "two", "three"], "metrics": ["792", "1.4K"]}
    img, manifest = compose(headline="x", style_name="herk", palette="desk",
                            arrow=False, card=card)
    assert img.size == (1280, 720)
    assert any(m["id"] == "hero" for m in manifest), f"{kind} produced no prop"


@pytest.mark.parametrize("kind", CARD_TYPES)
def test_card_types_are_visually_distinct(kind):
    base, _ = compose(headline="x", style_name="herk", palette="desk", arrow=False,
                      hidden=["subject", "headline"])
    card, _ = compose(headline="x", style_name="herk", palette="desk", arrow=False,
                      hidden=["subject", "headline"],
                      card={"type": kind, "text": "Body", "sublabel": "sub",
                            "items": ["a", "b"], "metrics": ["1"]})
    assert base.tobytes() != card.tobytes()


def test_cards_endpoint_matches_the_schema():
    """A type listed but not accepted would break the studio's dropdown."""
    from app.schema import CARD_TYPES as declared
    assert set(CARD_TYPES) == set(declared)


def test_legacy_card_fields_still_work():
    """Callers written before `card` existed must keep rendering."""
    old, _ = compose(headline="x", style_name="herk", arrow=False,
                     card_text="Body", card_name="Me", card_handle="@me")
    new, _ = compose(headline="x", style_name="herk", arrow=False,
                     card={"type": "tweet", "text": "Body", "name": "Me", "handle": "@me"})
    assert old.tobytes() == new.tobytes()

    toast_old, _ = compose(headline="x", style_name="herk", arrow=False,
                           toast_text="Paid", toast_amount="$10")
    toast_new, _ = compose(headline="x", style_name="herk", arrow=False,
                           card={"type": "toast", "text": "Paid", "sublabel": "$10"})
    assert toast_old.tobytes() == toast_new.tobytes()


def test_card_rejects_an_unknown_type():
    r = client.post("/generate", json={"headline": "x", "card": {"type": "hologram"}})
    assert r.status_code == 422


def test_studio_builds_the_card_picker_from_the_api():
    """The picker must come from /cards, or it goes stale when a type is added.

    Checked on the markup rather than by scanning for the type names: "chat" is
    also the id of the AI column, so a bare substring search reports a false
    hardcoding.
    """
    picker = re.search(r'<select id="cardtype">(.*?)</select>', PREVIEW_HTML, re.S)
    assert picker, "card picker missing"
    options = re.findall(r'<option[^>]*value="([^"]*)"', picker.group(1))
    assert options == [""], f"picker ships hardcoded options: {options}"
    assert "fetch('cards')" in PREVIEW_HTML
