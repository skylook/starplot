# Interactive Scene and Arrow Performance Design

**Status:** Approved design

**Date:** 2026-07-16

## 1. Purpose

Starplot's Plotly backend now reproduces the supplied Matplotlib example
matrix with acceptable visual parity, but the current data path is inefficient
for large charts. The million-star comparison produces a 72.78 MB HTML file,
of which 68.32 MB is figure JSON. Python also constructs Python lists,
per-point CSS RGBA strings, and one Shapely `Point` per point during clipping.

This design replaces that path with a backend-neutral, columnar Scene model and
Apache Arrow IPC transport. It improves every chart family without branching
on an example name, projection name, or catalog. It also separates chart data
from HTML so a website can load identical scenes from static URLs or APIs.

## 2. Goals

- Preserve the final Matplotlib artist as the source of visual truth.
- Preserve the existing public `to_plotly()` and `export_html()` capabilities.
- Make external data the default `export_html()` behavior.
- Retain explicit single-file inline export for direct `file://` use.
- Use one backend-neutral Scene protocol for Plotly and future renderers.
- Use one Arrow schema for static files and API streams.
- Separate astronomical Catalog data from projected Scene data.
- Keep original RA/Dec available without making the browser reimplement
  Cartopy, horizon, zenith, or optic projection behavior.
- Eliminate avoidable Python object creation and string serialization.
- Define measurable Python, payload, browser, and LOD performance gates.
- Guarantee transport equivalence across inline, static, and API modes.

## 3. Non-goals

- Replacing Plotly with deck.gl in this change.
- Implementing celestial projections in JavaScript.
- Making external sidecar files readable through unrestricted `file://`
  browser access.
- Making every catalog object hoverable at every density.
- Rasterizing or downsampling data by default.
- Adding a required FastAPI, Flask, Django, or other server framework.
- Changing Matplotlib rendering behavior to accommodate the web backend.

## 4. Binding decisions

1. The architecture uses a columnar Scene compiler, not post-processing of an
   already constructed Plotly Figure.
2. Apache Arrow IPC is the standard numeric and tabular transport.
3. A versioned JSON Scene Manifest carries scene structure, style, sources,
   hashes, and capabilities.
4. Scene semantics do not contain Plotly types such as `scattergl`.
5. Catalog RA/Dec is the astronomical semantic authority.
6. Scene final projected x/y is the rendering authority.
7. Scene rows may carry minimal RA/Dec and hover fields, but detailed object
   data is loaded by stable `object_id` from a Catalog source.
8. Static and API sources implement the same browser `SceneSource` contract.
9. Default `export_html()` creates an external bundle and requires HTTP(S).
10. `data_mode="inline"` produces a direct-open single HTML file.
11. Plotly's minimum supported Python version is raised to Plotly 6.0.
12. Plotly.js and Apache Arrow JS are version-pinned by the exporter.
13. The first optimization phases are lossless. Raster and tile strategies
    remain optional policies built on the same Scene protocol.

## 5. Architecture

```text
Catalog data
RA/Dec, magnitude, object identity
        |
        v
Matplotlib / Starplot drawing
        |
        v
Final Matplotlib artists
        |
        v
DrawingRecorder
NumPy-backed DrawingCommand data
        |
        v
SceneCompiler
vectorized clip, style resolution, palette encoding, precision policy
        |
        v
ScenePackage
manifest + columnar layers + capabilities
        |
        +---------------------+----------------------+------------------+
        |                     |                      |
        v                     v                      v
Python Plotly adapter    Arrow IPC exporter    Future renderer adapter
to_plotly()              inline/static/API     deck.gl or Bokeh
                              |
                              v
                         SceneSource
                   inline / static / API
                              |
                              v
                     PlotlySceneAdapter.js
                              |
                              v
                          Plotly.js
```

`ScenePackage` is the only input to render adapters and transport exporters.
Projection, collision, path splitting, clip resolution, and final text
placement are completed before this boundary.

## 6. Catalog and Scene protocols

### 6.1 Catalog protocol

Catalog Arrow data represents astronomy-domain objects independently of a
chart or backend. Its stable required fields are:

```text
object_id       utf8
object_type     dictionary-encoded utf8
ra              float64
dec             float64
```

Optional columns include magnitude, B-V color, object name, constellation,
HIP/NGC/Messier identifiers, angular size, and physical metadata. Optional
fields remain catalog concerns and are not required by the Scene renderer.

### 6.2 Scene protocol

Scene data represents resolved visual primitives. DATA-space positions are
final projected coordinates. AXES and PAPER positions retain their normalized
coordinate-space semantics.

Scene rows can include `object_id` to link back to Catalog data. A Scene layer
contains only the minimal metadata declared in its `hover_fields`. A layer with
`interactive: false` carries no hover or detail columns.

### 6.3 Why both coordinates can exist

Final x/y controls rendering. Optional RA/Dec supports hover, selection, and
Catalog queries. Browser renderers never derive x/y from RA/Dec in this design.
This preserves Cartopy seams, projected clip boundaries, observer/time
transforms, zenith geometry, optic transforms, and Matplotlib collision output.

## 7. Scene Manifest

The manifest is UTF-8 JSON with this top-level structure:

```json
{
  "schema_version": "1.0",
  "scene_id": "all-sky-mollweide",
  "content_hash": "sha256:...",
  "minimum_loader_version": "1.0",
  "viewport": {},
  "coordinate_spaces": {},
  "clips": [],
  "styles": [],
  "palettes": [],
  "layers": [],
  "capabilities": {}
}
```

The viewport includes reference width, reference height, final data bounds,
paper background, and axes background. Coordinate spaces explicitly declare
DATA, AXES, or PAPER. Clip entries carry normalized IDs and polygon points.

Each layer declares:

```text
id
kind
zorder
load_priority
coordinate_space
clip_id
style_id
required
interactive
hover_fields
data_source
content_hash
```

Supported version 1.0 primitive kinds are:

```text
scatter
line
line_collection
polygon
text
gradient
info_table
```

`kind` describes Scene semantics. A Plotly adapter is responsible for choosing
SVG `scatter`, WebGL `scattergl`, shapes, annotations, or heatmaps.

## 8. Arrow layer schemas

Every layer uses the Arrow IPC Stream format. A static `.arrow` resource stores
the complete stream bytes, inline mode base64-encodes those exact bytes, and a
complete-scene API response sends those exact bytes using HTTP streaming. The
protocol does not mix Arrow IPC File and Stream containers.

### 8.1 Scatter

Required columns:

```text
x             float32 or float64
y             float32 or float64
size          float32
color_index   uint8 or uint16
opacity       float32
```

Optional columns:

```text
symbol_index  uint8
object_id     utf8 or dictionary-encoded utf8
name          dictionary-encoded utf8
magnitude     float32
ra            float64
dec           float64
```

The palette is stored once in the manifest. Per-point CSS color strings are
not permitted in high-volume Scene layers.

### 8.2 Line and line collection

```text
path_id        uint32
vertex_index   uint32
x              float32 or float64
y              float32 or float64
style_id       uint16, optional
object_id      utf8, optional
```

`path_id` is a required semantic boundary. It preserves Matplotlib MOVETO and
prevents independent paths from being joined across 0/360 degrees.

### 8.3 Polygon

```text
polygon_id     uint32
ring_id        uint32
vertex_index   uint32
x              float32 or float64
y              float32 or float64
```

This represents multi-polygons, independent rings, projected clip results,
custom marker paths, nebula shapes, and Milky Way polygons.

### 8.4 Text

```text
x              float32 or float64
y              float32 or float64
text           dictionary-encoded utf8
rotation       float32
x_offset       float32
y_offset       float32
style_id       uint16
object_id      utf8, optional
```

Text contains final collision placement and offset information. Browser
adapters do not repeat collision resolution.

### 8.5 Small declarative layers

Gradients and other layers with no large arrays can store their resolved
parameters directly in the external manifest. They remain external to HTML in
static and API modes. An info table uses a small Arrow layer with required
dictionary-encoded `column` and `value` UTF-8 columns plus required
`width: float32`; `object_id` is optional. Width remains row-aligned Scene 1.0
data because the current compiler supports per-cell widths and exact visual
parity cannot reconstruct them from one layer-level style value.

## 9. Coordinate precision

The protocol supports two encodings per Arrow batch:

```text
absolute-f64
relative-f32 with origin_x, origin_y, scale_x, scale_y
```

Marker size and opacity are always float32. Palette indices use uint8 when the
palette has at most 256 entries and uint16 otherwise.

The compiler selects relative float32 only when its worst-case quantization
error is at most 0.05 pixels at the declared reference viewport and supported
static zoom range. Otherwise it selects float64. Viewport/LOD responses use
local origins and can normally use float32 without sacrificing this error
budget. The selected encoding is explicit in Arrow schema metadata.

## 10. Delivery modes

### 10.1 External static bundle, default

```python
plot.export_html("chart.html")
```

produces:

```text
chart.html
chart.scene/
  manifest.json
  layer-<id>-<content-hash>.arrow
  palettes.json
```

It must be loaded over HTTP(S). `starplot serve <directory>` provides a
development-only static server without modifying the scene.

### 10.2 Inline

```python
plot.export_html("chart.html", data_mode="inline")
```

embeds the exact manifest and Arrow IPC bytes in HTML. Arrow bytes are base64
encoded for transport, decoded to the same Arrow IPC payload, and passed
through the same loader. No list/Plotly-JSON fallback is used.

Inline defaults to embedded Plotly.js and Arrow JS so direct `file://` opening
works without a network connection.

### 10.3 Remote API

```python
plot.export_html(
    "chart.html",
    data_mode="remote",
    data_url="https://example.com/api/scenes/orion",
)
```

The HTML contains no chart data. It loads a manifest and Arrow IPC streams from
the configured base URL.

### 10.4 Library delivery

Data mode and JavaScript library delivery are independent:

```text
library_mode=cdn
library_mode=directory
library_mode=inline
```

External mode defaults to CDN. Inline mode defaults to inline libraries.
Directory mode supports air-gapped local HTTP deployment without coupling
scene data to HTML.

## 11. Browser SceneSource contract

```typescript
interface SceneSource {
  loadManifest(signal?: AbortSignal): Promise<SceneManifest>;

  loadLayer(
    layer: SceneLayer,
    request?: ViewportRequest,
    signal?: AbortSignal,
  ): AsyncIterable<ArrowRecordBatch>;

  loadObjectDetail?(
    objectId: string,
    signal?: AbortSignal,
  ): Promise<CatalogObject>;
}
```

`InlineSceneSource`, `StaticSceneSource`, and `ApiSceneSource` implement this
contract. `SceneLoader` and `PlotlySceneAdapter` cannot branch on source type.

## 12. Progressive rendering and layer ordering

Layer `load_priority` controls fetch order independently from `zorder`:

```text
0    background, gradient, clip
10   grid and coordinate labels
20   bright stars, DSOs, planets
30   constellation lines and labels
100  faint high-volume stars
```

The adapter creates stable layer slots in zorder before filling data. Network
completion order cannot change visual stacking.

Complete static Arrow streams are submitted to Plotly once per layer. Streams
may contain multiple RecordBatches, but the default adapter combines them before one
Plotly update. It does not repeatedly extend a million-point GPU buffer.
Viewport/LOD refresh atomically replaces the affected layer.

## 13. API capabilities and endpoints

The manifest advertises capabilities:

```json
{
  "viewport_query": true,
  "lod": true,
  "magnitude_filter": true,
  "catalog_detail": true,
  "max_batch_rows": 250000
}
```

The protocol defines these logical endpoints without requiring a framework:

```http
GET /scenes/{scene_id}/manifest
GET /scenes/{scene_id}/layers/{layer_id}
GET /catalog/objects/{object_id}
```

Viewport layer queries use final Scene coordinates:

```text
x_min, x_max, y_min, y_max
pixel_width, pixel_height
lod
magnitude_max
```

Responses use:

```http
Content-Type: application/vnd.apache.arrow.stream
ETag: "sha256:..."
X-Starplot-Schema-Version: 1.0
```

The browser debounces viewport changes, cancels stale requests with
`AbortController`, assigns a monotonically increasing request generation, and
accepts results only from the latest generation. A source without viewport or
LOD capability returns the complete layer with identical Scene semantics.

## 14. Hover and object details

Scene layers declare one of three interaction policies:

```text
none
hover
hover-and-detail
```

High-volume faint layers default to `none` and omit all metadata. Interactive
layers contain only declared hover columns. `hover-and-detail` uses
`object_id` to lazily load Catalog details. Detail responses are cached by
object ID. Missing detail capability does not remove local hover behavior.

## 15. Cache and integrity

Static Arrow filenames include their content hash and use:

```http
Cache-Control: public, max-age=31536000, immutable
```

Manifests use `ETag` and `Cache-Control: no-cache`. Dynamic response cache keys
include scene version, layer ID, quantized viewport or tile, LOD, magnitude
limit, and style version.

SHA-256 is computed over the canonical Arrow IPC Stream bytes. Inline, static, and
complete-scene API delivery of the same layer use the same bytes and therefore
the same content hash. Dynamic viewport responses have their own content hash.

The scene-level content hash is computed over a canonicalized manifest with its
own `content_hash` field omitted, followed by the ordered layer content hashes.
This avoids a self-referential hash while binding layout and layer identity.

## 16. Error handling

Required failures are explicit and visible:

- Unsupported schema major version stops scene loading.
- Missing required Arrow columns stops the affected required layer and shows a
  chart error overlay.
- Required layer download, decode, or hash failure stops successful completion.
- Optional layer failure shows a warning and retry action.
- Data from a stale scene version is not mixed with the active manifest.
- Opening an external bundle with `file://` explains `starplot serve` and
  `data_mode="inline"`.
- CORS errors show the failed URL and required server configuration.
- Idempotent GET requests retry at most twice with exponential backoff.
- Aborted viewport requests are not reported as errors.

The renderer must not log and silently omit a failed required primitive.

## 17. Security boundaries

- The loader never evaluates JavaScript from a manifest or Arrow column.
- Text and hover values are treated as text, not trusted HTML.
- Manifest layer kinds, style keys, dtypes, row counts, and byte sizes are
  validated before allocation.
- Remote layer URLs default to the manifest origin. Additional origins require
  an explicit `allowed_data_origins` export configuration.
- API deployments must configure CORS for the actual chart origin.
- Loader limits cap manifest bytes, layer bytes, row count, nested geometry
  depth, and string length before Plotly construction.
- Content hashes provide integrity and cache identity, not authentication.
  Authentication remains an application/server concern.

## 18. Python internal refactor

### 18.1 Recorder

Large DrawingCommand fields remain NumPy arrays. The recorder converts inputs
to contiguous arrays and marks retained arrays read-only. It does not convert
scatter data to Python lists.

### 18.2 Vectorized clipping

Rectangular scatter clips use NumPy comparisons. Polygon scatter clips use
Shapely 2 `contains_xy`. The resulting mask filters every aligned column.
There is no per-point Shapely geometry allocation.

Line and polygon topology continues to use Shapely where topology operations
are required. MOVETO/path/ring identifiers remain explicit.

### 18.3 Marker conversion

Marker diameter, subpixel coverage, and opacity calculations use NumPy arrays.
Colors are converted once into a palette plus numeric index. High-volume
rendering never creates per-point CSS RGBA strings.

### 18.4 Adapters

`to_plotly()` compiles a ScenePackage and passes it to a Python Plotly adapter
using Plotly 6 typed arrays. Web exports pass the same ScenePackage to Arrow and
the JavaScript Plotly adapter. Normalized Plotly snapshots verify that the two
adapter implementations do not drift.

### 18.5 Framework-neutral server interface

`SceneProvider` exposes manifest, layer, viewport, and object-detail operations
as Python methods returning JSON-compatible metadata or Arrow bytes/streams.
Framework adapters can wrap this protocol, but core starplot does not depend on
a web framework.

## 19. Compatibility and versioning

- The optional interactive dependency becomes `plotly>=6.0`.
- PyArrow remains the Python Arrow implementation.
- The exporter pins compatible Plotly.js and Apache Arrow JS major versions.
- Scene schema uses semantic major/minor versioning.
- Unknown optional minor-version fields are ignored.
- Unknown required fields, primitive kinds, or major versions fail explicitly.
- `to_plotly()` remains public and returns a Plotly Figure.
- `export_html()` remains public, but its default output changes from a single
  file to an external bundle. Release notes must call out this behavior.
- Existing direct-open workflows use `data_mode="inline"`.

## 20. Performance acceptance

Benchmarks isolate catalog query, Matplotlib drawing, Scene compilation, Arrow
encoding, HTML generation, Kaleido rendering, browser download, Arrow decode,
Plotly construction, first complete render, and viewport replacement.

Each benchmark uses the same host and versions, one warm-up, five measured
runs, and reports median and p95 to a committed JSON result.

For the current million-star comparison:

| Metric | Current | First acceptance gate |
| --- | ---: | ---: |
| Figure data | 68.32 MB JSON | Scene Arrow at most 30 MB |
| HTML | 72.78 MB | External HTML shell at most 1 MB, excluding CDN libraries |
| Per-point RGBA strings | 28.76 MB | zero |
| Scatter clip allocations | about 974,000 Point objects | zero Point objects |
| Scene compile median | baseline captured before change | at most 50% of baseline |
| Scene compile peak RSS | baseline captured before change | at most 60% of baseline |
| Browser complete-render median | baseline captured before change | at most 60% of baseline |
| Ordinary chart complete render | baseline captured before change | no regression above 10% |

Localhost warm-cache viewport/LOD replacement must achieve median at most
500 ms and p95 at most 1000 ms on the recorded reference environment.

## 21. Test and verification matrix

### 21.1 Unit contracts

- Recorder retains contiguous, read-only NumPy columns.
- Rectangle and polygon scatter clips are vectorized.
- Precision policy selects float32 or float64 from the error budget.
- Palette, index, and opacity conversion preserves rendered color.
- Every primitive has a valid Arrow schema and round-trip.
- Manifest versions, sources, hashes, and capabilities validate.
- Every SceneSource implements the same success and failure semantics.

### 21.2 Transport equivalence

For all 22 examples, decoded inline, static, and complete-scene API forms must
have identical manifest semantic hashes, layer hashes, Arrow schemas, and
column values.

### 21.3 Adapter equivalence

The Python and JavaScript Plotly adapters consume the same Scene fixture.
Normalized trace/layout snapshots must match. Backend-specific object identity
or serialization order is excluded from normalization; geometry, style,
ordering, visibility, hover fields, and layout are not excluded.

### 21.4 Visual verification

- Regenerate and inspect all 22 examples in external mode.
- For one Map, Horizon, Zenith, and Optic representative, compare inline,
  static, and API screenshots.
- Recheck million-star point counts, Mollweide clip, Milky Way brightness,
  payload size, and first-render performance.
- Preserve the accepted visual parity ledger.

### 21.5 Failure verification

Cover file protocol misuse, CORS, missing required layers, optional retries,
hash mismatch, schema mismatch, stale scene version, request cancellation,
out-of-order viewport results, unavailable details, and loader resource limits.

## 22. Delivery phases

### Phase 1: Columnar Scene and vectorized Python path

Introduce ScenePackage and NumPy-backed recording, then make `to_plotly()` use
Plotly 6 typed arrays. Preserve current public output behavior until this phase
passes visual and performance regression gates.

### Phase 2: Arrow and inline/static web loader

Add Arrow schemas, manifest validation, content hashing, JS loader, inline
source, static source, and external-default export migration.

### Phase 3: API source and Catalog details

Add framework-neutral SceneProvider, API SceneSource, Arrow stream responses,
minimal hover metadata, and lazy Catalog detail retrieval.

### Phase 4: Viewport and LOD capability

Add capability negotiation, viewport request contracts, request cancellation,
cache keys, local coordinate batches, and atomic layer replacement.

### Phase 5: Final acceptance

Run the full transport, adapter, visual, failure, and performance matrix. Record
benchmark artifacts and update public documentation and migration guidance.

Each phase is independently testable and reversible. Dynamic service behavior
does not block the static bundle delivered in Phase 2.

## 23. Rejected alternatives

### Post-process Plotly Figure data

Rejected because it leaves Python list conversion, per-point colors, and
per-point clipping intact and makes the external protocol Plotly-specific.

### Raw RA/Dec-only browser rendering

Rejected because it requires browser implementations of Cartopy projections,
observer/time conversion, path seam splitting, zenith and optic transforms,
and final collision placement.

### Dynamic API/LOD as the first delivery

Rejected because it couples renderer optimization to server deployment and
delays a useful static external bundle.

### Custom untyped binary format

Rejected in favor of Arrow IPC because Arrow provides a maintained cross-
language schema, record batches, strings, null handling, and browser support.

## 24. Completion condition

The work is complete when all five phases satisfy their specified contracts,
the 22-example visual matrix remains accepted, inline/static/API complete-scene
data is provably equivalent, performance gates pass on the recorded reference
environment, and public documentation describes the new default external
bundle plus the inline migration path.
