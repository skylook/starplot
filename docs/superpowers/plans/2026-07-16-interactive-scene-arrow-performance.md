# Interactive Scene and Arrow Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the list/JSON-heavy Plotly path with a backend-neutral, NumPy-backed Scene pipeline and Apache Arrow IPC delivery that supports identical inline, static, and API rendering.

**Architecture:** Final Matplotlib artists remain the geometry and layout authority. A `SceneCompiler` converts recorded commands into immutable columnar `SceneLayer` objects; Python and JavaScript Plotly adapters consume the same `ScenePackage`, while Arrow IPC Stream bytes and a versioned manifest provide inline, static, and remote transport.

**Tech Stack:** Python 3.10+, NumPy, Shapely 2, PyArrow, Pydantic 2, Plotly 6+, standard-library HTTP server, browser JavaScript, Apache Arrow JS 21.1, pytest, Node's built-in test runner, Kaleido/Chrome for final screenshots.

## Global Constraints

- Read `docs/superpowers/specs/2026-07-16-interactive-scene-arrow-performance-design.md` before every task.
- Do not modify Matplotlib rendering to hide a web-backend difference.
- Do not branch on example names, catalog names, or a specific projection name.
- Raw RA/Dec is Catalog authority; final projected x/y is Scene rendering authority.
- Scene and Arrow schemas must not contain Plotly trace names.
- Inline, static, and complete-scene API modes must decode to identical Scene data.
- Use Arrow IPC Stream format in every delivery mode; do not mix IPC File and Stream containers.
- Preserve `to_plotly()` and `export_html()`; external bundle becomes the default only in Task 8.
- Raise the optional dependency floor to `plotly>=6.0`; do not implement a Plotly 5 fallback.
- Add no required Python web framework.
- New browser runtime dependency is limited to version-pinned Apache Arrow JS.
- Keep arrays contiguous and read-only after recording; do not convert high-volume arrays to Python lists.
- Required layer failures are fail-fast and visible; never silently omit a failed layer.
- Preserve unrelated dirty-worktree changes and stage only files owned by the current task.
- Every commit follows the repository Lore Commit Protocol and records exact tests and known gaps.

---

## Locked file structure

| Path | Responsibility |
| --- | --- |
| `src/starplot/interactive/scene.py` | Scene enums, immutable columnar data, layers, package, capabilities |
| `src/starplot/interactive/scene_compiler.py` | DrawingCommand to ScenePackage, vectorized clip, palette, precision |
| `src/starplot/interactive/scene_manifest.py` | Pydantic manifest models, version validation, canonical hashing |
| `src/starplot/interactive/arrow_transport.py` | Arrow schemas, IPC Stream encode/decode, layer hashes |
| `src/starplot/interactive/plotly_adapter.py` | Python ScenePackage to Plotly Figure adapter |
| `src/starplot/interactive/web_export.py` | HTML shell and inline/static/remote bundle export |
| `src/starplot/interactive/scene_provider.py` | Framework-neutral complete-scene, viewport, and detail provider |
| `src/starplot/interactive/assets/starplot-scene-loader.js` | Browser SceneSource implementations and orchestration |
| `src/starplot/interactive/assets/plotly-scene-adapter.js` | Browser Scene primitive to Plotly trace/layout mapping |
| `src/starplot/interactive/assets/vendor/apache-arrow.min.js` | Pinned official Apache Arrow JS browser bundle |
| `web/package.json` | Arrow JS pin and Node test commands; no bundler |
| `web/tests/*.test.mjs` | Browser-loader and adapter unit contracts using `node:test` |
| `benchmarks/interactive_scene_pipeline.py` | Isolated Python/payload/browser benchmark harness |
| `benchmarks/baselines/*.json` | Machine-readable pre-change and final benchmark records |

The existing `PlotlyRenderer` remains a compatibility facade until Task 5. Do not duplicate Scene semantics in new files and the legacy renderer.

### Task 1: Capture a reproducible pre-change baseline

**Files:**
- Create: `benchmarks/interactive_scene_pipeline.py`
- Create: `tests/test_interactive/test_performance_harness.py`
- Create by running harness: `benchmarks/baselines/interactive_scene_pre_arrow.json`

**Interfaces:**
- Produces: `run_python_benchmark(point_count: int, repeats: int) -> dict`
- Produces: JSON keys `environment`, `point_count`, `scene_compile`, `peak_rss_mb`, `payload_bytes`, and `browser`.
- Consumes: current `DrawingCommand`, `PlotlyRenderer`, and the existing million-star HTML if present.

- [ ] **Step 1: Write the failing harness-schema test**

```python
from benchmarks.interactive_scene_pipeline import validate_result


def test_benchmark_result_schema_rejects_missing_metrics():
    with pytest.raises(ValueError, match="scene_compile"):
        validate_result({"environment": {}, "point_count": 100})


def test_benchmark_result_schema_accepts_complete_result():
    validate_result({
        "environment": {"python": "3.12", "platform": "test"},
        "point_count": 100,
        "scene_compile": {"median_seconds": 1.0, "p95_seconds": 1.2},
        "peak_rss_mb": 10.0,
        "payload_bytes": 1000,
        "browser": {"complete_render_median_ms": 100.0},
    })
```

- [ ] **Step 2: Run the focused test and verify failure**

Run:

```bash
python -m pytest -o addopts='' tests/test_interactive/test_performance_harness.py -q
```

Expected: FAIL because `benchmarks.interactive_scene_pipeline` does not exist.

- [ ] **Step 3: Implement the deterministic harness**

Implement these exact public helpers:

```python
REQUIRED_RESULT_KEYS = {
    "environment", "point_count", "scene_compile",
    "peak_rss_mb", "payload_bytes", "browser",
}


def validate_result(result: dict) -> None:
    missing = REQUIRED_RESULT_KEYS - result.keys()
    if missing:
        raise ValueError(f"Missing benchmark keys: {sorted(missing)}")


def percentile(values: list[float], q: float) -> float:
    return float(np.percentile(np.asarray(values, dtype=np.float64), q))


def summarize(values: list[float]) -> dict[str, float]:
    return {
        "median_seconds": percentile(values, 50),
        "p95_seconds": percentile(values, 95),
    }
```

The harness must construct a seeded 974,153-row scatter command with x/y,
size, 50 repeating colors, and 50 repeating alpha values; use a Mollweide-like
polygon clip; run one warm-up plus five measurements; isolate renderer work
from catalog queries and Matplotlib drawing; and write sorted JSON.

- [ ] **Step 4: Run the harness and commit its actual baseline output**

Run:

```bash
MPLCONFIGDIR=/private/tmp/starplot-mplcache \
python benchmarks/interactive_scene_pipeline.py \
  --points 974153 --repeats 5 \
  --output benchmarks/baselines/interactive_scene_pre_arrow.json
```

Expected: output JSON passes `validate_result`; it contains measured values, not hand-entered targets.

- [ ] **Step 5: Run tests and commit**

```bash
python -m pytest -o addopts='' tests/test_interactive/test_performance_harness.py -q
git diff --check
git add benchmarks/interactive_scene_pipeline.py benchmarks/baselines/interactive_scene_pre_arrow.json tests/test_interactive/test_performance_harness.py
git commit -m "Establish evidence before changing interactive transport" \
  -m "Constraint: Catalog and Matplotlib time must not contaminate Scene benchmarks" \
  -m "Confidence: high" -m "Scope-risk: narrow" \
  -m "Tested: performance harness schema and five-run baseline"
```

### Task 2: Define immutable columnar Scene primitives

**Files:**
- Create: `src/starplot/interactive/scene.py`
- Modify: `src/starplot/interactive/commands.py`
- Modify: `src/starplot/interactive/recorder.py`
- Modify: `src/starplot/interactive/__init__.py`
- Modify: `pyproject.toml`
- Test: `tests/test_interactive/test_scene.py`
- Test: `tests/test_interactive/test_recorder.py`

**Interfaces:**
- Produces: `readonly_array(value, dtype=None) -> np.ndarray`
- Produces: `ColumnarData`, `SceneLayer`, `SceneCapabilities`, `ScenePackage`.
- Consumed by: Task 3 `SceneCompiler`, Task 5 `PlotlySceneAdapter`, Task 6 Arrow transport.

- [ ] **Step 1: Write failing immutability and length tests**

```python
def test_columnar_data_is_contiguous_read_only_and_aligned():
    columns = ColumnarData.from_mapping({
        "x": [1.0, 2.0],
        "y": np.array([3.0, 4.0], dtype=np.float32)[::-1],
    })
    assert columns.row_count == 2
    assert columns["x"].flags.c_contiguous
    assert not columns["x"].flags.writeable
    with pytest.raises(ValueError):
        columns["x"][0] = 9


def test_columnar_data_rejects_misaligned_columns():
    with pytest.raises(ValueError, match="same row count"):
        ColumnarData.from_mapping({"x": [1, 2], "y": [3]})


def test_record_scatter_preserves_numpy_columns():
    recorder = DrawingRecorder()
    recorder.record_scatter(
        x=np.array([1, 2], dtype=np.float32),
        y=np.array([3, 4], dtype=np.float32),
        sizes=np.array([5, 6], dtype=np.float32),
        colors=np.array(["#fff", "#000"]),
        alphas=np.array([1, 0.5], dtype=np.float32),
        metadata=[],
    )
    assert isinstance(recorder.commands[0].data["x"], np.ndarray)
    assert not recorder.commands[0].data["x"].flags.writeable
```

- [ ] **Step 2: Run tests and verify they fail**

```bash
python -m pytest -o addopts='' \
  tests/test_interactive/test_scene.py \
  tests/test_interactive/test_recorder.py -q
```

Expected: FAIL because Scene types do not exist and recorder returns lists.

- [ ] **Step 3: Implement the Scene core**

Use these exact public types:

```python
class SceneKind(StrEnum):
    SCATTER = "scatter"
    LINE = "line"
    LINE_COLLECTION = "line_collection"
    POLYGON = "polygon"
    TEXT = "text"
    GRADIENT = "gradient"
    INFO_TABLE = "info_table"


class InteractionPolicy(StrEnum):
    NONE = "none"
    HOVER = "hover"
    HOVER_AND_DETAIL = "hover-and-detail"


def readonly_array(value, dtype=None) -> np.ndarray:
    array = np.ascontiguousarray(value, dtype=dtype)
    array.setflags(write=False)
    return array


@dataclass(frozen=True)
class ColumnarData:
    columns: Mapping[str, np.ndarray]
    row_count: int

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "ColumnarData":
        columns = {name: readonly_array(value) for name, value in values.items()}
        lengths = {len(column) for column in columns.values()}
        if len(lengths) > 1:
            raise ValueError("ColumnarData columns must have the same row count")
        return cls(MappingProxyType(columns), lengths.pop() if lengths else 0)

    def __getitem__(self, name: str) -> np.ndarray:
        return self.columns[name]
```

`SceneLayer` contains `id`, `kind`, `zorder`, `load_priority`, `space`,
`clip_id`, `style`, `data`, `interaction`, `hover_fields`, and `required`.
`ScenePackage` contains ordered layers, projection info, style info, viewport,
clips, palettes, and capabilities. Use frozen dataclasses and immutable tuples
or mapping proxies at every retained boundary.

- [ ] **Step 4: Update recorder without repeated materialization**

Materialize every scatter input exactly once, validate aligned lengths, and
store read-only arrays. Do not call `len(list(x))`. Preserve metadata as a tuple
for compatibility until Task 4 columnizes it.

- [ ] **Step 5: Raise Plotly floor and expose Scene types**

Change:

```toml
interactive = ["plotly>=6.0", "kaleido>=0.2"]
```

Export `SceneKind`, `InteractionPolicy`, `ColumnarData`, `SceneLayer`, and
`ScenePackage` from `starplot.interactive`.

- [ ] **Step 6: Run tests and commit**

```bash
python -m pytest -o addopts='' \
  tests/test_interactive/test_scene.py \
  tests/test_interactive/test_recorder.py \
  tests/test_interactive/test_commands.py -q
git diff --check
git add pyproject.toml src/starplot/interactive/scene.py src/starplot/interactive/commands.py src/starplot/interactive/recorder.py src/starplot/interactive/__init__.py tests/test_interactive/test_scene.py tests/test_interactive/test_recorder.py
git commit -m "Keep interactive geometry columnar from the recording boundary" \
  -m "Constraint: Plotly 6 typed arrays require NumPy inputs to survive recording" \
  -m "Confidence: high" -m "Scope-risk: moderate" \
  -m "Tested: Scene immutability, aligned columns, recorder and command tests"
```

### Task 3: Vectorize scatter clipping, marker calibration, and palettes

**Files:**
- Create: `src/starplot/interactive/scene_compiler.py`
- Modify: `src/starplot/interactive/style_converter.py`
- Test: `tests/test_interactive/test_scene_compiler.py`
- Test: `tests/test_interactive/test_plotly_renderer.py`

**Interfaces:**
- Produces: `scatter_clip_mask(x, y, clip) -> np.ndarray[np.bool_]`
- Produces: `filter_columns(data, mask) -> ColumnarData`
- Produces: `calibrate_marker_sizes_array(...) -> np.ndarray`
- Produces: `encode_palette(colors, opacity) -> PaletteEncoding`.
- Consumes: `ClipGeometry`, `ColumnarData` from Task 2.

- [ ] **Step 1: Write failing vectorized behavior tests**

```python
def test_rectangle_clip_mask_is_vectorized_and_boundary_inclusive():
    clip = ClipGeometry(kind="rect", points=((0, 0), (1, 0), (1, 1), (0, 1)))
    mask = scatter_clip_mask(
        np.array([-1, 0, 0.5, 1, 2], dtype=np.float32),
        np.array([0.5, 0, 0.5, 1, 0.5], dtype=np.float32),
        clip,
    )
    assert mask.tolist() == [False, True, True, True, False]


def test_polygon_clip_uses_contains_xy_without_point_objects(monkeypatch):
    def forbidden_point(*args, **kwargs):
        raise AssertionError("per-point Point allocation")
    monkeypatch.setattr(shapely.geometry, "Point", forbidden_point)
    mask = scatter_clip_mask(x, y, circle_clip)
    assert mask.dtype == np.bool_


def test_palette_encoding_deduplicates_rgb_and_separates_opacity():
    encoded = encode_palette(
        np.array(["#ffffff", "#ffffff", "#ff0000"]),
        np.array([0.1, 0.5, 1.0], dtype=np.float32),
    )
    assert encoded.palette == ("#ffffff", "#ff0000")
    assert encoded.color_index.dtype == np.uint8
    assert encoded.opacity.tolist() == pytest.approx([0.1, 0.5, 1.0])
```

- [ ] **Step 2: Verify failure**

```bash
python -m pytest -o addopts='' tests/test_interactive/test_scene_compiler.py -q
```

Expected: FAIL because compiler functions do not exist.

- [ ] **Step 3: Implement vectorized clip and aligned filtering**

Use NumPy min/max comparisons for rectangles and
`shapely.contains_xy(Polygon(clip.points), x, y)` for polygons. Combine the
polygon result with an explicit finite mask. `filter_columns` must apply one
boolean array to every column and return new contiguous, read-only arrays.

- [ ] **Step 4: Implement array marker conversion**

```python
def calibrate_marker_sizes_array(
    mpl_sizes, *, dpi, target_width, source_axes_width,
    min_size=1.5, kaleido_scale=1.15,
) -> np.ndarray:
    mpl_sizes = np.asarray(mpl_sizes, dtype=np.float32)
    diameter = (
        2.0 * np.sqrt(np.maximum(mpl_sizes, 0) / np.pi)
        * (dpi / 72.0) * (target_width / source_axes_width)
        * kaleido_scale
    )
    return np.maximum(np.float32(min_size), diameter).astype(np.float32)
```

For high-volume subpixel coverage, apply the existing shared calibration to
the array and keep opacity numeric. Verify array output against the existing
scalar function over representative sizes, including zero and subpixel values.

- [ ] **Step 5: Implement palette encoding over unique colors only**

Call `np.unique(colors, return_inverse=True)` first. Convert only unique values
through Matplotlib `to_rgba`. Keep RGB in a tuple palette, multiply source alpha
into the numeric opacity array, and select uint8/uint16 from palette length.

- [ ] **Step 6: Run tests and commit**

```bash
python -m pytest -o addopts='' \
  tests/test_interactive/test_scene_compiler.py \
  tests/test_interactive/test_plotly_renderer.py -q
git diff --check
git add src/starplot/interactive/scene_compiler.py src/starplot/interactive/style_converter.py tests/test_interactive/test_scene_compiler.py tests/test_interactive/test_plotly_renderer.py
git commit -m "Remove per-point Python work from scatter preparation" \
  -m "Constraint: Visual marker calibration must remain shared across chart families" \
  -m "Rejected: Special-case the million-star example | hides the generic bottleneck" \
  -m "Confidence: high" -m "Scope-risk: broad" \
  -m "Tested: vector clips, palette encoding, scalar-array marker parity"
```

### Task 4: Compile every recorded primitive into one backend-neutral Scene

**Files:**
- Modify: `src/starplot/interactive/scene.py`
- Modify: `src/starplot/interactive/scene_compiler.py`
- Modify: `src/starplot/interactive/commands.py`
- Test: `tests/test_interactive/test_scene_compiler.py`
- Test: `tests/test_interactive/test_recording_contract.py`

**Interfaces:**
- Produces: `SceneCompiler.compile(commands, projection_info, style_info, width, height, transparent) -> ScenePackage`
- Produces: `SceneCompiler.compile_command(command, index) -> SceneLayer`
- Produces: `choose_coordinate_encoding(values, pixel_span, supported_zoom, max_pixel_error=0.05) -> CoordinateEncoding`
- Consumed by: both Plotly adapters and all three delivery modes.

- [ ] **Step 1: Lock the complete primitive contract with failing tests**

Parametrize over `SCATTER`, `LINE`, `LINE_COLLECTION`, `POLYGON`, `TEXT`,
`GRADIENT`, and `INFO_TABLE`. For every command, assert stable layer id,
kind, z-order, clip reference, data-space declaration, required flag, and
aligned column lengths. Add explicit regressions for discontinuous path
segments and longitude-wrap paths so no adapter can reconnect them.

```python
@pytest.mark.parametrize("command, expected_kind", PRIMITIVE_CASES)
def test_compiler_covers_every_recorded_primitive(command, expected_kind):
    scene = SceneCompiler().compile([command], PROJECTION, STYLE, 1200, 800, False)
    assert len(scene.layers) == 1
    assert scene.layers[0].kind is expected_kind
    assert scene.layers[0].id == f"layer-0000-{expected_kind.value}"


def test_discontinuous_line_keeps_path_boundaries():
    layer = SceneCompiler().compile_command(wrapped_line_command(), 0)
    assert layer.data["path_id"].tolist() == [0, 0, 1, 1]
```

- [ ] **Step 2: Verify the contract fails before implementation**

```bash
python -m pytest -o addopts='' \
  tests/test_interactive/test_scene_compiler.py \
  tests/test_interactive/test_recording_contract.py -q
```

Expected: FAIL because compilation is scatter-only and path boundaries are
not represented as Scene columns.

- [ ] **Step 3: Implement one compiler dispatch table**

Use this public entry point and keep primitive-specific handlers private:

```python
class SceneCompiler:
    def compile(
        self, commands, projection_info, style_info,
        width: int, height: int, transparent: bool,
    ) -> ScenePackage: ...

    def compile_command(self, command: DrawingCommand, index: int) -> SceneLayer: ...


COMMAND_COMPILERS = {
    CommandType.SCATTER: "_compile_scatter",
    CommandType.LINE: "_compile_line",
    CommandType.LINE_COLLECTION: "_compile_line_collection",
    CommandType.POLYGON: "_compile_polygon",
    CommandType.TEXT: "_compile_text",
    CommandType.GRADIENT: "_compile_gradient",
    CommandType.INFO_TABLE: "_compile_info_table",
}
```

Flatten compound lines and polygons into coordinate columns plus `path_id`;
preserve explicit breaks from the Matplotlib-authoritative geometry. Columnize
hover metadata only when the interaction policy requires it. Derive
`load_priority` from semantic layer kind and row count, never from z-order or
an example name.

- [ ] **Step 4: Add precision selection with an error bound**

For each x/y pair, evaluate `relative-f32` using explicit `origin_x`,
`origin_y`, `scale_x`, and `scale_y`. Select it only when reconstruction error
across the declared reference viewport and supported static zoom is at most
`0.05` pixel; otherwise emit `absolute-f64`. Absolute float32 is not a protocol
encoding. Test very large projected coordinates, tiny optical fields, NaN
breaks, and ordinary map coordinates.

Use these generic load priorities unless a public capability explicitly
overrides them: background/gradient/clip `0`, grid/coordinate labels `10`,
bright stars/DSOs/planets `20`, constellation lines/labels `30`, and faint
high-volume stars `100`. Z-order remains independently copied from the final
artist order.

- [ ] **Step 5: Run compiler and legacy contract tests, then commit**

```bash
python -m pytest -o addopts='' \
  tests/test_interactive/test_scene_compiler.py \
  tests/test_interactive/test_recording_contract.py \
  tests/test_interactive/test_visual_consistency.py -q
git diff --check
git add src/starplot/interactive/scene.py src/starplot/interactive/scene_compiler.py src/starplot/interactive/commands.py tests/test_interactive/test_scene_compiler.py tests/test_interactive/test_recording_contract.py
git commit -m "Make one Scene the authority for every interactive primitive" \
  -m "Constraint: Matplotlib-final geometry remains the projection and clipping authority" \
  -m "Rejected: Reproject catalog coordinates in JavaScript | duplicates mature astronomy edge-case handling" \
  -m "Confidence: high" -m "Scope-risk: broad" \
  -m "Tested: all primitive kinds, path discontinuities, precision bounds, recording contracts"
```

### Task 5: Route Python Plotly rendering through Scene and Plotly 6 typed arrays

**Files:**
- Create: `src/starplot/interactive/plotly_adapter.py`
- Modify: `src/starplot/interactive/plotly_renderer.py`
- Modify: `src/starplot/interactive/plots.py`
- Modify: `src/starplot/interactive/__init__.py`
- Test: `tests/test_interactive/test_plotly_adapter.py`
- Test: `tests/test_interactive/test_plotly_renderer.py`
- Test: `tests/test_interactive/test_visual_consistency.py`

**Interfaces:**
- Produces: `PlotlySceneAdapter.render(scene: ScenePackage) -> plotly.graph_objects.Figure`
- Preserves: `PlotlyRenderer` as a compatibility facade.
- Preserves: `BaseInteractivePlot.to_plotly()` public behavior.

- [ ] **Step 1: Write failing typed-array and adapter-parity tests**

```python
def test_scatter_trace_keeps_plotly6_typed_arrays():
    figure = PlotlySceneAdapter().render(scatter_scene(1000))
    encoded = json.loads(figure.to_json())["data"][0]
    assert encoded["x"]["dtype"] == "f4"
    assert "bdata" in encoded["x"]
    assert encoded["marker"]["size"]["dtype"] == "f4"


def test_adapter_never_builds_per_point_css_colors():
    figure = PlotlySceneAdapter().render(palette_scene(10_000))
    colors = figure.data[0].marker.color
    assert not (len(colors) and isinstance(colors[0], str) and colors[0].startswith("rgba("))
```

Also compare normalized trace/layout snapshots from the legacy renderer and
Scene adapter for one fixture of every primitive. Normalize only generated
uids and Plotly serialization representation; do not normalize geometry,
styles, labels, axes, trace order, or hover behavior.

- [ ] **Step 2: Verify tests fail**

```bash
python -m pytest -o addopts='' \
  tests/test_interactive/test_plotly_adapter.py \
  tests/test_interactive/test_plotly_renderer.py -q
```

- [ ] **Step 3: Implement the adapter and keep arrays numeric**

```python
class PlotlySceneAdapter:
    def render(self, scene: ScenePackage) -> go.Figure:
        figure = go.Figure()
        for layer in scene.layers:
            self._add_layer(figure, scene, layer)
        self._apply_layout(figure, scene)
        return figure
```

Use `Scattergl` for high-volume scatter and line layers where Plotly supports
the required semantics. Reconstruct palette colors at palette granularity;
when Plotly cannot apply a per-row opacity array, partition by the bounded
palette/opacity groups produced by the compiler, never by individual point.
Pass contiguous NumPy numeric arrays directly into Plotly 6.

- [ ] **Step 4: Replace the legacy semantic path with a facade**

`PlotlyRenderer.render()` must compile commands once and delegate to
`PlotlySceneAdapter`. Delete or reduce old handlers after their behavior is
covered by adapter tests; no clipping, marker conversion, path splitting, or
label policy may remain duplicated in the facade. `to_plotly()` must still
return a normal `go.Figure`.

- [ ] **Step 5: Run all interactive tests and commit**

```bash
python -m pytest -o addopts='' tests/test_interactive -q
git diff --check
git add src/starplot/interactive/plotly_adapter.py src/starplot/interactive/plotly_renderer.py src/starplot/interactive/plots.py src/starplot/interactive/__init__.py tests/test_interactive/test_plotly_adapter.py tests/test_interactive/test_plotly_renderer.py tests/test_interactive/test_visual_consistency.py
git commit -m "Keep Plotly serialization on the shared Scene path" \
  -m "Constraint: Public to_plotly behavior remains compatible while Plotly 6 receives typed arrays" \
  -m "Rejected: Maintain separate legacy and Scene renderers | semantic drift would return immediately" \
  -m "Confidence: high" -m "Scope-risk: broad" \
  -m "Tested: full interactive suite, typed-array JSON, normalized primitive parity"
```

### Task 6: Serialize Scene layers as deterministic Arrow IPC Streams

**Files:**
- Create: `src/starplot/interactive/scene_manifest.py`
- Create: `src/starplot/interactive/arrow_transport.py`
- Modify: `src/starplot/interactive/__init__.py`
- Test: `tests/test_interactive/test_scene_manifest.py`
- Test: `tests/test_interactive/test_arrow_transport.py`

**Interfaces:**
- Produces: `SceneManifestModel`, `LayerManifestModel`, `DataSourceModel`, `CapabilitiesModel`.
- Produces: `layer_to_table(layer) -> pyarrow.Table`
- Produces: `encode_layer_stream(layer, max_chunksize=250_000) -> bytes`
- Produces: `decode_layer_stream(data, manifest_layer) -> SceneLayer`
- Produces: `layer_content_hash(data) -> str`, `scene_content_hash(manifest, layers) -> str`.

- [ ] **Step 1: Write failing schema, round-trip, and determinism tests**

```python
@pytest.mark.parametrize("layer", EVERY_SCENE_KIND)
def test_arrow_stream_round_trip_preserves_layer(layer):
    payload = encode_layer_stream(layer)
    restored = decode_layer_stream(payload, manifest_for(layer, payload))
    assert_scene_layer_equal(restored, layer)


def test_arrow_stream_is_deterministic():
    first = encode_layer_stream(scatter_layer())
    second = encode_layer_stream(scatter_layer())
    assert first == second
    assert layer_content_hash(first) == layer_content_hash(second)


def test_manifest_rejects_unknown_major_version():
    with pytest.raises(ValueError, match="major version"):
        SceneManifestModel.model_validate({**VALID_MANIFEST, "schema_version": "2.0"})
```

Assert the first six payload bytes identify an Arrow IPC Stream and prove the
writer did not produce IPC File format. Assert canonical manifest JSON is
stable across mapping insertion order.

- [ ] **Step 2: Verify tests fail**

```bash
python -m pytest -o addopts='' \
  tests/test_interactive/test_scene_manifest.py \
  tests/test_interactive/test_arrow_transport.py -q
```

- [ ] **Step 3: Implement Pydantic manifest models**

Use schema version `1.0`, reject unknown major versions, ignore only explicitly
documented compatible minor fields, and model top-level `scene_id`,
`content_hash`, `minimum_loader_version`, `viewport`, `coordinate_spaces`,
`clips`, `styles`, `palettes`, `layers`, and `capabilities`. Each layer includes
`id`, `kind`, `required`, `zorder`, `load_priority`, `coordinate_space`,
`clip_id`, `style_id`, `interactive`, `hover_fields`, `row_count`,
`byte_length`, `content_hash`, `coordinate_encoding`, and `data_source`.
Canonical bytes use UTF-8 JSON with sorted keys and compact separators.

The scene hash is SHA-256 over canonical manifest bytes with `content_hash`
omitted, followed by ordered layer hashes. Unknown required fields, primitive
kinds, or major versions fail; unknown optional minor fields are ignored.

- [ ] **Step 4: Implement IPC Stream encoding**

```python
def encode_table_stream(table: pa.Table, max_chunksize: int = 250_000) -> bytes:
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, table.schema) as writer:
        writer.write_table(table, max_chunksize=max_chunksize)
    return sink.getvalue().to_pybytes()
```

Store Scene schema metadata (`starplot_schema_version`, `layer_id`, `kind`,
`coordinate_encoding`, and relative-coordinate origin/scale) on the Arrow
schema. Implement these exact columns:

| Kind | Required columns | Optional columns |
| --- | --- | --- |
| scatter | `x`, `y`, `size: float32`, `color_index: uint8/uint16`, `opacity: float32` | `symbol_index: uint8`, `object_id`, dictionary `name`, `magnitude: float32`, `ra: float64`, `dec: float64` |
| line / line_collection | `path_id: uint32`, `vertex_index: uint32`, `x`, `y` | `style_id: uint16`, `object_id` |
| polygon | `polygon_id: uint32`, `ring_id: uint32`, `vertex_index: uint32`, `x`, `y` | none |
| text | `x`, `y`, dictionary `text`, `rotation: float32`, `x_offset: float32`, `y_offset: float32`, `style_id: uint16` | `object_id` |
| info_table | dictionary `column`, dictionary `value`, `width: float32` | `object_id` |

`info_table.width` is required Scene 1.0 data, not a transport-only field: the
current Scene compiler preserves row-aligned cell widths needed for exact
Matplotlib parity.

Here x/y are float64 for `absolute-f64` and reconstructed relative float32 for
`relative-f32`. Gradients and other small resolved declarative parameters live
in the manifest and still have a validated empty/small layer schema. Use flat
columns plus ids instead of nested lists wherever possible. Hash exact emitted
bytes with SHA-256.

- [ ] **Step 5: Prove every transport can reuse exact bytes**

Add a fixture that creates one encoded layer, then labels the same `bytes`
object as inline, static, and API input. Decode all three and compare arrays,
dtypes, null masks, schema metadata, and hashes.

- [ ] **Step 6: Run tests and commit**

```bash
python -m pytest -o addopts='' \
  tests/test_interactive/test_scene_manifest.py \
  tests/test_interactive/test_arrow_transport.py -q
git diff --check
git add src/starplot/interactive/scene_manifest.py src/starplot/interactive/arrow_transport.py src/starplot/interactive/__init__.py tests/test_interactive/test_scene_manifest.py tests/test_interactive/test_arrow_transport.py
git commit -m "Give every delivery mode one deterministic Arrow representation" \
  -m "Constraint: Inline, static, and API modes all use Arrow IPC Stream bytes" \
  -m "Rejected: JSON fallback for local files | creates a second data protocol" \
  -m "Confidence: high" -m "Scope-risk: moderate" \
  -m "Tested: all-layer round trips, deterministic hashes, schema version rejection"
```

### Task 7: Build one browser loader and one browser Plotly adapter

**Files:**
- Create: `src/starplot/interactive/assets/starplot-scene-loader.js`
- Create: `src/starplot/interactive/assets/plotly-scene-adapter.js`
- Create: `src/starplot/interactive/assets/vendor/apache-arrow.min.js`
- Create: `src/starplot/interactive/assets/THIRD_PARTY_NOTICES.md`
- Create: `tools/sync_arrow_js_asset.py`
- Create: `web/package.json`
- Create: `web/package-lock.json`
- Create: `web/tests/scene-source.test.mjs`
- Create: `web/tests/plotly-scene-adapter.test.mjs`
- Modify: `pyproject.toml`

**Interfaces:**
- Produces browser globals under `window.StarplotScene`; no bundler required.
- Produces: `BaseSceneSource`, `InlineSceneSource`, `StaticSceneSource`, `ApiSceneSource`.
- Produces: `layerToPlotlyTrace(layer, table, scene)` and `renderScene(target, source, options)`.
- Consumes: `window.Arrow` 21.1 and `window.Plotly` 3.x supplied by Plotly Python 6.

- [ ] **Step 1: Pin Apache Arrow JS and write failing Node tests**

Use exact dependency and runtime commands:

```json
{
  "private": true,
  "type": "module",
  "scripts": {"test": "node --test tests/*.test.mjs"},
  "dependencies": {"apache-arrow": "21.1.0"}
}
```

Tests must import Arrow from the npm package, execute the plain runtime files
in a minimal `vm` context, and provide a Plotly stub. Assert that all three
SceneSources implement the same methods, `loadLayer()` returns an async
iterable of RecordBatches, and batches expose typed arrays.

```javascript
for (const Source of [InlineSceneSource, StaticSceneSource, ApiSceneSource]) {
  const source = new Source(fixtureOptions(Source));
  assert.equal(typeof source.loadManifest, "function");
  assert.equal(typeof source.loadLayer, "function");
  assert.equal(typeof source.loadObjectDetail, "function");
}
```

- [ ] **Step 2: Verify the browser tests fail**

```bash
cd web
npm install
npm test
cd ..
```

Expected: FAIL because the browser assets do not exist.

- [ ] **Step 3: Implement SceneSources behind a shared base contract**

```javascript
class BaseSceneSource {
  async loadManifest() { throw new Error("loadManifest must be implemented"); }
  async *loadLayer(_layer, _request, _signal) {
    throw new Error("loadLayer must be implemented");
  }
  async loadObjectDetail(_objectId) { return null; }
}
```

`InlineSceneSource` base64-decodes embedded exact IPC bytes.
`StaticSceneSource` fetches `manifest.json` and relative hashed layer files.
`ApiSceneSource` fetches the same manifest/layer response contract from a URL.
All run the same version, length, and SHA-256 checks, create an Arrow
`RecordBatchReader`, and asynchronously yield its RecordBatches. The loader
combines complete-layer batches into one table immediately before the single
Plotly update; it never repeatedly extends a million-point GPU buffer.

- [ ] **Step 4: Implement the browser Plotly adapter**

Read columns via:

```javascript
const x = table.getChild("x").toArray();
const y = table.getChild("y").toArray();
```

Map every Scene kind to the same trace/layout semantics asserted for the
Python adapter. Preserve stable trace slots sorted by `(zorder, layer.id)` so
progressive loading cannot reorder visible layers. Keep numeric typed arrays
through `Plotly.react`; expand only bounded dictionaries/palettes. Use
`Plotly.restyle` for a loaded layer and never rebuild completed traces merely
because a later layer arrived.

- [ ] **Step 5: Vendor the official Arrow browser artifact reproducibly**

`tools/sync_arrow_js_asset.py` must:

1. Read version `21.1.0` from `web/package-lock.json`.
2. Copy the official `web/node_modules/apache-arrow/Arrow.es2015.min.js`
   browser distribution from installed `apache-arrow`.
3. Verify a checked-in SHA-256 constant before replacing the vendored file.
4. Preserve the Apache-2.0 license notice in `THIRD_PARTY_NOTICES.md`.
5. Exit non-zero if the expected upstream file or checksum changes.

Do not hand-edit `apache-arrow.min.js`. Configure Flit package data so all JS
assets and notices are present in both wheel and sdist.

- [ ] **Step 6: Run browser tests, package smoke test, and commit**

```bash
cd web && npm test && cd ..
python tools/sync_arrow_js_asset.py --check
python -m build --wheel --outdir /private/tmp/starplot-dist
python -c "import zipfile,glob; p=glob.glob('/private/tmp/starplot-dist/*.whl')[0]; z=zipfile.ZipFile(p); required=('starplot/interactive/assets/starplot-scene-loader.js','starplot/interactive/assets/plotly-scene-adapter.js','starplot/interactive/assets/vendor/apache-arrow.min.js'); assert all(any(n.endswith(r) for n in z.namelist()) for r in required)"
git diff --check
git add pyproject.toml tools/sync_arrow_js_asset.py web/package.json web/package-lock.json web/tests src/starplot/interactive/assets
git commit -m "Give browsers one transport-neutral Scene runtime" \
  -m "Constraint: Browser assets must work without adding a bundler to the Python package" \
  -m "Rejected: Separate local and server loaders | they would diverge in validation and rendering" \
  -m "Confidence: high" -m "Scope-risk: moderate" \
  -m "Tested: Node source and adapter tests, Arrow asset checksum, wheel asset inspection"
```

### Task 8: Expose identical inline, static, and remote HTML exports

**Files:**
- Create: `src/starplot/interactive/web_export.py`
- Modify: `src/starplot/interactive/plots.py`
- Modify: `src/starplot/interactive/__init__.py`
- Test: `tests/test_interactive/test_web_export.py`
- Test: `tests/test_interactive/test_plots.py`

**Interfaces:**
- Produces: `DataMode.INLINE`, `DataMode.EXTERNAL`, `DataMode.REMOTE`.
- Produces: `LibraryMode.CDN`, `LibraryMode.DIRECTORY`, `LibraryMode.INLINE`.
- Produces: `export_scene_html(scene, filename, data_mode=DataMode.EXTERNAL, library_mode=None, data_url=None, allowed_data_origins=()) -> ExportResult`.
- Changes default: `BaseInteractivePlot.export_html()` writes an external bundle.

- [ ] **Step 1: Write failing export matrix tests**

```python
@pytest.mark.parametrize(
    "data_mode,library_mode",
    [
        (DataMode.INLINE, LibraryMode.INLINE),
        (DataMode.INLINE, LibraryMode.CDN),
        (DataMode.EXTERNAL, LibraryMode.DIRECTORY),
        (DataMode.EXTERNAL, LibraryMode.CDN),
        (DataMode.REMOTE, LibraryMode.CDN),
    ],
)
def test_export_mode_uses_the_same_scene_hash(tmp_path, data_mode, library_mode):
    result = export_scene_html(TEST_SCENE, tmp_path / "chart.html", data_mode, library_mode,
                               data_url="https://example.test/api/scenes/test-scene")
    assert result.scene_hash == EXPECTED_SCENE_HASH
```

Assert default export creates `chart.html` plus
`chart.scene/manifest.json` and content-hashed `.arrow` files. Assert inline
embeds the exact IPC bytes as base64, and remote HTML embeds no scene rows.
Reject `REMOTE` without `data_url` and reject unsafe path escape in filenames.

- [ ] **Step 2: Verify tests fail**

```bash
python -m pytest -o addopts='' \
  tests/test_interactive/test_web_export.py \
  tests/test_interactive/test_plots.py -q
```

- [ ] **Step 3: Implement the export policy explicitly**

```python
class DataMode(StrEnum):
    INLINE = "inline"
    EXTERNAL = "external"
    REMOTE = "remote"


class LibraryMode(StrEnum):
    CDN = "cdn"
    DIRECTORY = "directory"
    INLINE = "inline"


@dataclass(frozen=True)
class ExportResult:
    html_path: Path
    bundle_path: Path | None
    scene_hash: str
    manifest_bytes: bytes
    layer_bytes: Mapping[str, bytes]
```

Defaults:

- `EXTERNAL` data uses `CDN` libraries, keeping the default HTML shell small.
- `INLINE` data uses `INLINE` libraries, producing one direct-`file://` HTML.
- `REMOTE` data uses `CDN` libraries unless explicitly overridden.

Allow explicit valid combinations. `DIRECTORY` copies version-pinned libraries
for air-gapped HTTP use. `LibraryMode` changes only script sourcing, never
Scene bytes or loader/adapter behavior. CDN URLs pin exact Plotly.js and Arrow
JS versions; inline/directory use byte-identical versions.

- [ ] **Step 4: Implement deterministic, atomic bundle layout**

Write a sibling `<stem>.scene/` directory containing canonical
`manifest.json`, `palettes.json`, and
`layer-<id>-<sha256>.arrow` files. In `DIRECTORY` library mode it additionally
contains the loader, adapter, Arrow JS, and Plotly JS obtained from
`plotly.offline.get_plotlyjs()`; CDN mode references exact pinned URLs instead.
Write into a temporary sibling directory, fsync files, replace the final
directory, then replace HTML. Remove stale bundle files only inside the owned
temporary/final bundle directory; never delete unrelated sibling files.

Inline mode inserts exact base64 IPC payloads into inert `<script
type="application/vnd.apache.arrow.stream">` elements. Escape closing script
sequences in JSON and textual metadata. Remote mode stores only the manifest
URL and loader configuration.

- [ ] **Step 5: Preserve public APIs and document the file:// boundary**

`export_html(filename, data_mode="external", library_mode=None,
data_url=None, allowed_data_origins=())` delegates to `export_scene_html`.
Direct `file://` is supported only by `data_mode="inline"`; external bundles
are intentionally served over HTTP through Task 9. `allowed_data_origins`
serializes an explicit HTTPS/HTTP origin allow-list for remote layer URLs and
defaults to the manifest origin only. Add a compatibility warning only when
callers depended on the previous single-file default and explicitly request no
external assets.

- [ ] **Step 6: Run tests and commit**

```bash
python -m pytest -o addopts='' \
  tests/test_interactive/test_web_export.py \
  tests/test_interactive/test_plots.py \
  tests/test_interactive/test_plotly_adapter.py -q
git diff --check
git add src/starplot/interactive/web_export.py src/starplot/interactive/plots.py src/starplot/interactive/__init__.py tests/test_interactive/test_web_export.py tests/test_interactive/test_plots.py
git commit -m "Separate chart data without changing browser rendering semantics" \
  -m "Constraint: Inline file and server bundles must decode identical Arrow bytes" \
  -m "Rejected: Make file transport a separate JSON implementation | violates transport equivalence" \
  -m "Confidence: high" -m "Scope-risk: broad" \
  -m "Tested: export matrix, hashes, atomic replacement, invalid combinations"
```

### Task 9: Add a safe local static server for exported bundles

**Files:**
- Modify: `src/starplot/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Adds: `starplot serve DIRECTORY [--host 127.0.0.1] [--port 8000] [--no-open]`.
- Preserves: `starplot setup`.
- Produces: `serve(directory, host="127.0.0.1", port=8000, open_browser=True) -> None`.

- [ ] **Step 1: Write failing CLI and HTTP tests**

Test argparse dispatch without opening a browser. Start the server on port `0`
in a background thread and assert:

- `chart.html`, `manifest.json`, and `.arrow` return byte-identical files.
- `.arrow` content type is `application/vnd.apache.arrow.stream`.
- directory traversal outside the selected root returns 404.
- cache headers are immutable for content-hashed Arrow paths and `no-cache`
  for `manifest.json`.
- the bound URL printed to stdout uses the actual ephemeral port.

- [ ] **Step 2: Verify tests fail**

```bash
python -m pytest -o addopts='' tests/test_cli.py -q
```

- [ ] **Step 3: Replace manual argv handling with argparse subcommands**

Keep the existing setup implementation intact behind a `setup` subparser.
Use `ThreadingHTTPServer` and a `SimpleHTTPRequestHandler(directory=...)`
subclass; bind to `127.0.0.1` by default. Add MIME type registration before
serving. Resolve the requested directory once and reject a non-directory.

Open the default browser only after a successful bind and only when `--no-open`
is absent. This browser action belongs to the user-invoked CLI, not library
export code or tests.

- [ ] **Step 4: Run CLI regression tests and commit**

```bash
python -m pytest -o addopts='' tests/test_cli.py -q
python -m starplot.cli --help
python -m starplot.cli serve --help
git diff --check
git add src/starplot/cli.py tests/test_cli.py
git commit -m "Make external chart bundles easy to inspect locally" \
  -m "Constraint: The convenience server must expose only the selected directory" \
  -m "Confidence: high" -m "Scope-risk: narrow" \
  -m "Tested: CLI compatibility, MIME types, cache headers, traversal rejection"
```

### Task 10: Provide a framework-neutral complete-scene and object-detail API

**Files:**
- Create: `src/starplot/interactive/scene_provider.py`
- Modify: `src/starplot/interactive/scene_manifest.py`
- Test: `tests/test_interactive/test_scene_provider.py`

**Interfaces:**
- Produces: `CatalogDetailProvider` protocol.
- Produces: `LayerRequest` protocol, `SceneResponse`, and `SceneProvider`.
- Produces logical endpoints: manifest, layer stream, and object detail without choosing Flask/FastAPI/Django.

- [ ] **Step 1: Write failing provider contract tests**

```python
class CatalogDetailProvider(Protocol):
    def get_object(self, object_id: str) -> Mapping[str, object] | None: ...


class LayerRequest(Protocol):
    def cache_key_parts(self) -> tuple[object, ...]: ...


def test_complete_scene_provider_returns_exported_bytes(provider, exported_bundle):
    assert provider.manifest().body_bytes() == exported_bundle.manifest_bytes
    for layer in exported_bundle.manifest.layers:
        assert provider.layer(layer.id).body_bytes() == exported_bundle.layer_bytes[layer.id]


def test_detail_lookup_uses_stable_object_id(provider, detail_catalog):
    response = provider.object_detail("star:hip:32349")
    assert response.status == 200
    assert json.loads(response.body)["object_id"] == "star:hip:32349"
```

Also assert unknown ids return 404, conditional `If-None-Match` returns 304,
and metadata omitted from a `NONE` interaction layer cannot leak through the
layer stream.

- [ ] **Step 2: Verify tests fail**

```bash
python -m pytest -o addopts='' tests/test_interactive/test_scene_provider.py -q
```

- [ ] **Step 3: Implement the framework-neutral provider**

```python
@dataclass(frozen=True)
class SceneResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes | Iterable[bytes]

    def iter_body(self) -> Iterator[bytes]:
        if isinstance(self.body, bytes):
            yield self.body
        else:
            yield from self.body

    def body_bytes(self) -> bytes:
        return b"".join(self.iter_body())


class SceneProvider:
    def manifest(self, if_none_match: str | None = None) -> SceneResponse: ...
    def layer(self, layer_id: str, request: LayerRequest | None = None,
              if_none_match: str | None = None) -> SceneResponse: ...
    def object_detail(self, object_id: str) -> SceneResponse: ...
```

Return canonical manifest and exact pre-encoded Arrow bytes or zero-copy chunk
iterables for complete-scene requests. Add `ETag`, `Content-Length`,
`Content-Type`, `X-Starplot-Schema-Version`, and explicit `Cache-Control`.
Concatenating a streamed response must reproduce the static layer bytes
exactly. Keep response objects bytes-oriented so any web framework can copy
status, headers, and body without reserializing Scene data.

- [ ] **Step 4: Enforce the mixed-hover policy**

The compiler/provider boundary must support exactly:

- `NONE`: no per-row hover columns or object-detail calls.
- `HOVER`: only manifest-declared compact hover fields.
- `HOVER_AND_DETAIL`: compact hover plus stable `object_id`; full detail is
  resolved lazily by `CatalogDetailProvider`.

The provider must not retain full catalog records merely to render a Scene.
Catalog RA/Dec and names remain optional semantic metadata; final x/y remains
the browser rendering authority.

- [ ] **Step 5: Run tests and commit**

```bash
python -m pytest -o addopts='' \
  tests/test_interactive/test_scene_provider.py \
  tests/test_interactive/test_scene_manifest.py \
  tests/test_interactive/test_arrow_transport.py -q
git diff --check
git add src/starplot/interactive/scene_provider.py src/starplot/interactive/scene_manifest.py tests/test_interactive/test_scene_provider.py
git commit -m "Let web frameworks serve Scene bytes without owning chart semantics" \
  -m "Constraint: Starplot must not require a Python web framework" \
  -m "Rejected: Send raw catalog rows to the browser | couples transport to catalogs and leaks unused data" \
  -m "Confidence: high" -m "Scope-risk: moderate" \
  -m "Tested: byte equivalence, ETags, detail lookup, mixed-hover policies"
```

### Task 11: Add generic viewport and LOD requests without changing full-scene output

**Files:**
- Modify: `src/starplot/interactive/scene_provider.py`
- Modify: `src/starplot/interactive/scene.py`
- Modify: `src/starplot/interactive/assets/starplot-scene-loader.js`
- Test: `tests/test_interactive/test_scene_provider.py`
- Test: `tests/test_interactive/test_scene_lod.py`
- Test: `web/tests/scene-source.test.mjs`

**Interfaces:**
- Produces: `ViewportRequest`, `LodPolicy`, `FullResolutionPolicy`, `MagnitudeLodPolicy`.
- Extends: `SceneProvider.layer(layer_id, request=...)`.
- Extends browser loader with debounced, cancellable viewport requests.

- [ ] **Step 1: Write failing LOD correctness tests**

```python
def test_viewport_filter_uses_final_scene_coordinates(provider):
    request = ViewportRequest(x_min=-1, x_max=1, y_min=-2, y_max=2,
                              pixel_width=800, pixel_height=600, lod=1)
    table = decode_response(provider.layer("stars", request))
    assert np.all((-1 <= table["x"]) & (table["x"] <= 1))
    assert np.all((-2 <= table["y"]) & (table["y"] <= 2))


def test_full_resolution_request_is_exact_complete_layer(provider):
    assert provider.layer("stars", ViewportRequest.full()).body_bytes() == provider.layer("stars").body_bytes()
```

Add a deterministic magnitude-priority fixture proving that bright stars are
retained before faint stars at a fixed point budget, while non-star layers use
full resolution unless they explicitly declare another policy.

In Node, simulate two viewport requests resolving in reverse order and assert
only the newest generation reaches `Plotly.react`.

- [ ] **Step 2: Verify tests fail**

```bash
python -m pytest -o addopts='' tests/test_interactive/test_scene_lod.py -q
cd web && npm test && cd ..
```

- [ ] **Step 3: Implement data-driven LOD policies**

```python
class LodPolicy(Protocol):
    def select(self, layer: SceneLayer, request: ViewportRequest) -> np.ndarray: ...


@dataclass(frozen=True)
class ViewportRequest:
    x_min: float | None = None
    x_max: float | None = None
    y_min: float | None = None
    y_max: float | None = None
    pixel_width: int | None = None
    pixel_height: int | None = None
    lod: int | None = None
    magnitude_max: float | None = None
    point_budget: int | None = None

    @classmethod
    def full(cls) -> "ViewportRequest":
        return cls()

    @property
    def is_full(self) -> bool:
        return all(value is None for value in dataclasses.astuple(self))

    def cache_key_parts(self) -> tuple[object, ...]: ...


class MagnitudeLodPolicy:
    def select(self, layer: SceneLayer, request: ViewportRequest) -> np.ndarray:
        visible = viewport_mask(layer.data["x"], layer.data["y"], request)
        return stable_bright_first_budget(visible, layer.data["magnitude"], request.point_budget)


class FullResolutionPolicy:
    def select(self, layer: SceneLayer, request: ViewportRequest) -> np.ndarray:
        if request.is_full:
            return np.ones(layer.data.row_count, dtype=np.bool_)
        return viewport_mask(layer.data["x"], layer.data["y"], request)
```

Selection uses only Scene columns/capabilities, never example, catalog, or
projection names. Crop against final projected x/y. Re-encode selected
coordinates relative to the requested viewport when that meets the same
`0.05` pixel error bound; otherwise retain original dtype.

Cache keys are a canonical tuple of scene hash, layer hash, quantized viewport,
pixel dimensions, LOD level, magnitude/filter options, and schema version.

- [ ] **Step 4: Implement browser request scheduling**

Use a 150 ms debounce, one `AbortController` per layer, and monotonically
increasing generation numbers. Abort prior requests on a new viewport. Treat
`AbortError` as expected; display other required-layer errors. Apply a result
only when its generation is still current. If the manifest does not advertise
viewport support, keep the complete layer and perform no API request.

- [ ] **Step 5: Run tests and commit**

```bash
python -m pytest -o addopts='' \
  tests/test_interactive/test_scene_lod.py \
  tests/test_interactive/test_scene_provider.py -q
cd web && npm test && cd ..
git diff --check
git add src/starplot/interactive/scene.py src/starplot/interactive/scene_provider.py src/starplot/interactive/assets/starplot-scene-loader.js tests/test_interactive/test_scene_lod.py tests/test_interactive/test_scene_provider.py web/tests/scene-source.test.mjs
git commit -m "Scale dense charts through Scene capabilities rather than examples" \
  -m "Constraint: Complete-scene responses remain byte-identical and viewport requests use final x/y" \
  -m "Rejected: Reproject RA and Dec in the browser | creates a second astronomy implementation" \
  -m "Confidence: high" -m "Scope-risk: broad" \
  -m "Tested: viewport filters, deterministic LOD, stale-request rejection, full-scene fallback"
```

### Task 12: Enforce security, failure, and transport-equivalence contracts

**Files:**
- Create: `src/starplot/interactive/scene_validation.py`
- Modify: `src/starplot/interactive/scene_manifest.py`
- Modify: `src/starplot/interactive/web_export.py`
- Modify: `src/starplot/interactive/assets/starplot-scene-loader.js`
- Modify: `src/starplot/interactive/assets/plotly-scene-adapter.js`
- Test: `tests/test_interactive/test_scene_security.py`
- Test: `tests/test_interactive/test_scene_transport_equivalence.py`
- Create: `web/tests/error-handling.test.mjs`

**Interfaces:**
- Produces: `LoaderLimits` shared as manifest defaults and enforced in Python/JavaScript.
- Produces: normalized Scene and Plotly snapshots for cross-mode contract tests.

- [ ] **Step 1: Write failing adversarial and failure-mode tests**

Use these default limits:

```python
@dataclass(frozen=True)
class LoaderLimits:
    max_manifest_bytes: int = 4 * 1024 * 1024
    max_layer_bytes: int = 512 * 1024 * 1024
    max_layer_rows: int = 10_000_000
    max_string_bytes: int = 64 * 1024
    max_geometry_depth: int = 8
```

Test over-limit manifests/layers/strings/geometry, non-finite bounds, hash and
length mismatch, unknown required fields, cross-origin URLs without explicit
allow-list, `javascript:` URLs, HTML/script text in labels and hover fields,
and malformed Arrow. Assert a required layer produces a visible error overlay;
an optional layer can be skipped only with a recorded warning and retry action.

- [ ] **Step 2: Write the cross-mode equivalence test before implementation**

For representative horizon, map, orthographic, optics, and star-chart fixtures:

1. Compile one `ScenePackage`.
2. Export inline and static and expose the same bytes through `SceneProvider`.
3. Decode all three transports.
4. Compare manifest semantics, layer order, column names, dtypes, values, null
   masks, hashes, interaction fields, and normalized Plotly trace/layout output.

Any permitted difference must be limited to transport URL and script source.

- [ ] **Step 3: Verify tests fail**

```bash
python -m pytest -o addopts='' \
  tests/test_interactive/test_scene_security.py \
  tests/test_interactive/test_scene_transport_equivalence.py -q
cd web && npm test && cd ..
```

- [ ] **Step 4: Implement identical validation in both runtimes**

Validate manifest byte length before JSON parse when available, validate schema
and declared counts before Arrow allocation, verify SHA-256 with
`crypto.subtle.digest` before `tableFromIPC`, and enforce same-origin URLs by
default. An explicit `allowedOrigins` option may widen origins; it cannot allow
non-HTTP(S) remote URLs.

Treat all label and hover content as text. Python JSON-escapes metadata; the
browser adapter supplies Plotly text with HTML disabled/escaped and constructs
error UI using `textContent`, never `innerHTML` with untrusted values.

- [ ] **Step 5: Implement required/optional failure UX**

Required manifest or layer failure stops initial completion, preserves already
rendered safe background layers, and shows layer id plus a retry button without
dumping remote payloads. Optional failure records a warning and allows render
completion. Retries rerun the same validation and replace the stable trace
slot; they do not append duplicate traces. Idempotent GET failures retry at
most twice with exponential delays of 250 ms and 500 ms. Aborted viewport
requests never retry or surface as errors. A detected external `file://` load
shows the exact remedies `starplot serve <directory>` and
`data_mode="inline"`; a CORS failure shows the failed origin and the need to
configure the chart origin without echoing credentials or response bodies.

- [ ] **Step 6: Run tests and commit**

```bash
python -m pytest -o addopts='' \
  tests/test_interactive/test_scene_security.py \
  tests/test_interactive/test_scene_transport_equivalence.py \
  tests/test_interactive/test_web_export.py -q
cd web && npm test && cd ..
git diff --check
git add src/starplot/interactive/scene_validation.py src/starplot/interactive/scene_manifest.py src/starplot/interactive/web_export.py src/starplot/interactive/assets/starplot-scene-loader.js src/starplot/interactive/assets/plotly-scene-adapter.js tests/test_interactive/test_scene_security.py tests/test_interactive/test_scene_transport_equivalence.py web/tests/error-handling.test.mjs
git commit -m "Fail safely when external Scene data is invalid" \
  -m "Constraint: External URLs and API streams are untrusted inputs" \
  -m "Rejected: Best-effort rendering of corrupt required layers | creates silent astronomy omissions" \
  -m "Confidence: high" -m "Scope-risk: broad" \
  -m "Tested: limits, origins, hashes, text safety, required failures, transport equivalence"
```

### Task 13: Prove performance, visual parity, packaging, and public usage

**Files:**
- Modify: `benchmarks/interactive_scene_pipeline.py`
- Create by running harness: `benchmarks/baselines/interactive_scene_arrow.json`
- Modify: `comparison_outputs/gen_comparison.py`
- Modify: `comparison_outputs/interactive-parity-ledger.md`
- Modify: `README.md`
- Create: `docs/reference/interactive-web-export.md`
- Create: `docs/migrations/plotly-6-arrow-export.md`
- Modify: `pyproject.toml`
- Test: `tests/test_interactive/test_performance_harness.py`
- Test: `tests/test_interactive/test_scene_transport_equivalence.py`

**Interfaces:**
- Documents: `to_plotly`, three export modes, `starplot serve`, SceneProvider
  integration, viewport/LOD, caching, security defaults, and Plotly 6 migration.
- Produces: reproducible final benchmark JSON and 22-example parity ledger.

- [ ] **Step 1: Extend the benchmark with gate evaluation**

```python
PERFORMANCE_GATES = {
    "scene_compile_ratio_max": 0.50,
    "peak_rss_ratio_max": 0.60,
    "arrow_payload_bytes_max": 30 * 1024 * 1024,
    "external_html_bytes_max": 1 * 1024 * 1024,
    "browser_complete_render_ratio_max": 0.60,
    "ordinary_chart_regression_ratio_max": 1.10,
    "viewport_warm_median_ms_max": 500,
    "viewport_warm_p95_ms_max": 1000,
}
```

Add `compare_results(before, after) -> list[str]`; return a failure message for
every missed gate. Store environment fingerprints and raw repetitions so
future results are auditable. Do not overwrite the pre-change baseline.

- [ ] **Step 2: Run the million-point and ordinary-chart benchmarks**

```bash
MPLCONFIGDIR=/private/tmp/starplot-mplcache \
python benchmarks/interactive_scene_pipeline.py \
  --points 974153 --ordinary-points 5000 --repeats 5 \
  --baseline benchmarks/baselines/interactive_scene_pre_arrow.json \
  --output benchmarks/baselines/interactive_scene_arrow.json \
  --enforce
```

Required outcomes:

- Arrow Scene payload at most 30 MiB.
- External HTML shell at most 1 MiB excluding separately loaded libraries.
- No per-point RGBA strings and no per-point Shapely `Point` allocations.
- Scene compile median at most 50% of baseline.
- Peak RSS at most 60% of baseline.
- Browser complete render median at most 60% of baseline.
- Ordinary chart median regression at most 10%.
- Warm cached viewport median at most 500 ms and p95 at most 1000 ms.

If the test machine is materially different from the baseline fingerprint,
regenerate both records on that machine in the same run and retain both raw
results in the final record.

- [ ] **Step 3: Run transport equivalence for all 22 examples**

Update `gen_comparison.py` so each example can export inline, static, and
provider-backed artifacts from the same compiled Scene. For every example,
assert equal scene/layer hashes and normalized decoded columns before taking
screenshots.

```bash
cd comparison_outputs
for example in \
  horizon_double_cluster horizon_gradient horizon_sgr \
  galaxy_custom_marker map_big map_big_dipper map_canis_major map_carina map_cas \
  map_milky_way_stars map_orion map_orthographic map_sagittarius map_virgo_cluster \
  optic_iss_transit optic_m45 optic_moon_saturn optic_orion_nebula \
  optic_solar_eclipse star_chart_basic star_chart_detail star_chart_french
do
  python gen_comparison.py "$example" --transports inline,static,provider
done
cd ..
```

Record pass/fail, scene hash, screenshot paths, and any accepted Plotly-engine
difference in `interactive-parity-ledger.md`. No accepted difference may be a
missing object, label, grid annotation, boundary, constellation segment, or
incorrect coordinate/size/color.

- [ ] **Step 4: Perform paired visual review**

For each example, inspect Matplotlib and each Plotly transport as paired images
at the same pixel dimensions. Check geometry, longitude-wrap discontinuities,
clip boundaries, label presence/placement, axes/grid annotations, marker size,
opacity, z-order, gradients, overlays, and background. Fix generic compiler or
adapter logic, regenerate the affected example, and recheck all chart families
before accepting the ledger. Do not add example-name branches.

- [ ] **Step 5: Write public and migration documentation**

`docs/reference/interactive-web-export.md` must include executable examples for:

```python
plot.export_html("chart.html")  # chart.html + chart.scene/, serve over HTTP
plot.export_html("chart-inline.html", data_mode="inline")  # direct file://
plot.export_html("chart-api.html", data_mode="remote",
                 data_url="https://example.org/api/scenes/orion")
```

And:

```bash
starplot serve . --port 8000
```

Provide a minimal framework adapter example that copies `SceneResponse`
status/headers/body into a response. Explain Catalog RA/Dec versus Scene x/y,
the mixed-hover/detail contract, caching headers, allowed origins, failure UX,
and how static and server modes remain visually identical.

Migration notes must call out `plotly>=6.0`, the new default external bundle,
how to request the old single-file behavior explicitly, Arrow JS 21.1 asset
licensing, and the absence of a Plotly 5 fallback.

- [ ] **Step 6: Run the full verification matrix**

```bash
python -m pytest -o addopts='' tests/test_interactive tests/test_cli.py -q
cd web && npm test && cd ..
python -m build --sdist --wheel --outdir /private/tmp/starplot-dist-final
python tools/sync_arrow_js_asset.py --check
git diff --check
```

If the local Python environment exits with signal 11/139, rerun focused tests
with the project's explicit environment Python and record the crash command;
the complete suite still must pass in CI before merge. A local crash is not a
reason to weaken or skip tests.

- [ ] **Step 7: Commit documentation and evidence**

```bash
git add README.md pyproject.toml docs/reference/interactive-web-export.md docs/migrations/plotly-6-arrow-export.md benchmarks/interactive_scene_pipeline.py benchmarks/baselines/interactive_scene_arrow.json comparison_outputs/gen_comparison.py comparison_outputs/interactive-parity-ledger.md tests/test_interactive/test_performance_harness.py tests/test_interactive/test_scene_transport_equivalence.py
git commit -m "Make interactive performance and parity independently verifiable" \
  -m "Constraint: Optimization claims require reproducible Python, payload, browser, and visual evidence" \
  -m "Confidence: high" -m "Scope-risk: moderate" \
  -m "Directive: Do not relax performance or parity gates without a new measured baseline" \
  -m "Tested: full Python and Node suites, package builds, 22 example transports, performance gates"
```

## Final acceptance checklist

- [ ] `to_plotly()` and all HTML modes consume the same backend-neutral Scene.
- [ ] No high-volume coordinate, size, alpha, or index array becomes a Python list.
- [ ] Plotly 6 emits typed-array `dtype`/`bdata` structures for supported numeric columns.
- [ ] All data modes carry Arrow IPC Stream, including inline mode.
- [ ] Inline, static, and complete-scene API hashes and decoded values are identical.
- [ ] Static and API paths use one browser loader and one Plotly adapter.
- [ ] Raw RA/Dec remains Catalog authority; final x/y remains Scene rendering authority.
- [ ] Viewport/LOD logic is declared by capabilities and contains no example-name branches.
- [ ] Required layer errors are visible and cannot silently produce incomplete charts.
- [ ] Same-origin, content limits, hashes, and text escaping are enforced before rendering.
- [ ] Arrow JS, loader, adapter, and notices are present in wheel and sdist.
- [ ] Performance gates pass from recorded raw measurements.
- [ ] All 22 examples pass transport equivalence and paired visual review.
- [ ] Python tests, Node tests, build, asset checksum, and `git diff --check` pass.

## Implementation order and rollback boundaries

Execute Tasks 1–13 in order. Tasks 1–6 establish the internal Scene and Arrow
contract; Tasks 7–9 add delivery without changing Scene semantics; Tasks 10–12
add server-scale behavior and hardening; Task 13 changes defaults only after all
gates exist. Each task is an independent Lore commit. If a later task fails,
revert that commit rather than restoring duplicate legacy semantics inside the
shared compiler or adapters.
