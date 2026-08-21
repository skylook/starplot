import json
from pathlib import Path
import subprocess
import base64

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_browser_layout_only_payloads_pass_real_plotly_schema_validation():
    import plotly.graph_objects as go

    script = r"""
import { Arrow, loadRuntime } from "./tests/test-helpers.mjs";
const runtime = await loadRuntime(["plotly-scene-adapter.js"]);
const encoding = {
  x: { kind: "absolute-f64", origin: 0, scale: 1, max_error_pixels: 0 },
  y: { kind: "absolute-f64", origin: 0, scale: 1, max_error_pixels: 0 },
};
function layer(id, kind, style = {}) {
  return { id, kind, group_id: id, required: true, zorder: 0, load_priority: 0,
    coordinate_space: "data", clip_id: null, style_id: null, interactive: false,
    interaction: "none", hover_fields: [], coordinate_encoding: kind === "info_table" ? {} : encoding, style };
}
const cases = [
  [layer("text", "text", { ha: "right", va: "top" }), Arrow.tableFromArrays({
    x: new Float64Array([1]), y: new Float64Array([2]), text: ["A"], rotation: new Float32Array([15]),
    x_offset: new Float32Array([2]), y_offset: new Float32Array([3]), style_id: new Uint16Array([0]),
  })],
  [layer("footer", "info_table"), Arrow.tableFromArrays({ column: ["RA"], value: ["1h"], width: new Float32Array([1]) })],
  [layer("hole", "polygon", { fill_color: "#fff" }), Arrow.tableFromArrays({
    polygon_id: new Uint32Array([0,0,0,0,0,0]), ring_id: new Uint32Array([0,0,0,1,1,1]),
    vertex_index: new Uint32Array([0,1,2,0,1,2]), x: new Float64Array([0,4,0,1,2,1]), y: new Float64Array([0,0,4,1,1,2]),
  })],
];
const output = cases.map(([current, table]) => {
  const trace = runtime.layerToPlotlyTrace(current, table, { viewport: {}, styles: [], palettes: [], clips: [] });
  return { trace, effects: runtime.layerToPlotlyLayoutEffects(trace) };
});
console.log(JSON.stringify(output, (_key, value) => ArrayBuffer.isView(value) ? Array.from(value) : value));
"""
    completed = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=ROOT / "web",
        check=True,
        capture_output=True,
        text=True,
    )
    for item in json.loads(completed.stdout):
        figure = go.Figure(
            data=[item["trace"]],
            layout={
                "annotations": item["effects"].get("annotations", []),
                "shapes": item["effects"].get("shapes", []),
            },
        )
        figure.to_plotly_json()


def test_browser_text_scales_to_the_compiled_viewport():
    """Browser text must shrink with a high-resolution source plot."""
    script = r"""
import { Arrow, loadRuntime } from "./tests/test-helpers.mjs";
const runtime = await loadRuntime(["starplot-scene-loader.js", "plotly-scene-adapter.js"]);
const layer = {
  id: "text", kind: "text", group_id: "labels", required: true, zorder: 0,
  load_priority: 0, coordinate_space: "data", clip_id: null, style_id: null,
  interaction: "none", hover_fields: [],
  coordinate_encoding: {
    x: { kind: "absolute-f64", origin: 0, scale: 1, max_error_pixels: 0 },
    y: { kind: "absolute-f64", origin: 0, scale: 1, max_error_pixels: 0 },
  },
  style: { font_size: 20 },
};
const lineLayer = {
  id: "line", kind: "line", group_id: "grid", required: true, zorder: 0,
  load_priority: 0, coordinate_space: "data", clip_id: null, style_id: null,
  interaction: "none", hover_fields: [], coordinate_encoding: {
    x: { kind: "absolute-f64", origin: 0, scale: 1, max_error_pixels: 0 },
    y: { kind: "absolute-f64", origin: 0, scale: 1, max_error_pixels: 0 },
  },
  style: { line_width: 1 },
};
const table = Arrow.tableFromArrays({
  x: new Float64Array([1]), y: new Float64Array([1]), text: ["label"],
  rotation: new Float32Array([0]), x_offset: new Float32Array([0]),
  y_offset: new Float32Array([0]), style_id: new Uint16Array([0]),
});
const lineTable = Arrow.tableFromArrays({
  x: new Float64Array([0, 2]), y: new Float64Array([0, 2]),
  path_id: new Uint32Array([0, 0]),
});
const source = {
  async loadManifest() {
    return { layers: [layer, lineLayer], styles: [], palettes: [], clips: [], viewport: {
      reference_width: 1000, reference_height: 500, target_axes_width: 1000,
      source_axes_width: 2000, dpi: 72, data_bounds: { x_min: 0, x_max: 2, y_min: 0, y_max: 2 },
      margin: { l: 100, r: 80, t: 30, b: 20 },
    }};
  },
  async *loadLayer(layer) { yield layer.id === "text" ? table : lineTable; },
};
let captured;
const Plotly = {
  async react(_target, traces, layout) { captured = { traces, layout }; },
  async restyle() {}, async relayout() {},
};
await runtime.renderScene({}, source, { Plotly });
console.log(JSON.stringify({
  fontSize: captured.layout.annotations[0].font.size,
  lineWidth: captured.traces.find((trace) => trace.name === "Grid").line.width,
  lineSimplify: captured.traces.find((trace) => trace.name === "Grid").line.simplify,
  margin: captured.layout.margin,
  shapes: captured.layout.shapes.length,
}));
"""
    completed = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=ROOT / "web",
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    metrics = json.loads(completed.stdout)
    assert metrics["fontSize"] == 10.0
    # Text and strokes are both Matplotlib point units, so each is scaled once
    # from the source canvas to the compiled browser viewport.
    assert metrics["lineWidth"] == 0.5
    # Plotly's default path simplification turns recorded circular borders into
    # visibly faceted polygons, so Scene line fidelity requires it disabled.
    assert metrics["lineSimplify"] is False
    assert metrics["margin"] == {
        "l": 100, "r": 80, "t": 30, "b": 20, "autoexpand": False,
    }
    assert metrics["shapes"] == 0


def test_browser_scattergl_subpixel_opacity_uses_empirical_coverage():
    """A 1px WebGL fallback uses the same empirical area scaling as Kaleido."""
    script = r"""
import { Arrow, loadRuntime } from "./tests/test-helpers.mjs";
const runtime = await loadRuntime(["plotly-scene-adapter.js"]);
const layer = {
  id: "stars", kind: "scatter", group_id: "stars", row_count: 1,
  required: true, zorder: 0, load_priority: 0, coordinate_space: "data",
  clip_id: null, style_id: null, interaction: "none", hover_fields: [],
  coordinate_encoding: {
    x: { kind: "absolute-f64", origin: 0, scale: 1, max_error_pixels: 0 },
    y: { kind: "absolute-f64", origin: 0, scale: 1, max_error_pixels: 0 },
  }, style: { palette_id: "stars" },
};
const table = Arrow.tableFromArrays({
  x: new Float64Array([0]), y: new Float64Array([0]),
  size: new Float32Array([0.5]), opacity: new Float32Array([1]),
  color_index: new Uint16Array([0]),
});
const trace = runtime.layerToPlotlyTrace(layer, table, {
  viewport: {}, styles: [], palettes: [{ id: "stars", colors: ["#fff"] }], clips: [],
});
console.log(trace.marker.opacity[0]);
"""
    completed = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=ROOT / "web",
        check=True,
        capture_output=True,
        text=True,
    )
    assert float(completed.stdout.strip()) == pytest.approx(0.5)


def test_python_arrow_and_manifest_authorities_load_in_browser_runtime():
    from starplot.interactive.arrow_transport import encode_layer_stream
    from starplot.interactive.commands import CoordinateSpace
    from starplot.interactive.scene import (
        ColumnarData,
        CoordinateEncoding,
        CoordinateEncodingKind,
        InteractionPolicy,
        SceneKind,
        SceneLayer,
    )
    from starplot.interactive.scene_manifest import (
        CapabilitiesModel,
        build_scene_manifest,
        canonical_manifest_bytes,
    )

    layer = SceneLayer(
        id="python-stars",
        kind=SceneKind.SCATTER,
        zorder=2.0,
        load_priority=3,
        space=CoordinateSpace.DATA,
        clip_id=None,
        style={"label": "星", "palette_id": "python-palette"},
        palette=("#fff",),
        group_id="stars",
        interaction=InteractionPolicy.HOVER,
        hover_fields=("name", "object_id"),
        coordinate_encoding={
            "x": CoordinateEncoding(
                CoordinateEncodingKind.RELATIVE_F32, 10.0, 2.0, 0.1
            ),
            "y": CoordinateEncoding(CoordinateEncodingKind.ABSOLUTE_F64),
        },
        data=ColumnarData.from_mapping(
            {
                "x": np.array([0.0, 1.0], dtype=np.float32),
                "y": np.array([2.0, 3.0], dtype=np.float64),
                "size": np.array([1.0, 2.0], dtype=np.float32),
                "color_index": np.array([0, 0], dtype=np.uint8),
                "opacity": np.array([1.0, 0.5], dtype=np.float32),
                "name": np.array(["A", "A"], dtype="U1"),
                "object_id": np.array(["a", None], dtype=object),
            }
        ),
    )
    arrow_bytes = encode_layer_stream(layer)
    manifest = build_scene_manifest(
        scene_id="python-scene",
        layers=[layer],
        layer_bytes={layer.id: arrow_bytes},
        viewport={
            "reference_width": 800,
            "data_bounds": {"x_min": 0.0, "x_max": 1.0, "y_min": 0.0, "y_max": 1.0},
        },
        coordinate_spaces={"data": {"authority": "projected-x-y"}},
        clips=[],
        capabilities=CapabilitiesModel(
            viewport_query=False,
            lod=False,
            magnitude_filter=False,
            catalog_detail=False,
            max_batch_rows=250_000,
        ),
    )
    manifest_json = canonical_manifest_bytes(manifest).decode()
    script = r"""
import { loadRuntime } from "./tests/test-helpers.mjs";
const chunks = [];
for await (const chunk of process.stdin) chunks.push(chunk);
const input = JSON.parse(Buffer.concat(chunks).toString("utf8"));
const runtime = await loadRuntime(["starplot-scene-loader.js"]);
const source = new runtime.InlineSceneSource({ manifest: JSON.parse(input.manifestJson), manifestJson: input.manifestJson, layers: { "python-stars": input.arrow } });
const manifest = await source.loadManifest();
let rows = 0;
for await (const batch of source.loadLayer(manifest.layers[0])) {
  rows += batch.numRows;
  if (!(batch.getChild("x").toArray() instanceof Float32Array)) throw new Error("x dtype drift");
  if (String(batch.schema.fields.find((field) => field.name === "name").type).startsWith("Dictionary") === false) throw new Error("dictionary policy drift");
}
console.log(rows);
"""
    completed = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=ROOT / "web",
        input=json.dumps(
            {
                "manifestJson": manifest_json,
                "arrow": base64.b64encode(arrow_bytes).decode(),
            }
        ),
        check=True,
        capture_output=True,
        text=True,
    )
    assert completed.stdout.strip() == "2"


def test_python_generated_edge_lexemes_nullability_and_dictionary_indices_load_in_browser():
    import pyarrow as pa

    from starplot.interactive.arrow_transport import encode_table_stream, layer_to_table
    from starplot.interactive.commands import CoordinateSpace
    from starplot.interactive.scene import (
        ColumnarData,
        CoordinateEncoding,
        CoordinateEncodingKind,
        InteractionPolicy,
        SceneKind,
        SceneLayer,
    )
    from starplot.interactive.scene_manifest import (
        CapabilitiesModel,
        build_scene_manifest,
        canonical_manifest_bytes,
    )

    layer = SceneLayer(
        id="python-edge",
        kind=SceneKind.SCATTER,
        zorder=2.0,
        load_priority=3,
        space=CoordinateSpace.DATA,
        clip_id=None,
        style={"label": "星", "palette_id": "python-palette"},
        palette=("#fff",),
        group_id="stars",
        interaction=InteractionPolicy.HOVER,
        hover_fields=("name", "catalog"),
        coordinate_encoding={
            "x": CoordinateEncoding(
                CoordinateEncodingKind.RELATIVE_F32, 1e16, 1e-7, -0.0
            ),
            "y": CoordinateEncoding(CoordinateEncodingKind.ABSOLUTE_F64),
        },
        data=ColumnarData.from_mapping(
            {
                "x": np.array([0.0, 1.0], dtype=np.float32),
                "y": np.array([2.0, 3.0], dtype=np.float64),
                "size": np.array([1.0, 2.0], dtype=np.float32),
                "color_index": np.array([0, 0], dtype=np.uint8),
                "opacity": np.array([1.0, 0.5], dtype=np.float32),
                "name": np.array(["A", "B"], dtype="U1"),
                "catalog": np.array(["one", "two"], dtype=object),
            }
        ),
    )
    canonical = layer_to_table(layer)
    arrays = []
    fields = []
    for field, column in zip(canonical.schema, canonical.columns):
        if field.name in {"name", "catalog"}:
            index_type = pa.int8() if field.name == "name" else pa.int16()
            values = column.to_pylist()
            dictionary = pa.array(list(dict.fromkeys(values)), type=pa.string())
            positions = {
                value: index for index, value in enumerate(dictionary.to_pylist())
            }
            array = pa.DictionaryArray.from_arrays(
                pa.array([positions[value] for value in values], type=index_type),
                dictionary,
            )
            arrays.append(array)
            fields.append(
                pa.field(
                    field.name, array.type, nullable=False, metadata=field.metadata
                )
            )
        else:
            arrays.append(column.combine_chunks())
            fields.append(
                pa.field(
                    field.name,
                    field.type,
                    nullable=True if field.name == "size" else field.nullable,
                    metadata=field.metadata,
                )
            )
    table = pa.Table.from_arrays(
        arrays, schema=pa.schema(fields, metadata=canonical.schema.metadata)
    )
    arrow_bytes = encode_table_stream(table)
    manifest = build_scene_manifest(
        scene_id="python-é-edge-scene",
        layers=[layer],
        layer_bytes={layer.id: arrow_bytes},
        viewport={
            "data_bounds": {"x_min": 0.0001, "x_max": 1e16, "y_min": -0.0, "y_max": 1.0}
        },
        coordinate_spaces={},
        clips=[],
        capabilities=CapabilitiesModel(
            viewport_query=False,
            lod=False,
            magnitude_filter=False,
            catalog_detail=False,
            max_batch_rows=250_000,
        ),
    )
    manifest_json = canonical_manifest_bytes(manifest).decode()
    assert "1e-07" in manifest_json
    assert "1e+16" in manifest_json
    assert "-0.0" in manifest_json
    assert "é" in manifest_json
    assert "星" in manifest_json
    assert "\\u00e9" not in manifest_json
    assert "\\u661f" not in manifest_json
    script = r"""
import { loadRuntime } from "./tests/test-helpers.mjs";
const chunks = []; for await (const chunk of process.stdin) chunks.push(chunk);
const input = JSON.parse(Buffer.concat(chunks).toString("utf8"));
const runtime = await loadRuntime(["starplot-scene-loader.js"]);
const source = new runtime.InlineSceneSource({ manifest: JSON.parse(input.manifestJson), manifestJson: input.manifestJson, layers: { "python-edge": input.arrow } });
const manifest = await source.loadManifest();
let rows = 0;
for await (const batch of source.loadLayer(manifest.layers[0])) {
  rows += batch.numRows;
  const fields = Object.fromEntries(batch.schema.fields.map((field) => [field.name, String(field.type)]));
  if (!fields.name.startsWith("Dictionary<Int8")) throw new Error(`known dictionary index rejected: ${fields.name}`);
  if (!fields.catalog.startsWith("Dictionary<Int16")) throw new Error(`extension dictionary index rejected: ${fields.catalog}`);
}
console.log(rows);
"""
    completed = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=ROOT / "web",
        input=json.dumps(
            {
                "manifestJson": manifest_json,
                "arrow": base64.b64encode(arrow_bytes).decode(),
            }
        ),
        check=True,
        capture_output=True,
        text=True,
    )
    assert completed.stdout.strip() == "2"
