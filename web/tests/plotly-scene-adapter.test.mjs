import test from "node:test";
import { Arrow, assert, loadRuntime } from "./test-helpers.mjs";

const coordinateEncoding = {
  x: { kind: "absolute-f64", origin: 0, scale: 1, max_error_pixels: 0 },
  y: { kind: "absolute-f64", origin: 0, scale: 1, max_error_pixels: 0 },
};

function layer(id, kind, zorder, style = {}) {
  return {
    id, kind, group_id: id, required: true, zorder, load_priority: 10,
    coordinate_space: "data", clip_id: null, style_id: `style-${id}`,
    interactive: false, interaction: "none", hover_fields: [],
    coordinate_encoding: ["gradient", "info_table"].includes(kind) ? {} : coordinateEncoding,
    style,
  };
}

const tables = {
  scatter: () => Arrow.tableFromArrays({
    x: new Float64Array([1, 2]), y: new Float64Array([3, 4]),
    size: new Float32Array([2, 3]), color_index: new Uint8Array([0, 1]),
    opacity: new Float32Array([1, 0.5]),
  }),
  line: () => Arrow.tableFromArrays({
    path_id: new Uint32Array([0, 0, 1, 1]), vertex_index: new Uint32Array([0, 1, 0, 1]),
    x: new Float64Array([0, 1, 9, 10]), y: new Float64Array([0, 1, 1, 0]),
  }),
  line_collection: () => tables.line(),
  polygon: () => Arrow.tableFromArrays({
    polygon_id: new Uint32Array([0, 0, 0]), ring_id: new Uint32Array([0, 0, 0]),
    vertex_index: new Uint32Array([0, 1, 2]), x: new Float64Array([0, 1, 0]),
    y: new Float64Array([0, 0, 1]),
  }),
  text: () => Arrow.tableFromArrays({
    x: new Float64Array([1]), y: new Float64Array([2]), text: ["M42"],
    rotation: new Float32Array([15]), x_offset: new Float32Array([2]),
    y_offset: new Float32Array([3]), style_id: new Uint16Array([0]),
  }),
  gradient: () => Arrow.tableFromArrays({}),
  info_table: () => Arrow.tableFromArrays({ column: ["RA"], value: ["5h"], width: new Float32Array([1]) }),
};

test("layerToPlotlyTrace covers every Scene kind and keeps numeric typed arrays", async () => {
  const runtime = await loadRuntime(["plotly-scene-adapter.js"]);
  const scene = {
    viewport: { data_bounds: { x_min: 0, x_max: 10, y_min: 0, y_max: 10 } },
    palettes: [{ id: "palette-scatter", colors: ["#fff", "#aaa"] }],
    styles: [], clips: [],
  };
  const expectedTypes = {
    scatter: "scatter", line: "scatter", line_collection: "scattergl",
    polygon: "scatter", text: "scatter", gradient: "heatmap", info_table: "scatter",
  };
  for (const [kind, makeTable] of Object.entries(tables)) {
    const current = layer(kind, kind, 1, kind === "scatter"
      ? { palette_id: "palette-scatter", symbol: "circle" }
      : kind === "gradient" ? { direction: "linear", color_stops: [[0, "#000"], [1, "#fff"]] } : {});
    const trace = runtime.layerToPlotlyTrace(current, makeTable(), scene);
    assert.equal(trace.type, expectedTypes[kind], kind);
    if (["scatter", "line", "line_collection", "polygon", "gradient"].includes(kind) && trace.x) assert.ok(ArrayBuffer.isView(trace.x), `${kind} x must stay typed`);
    if (["scatter", "line", "line_collection", "polygon", "gradient"].includes(kind) && trace.y) assert.ok(ArrayBuffer.isView(trace.y), `${kind} y must stay typed`);
  }
});

test("renderScene reserves stable zorder slots and updates each completed layer once", async () => {
  const calls = { react: [], restyle: [] };
  const Plotly = {
    async react(...args) { calls.react.push(args); },
    async restyle(...args) { calls.restyle.push(args); },
    async relayout() {},
  };
  const runtime = await loadRuntime(["starplot-scene-loader.js", "plotly-scene-adapter.js"], { Plotly });
  const sceneLayers = [layer("late", "line", 20), layer("early-b", "line", 10), layer("early-a", "line", 10)];
  const table = tables.line();
  const source = {
    async loadManifest() { return { viewport: {}, styles: [], palettes: [], clips: [], layers: sceneLayers }; },
    async *loadLayer(current) {
      await new Promise((resolve) => setTimeout(resolve, current.id === "late" ? 1 : 0));
      for (const batch of table.batches) yield batch;
    },
  };
  await runtime.renderScene("chart", source, { Plotly });
  assert.equal(calls.react.length, 1, "one initial reservation update");
  assert.deepEqual(
    Array.from(calls.react[0][1], (trace) => trace.meta.starplot_layer_id),
    ["early-a", "early-b", "late"],
  );
  assert.equal(calls.restyle.length, sceneLayers.length);
  assert.deepEqual(Array.from(calls.restyle, (call) => call[2][0]), [0, 1, 2]);
  assert.equal(new Set(calls.restyle.map((call) => call[2][0])).size, sceneLayers.length);
  assert.equal(calls.react.length, 1, "later layers never rebuild completed traces");
});

test("relative-f32 coordinates decode only when origin or scale is nonidentity", async () => {
  const runtime = await loadRuntime(["plotly-scene-adapter.js"]);
  const table = Arrow.tableFromArrays({
    path_id: new Uint32Array([0, 0]), vertex_index: new Uint32Array([0, 1]),
    x: new Float32Array([0, 1]), y: new Float32Array([1, 0]),
  });
  const identity = layer("identity", "line", 0);
  identity.coordinate_encoding = {
    x: { kind: "relative-f32", origin: 0, scale: 1, max_error_pixels: 0.01 },
    y: { kind: "relative-f32", origin: 0, scale: 1, max_error_pixels: 0.01 },
  };
  const identityTrace = runtime.layerToPlotlyTrace(identity, table, { styles: [], palettes: [] });
  assert.ok(identityTrace.x instanceof Float32Array);
  const relative = structuredClone(identity);
  relative.coordinate_encoding.x = { kind: "relative-f32", origin: 10, scale: 2, max_error_pixels: 0.01 };
  const relativeTrace = runtime.layerToPlotlyTrace(relative, table, { styles: [], palettes: [] });
  assert.ok(relativeTrace.x instanceof Float64Array);
  assert.deepEqual(Array.from(relativeTrace.x), [10, 12]);
});

test("path and polygon ring boundaries never connect unrelated geometry", async () => {
  const runtime = await loadRuntime(["plotly-scene-adapter.js"]);
  const lineTrace = runtime.layerToPlotlyTrace(layer("paths", "line", 0), tables.line(), { styles: [], palettes: [] });
  assert.ok(Number.isNaN(lineTrace.x[2]));
  assert.deepEqual(Array.from(lineTrace.x).slice(0, 2), [0, 1]);
  assert.deepEqual(Array.from(lineTrace.x).slice(3), [9, 10]);

  const hole = Arrow.tableFromArrays({
    polygon_id: new Uint32Array([0, 0, 0, 0, 0, 0]),
    ring_id: new Uint32Array([0, 0, 0, 1, 1, 1]),
    vertex_index: new Uint32Array([0, 1, 2, 0, 1, 2]),
    x: new Float64Array([0, 4, 0, 1, 2, 1]), y: new Float64Array([0, 0, 4, 1, 1, 2]),
  });
  const holeTrace = runtime.layerToPlotlyTrace(layer("hole", "polygon", 0, { fill_color: "#fff" }), hole, { styles: [], palettes: [] });
  const effects = runtime.layerToPlotlyLayoutEffects(holeTrace);
  assert.equal(holeTrace.visible, undefined);
  assert.equal(holeTrace.fill, "toself");
  assert.equal(holeTrace.zorder, 0);
  assert.equal(effects.shapes, undefined);
  const rings = Array.from(holeTrace.x).reduce((count, value) => count + Number(Number.isNaN(value)), 0);
  assert.equal(rings, 2, "outer and hole rings stay separated in one SVG trace");
  const finite = (values) => values.filter(Number.isFinite);
  const area = (xs, ys) => xs.reduce((sum, x, index) => {
    const next = (index + 1) % xs.length;
    return sum + x * ys[next] - xs[next] * ys[index];
  }, 0) / 2;
  const split = Array.from(holeTrace.x).findIndex(Number.isNaN);
  const outerX = finite(Array.from(holeTrace.x).slice(0, split));
  const outerY = finite(Array.from(holeTrace.y).slice(0, split));
  const holeX = finite(Array.from(holeTrace.x).slice(split + 1));
  const holeY = finite(Array.from(holeTrace.y).slice(split + 1));
  assert.ok(area(outerX, outerY) * area(holeX, holeY) < 0, "holes use opposite winding");

  const paperLayer = layer("paper-hole", "polygon", 0);
  paperLayer.coordinate_space = "paper";
  const paperTrace = runtime.layerToPlotlyTrace(paperLayer, hole, { styles: [], palettes: [] });
  assert.equal(paperTrace.visible, false);
  assert.equal(runtime.layerToPlotlyLayoutEffects(paperTrace).shapes[0].fillrule, "evenodd");
});

test("layout effects rebuild in stable zorder/id order instead of load order", async () => {
  const calls = { relayout: [] };
  const Plotly = {
    async react() {}, async restyle() {},
    async relayout(...args) { calls.relayout.push(args); },
  };
  const runtime = await loadRuntime(["starplot-scene-loader.js", "plotly-scene-adapter.js"], { Plotly });
  const foreground = layer("foreground", "text", 20); foreground.load_priority = 0;
  const backgroundB = layer("background-b", "text", 5); backgroundB.load_priority = 2;
  const backgroundA = layer("background-a", "text", 5); backgroundA.load_priority = 3;
  const source = {
    async loadManifest() { return { viewport: {}, styles: [], palettes: [], clips: [], layers: [foreground, backgroundB, backgroundA] }; },
    async *loadLayer(current) {
      const table = Arrow.tableFromArrays({
        x: new Float64Array([0]), y: new Float64Array([0]), text: [current.id],
        rotation: new Float32Array([0]), x_offset: new Float32Array([0]),
        y_offset: new Float32Array([0]), style_id: new Uint16Array([0]),
      });
      for (const batch of table.batches) yield batch;
    },
  };
  await runtime.renderScene("chart", source, { Plotly });
  assert.deepEqual(
    Array.from(calls.relayout.at(-1)[1].annotations, (annotation) => annotation.text),
    ["background-a", "background-b", "foreground"],
  );
});

test("DATA polygon holes keep their zorder trace plane when load priority is reversed", async () => {
  const calls = { react: [], restyle: [] };
  const Plotly = {
    async react(...args) { calls.react.push(args); },
    async restyle(...args) { calls.restyle.push(args); },
    async relayout() {},
  };
  const runtime = await loadRuntime(["starplot-scene-loader.js", "plotly-scene-adapter.js"], { Plotly });
  const hole = layer("hole", "polygon", 5, { fill_color: "#f00" }); hole.load_priority = 100;
  const foreground = layer("foreground", "line", 10); foreground.load_priority = 0;
  const holeTable = Arrow.tableFromArrays({
    polygon_id: new Uint32Array([0, 0, 0, 0, 0, 0]),
    ring_id: new Uint32Array([0, 0, 0, 1, 1, 1]),
    vertex_index: new Uint32Array([0, 1, 2, 0, 1, 2]),
    x: new Float64Array([0, 4, 0, 1, 2, 1]), y: new Float64Array([0, 0, 4, 1, 1, 2]),
  });
  const source = {
    async loadManifest() { return { viewport: {}, styles: [], palettes: [], clips: [], layers: [foreground, hole] }; },
    async *loadLayer(current) {
      for (const batch of (current.kind === "polygon" ? holeTable : tables.line()).batches) yield batch;
    },
  };
  await runtime.renderScene("chart", source, { Plotly });
  assert.deepEqual(Array.from(calls.react[0][1], (trace) => trace.meta.starplot_layer_id), ["hole", "foreground"]);
  assert.deepEqual(Array.from(calls.restyle, (call) => call[2][0]), [1, 0]);
  const holeUpdate = calls.restyle[1][1];
  assert.equal(holeUpdate.type[0], "scatter");
  assert.equal(holeUpdate.fill[0], "toself");
  assert.equal(holeUpdate.zorder[0], 5);
});

test("a DATA hole keeps mixed stars and line collections on one SVG zorder plane", async () => {
  const calls = { react: [], restyle: [], loads: [] };
  const Plotly = {
    async react(...args) { calls.react.push(args); },
    async restyle(...args) { calls.restyle.push(args); },
    async relayout() {},
  };
  const runtime = await loadRuntime(["starplot-scene-loader.js", "plotly-scene-adapter.js"], { Plotly });
  const stars = layer("stars", "scatter", 2, { palette_id: "p" }); stars.load_priority = 0;
  const hole = layer("hole", "polygon", 5, { fill_color: "#f00" }); hole.load_priority = 100;
  const lines = layer("lines", "line_collection", 8); lines.load_priority = 1;
  const holeTable = Arrow.tableFromArrays({
    polygon_id: new Uint32Array([0, 0, 0, 0, 0, 0]),
    ring_id: new Uint32Array([0, 0, 0, 1, 1, 1]),
    vertex_index: new Uint32Array([0, 1, 2, 0, 1, 2]),
    x: new Float64Array([0, 4, 0, 1, 2, 1]), y: new Float64Array([0, 0, 4, 1, 1, 2]),
  });
  const source = {
    async loadManifest() { return { viewport: {}, styles: [], palettes: [{ id: "p", colors: ["#fff"] }], clips: [], layers: [lines, hole, stars] }; },
    async *loadLayer(current) {
      calls.loads.push(current.id);
      const table = current.kind === "polygon" ? holeTable
        : current.kind === "scatter" ? tables.scatter() : tables.line_collection();
      for (const batch of table.batches) yield batch;
    },
  };
  await runtime.renderScene("chart", source, { Plotly });
  assert.deepEqual(Array.from(calls.react[0][1], (trace) => trace.type), ["scatter", "scatter", "scatter"]);
  assert.deepEqual(Array.from(calls.restyle, (call) => call[1].type[0]), ["scatter", "scatter", "scatter"]);
  assert.equal(calls.loads.filter((id) => id === "hole").length, 1, "hole detection reuses its decoded table");
});

test("text preserves coordinate references, rotation, offsets, and per-row styles", async () => {
  const runtime = await loadRuntime(["plotly-scene-adapter.js"]);
  const current = layer("labels", "text", 0, {
    text_styles: [
      { font_size: 10, font_color: "#fff", font_name: "Inter" },
      { font_size: 14, font_color: "#f00", font_name: "Arial" },
    ],
  });
  current.coordinate_space = "axes";
  const table = Arrow.tableFromArrays({
    x: new Float64Array([0.5, 0.75]), y: new Float64Array([0.5, 0.75]), text: ["A", "B"],
    rotation: new Float32Array([15, 30]), x_offset: new Float32Array([10, -10]),
    y_offset: new Float32Array([5, -5]), style_id: new Uint16Array([0, 1]),
  });
  const trace = runtime.layerToPlotlyTrace(current, table, {
    viewport: { reference_width: 1000, reference_height: 500 }, styles: [], palettes: [],
  });
  const effects = runtime.layerToPlotlyLayoutEffects(trace);
  assert.equal(trace.visible, false);
  assert.equal(effects.annotations[0].xref, "x domain");
  assert.equal(effects.annotations[0].yref, "y domain");
  assert.deepEqual(Array.from(effects.annotations, (item) => item.textangle), [15, 30]);
  assert.deepEqual(Array.from(effects.annotations, (item) => item.font.size), [10, 14]);
  assert.deepEqual(Array.from(effects.annotations, (item) => item.xshift), [10, -10]);
  assert.deepEqual(Array.from(effects.annotations, (item) => item.yshift), [5, -5]);

  const paperLayer = { ...current, id: "paper-labels", coordinate_space: "paper" };
  const paper = runtime.layerToPlotlyTrace(paperLayer, table, {
    viewport: { reference_width: 1000, reference_height: 500 }, styles: [], palettes: [],
  });
  assert.equal(runtime.layerToPlotlyLayoutEffects(paper).annotations[0].xref, "paper");
});

test("interactive scatter binds hover fields and retains calibrated WebGL marker arrays", async () => {
  const runtime = await loadRuntime(["plotly-scene-adapter.js"]);
  const current = layer("stars", "scatter", 5, { palette_id: "p", symbol: "circle" });
  current.interactive = true;
  current.interaction = "hover";
  current.hover_fields = ["magnitude", "name"];
  const table = Arrow.tableFromArrays({
    x: new Float64Array([1]), y: new Float64Array([2]), size: new Float32Array([0.2]),
    color_index: new Uint8Array([1]), opacity: new Float32Array([0.5]),
    magnitude: new Float32Array([2.5]), name: ["Sirius"],
  });
  const trace = runtime.layerToPlotlyTrace(current, table, {
    styles: [], palettes: [{ id: "p", colors: ["#111", "#eee"] }],
  });
  assert.equal(trace.type, "scattergl");
  assert.ok(trace.marker.color instanceof Uint8Array);
  assert.equal(trace.marker.size[0], 1);
  assert.equal(trace.marker.opacity[0], Math.fround(0.5 * 0.2 * 1.15 * 0.2 * 1.15 * 6));
  assert.deepEqual(trace.customdata[0], [2.5, "Sirius"]);
  assert.match(trace.hovertemplate, /magnitude/);
});

test("scatter policy keeps small custom markers SVG and stars or large layers WebGL", async () => {
  const runtime = await loadRuntime(["plotly-scene-adapter.js"]);
  const table = tables.scatter();
  const scene = { styles: [], palettes: [{ id: "p", colors: ["#111", "#eee"] }] };
  const custom = layer("custom", "scatter", 1, {
    palette_id: "p", edge_color: "#abcdef", edge_width: 1.25,
  });
  custom.row_count = table.numRows;
  const svg = runtime.layerToPlotlyTrace(custom, table, scene);
  assert.equal(svg.type, "scatter");
  assert.ok(Math.abs(svg.marker.size[0] - 2.3) < 1e-6);
  assert.equal(svg.marker.opacity[1], 0.5);
  assert.equal(svg.marker.line.color, "#abcdef");
  assert.equal(svg.marker.line.width, 2.5);

  const stars = { ...custom, id: "stars", group_id: "stars" };
  const webgl = runtime.layerToPlotlyTrace(stars, table, scene);
  assert.equal(webgl.type, "scattergl");
  assert.equal(webgl.marker.line.width, 0);

  const large = { ...custom, id: "large", row_count: 1001 };
  assert.equal(runtime.layerToPlotlyTrace(large, table, scene).type, "scattergl");
  assert.equal(runtime.traceTypeForLayer(custom), "scatter");
  assert.equal(runtime.traceTypeForLayer(stars), "scattergl");
  assert.equal(runtime.traceTypeForLayer(large), "scattergl");
});

test("gradients honor clip identities, directions, and fail closed for unsupported modes", async () => {
  const runtime = await loadRuntime(["plotly-scene-adapter.js"]);
  const scene = {
    viewport: { data_bounds: { x_min: -2, x_max: 2, y_min: -2, y_max: 2 } },
    styles: [], palettes: [],
    clips: [{ id: "plot", kind: "rect", points: [[-1, -1], [1, 1]] }],
  };
  for (const direction of ["linear", "radial", "mollweide"]) {
    const current = layer(direction, "gradient", 0, { direction, color_stops: [[0, "#000"], [1, "#fff"]] });
    current.clip_id = "plot";
    const trace = runtime.layerToPlotlyTrace(current, tables.gradient(), scene);
    assert.equal(trace.type, "heatmap");
    assert.ok(Number.isNaN(trace.z[0][0]), `${direction} must mask outside clip`);
    assert.equal(trace.x.length, direction === "mollweide" ? 250 : 220);
    assert.equal(trace.y.length, direction === "mollweide" ? 250 : 220);
    assert.equal(trace.zsmooth, direction === "linear" ? false : "best");
  }
  const unknown = layer("bad", "gradient", 0, { direction: "diagonal", color_stops: [[0, "#000"], [1, "#fff"]] });
  assert.throws(() => runtime.layerToPlotlyTrace(unknown, tables.gradient(), scene), /unsupported gradient direction/);
  const missingClip = layer("missing", "gradient", 0, { direction: "linear", color_stops: [[0, "#000"], [1, "#fff"]] });
  missingClip.clip_id = "unknown";
  assert.throws(() => runtime.layerToPlotlyTrace(missingClip, tables.gradient(), scene), /unknown clip id/);
});

test("gradient sampling honors radial center and radius plus Galactic Mollweide rotation", async () => {
  const runtime = await loadRuntime(["plotly-scene-adapter.js"]);
  const scene = {
    viewport: { data_bounds: { x_min: -10, x_max: 10, y_min: -10, y_max: 10 } },
    styles: [], palettes: [], clips: [],
  };
  const radialLayer = layer("radial", "gradient", 0, {
    direction: "radial", center: [2, -3], radius: 4,
    color_stops: [[0, "#000"], [1, "#fff"]],
  });
  const radial = runtime.layerToPlotlyTrace(radialLayer, tables.gradient(), scene);
  assert.equal(radial.x.length, 220);
  assert.equal(radial.y.length, 220);
  let min = { value: Infinity, row: -1, col: -1 };
  for (let row = 0; row < radial.z.length; row += 1) {
    for (let col = 0; col < radial.z[row].length; col += 1) {
      if (radial.z[row][col] < min.value) min = { value: radial.z[row][col], row, col };
    }
  }
  assert.ok(Math.abs(radial.x[min.col] - 2) < 0.1);
  assert.ok(Math.abs(radial.y[min.row] + 3) < 0.1);

  const clippedScene = {
    ...scene,
    clips: [{ id: "wide", kind: "rect", points: [[-8, -8], [8, 8]] }],
  };
  const clippedRadialLayer = layer("clipped-radial", "gradient", 0, {
    direction: "radial", center: [0, 0], radius: 1,
    color_stops: [[0, "#000"], [1, "#fff"]],
  });
  clippedRadialLayer.clip_id = "wide";
  const clippedRadial = runtime.layerToPlotlyTrace(
    clippedRadialLayer, tables.gradient(), clippedScene,
  );
  const farInsideClip = clippedRadial.z[150][150];
  assert.equal(farInsideClip, 1, "an explicit clip, not radius, is the Python radial mask");

  const mollweideLayer = layer("mollweide", "gradient", 0, {
    direction: "mollweide", color_stops: [[0, "#000"], [1, "#fff"]],
  });
  const mollweide = runtime.layerToPlotlyTrace(mollweideLayer, tables.gradient(), scene);
  const middle = Math.floor(mollweide.z.length / 2);
  assert.ok(Math.abs(mollweide.z[middle][middle] - 0.165) < 0.03);

  const linearLayer = layer("linear", "gradient", 0, {
    direction: "linear", color_stops: [[0, "#000"], [1, "#fff"]],
  });
  const linear = runtime.layerToPlotlyTrace(linearLayer, tables.gradient(), scene);
  assert.equal(linear.x.length, 2);
  assert.equal(linear.y.length, 2000);
});

test("info table widths and viewport layout remain exact in initial Plotly reservation", async () => {
  const calls = [];
  const Plotly = { async react(...args) { calls.push(args); }, async restyle() {}, async relayout() {} };
  const runtime = await loadRuntime(["starplot-scene-loader.js", "plotly-scene-adapter.js"], { Plotly });
  const table = tables.info_table();
  const source = {
    async loadManifest() {
      return {
        viewport: {
          data_bounds: { x_min: -1, x_max: 1, y_min: -2, y_max: 2 },
          axes_background: "#123", paper_background: "#456", showlegend: true,
          margin: { l: 20, r: 21, t: 22, b: 23 },
        },
        styles: [], palettes: [], clips: [], layers: [layer("table", "info_table", 1)],
      };
    },
    async *loadLayer() { for (const batch of table.batches) yield batch; },
  };
  await runtime.renderScene("chart", source, { Plotly });
  const layout = calls[0][2];
  assert.deepEqual(Array.from(layout.xaxis.range), [-1, 1]);
  assert.deepEqual(Array.from(layout.yaxis.range), [-2, 2]);
  assert.equal(layout.plot_bgcolor, "#123");
  assert.equal(layout.paper_bgcolor, "#456");
  assert.equal(layout.showlegend, true);
  assert.deepEqual({ ...layout.margin }, { l: 20, r: 21, t: 22, b: 23 });
  const trace = runtime.layerToPlotlyTrace(layer("table", "info_table", 1), table, { viewport: {}, styles: [], palettes: [] });
  const effects = runtime.layerToPlotlyLayoutEffects(trace);
  assert.equal(trace.visible, false);
  assert.equal(effects.shapes[0].type, "rect");
  assert.equal(effects.annotations.length, 2);
});

test("layout-only layers keep one trace slot and emit valid annotations and footer shapes", async () => {
  const calls = { react: [], restyle: [], relayout: [] };
  const Plotly = {
    async react(...args) { calls.react.push(args); },
    async restyle(...args) { calls.restyle.push(args); },
    async relayout(...args) { calls.relayout.push(args); },
  };
  const runtime = await loadRuntime(["starplot-scene-loader.js", "plotly-scene-adapter.js"], { Plotly });
  const layers = [layer("label", "text", 1, { ha: "right", va: "top", font_weight: "bold" }), layer("footer", "info_table", 2, { background_color: "#abc", line_color: "#def" })];
  const source = {
    async loadManifest() { return { viewport: { margin: { l: 1, r: 2, t: 3, b: 4 } }, styles: [], palettes: [], clips: [], layers }; },
    async *loadLayer(current) { for (const batch of (current.kind === "text" ? tables.text() : tables.info_table()).batches) yield batch; },
  };
  await runtime.renderScene("chart", source, { Plotly });
  assert.equal(calls.react.length, 1);
  assert.equal(calls.restyle.length, 2);
  assert.deepEqual(Array.from(calls.react[0][1], (trace) => trace.type), ["scatter", "scatter"]);
  assert.equal(calls.relayout.length, 2);
  const final = calls.relayout.at(-1)[1];
  assert.equal(final.annotations.length, 3);
  assert.equal(final.annotations[0].xanchor, "right");
  assert.equal(final.annotations[0].yanchor, "top");
  assert.equal(final.annotations[0].textangle, 15);
  assert.equal(final.shapes[0].fillcolor, "#abc");
  assert.equal(final.margin.b, 105);
});

test("hover is bounded, invalid gradient bounds skip closed, and radial defaults precede overrides", async () => {
  const runtime = await loadRuntime(["plotly-scene-adapter.js"]);
  const hoverLayer = layer("large", "scatter", 0, { palette_id: "p" });
  hoverLayer.interactive = true; hoverLayer.interaction = "hover"; hoverLayer.hover_fields = ["magnitude"]; hoverLayer.row_count = 100001;
  const hoverTable = Arrow.tableFromArrays({
    x: new Float64Array([0]), y: new Float64Array([0]), size: new Float32Array([1]),
    color_index: new Uint8Array([0]), opacity: new Float32Array([1]), magnitude: new Float32Array([1]),
  });
  const hover = runtime.layerToPlotlyTrace(hoverLayer, hoverTable, { styles: [], palettes: [{ id: "p", colors: ["#fff"] }] });
  assert.equal(hover.customdata, undefined);
  assert.equal(hover.hovertemplate, undefined);
  assert.equal(hover.hoverinfo, "skip");

  const missing = runtime.layerToPlotlyTrace(layer("missing", "gradient", 0, { direction: "linear", color_stops: [[0, "#000"], [1, "#fff"]] }), tables.gradient(), { viewport: { data_bounds: { x_min: 0, x_max: NaN, y_min: 0, y_max: 1 } }, styles: [], palettes: [], clips: [] });
  assert.equal(missing.type, "heatmap"); assert.equal(missing.visible, false);

  const radial = runtime.layerToPlotlyTrace(layer("radial-default", "gradient", 0, { direction: "radial", center: [9, 0], color_stops: [[0, "#000"], [1, "#fff"]] }), tables.gradient(), { viewport: { data_bounds: { x_min: -10, x_max: 10, y_min: -10, y_max: 10 } }, styles: [], palettes: [], clips: [] });
  const centerRow = Math.round((0 - radial.y[0]) / (radial.y.at(-1) - radial.y[0]) * (radial.y.length - 1));
  const nearOriginCol = Math.round((0 - radial.x[0]) / (radial.x.at(-1) - radial.x[0]) * (radial.x.length - 1));
  assert.ok(Number.isFinite(radial.z[centerRow][nearOriginCol]), "implicit radius must be based on the default center");
});

test("optional layer failures do not block safe layers and required failures preserve them", async () => {
  const calls = { restyle: [], relayout: [] };
  const Plotly = { async react() {}, async restyle(...args) { calls.restyle.push(args); }, async relayout(...args) { calls.relayout.push(args); } };
  const runtime = await loadRuntime(["starplot-scene-loader.js", "plotly-scene-adapter.js"], { Plotly });
  const good = layer("good", "line", 0); const optional = layer("optional", "line", 1); optional.required = false; const required = layer("required", "line", 2);
  const source = {
    async loadManifest() { return { viewport: {}, styles: [], palettes: [], clips: [], layers: [good, optional, required] }; },
    async *loadLayer(current) { if (current.id !== "good") throw new Error(`${current.id} failed`); for (const batch of tables.line().batches) yield batch; },
  };
  await assert.rejects(runtime.renderScene("chart", source, { Plotly }), /required failed/);
  assert.equal(calls.restyle.length, 1, "the completed safe layer remains visible");
  assert.deepEqual(Array.from(calls.restyle.at(-1)[2]), [0]);
});
