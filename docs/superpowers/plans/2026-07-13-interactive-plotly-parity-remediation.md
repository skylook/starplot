# Interactive Plotly Parity Remediation Implementation Plan

> For agentic workers: execute the numbered tasks in order. Do not start visual example tuning until Tasks 1 through 6 pass. Use checkbox items as the execution log.

**Goal:** Make the Plotly backend reproduce final Matplotlib geometry, clipping, labels, gradients, layout, and auxiliary content for Map, Horizon, Zenith, and Optic plots.

**Architecture:** Matplotlib is the projection/layout authority. The recorder emits a typed final display list in DATA, AXES, or PAPER coordinates. PlotlyRenderer only replays final coordinates and clips spatial primitives against the recorded data-space clip polygon.

**Tech stack:** Python, Matplotlib, Cartopy, Shapely already in this repository, Plotly, Kaleido, pytest.

## Non-negotiable constraints

- Work on the current dirty branch. Begin with git status --short. Never reset, checkout, or overwrite unrelated changes.
- No added dependency and no public API change to Interactive*Plot, to_plotly, or export_html.
- Raw RA/DEC/AZ/ALT must never reach PlotlyRenderer.
- Unknown coordinate spaces must raise ValueError. Never silently guess a source coordinate frame.
- Preserve Matplotlib behavior. Record after source rendering or extract final artists.
- transparent=True means both Plotly paper and plotting backgrounds are transparent.
- Do not use a permanently skipped visual test. pytest.importorskip("kaleido") is permitted only when Kaleido is absent.
- Never implement an example-name branch, per-example offset, or change an original example to conceal a Plotly defect.
- Generate a comparison only from comparison_outputs: python gen_comparison.py <example>.

## Required display-list contract

Implement this exact contract in src/starplot/interactive/commands.py.

~~~python
from dataclasses import dataclass, field
from enum import StrEnum

class CoordinateSpace(StrEnum):
    DATA = "data"      # final x/y in x_min/x_max/y_min/y_max
    AXES = "axes"      # normalized [0, 1] in Matplotlib axes
    PAPER = "paper"    # normalized [0, 1] in full figure

@dataclass(frozen=True)
class ClipGeometry:
    kind: str  # "none", "rect", "polygon"
    points: tuple[tuple[float, float], ...] = ()

@dataclass
class DrawingCommand:
    kind: str
    data: dict = field(default_factory=dict)
    style: dict = field(default_factory=dict)
    metadata: list = field(default_factory=list)
    zorder: int = 0
    gid: str = ""
    space: CoordinateSpace = CoordinateSpace.DATA
    clip_id: str | None = "plot"

    def __post_init__(self):
        try:
            self.space = CoordinateSpace(self.space)
        except ValueError as error:
            raise ValueError(f"Unknown coordinate space: {self.space}") from error
~~~

| Kind | Required space | Mandatory details |
| --- | --- | --- |
| scatter, line, line_collection, polygon | DATA | final projected geometry only |
| sky-attached text | DATA | offset_points tuple, final alignment and rotation |
| footer/title/grid/info text | AXES or PAPER | no data projection |
| gradient | DATA | normalized stops and clip_id |
| info table | PAPER | final normalized rectangle/cell coordinates |

DrawingRecorder.projection_info must contain:

~~~python
{
    "x_min": float, "x_max": float, "y_min": float, "y_max": float,
    "axes_bbox": (left, bottom, width, height),
    "axes_pixels": (width_px, height_px),
    "plot_kind": "map" | "horizon" | "zenith" | "optic",
    "clip_geometries": {"plot": ClipGeometry(...)},
}
~~~

Clip points are final DATA coordinates. Do not serialize Matplotlib Patches, transforms, CRSs, or Shapely objects.

## File ownership

| File | Change responsibility |
| --- | --- |
| src/starplot/interactive/commands.py | typed spaces and serializable clip contract |
| src/starplot/interactive/recorder.py | enforce command contract |
| src/starplot/interactive/recording_mixin.py | sole conversion boundary, artist extraction, metadata, missing content |
| src/starplot/interactive/plotly_renderer.py | pure replay, clipping, layout, annotations, gradients |
| src/starplot/interactive/plots.py | pass requested dimensions without API changes |
| tests/test_interactive/test_recording_contract.py | new artist-to-command parity tests |
| tests/test_interactive/test_plotly_renderer.py | clipping/text/gradient/transparency tests |
| tests/test_interactive/test_visual_consistency.py | enabled Kaleido visual gates |

## Task 1: Freeze the typed command contract

**Files:**
- Modify: src/starplot/interactive/commands.py
- Modify: src/starplot/interactive/recorder.py
- Create: tests/test_interactive/test_recording_contract.py

**Produces:** CoordinateSpace, ClipGeometry, DrawingCommand.space, DrawingCommand.clip_id; every record_* supports keyword-only space and clip_id.

- [ ] **1. Write failing tests.**

~~~python
import pytest
from starplot.interactive.commands import CoordinateSpace, DrawingCommand
from starplot.interactive.recorder import DrawingRecorder

def test_recorder_marks_spatial_commands_as_final_data_space():
    recorder = DrawingRecorder()
    recorder.record_line(x=[1.0, 2.0], y=[3.0, 4.0], style_dict={},
                         gid="line", zorder=0, space=CoordinateSpace.DATA,
                         clip_id="plot")
    assert recorder.commands[0].space is CoordinateSpace.DATA
    assert recorder.commands[0].clip_id == "plot"

def test_command_rejects_unknown_coordinate_space():
    with pytest.raises(ValueError, match="Unknown coordinate space"):
        DrawingCommand(kind="line", space="ra_dec")
~~~

- [ ] **2. Verify red.**

Run: python -m pytest -o addopts='' tests/test_interactive/test_recording_contract.py -q  
Expected: FAIL because the types/arguments do not exist.

- [ ] **3. Implement.** Add the exact types above. Give every recorder method keyword-only space=CoordinateSpace.DATA and clip_id="plot"; pass both to DrawingCommand. Make record_text require explicit space because text can be DATA, AXES, or PAPER. Update all call sites in the same change.

- [ ] **4. Verify green.**

Run: python -m pytest -o addopts='' tests/test_interactive/test_recording_contract.py -q  
Expected: PASS.

- [ ] **5. Commit.**

~~~bash
git add src/starplot/interactive/commands.py src/starplot/interactive/recorder.py tests/test_interactive/test_recording_contract.py
git commit -m "Define final-coordinate contract for interactive drawing commands" -m "Constraint: Plotly must replay geometry without a second projection" -m "Confidence: high" -m "Scope-risk: moderate" -m "Tested: test_recording_contract"
~~~

## Task 2: Record final axes and clipping geometry once

**Files:**
- Modify: src/starplot/interactive/recording_mixin.py, methods _record_plot_info and _plot_border
- Modify: tests/test_interactive/test_recording_contract.py

**Produces:** plot metadata has axes_bbox, axes_pixels, plot_kind, and clip_geometries["plot"] for Map/Horizon/Zenith/Optic.

- [ ] **1. Write a failing four-family metadata test.**

~~~python
import math
import pytest

@pytest.mark.parametrize("plot_factory, expected_kind", [
    (make_map_plot, "rect"),
    (make_horizon_plot, "rect"),
    (make_zenith_plot, "polygon"),
    (make_optic_plot, "polygon"),
])
def test_plot_metadata_has_final_clip_and_axes_geometry(plot_factory, expected_kind):
    plot = plot_factory()
    plot._record_plot_info()
    info = plot._recorder.projection_info
    assert info["plot_kind"] in {"map", "horizon", "zenith", "optic"}
    assert info["axes_pixels"][0] > 0 and info["axes_pixels"][1] > 0
    clip = info["clip_geometries"]["plot"]
    assert clip.kind == expected_kind
    assert len(clip.points) >= (4 if expected_kind == "rect" else 64)
    assert all(math.isfinite(v) for point in clip.points for v in point)
~~~

Define the factories in this test module as follows: make_map_plot uses InteractiveMapPlot(projection=Miller(), ra_min=60, ra_max=120, dec_min=-10, dec_max=30, resolution=512); make_horizon_plot uses InteractiveHorizonPlot(altitude=(0, 60), azimuth=(325, 440), resolution=512); make_zenith_plot copies the observer and constructor arguments from examples/interactive/star_chart_basic_interactive.py with resolution=512; make_optic_plot copies observer/optic constructor arguments from examples/interactive/optic_m45_interactive.py but uses ra=90.0 and dec=10.0 rather than DSO.get. Factory construction must not query a catalog.

- [ ] **2. Verify red.**

Run: python -m pytest -o addopts='' tests/test_interactive/test_recording_contract.py::test_plot_metadata_has_final_clip_and_axes_geometry -q  
Expected: FAIL for missing metadata.

- [ ] **3. Implement _record_final_clip_geometry().** Call fig.draw_without_rendering first. Transform _background_clip_path.get_path through patch.get_transform and then ax.transData.inverted. Filter finite vertices and remove duplicate closing point. Require at least 3 vertices. Record rect only for exactly four unique vertices; otherwise polygon. Record ax.get_position().bounds, ax.get_window_extent width/height, and plot kind through explicit isinstance checks. The current synthetic Optic circle may remain cosmetic but is never the source of clip truth.

- [ ] **4. Verify and commit.**

Run: python -m pytest -o addopts='' tests/test_interactive/test_recording_contract.py -q  
Expected: PASS.

~~~bash
git add src/starplot/interactive/recording_mixin.py tests/test_interactive/test_recording_contract.py
git commit -m "Record final axes and clip geometry for interactive plots" -m "Constraint: circular Matplotlib clips must be serializable" -m "Confidence: high" -m "Scope-risk: moderate" -m "Tested: clip metadata cases"
~~~

## Task 3: Use one conversion boundary; extract final source artists

**Files:**
- Modify: src/starplot/interactive/recording_mixin.py, coordinate helper, marker/text/lines/constellations/gridlines
- Modify: tests/test_interactive/test_recording_contract.py
- Modify: tests/test_interactive/test_plotly_renderer.py

**Produces:** _to_final_data is the only coordinate converter. Constellation and grid geometry are captured from final Matplotlib artists.

- [ ] **1. Write failing geometry tests.**

~~~python
@pytest.mark.parametrize("plot_factory", [
    make_map_plot, make_horizon_plot, make_zenith_plot, make_optic_plot,
])
def test_recorded_marker_matches_matplotlib_artist_data_coordinate(plot_factory):
    plot = plot_factory()
    plot.marker(ra=90.0, dec=10.0, label="probe")
    command = next(c for c in plot._recorder.commands if c.gid == "marker")
    expected = plot.ax.collections[-1].get_offsets()[0]
    assert command.space.value == "data"
    assert command.data["x"] == pytest.approx([expected[0]])
    assert command.data["y"] == pytest.approx([expected[1]])

def test_renderer_contains_no_coordinate_transform_calls():
    source = Path("src/starplot/interactive/plotly_renderer.py").read_text()
    assert "transform_point(" not in source
    assert "_prepare_coords(" not in source
~~~

- [ ] **2. Verify red.**

Run: python -m pytest -o addopts='' tests/test_interactive/test_recording_contract.py -q  
Expected: at least one plot family fails before cleanup.

- [ ] **3. Add the sole conversion boundary.**

~~~python
def _to_final_data(self, x: float, y: float, source_space: str) -> tuple[float, float]:
    if source_space == "prepared":
        return tuple(map(float, self._proj.transform_point(x, y, self._crs)))
    if source_space == "radec":
        px, py = self._prepare_coords(x, y)
        return tuple(map(float, self._proj.transform_point(px, py, self._crs)))
    raise ValueError(f"Unknown interactive source space: {source_space}")
~~~

Use radec only for public RA/DEC arguments. Use prepared only after source code called _prepare_coords. Delete _project_coords after migrating callers.

For constellations(), constellation_borders(), and gridlines(): record final artists created by super(), not regenerated catalog coordinates. Capture newly created LineCollection, Line2D, and Text artists through pre/post collection counts and gid. Read final data vertices, split non-finite segments, and record unchanged. This preserves Map RA wrap/inversion and Horizon azimuth shift, divider, ticks, and formatter behavior. Delete manual grid reconstruction only after tests pass.

- [ ] **4. Verify and commit.**

Run: python -m pytest -o addopts='' tests/test_interactive/test_recording_contract.py tests/test_interactive/test_plotly_renderer.py -q  
Expected: PASS.

~~~bash
git add src/starplot/interactive/recording_mixin.py tests/test_interactive/test_recording_contract.py tests/test_interactive/test_plotly_renderer.py
git commit -m "Record final Matplotlib geometry without projection guesses" -m "Rejected: catalog reconstruction loses source wrap and transforms" -m "Confidence: high" -m "Scope-risk: broad" -m "Tested: four-family geometry parity"
~~~

## Task 4: Clip every spatial primitive

**Files:**
- Modify: src/starplot/interactive/plotly_renderer.py
- Modify: tests/test_interactive/test_plotly_renderer.py
- Modify: tests/test_interactive/test_recording_contract.py

**Produces:** no scatter, line, polygon, or gradient pixels outside clip_id.

- [ ] **1. Write failing renderer tests.**

~~~python
def test_scatter_points_outside_clip_are_not_rendered():
    renderer = renderer_with_circle_clip()
    figure = renderer.render([scatter_command(x=[0.0, 1.5], y=[0.0, 0.0])])
    assert list(figure.data[0].x) == [0.0]

def test_line_crossing_circle_is_trimmed_to_boundary():
    renderer = renderer_with_circle_clip()
    figure = renderer.render([line_command(x=[-2.0, 2.0], y=[0.0, 0.0])])
    assert list(figure.data[0].x) == pytest.approx([-1.0, 1.0])
~~~

renderer_with_circle_clip must use a 64-vertex unit-circle ClipGeometry. Calculate expected geometry with Shapely Point, LineString, and Polygon; do not assert only trace counts.

- [ ] **2. Verify red.**

Run: python -m pytest -o addopts='' tests/test_interactive/test_plotly_renderer.py -q  
Expected: FAIL because traces are unbounded.

- [ ] **3. Implement one _clip_command().** Build Shapely polygons once in renderer construction. For scatter, filter x/y/sizes/colors/alphas/metadata with one mask. Intersect line and collection geometry with clip polygon and retain every LineString fragment separated by None. Intersect polygons and render every result exterior. For gradients, set samples outside clip to np.nan and use transparent missing cells. Invoke clipping before renderer dispatch and skip empty commands. Do not use opaque masks; transparent exports must still work.

- [ ] **4. Add integration check.** Parameterize Zenith, circular Optic, and Camera Optic after stars(); assert every emitted marker is covered by Polygon(recorded_clip.points).

- [ ] **5. Verify and commit.**

Run: python -m pytest -o addopts='' tests/test_interactive/test_plotly_renderer.py tests/test_interactive/test_recording_contract.py -q  
Expected: PASS.

Run: cd comparison_outputs && python gen_comparison.py optic_m45  
Expected: no star, DSO, line, or gradient outside the source field.

~~~bash
git add src/starplot/interactive/plotly_renderer.py tests/test_interactive/test_plotly_renderer.py tests/test_interactive/test_recording_contract.py
git commit -m "Clip interactive primitives to the final plot boundary" -m "Constraint: Plotly lacks native circular trace clipping" -m "Rejected: cosmetic outer ring leaks visual content" -m "Confidence: high" -m "Scope-risk: broad" -m "Tested: clipping tests and optic_m45"
~~~

## Task 5: Preserve final label placement and style

**Files:**
- Modify: src/starplot/interactive/recording_mixin.py, _text/gridlines/labels
- Modify: src/starplot/interactive/plotly_renderer.py, _render_text
- Modify: both interactive test files

**Produces:** offsets, final anchor, rotation, alpha, font style/weight, and text stroke survive replay.

- [ ] **1. Write failing tests.**

~~~python
def test_text_command_preserves_offset_and_rotation():
    plot = make_horizon_plot()
    plot._text(380.0, 30.0, "Probe", xytext=(12, -8), rotation=15, gid="probe")
    command = next(c for c in plot._recorder.commands if c.gid == "probe")
    assert command.data["offset_points"] == (12.0, -8.0)
    assert command.style["rotation"] == 15.0
    assert command.space.value == "data"

def test_renderer_converts_offset_points_to_pixels():
    figure = renderer_with_known_axes_pixels().render([
        text_command(offset_points=(7.2, -3.6))
    ])
    annotation = figure.layout.annotations[0]
    assert annotation.xshift == pytest.approx(10.0)
    assert annotation.yshift == pytest.approx(-5.0)
~~~

- [ ] **2. Verify red.**

Run: python -m pytest -o addopts='' tests/test_interactive/test_recording_contract.py tests/test_interactive/test_plotly_renderer.py -q  
Expected: FAIL because xytext and rotation are discarded.

- [ ] **3. Implement.** Read final properties from Annotation returned by super()._text: xyann, alignment, rotation, alpha, font weight/style, clip flag, and path effects. Store offset_points in data, resolved properties in style, and keep existing collision remove patch. Extracted grid/footer/title/info uses AXES/PAPER. Add one renderer _points_to_pixels helper used for font size and offsets. Set textangle. For has_text_stroke=True render one behind annotation; do not serialize Matplotlib path-effect objects.

- [ ] **4. Verify and visual gate.**

Run: python -m pytest -o addopts='' tests/test_interactive/test_recording_contract.py tests/test_interactive/test_plotly_renderer.py -q  
Expected: PASS.

Run: cd comparison_outputs && python gen_comparison.py horizon_gradient && python gen_comparison.py horizon_double_cluster  
Expected: all source labels appear, including 30/40/50 degree labels and DSO/constellation labels, with equivalent anchor and offset.

- [ ] **5. Commit.**

~~~bash
git add src/starplot/interactive/recording_mixin.py src/starplot/interactive/plotly_renderer.py tests/test_interactive/test_recording_contract.py tests/test_interactive/test_plotly_renderer.py
git commit -m "Preserve final Matplotlib label placement in Plotly" -m "Constraint: collision handling mutates final anchor and offset" -m "Confidence: high" -m "Scope-risk: moderate" -m "Tested: annotation tests and Horizon pairs"
~~~

## Task 6: Layout, gradients, transparency, scale, and info

**Files:**
- Modify: src/starplot/interactive/plotly_renderer.py
- Modify: src/starplot/interactive/recording_mixin.py
- Modify: src/starplot/interactive/plots.py
- Modify: renderer and visual tests

**Produces:** correct layout and gradients; no hard-coded footer/table geometry; magnitude scale, Zenith info, Optic info, and transparency work.

- [ ] **1. Write failing tests.**

~~~python
def test_transparent_export_clears_paper_and_plot_backgrounds():
    fig = make_map_plot().to_plotly(transparent=True)
    assert fig.layout.paper_bgcolor == "rgba(0,0,0,0)"
    assert fig.layout.plot_bgcolor == "rgba(0,0,0,0)"

def test_radial_gradient_uses_source_radius_squared_and_reversal():
    figure = renderer_with_circle_clip().render([radial_gradient_command()])
    heatmap = next(trace for trace in figure.data if trace.type == "heatmap")
    assert heatmap.z[0][0] == pytest.approx(1.0)

def test_magnitude_scale_and_zenith_info_are_recorded():
    plot = make_zenith_plot()
    plot.star_magnitude_scale()
    plot.info()
    assert any(c.gid == "star-magnitude-scale" for c in plot._recorder.commands)
    assert any(c.gid == "zenith-info" for c in plot._recorder.commands)
~~~

- [ ] **2. Verify red.**

Run: python -m pytest -o addopts='' tests/test_interactive/test_plotly_renderer.py tests/test_interactive/test_visual_consistency.py -q  
Expected: FAIL for missing behavior.

- [ ] **3. Implement layout/transparency.** Use recorded axes_bbox as axis domains and calculate target axes pixels from width/height/domain. Do not mutate margins after trace dispatch for Horizon labels/footer. Retain 1:1 only when recorded data/axes aspect requires it. Set both Plotly backgrounds to rgba(0,0,0,0) when transparent.

- [ ] **4. Implement gradient parity.** Mirror GradientBackgroundMixin: radial stop positions divide by two with final position one; colors reverse; value is radius ** 2; cells are clipped. Linear rises bottom-to-top. Mollweide must record/render its dedicated source mesh and cannot fall through to linear.

- [ ] **5. Extract missing artists.** After super().star_magnitude_scale(), record newly-created handles/text as star-magnitude-scale. After ZenithPlot.info(), record actual ax.text as AXES zenith-info. For Optic info, extract final rectangle/text geometry and normalize to PAPER; delete hard-coded renderer constants -0.045, -0.09, 0.55, 0.48.

- [ ] **6. Enable visual gates.** Replace permanent skip in test_visual_consistency.py with pytest.mark.integration plus pytest.importorskip("kaleido"). Resize/crop images to the recorded axes bbox before diff. Add separate tests for horizon_gradient, optic_m45, map_orthographic, and star_chart_detail. Each test must require a changed-pixel fraction no greater than 0.35 after identical-size axes cropping, and must also run the Task 7 visual checklist; a numeric pass alone never accepts a result.

- [ ] **7. Verify and commit.**

Run: python -m pytest -o addopts='' tests/test_interactive/test_plotly_renderer.py tests/test_interactive/test_visual_consistency.py -q  
Expected: PASS.

Run: cd comparison_outputs && python gen_comparison.py optic_m45 && python gen_comparison.py map_orthographic && python gen_comparison.py star_chart_detail && python gen_comparison.py horizon_gradient  
Expected: no clip leaks/missing scale/info; no obvious gradient inversion.

~~~bash
git add src/starplot/interactive/plots.py src/starplot/interactive/recording_mixin.py src/starplot/interactive/plotly_renderer.py tests/test_interactive/test_plotly_renderer.py tests/test_interactive/test_visual_consistency.py
git commit -m "Complete Plotly layout gradients and auxiliary chart content" -m "Rejected: hard-coded footer/table coordinates are not size-stable" -m "Confidence: medium" -m "Scope-risk: broad" -m "Tested: focused tests and four comparison examples"
~~~

## Task 7: Accept all 22 pairs sequentially

**Files:**
- Create: comparison_outputs/interactive-parity-ledger.md
- Modify shared interactive code only for a newly tested common root cause.

- [ ] **1. Generate in this exact order.**

~~~bash
cd comparison_outputs
for example in horizon_double_cluster horizon_gradient horizon_sgr galaxy_custom_marker map_big map_big_dipper map_canis_major map_carina map_cas map_milky_way_stars map_orion map_orthographic map_sagittarius map_virgo_cluster optic_iss_transit optic_m45 optic_moon_saturn optic_orion_nebula optic_solar_eclipse star_chart_basic star_chart_detail star_chart_french; do python gen_comparison.py "$example" || exit 1; done
~~~

- [ ] **2. Review every orig.png / plotly.png pair in this fixed order.**

1. canvas/axes bounds/background/transparency;
2. clip boundary/no outside pixels;
3. star/DSO positions and relative size;
4. constellation endpoints, seams, borders;
5. gridlines, ticks, footer, all labels;
6. gradient and Milky Way/polygon fills;
7. title, legend, scale, info table, custom markers.

Only use PASS, renderer-font-only, or FAIL. Font-only is allowed only when glyph count, anchor, position, color, and size match. Missing/shifted content, incorrect coordinates, clip leaks, size mismatch, or wrong gradient direction is FAIL.

- [ ] **3. For each FAIL:** first write a focused regression test; fix shared code; rerun the failed example and one different plot family using the same primitive. Never add an example-specific condition.

- [ ] **4. Add 22 ledger rows.**

~~~markdown
| Example | Generated | Visual result | Difference explained | Regression tests | Notes |
| --- | --- | --- | --- | --- | --- |
| horizon_double_cluster | yes | PASS | n/a | test_horizon_* | verified clip/grid/lines/labels |
~~~

- [ ] **5. Run final gates.**

~~~bash
python -m pytest -o addopts='' tests/test_interactive/ -q
python -m py_compile src/starplot/interactive/commands.py src/starplot/interactive/recorder.py src/starplot/interactive/recording_mixin.py src/starplot/interactive/plotly_renderer.py src/starplot/interactive/plots.py
git diff --check
~~~

Expected: every command exits zero and ledger has 22 rows with no FAIL.

## Completion review checklist

- [ ] PlotlyRenderer has no Cartopy/projection call.
- [ ] spatial commands are DATA; footer/title/info are AXES/PAPER.
- [ ] scatter, line, polygon, and gradient are clip-aware.
- [ ] constellations/gridlines use final source artists, not coordinate reconstruction.
- [ ] final text offsets/collision placement survive replay.
- [ ] radial and Mollweide gradients have dedicated behavior.
- [ ] magnitude scale, Zenith info, Optic info, and transparency work.
- [ ] all interactive tests pass and visual ledger contains no failure.

## Scope self-review

This plan covers coordinate-frame drift and double transform (Tasks 1-3), constellation/grid semantics (Task 3), non-rectangular clips (Tasks 2 and 4), labels (Task 5), gradients/layout/transparency/missing primitives (Task 6), and the 22 visual pairs (Task 7). It does not authorize new dependencies, public API changes, original-example edits, or one-off visual hacks.
