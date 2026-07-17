import json
from pathlib import Path
import subprocess
import base64

import numpy as np

ROOT = Path(__file__).resolve().parents[2]


def test_browser_layout_only_payloads_pass_real_plotly_schema_validation():
    import plotly.graph_objects as go
    script = r'''
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
console.log(JSON.stringify(output));
'''
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
        style={"palette_id": "python-palette"},
        palette=("#fff",),
        group_id="stars",
        interaction=InteractionPolicy.HOVER,
        hover_fields=("name", "object_id"),
        coordinate_encoding={
            "x": CoordinateEncoding(CoordinateEncodingKind.RELATIVE_F32, 10.0, 2.0, 0.1),
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
        viewport={"reference_width": 800, "data_bounds": {"x_min": 0.0, "x_max": 1.0, "y_min": 0.0, "y_max": 1.0}},
        coordinate_spaces={"data": {"authority": "projected-x-y"}},
        clips=[],
        capabilities=CapabilitiesModel(viewport_query=False, lod=False, magnitude_filter=False, catalog_detail=False, max_batch_rows=250_000),
    )
    manifest_json = canonical_manifest_bytes(manifest).decode()
    script = r'''
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
'''
    completed = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=ROOT / "web",
        input=json.dumps({"manifestJson": manifest_json, "arrow": base64.b64encode(arrow_bytes).decode()}),
        check=True,
        capture_output=True,
        text=True,
    )
    assert completed.stdout.strip() == "2"
