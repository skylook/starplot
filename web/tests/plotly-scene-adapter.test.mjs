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

test("dense finite-palette ScatterGL data uses bounded scalar-colour batches", async () => {
  const runtime = await loadRuntime(["plotly-scene-adapter.js"]);
  const rowCount = 100_000;
  const colorIndex = new Uint8Array(rowCount);
  for (let index = 0; index < rowCount; index += 1) colorIndex[index] = index % 2;
  const table = Arrow.tableFromArrays({
    x: new Float64Array(rowCount), y: new Float64Array(rowCount),
    size: new Float32Array(rowCount).fill(1), color_index: colorIndex,
    opacity: new Float32Array(rowCount).fill(0.5),
  });
  const current = layer("dense-stars", "scatter", 1, { palette_id: "palette", symbol: "circle" });
  current.group_id = "stars";
  current.row_count = rowCount;
  const traces = runtime.layerToPlotlyTraces(current, table, {
    styles: [], palettes: [{ id: "palette", colors: ["#fff", "#f80"] }], clips: [],
  });
  assert.equal(traces.length, 2);
  assert.deepEqual(Array.from(traces, (trace) => trace.marker.color), ["#fff", "#f80"]);
  assert.ok(traces.every((trace) => trace.type === "scattergl"));
  assert.ok(traces.every((trace) => !Object.hasOwn(trace.marker, "colorscale")));
  assert.equal(traces.reduce((total, trace) => total + trace.x.length, 0), rowCount);
  assert.ok(traces.every((trace) => trace.meta.starplot_layer_id === "dense-stars"));
});

test("dense palette fast path decodes coordinates and marker values into final buckets", async () => {
  const runtime = await loadRuntime(["plotly-scene-adapter.js"]);
  const rowCount = 100_000;
  const x = new Float32Array(rowCount);
  const y = new Float32Array(rowCount);
  const size = new Float32Array(rowCount);
  const opacity = new Float32Array(rowCount);
  const colorIndex = new Uint8Array(rowCount);
  for (let index = 0; index < rowCount; index += 1) {
    x[index] = index / rowCount;
    y[index] = 1 - index / rowCount;
    colorIndex[index] = index % 2;
    size[index] = index % 2 ? 2 : 0.5;
    opacity[index] = index % 2 ? 0.75 : 0.5;
  }
  const table = Arrow.tableFromArrays({ x, y, size, color_index: colorIndex, opacity });
  const current = layer("dense-relative", "scatter", 1, { palette_id: "palette", symbol: "circle" });
  current.group_id = "stars";
  current.row_count = rowCount;
  current.coordinate_encoding = {
    x: { kind: "relative-f32", origin: 10, scale: 2, max_error_pixels: 0.01 },
    y: { kind: "relative-f32", origin: -5, scale: 3, max_error_pixels: 0.01 },
  };

  const traces = runtime.layerToPlotlyTraces(current, table, {
    styles: [], palettes: [{ id: "palette", colors: ["#fff", "#f80"] }], clips: [],
  });

  assert.equal(traces.length, 2);
  assert.equal(traces.reduce((total, trace) => total + trace.x.length, 0), rowCount);
  assert.equal(traces[0].x[0], 10);
  assert.equal(traces[0].y[0], -2);
  assert.ok(Math.abs(traces[1].x[0] - (10 + 2 / rowCount)) < 1e-7);
  assert.ok(Math.abs(traces[1].y[0] - (-2 - 3 / rowCount)) < 1e-7);
  assert.equal(traces[0].marker.size, 1);
  assert.ok(traces[1].marker.size instanceof Float32Array);
  assert.equal(traces[1].marker.size[0], 2);
  assert.equal(traces[0].marker.opacity[0], 0.25);
  assert.equal(traces[1].marker.opacity[0], 0.75);
});

test("interactive dense palette layers keep hover rows aligned at the batching threshold", async () => {
  const runtime = await loadRuntime(["plotly-scene-adapter.js"]);
  const rowCount = 100_000;
  const colorIndex = new Uint8Array(rowCount);
  for (let index = 0; index < rowCount; index += 1) colorIndex[index] = index % 2;
  const names = Array.from({ length: rowCount }, (_, index) => `star-${index}`);
  const table = Arrow.tableFromArrays({
    x: new Float64Array(rowCount), y: new Float64Array(rowCount),
    size: new Float32Array(rowCount).fill(1), color_index: colorIndex,
    opacity: new Float32Array(rowCount).fill(0.5), name: names,
  });
  const current = layer("dense-stars", "scatter", 1, { palette_id: "palette", symbol: "circle" });
  current.group_id = "stars";
  current.row_count = rowCount;
  current.interactive = true;
  current.interaction = "hover";
  current.hover_fields = ["name"];
  const traces = runtime.layerToPlotlyTraces(current, table, {
    styles: [], palettes: [{ id: "palette", colors: ["#fff", "#f80"] }], clips: [],
  });
  assert.equal(traces.length, 1, "interactive rows must not be split away from customdata");
  assert.equal(traces[0].customdata.length, rowCount);
  assert.deepEqual(Array.from(traces[0].customdata.at(-1)), [`star-${rowCount - 1}`]);
});

test("dense palette batches preserve source opacity for resize correction", async () => {
  const rowCount = 100_000;
  const colorIndex = new Uint8Array(rowCount);
  for (let index = 0; index < rowCount; index += 1) colorIndex[index] = index % 2;
  const table = Arrow.tableFromArrays({
    x: new Float64Array(rowCount), y: new Float64Array(rowCount),
    size: new Float32Array(rowCount).fill(0.5), color_index: colorIndex,
    opacity: new Float32Array(rowCount).fill(0.75),
  });
  const current = layer("dense-stars", "scatter", 1, { palette_id: "palette", symbol: "circle" });
  current.group_id = "stars";
  current.row_count = rowCount;
  const scene = {
    viewport: {
      source_axes_width: 1000, target_axes_width: 500, reference_width: 1000,
      dpi: 72, margin: { l: 0, r: 0, t: 0, b: 0 },
    },
    styles: [], palettes: [{ id: "palette", colors: ["#fff", "#f80"] }],
    clips: [], layers: [current],
  };
  const source = {
    async loadManifest() { return scene; },
    async *loadLayer() { for (const batch of table.batches) yield batch; },
  };
  const calls = [];
  let initialTraces;
  const Plotly = {
    async react(target, traces) {
      initialTraces = traces;
      target._fullLayout = {
        width: 400, height: 400, margin: { l: 0, r: 0, t: 0, b: 0 },
        xaxis: { domain: [0, 1] }, yaxis: { domain: [0, 1] }, annotations: [],
      };
    },
    async restyle(_target, update) { calls.push(update); },
    async relayout() {},
  };
  const runtime = await loadRuntime(["starplot-scene-loader.js", "plotly-scene-adapter.js"], { Plotly });
  await runtime.renderScene({ querySelectorAll() { return []; } }, source, { Plotly });
  assert.ok(initialTraces.every((trace) => trace.marker.size === 1));
  const markerUpdate = calls.find((update) => update["marker.size"]);
  assert.ok(markerUpdate["marker.opacity"], "every dense batch must recompute opacity from source values");
  assert.equal(markerUpdate["marker.opacity"].length, 2);
});

test("line hover, info-table cells, and legend names are escaped before Plotly sinks", async () => {
  const runtime = await loadRuntime(["plotly-scene-adapter.js"]);
  const attack = `<img src=x onerror="alert('x')">`;
  const lineTable = Arrow.tableFromArrays({
    path_id: new Uint32Array([0, 0]), vertex_index: new Uint32Array([0, 1]),
    x: new Float64Array([0, 1]), y: new Float64Array([0, 1]), name: [attack, attack],
  });
  const lineLayer = layer(attack, "line", 1, { legend_label: attack });
  lineLayer.interactive = true;
  lineLayer.interaction = "hover";
  lineLayer.hover_fields = ["name"];
  const lineTrace = runtime.layerToPlotlyTrace(lineLayer, lineTable, { styles: [], palettes: [] });
  assert.ok(lineTrace.text.every((value) => !value.includes("<img")));
  assert.ok(!lineTrace.name.includes("<img"));

  const infoTable = Arrow.tableFromArrays({
    column: [attack], value: [attack], width: new Float32Array([1]),
  });
  const infoTrace = runtime.layerToPlotlyTrace(
    layer("info", "info_table", 1), infoTable,
    { viewport: {}, styles: [], palettes: [] },
  );
  const effects = runtime.layerToPlotlyLayoutEffects(infoTrace);
  assert.ok(effects.annotations.every((annotation) => !annotation.text.includes("<img")));
  assert.match(effects.annotations[0].text, /^<b>&lt;img/);
});

test("renderScene performs one final zorder-stable Plotly update", async () => {
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
  assert.equal(calls.react.length, 1, "one final Plotly update");
  assert.deepEqual(
    Array.from(calls.react[0][1], (trace) => trace.meta.starplot_layer_id),
    ["early-a", "early-b", "late"],
  );
  assert.equal(calls.restyle.length, 0, "dense scenes never redraw once per layer");
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

test("polygon and line artists preserve serialized Matplotlib custom dash patterns", async () => {
  const runtime = await loadRuntime(["plotly-scene-adapter.js"]);
  const scene = { styles: [], palettes: [], clips: [] };
  const dashed = layer("dashed", "line", 0, { line_style: "(1, [2, 3])" });
  assert.equal(runtime.layerToPlotlyTrace(dashed, tables.line(), scene).line.dash, "dash");
  const polygon = layer("dashed-polygon", "polygon", 0, {
    fill_color: "rgba(0,0,0,0)", edge_color: "#f00", line_style: "(1, [2, 3])",
  });
  assert.equal(runtime.layerToPlotlyTrace(polygon, tables.polygon(), scene).line.dash, "dash");
});

test("Matplotlib line style short names map to Plotly dashes", async () => {
  const runtime = await loadRuntime(["plotly-scene-adapter.js"]);
  const scene = { styles: [], palettes: [], clips: [] };
  for (const [raw, expected] of [
    ["-", "solid"],
    ["--", "dash"],
    [":", "dot"],
    ["-.", "dashdot"],
    ["dotted", "dot"],
    ["dashdot", "dashdot"],
  ]) {
    const line = layer(`line-${raw}`, "line", 0, { line_style: raw });
    assert.equal(
      runtime.layerToPlotlyTrace(line, tables.line(), scene).line.dash,
      expected,
      raw,
    );
  }
});

test("layout effects rebuild in stable zorder/id order instead of load order", async () => {
  const calls = { react: [] };
  const Plotly = {
    async react(...args) { calls.react.push(args); }, async restyle() {}, async relayout() {},
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
    Array.from(calls.react[0][2].annotations, (annotation) => annotation.text),
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
  const holeTrace = calls.react[0][1][0];
  assert.equal(holeTrace.type, "scatter");
  assert.equal(holeTrace.fill, "toself");
  assert.equal(holeTrace.zorder, 5);
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
  assert.equal(calls.restyle.length, 0);
  assert.equal(calls.loads.filter((id) => id === "hole").length, 1, "hole detection reuses its decoded table");
});

test("mixed SVG geometry and WebGL stars use one SVG zorder plane when safely bounded", async () => {
  const calls = { react: [] };
  const Plotly = { async react(...args) { calls.react.push(args); }, async restyle() {}, async relayout() {} };
  const runtime = await loadRuntime(["starplot-scene-loader.js", "plotly-scene-adapter.js"], { Plotly });
  const optic = layer("optic", "polygon", -1, { fill_color: "rgba(0,0,0,0)", edge_color: "#f00" });
  const stars = layer("stars", "scatter", 1, { palette_id: "p" }); stars.group_id = "stars"; stars.row_count = 2;
  const source = {
    async loadManifest() { return { viewport: {}, styles: [], palettes: [{ id: "p", colors: ["#fff"] }], clips: [], layers: [optic, stars] }; },
    async *loadLayer(current) { for (const batch of (current.kind === "polygon" ? tables.polygon() : tables.scatter()).batches) yield batch; },
  };
  await runtime.renderScene("chart", source, { Plotly });
  assert.deepEqual(Array.from(calls.react[0][1], (trace) => trace.type), ["scatter", "scatter"]);
  assert.deepEqual(Array.from(calls.react[0][1], (trace) => trace.zorder), [0, 1]);
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
  const sizeValue = table.getChild("size").get(0);
  assert.equal(trace.type, "scattergl");
  assert.ok(trace.marker.color instanceof Uint8Array);
  assert.equal(trace.marker.size[0], 1);
  assert.equal(trace.marker.opacity[0], Math.fround(0.5 * sizeValue * sizeValue * 2));
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
  assert.ok(Math.abs(svg.marker.size[0] - 2.0) < 1e-6);
  assert.equal(svg.marker.opacity[1], 0.5);
  assert.equal(svg.marker.line.color, "#abcdef");
  assert.equal(svg.marker.line.width, 1.25);

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

test("ellipse scatter marker retains its semantic shape while using Plotly's valid circle", async () => {
  const runtime = await loadRuntime(["plotly-scene-adapter.js"]);
  const scene = { styles: [], palettes: [{ id: "p", colors: ["#fff"] }] };
  const galaxy = layer("galaxy", "scatter", 1, { palette_id: "p", symbol: "ellipse" });
  galaxy.row_count = 1001;
  const table = Arrow.tableFromArrays({
    x: new Float64Array([1, 2]), y: new Float64Array([3, 4]),
    size: new Float32Array([4, 4]), color_index: new Uint8Array([0, 0]),
    opacity: new Float32Array([1, 1]),
  });
  const trace = runtime.layerToPlotlyTrace(galaxy, table, scene);
  assert.equal(trace.type, "scatter");
  assert.equal(trace.marker.symbol, "circle");
  assert.equal(trace.meta.starplot_marker_symbol, "ellipse");
  const [renderTrace] = runtime.layerToPlotlyTraces(galaxy, table, scene);
  assert.equal(renderTrace.type, "scatter");
  assert.equal(renderTrace.meta.starplot_marker_symbol, "ellipse");
});

test("ellipse SVG transforms target only semantic ellipse marker paths", async () => {
  const runtime = await loadRuntime(["plotly-scene-adapter.js"]);
  const point = (transform) => {
    const attributes = new Map([["transform", transform]]);
    return {
      getAttribute(name) { return attributes.get(name) || null; },
      setAttribute(name, value) { attributes.set(name, value); },
    };
  };
  const ordinaryPoint = point("translate(10,20)");
  const ellipsePoint = point("translate(30,40)");
  const trace = (index, paths) => ({
    __data__: [{ trace: { index } }],
    querySelectorAll(selector) {
      assert.equal(selector, "path.point");
      return paths;
    },
  });
  const target = {
    _fullData: [
      { meta: { starplot_marker_symbol: "circle" } },
      { meta: { starplot_marker_symbol: "ellipse" } },
    ],
    querySelectorAll(selector) {
      assert.equal(selector, "g.trace");
      return [trace(0, [ordinaryPoint]), trace(1, [ellipsePoint])];
    },
  };

  runtime._applyEllipseMarkerTransforms(target);
  runtime._applyEllipseMarkerTransforms(target);

  assert.equal(ordinaryPoint.getAttribute("transform"), "translate(10,20)");
  assert.equal(ordinaryPoint.getAttribute("vector-effect"), null);
  assert.equal(
    ellipsePoint.getAttribute("transform"),
    "translate(30,40) rotate(15) scale(1 0.5)",
  );
  assert.equal(ellipsePoint.getAttribute("vector-effect"), "non-scaling-stroke");
});

test("star_8 scatter marker preserves starburst semantics", async () => {
  const runtime = await loadRuntime(["plotly-scene-adapter.js"]);
  const scene = { styles: [], palettes: [{ id: "p", colors: ["#fff"] }] };
  const stars = layer("stars", "scatter", 1, { palette_id: "p", symbol: "star_8" });
  stars.row_count = 2;
  const table = Arrow.tableFromArrays({
    x: new Float64Array([1, 2]), y: new Float64Array([3, 4]),
    size: new Float32Array([4, 4]), color_index: new Uint8Array([0, 0]),
    opacity: new Float32Array([1, 1]),
  });

  const trace = runtime.layerToPlotlyTrace(stars, table, scene);
  assert.equal(trace.marker.symbol, "star");
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
    assert.equal(trace.x.length, 512);
    assert.equal(trace.y.length, 512);
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
  assert.equal(radial.x.length, 512);
  assert.equal(radial.y.length, 512);
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
  assert.deepEqual({ ...layout.margin }, { l: 20, r: 21, t: 22, b: 105 });
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
  assert.equal(calls.restyle.length, 0);
  assert.deepEqual(Array.from(calls.react[0][1], (trace) => trace.type), ["scatter", "scatter"]);
  assert.equal(calls.relayout.length, 0);
  const final = calls.react[0][2];
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
  const calls = { react: [], restyle: [], relayout: [] };
  const Plotly = { async react(...args) { calls.react.push(args); }, async restyle(...args) { calls.restyle.push(args); }, async relayout(...args) { calls.relayout.push(args); } };
  const runtime = await loadRuntime(["starplot-scene-loader.js", "plotly-scene-adapter.js"], { Plotly });
  const good = layer("good", "line", 0); const optional = layer("optional", "line", 1); optional.required = false; const required = layer("required", "line", 2);
  const source = {
    async loadManifest() { return { viewport: {}, styles: [], palettes: [], clips: [], layers: [good, optional, required] }; },
    async *loadLayer(current) { if (current.id !== "good") throw new Error(`${current.id} failed`); for (const batch of tables.line().batches) yield batch; },
  };
  await assert.rejects(runtime.renderScene("chart", source, { Plotly }), /required failed/);
  assert.equal(calls.restyle.length, 0);
  assert.equal(calls.react.length, 1, "the completed safe layer remains visible");
  assert.equal(calls.react[0][1][0].meta.starplot_layer_id, "good");
});

// ---------------------------------------------------------------------------
// Scale-correction tests (Fixes 1–5)
// ---------------------------------------------------------------------------

/** Build a minimal scene + source for scale-correction tests. */
function scaleCorrectionScene(opts = {}) {
  const {
    sourceAxesWidth = 3600,
    targetAxesWidth = sourceAxesWidth,
    dpi = 100,
    markerSize = 10,
    lineWidth = 2,
    fontSize = 12,
    strokeColor = "#000",
    strokeWidth = 1.5,
    polygonEdgeWidth = 1.0,
  } = opts;
  const scatterTable = Arrow.tableFromArrays({
    x: new Float64Array([1, 2]), y: new Float64Array([3, 4]),
    size: new Float32Array([markerSize, markerSize]),
    color_index: new Uint8Array([0, 0]), opacity: new Float32Array([1, 1]),
  });
  const lineTable = Arrow.tableFromArrays({
    path_id: new Uint32Array([0, 0]), vertex_index: new Uint32Array([0, 1]),
    x: new Float64Array([0, 1]), y: new Float64Array([0, 1]),
  });
  const textTable = Arrow.tableFromArrays({
    x: new Float64Array([1]), y: new Float64Array([2]), text: ["M42"],
    rotation: new Float32Array([0]), x_offset: new Float32Array([0]),
    y_offset: new Float32Array([0]), style_id: new Uint16Array([0]),
  });
  const polygonTable = Arrow.tableFromArrays({
    polygon_id: new Uint32Array([0, 0, 0]), ring_id: new Uint32Array([0, 0, 0]),
    vertex_index: new Uint32Array([0, 1, 2]),
    x: new Float64Array([0, 1, 0]), y: new Float64Array([0, 0, 1]),
  });
  const scatterLayer = layer("stars", "scatter", 0, { palette_id: "p", symbol: "circle" });
  scatterLayer.row_count = 2;
  const lineLayer = layer("grid", "line", 1, { width: lineWidth, color: "#888" });
  const textLayer = layer("labels", "text", 2, {
    font_size: fontSize, font_color: "#fff", stroke_color: strokeColor, stroke_width: strokeWidth,
  });
  const polygonLayer = layer("horizon", "polygon", 3, {
    edge_width: polygonEdgeWidth, edge_color: "#555", fill_color: "none",
  });
  // Use axes coordinate space so polygonTrace emits shapes (exercising Fix 2)
  polygonLayer.coordinate_space = "axes";
  const scene = {
    viewport: {
      data_bounds: { x_min: 0, x_max: 10, y_min: 0, y_max: 10 },
      source_axes_width: sourceAxesWidth,
      target_axes_width: targetAxesWidth,
      reference_width: sourceAxesWidth,
      dpi,
      margin: { l: 10, r: 10, t: 10, b: 10, autoexpand: false },
    },
    palettes: [{ id: "p", colors: ["#fff"] }],
    styles: [],
    clips: [],
    layers: [scatterLayer, lineLayer, textLayer, polygonLayer],
  };
  const tables = {
    stars: scatterTable, grid: lineTable, labels: textTable, horizon: polygonTable,
  };
  const source = {
    async loadManifest() { return scene; },
    async *loadLayer(l) { for (const b of tables[l.id].batches) yield b; },
  };
  return { scene, source, scatterLayer, lineLayer, textLayer, polygonLayer };
}

test("explicit compile width does not scale marker sizes twice", async () => {
  const runtime = await loadRuntime(["starplot-scene-loader.js", "plotly-scene-adapter.js"]);
  // SceneCompiler has already converted a 10px source marker to 5px for the
  // requested 1800px target axes.  Rendering at that target must keep 5px.
  const { source } = scaleCorrectionScene({
    sourceAxesWidth: 3600,
    targetAxesWidth: 1800,
    markerSize: 5,
  });
  const { Plotly, calls } = mockPlotly({
    layoutWidth: 1820, layoutHeight: 1000,
    margin: { l: 10, r: 10, t: 10, b: 10 },
    xDomain: [0, 1], yDomain: [0, 1],
  });
  const target = {
    _fullLayout: null,
    getBoundingClientRect() { return { width: 1820, height: 1000 }; },
    querySelectorAll() { return []; },
  };

  await runtime.renderScene(target, source, { Plotly });

  assert.deepEqual(Array.from(calls.react[0].traces[0].marker.size), [5, 5]);
});

test("responsive scaleanchor predicts the axes width before dense marker rendering", async () => {
  const runtime = await loadRuntime(["starplot-scene-loader.js", "plotly-scene-adapter.js"]);
  const { source, scene } = scaleCorrectionScene({
    sourceAxesWidth: 1000,
    targetAxesWidth: 1000,
    markerSize: 10,
  });
  scene.viewport.data_bounds = { x_min: 0, x_max: 20, y_min: 0, y_max: 10 };
  const xDomainInset = 10 / 980;
  const { Plotly, calls } = mockPlotly({
    layoutWidth: 1000,
    layoutHeight: 500,
    margin: { l: 10, r: 10, t: 10, b: 10 },
    xDomain: [xDomainInset, 1 - xDomainInset],
    yDomain: [0, 1],
  });
  const target = {
    _fullLayout: null,
    getBoundingClientRect() { return { width: 1000, height: 500 }; },
    querySelectorAll() { return []; },
  };

  await runtime.renderScene(target, source, { Plotly });

  const markerSizes = Array.from(calls.react[0].traces[0].marker.size);
  assert.ok(markerSizes.every((size) => Math.abs(size - 9.6) < 1e-5));
  assert.equal(calls.restyle.length, 0, "the initial render must not resend dense marker arrays");
});

/** Mock Plotly with a configurable _fullLayout simulating scaleanchor. */
function mockPlotly(opts = {}) {
  const {
    layoutWidth = 1280, layoutHeight = 800,
    margin = { l: 10, r: 10, t: 10, b: 10 },
    xDomain = [0.19, 0.81],
    yDomain = [0, 1],
  } = opts;
  const calls = { react: [], restyle: [], relayout: [] };
  let fullLayout = {
    width: layoutWidth, height: layoutHeight, margin,
    xaxis: { domain: xDomain },
    yaxis: { domain: yDomain },
    annotations: [],
  };
  const Plotly = {
    async react(target, traces, layout) {
      calls.react.push({ traces, layout });
      // Simulate Plotly computing _fullLayout annotations from layout
      fullLayout = {
        ...fullLayout,
        annotations: (layout.annotations || []).map(a => ({ ...a })),
      };
      if (target) target._fullLayout = fullLayout;
    },
    async restyle(target, update, indices) { calls.restyle.push({ update, indices }); },
    async relayout(target, update) { calls.relayout.push(update); },
  };
  return { Plotly, calls, getFullLayout: () => fullLayout };
}

test("_actualAxesSize returns the measured horizontal axes width", async () => {
  const runtime = await loadRuntime(["plotly-scene-adapter.js"]);
  // Landscape 1280x800, xDomain shrunk by scaleanchor
  const landscape = {
    width: 1280, height: 800, margin: { l: 10, r: 10, t: 10, b: 10 },
    xaxis: { domain: [0.19, 0.81] }, yaxis: { domain: [0, 1] },
  };
  const result1 = runtime._actualAxesSize(landscape);
  const axesW1 = (1280 - 20) * (0.81 - 0.19);
  const axesH1 = (800 - 20) * 1.0;
  assert.equal(result1, axesW1);
  assert.ok(axesH1 > 0);
  // A non-square axes domain must not silently replace horizontal scale with height.
  const portrait = {
    width: 800, height: 1200, margin: { l: 10, r: 10, t: 10, b: 10 },
    xaxis: { domain: [0, 1] }, yaxis: { domain: [0.19, 0.81] },
  };
  const result2 = runtime._actualAxesSize(portrait);
  const axesW2 = (800 - 20) * 1.0;
  const axesH2 = (1200 - 20) * (0.81 - 0.19);
  assert.equal(result2, axesW2);
  assert.ok(axesH2 < axesW2);
  // Null guard
  assert.equal(runtime._actualAxesSize(null), null);
  assert.equal(runtime._actualAxesSize({}), null);
});

test("scale correction is idempotent and updates subpixel marker opacity with size", async () => {
  const runtime = await loadRuntime(["plotly-scene-adapter.js"]);
  const markerSize = new Float32Array([0.5]);
  const markerOpacity = new Float32Array([0.125]);
  const trace = { type: "scattergl", marker: { size: markerSize, opacity: markerOpacity } };
  const annotation = { font: { size: 20 }, xshift: 4, yshift: 6 };
  const layout = { annotations: [annotation], shapes: [] };
  const state = {
    scene: { viewport: { source_axes_width: 1000, dpi: 72 } },
    slots: [{ id: "stars" }], traces: new Map([["stars", [trace]]]), layout,
    metrics: { widthScale: 0.5, markerScale: 0.5, strokePixelScale: 0.5, fontPixelScale: 0.5 },
    markerSources: new Map([[trace, {
      size: new Float32Array([0.5]), opacity: new Float32Array([1]), webgl: true,
    }]]),
    polygonShapeIndices: [], textStrokes: [],
  };
  const target = {
    _fullLayout: {
      width: 420, height: 420, margin: { l: 10, r: 10, t: 10, b: 10 },
      xaxis: { domain: [0, 1] }, yaxis: { domain: [0, 1] },
      annotations: [structuredClone(annotation)],
    },
  };
  const calls = { restyle: [], relayout: [] };
  const Plotly = {
    async restyle(_target, update, indices) { calls.restyle.push({ update, indices }); },
    async relayout(_target, update) {
      calls.relayout.push(update);
      if (update.annotations) target._fullLayout.annotations = structuredClone(update.annotations);
    },
  };
  await runtime._applyScaleCorrection(target, state, Plotly);
  await runtime._applyScaleCorrection(target, state, Plotly);
  const markerCalls = calls.restyle.filter((call) => call.update["marker.size"]);
  assert.equal(markerCalls.length, 1, "an unchanged axes size must not be corrected twice");
  assert.ok(markerCalls[0].update["marker.opacity"], "subpixel opacity must follow marker size");
  assert.ok(markerCalls[0].update["marker.opacity"][0][0] < markerOpacity[0]);
  const annotationCalls = calls.relayout.filter((update) => update.annotations);
  assert.equal(annotationCalls.length, 1, "annotation correction must be idempotent");
});

test("successive scale corrections derive line and polygon widths from the compile baseline", async () => {
  const runtime = await loadRuntime(["plotly-scene-adapter.js"]);
  const trace = { type: "scatter", line: { width: 4 } };
  const layout = { annotations: [], shapes: [{ type: "path", line: { width: 6 } }] };
  const state = {
    scene: { viewport: { source_axes_width: 1000, target_axes_width: 1000, dpi: 72 } },
    slots: [{ id: "line" }], traces: new Map([["line", [trace]]]), layout,
    metrics: { widthScale: 1, markerScale: 1, strokePixelScale: 1, fontPixelScale: 1 },
    markerSources: new Map(), polygonShapeIndices: [0], textStrokes: [],
  };
  const target = { _fullLayout: null };
  const snapshots = [];
  const Plotly = {
    async restyle(_target, update) {
      trace.line.width = update["line.width"][0];
    },
    async relayout(_target, update) {
      layout.shapes[0].line.width = update["shapes[0].line.width"];
    },
  };

  for (const axesWidth of [500, 250, 750]) {
    target._fullLayout = {
      width: axesWidth, height: axesWidth, margin: { l: 0, r: 0, t: 0, b: 0 },
      xaxis: { domain: [0, 1] }, yaxis: { domain: [0, 1] },
    };
    await runtime._applyScaleCorrection(target, state, Plotly);
    snapshots.push([trace.line.width, layout.shapes[0].line.width]);
  }

  assert.deepEqual(snapshots, [[2, 3], [1, 1.5], [3, 4.5]]);
});

test("scale correction indexes traces after optional-layer placeholders", async () => {
  const runtime = await loadRuntime(["starplot-scene-loader.js", "plotly-scene-adapter.js"]);
  const optional = layer("optional", "line", 0, { width: 2, color: "#888" });
  optional.required = false;
  const good = layer("good", "line", 1, { width: 2, color: "#fff" });
  const scene = {
    viewport: {
      data_bounds: { x_min: 0, x_max: 10, y_min: 0, y_max: 10 },
      source_axes_width: 1000, target_axes_width: 1000, dpi: 72,
      margin: { l: 10, r: 10, t: 10, b: 10, autoexpand: false },
    },
    styles: [], palettes: [], clips: [], layers: [optional, good],
  };
  const source = {
    async loadManifest() { return scene; },
    async *loadLayer(current) {
      if (current.id === "optional") throw new Error("optional failed");
      for (const batch of tables.line().batches) yield batch;
    },
  };
  const calls = { react: [], restyle: [] };
  const Plotly = {
    async react(target, traces, layout) {
      calls.react.push({ traces, layout });
      target._fullLayout = {
        width: 420, height: 420, margin: { l: 10, r: 10, t: 10, b: 10 },
        xaxis: { domain: [0, 1] }, yaxis: { domain: [0, 1] },
      };
    },
    async restyle(_target, update, indices) { calls.restyle.push({ update, indices }); },
    async relayout() {},
  };
  const target = {
    _fullLayout: null,
    getBoundingClientRect() { return { width: 1000, height: 500 }; },
    querySelectorAll() { return []; },
  };

  await runtime.renderScene(target, source, { Plotly });

  assert.equal(calls.react[0].traces[0].meta.starplot_layer_id, "optional");
  assert.equal(calls.react[0].traces[1].meta.starplot_layer_id, "good");
  const lineCorrection = calls.restyle.find((call) => call.update["line.width"]);
  assert.deepEqual(Array.from(lineCorrection.indices), [1]);
});

test("_collectTextStrokes preserves stroke info parallel to annotations array", async () => {
  const runtime = await loadRuntime(["plotly-scene-adapter.js"]);
  // Create a text trace with stroke so textStrokeByAnnotation gets populated
  const textTable = Arrow.tableFromArrays({
    x: new Float64Array([1, 2]), y: new Float64Array([3, 4]), text: ["A", "B"],
    rotation: new Float32Array([0, 0]), x_offset: new Float32Array([0, 0]),
    y_offset: new Float32Array([0, 0]), style_id: new Uint16Array([0, 0]),
  });
  const textLayer = layer("labels", "text", 0, {
    font_size: 12, font_color: "#fff", stroke_color: "#000", stroke_width: 2.0,
  });
  const scene = {
    viewport: { data_bounds: { x_min: 0, x_max: 10, y_min: 0, y_max: 10 } },
    palettes: [], styles: [], clips: [],
  };
  // Pass fontPixelScale so stroke width is scaled
  const fontPixelScale = 100 / 72;
  const trace = runtime.layerToPlotlyTrace(textLayer, textTable, scene, { fontPixelScale });
  const effects = runtime.layerToPlotlyLayoutEffects(trace);
  const layout = { annotations: effects.annotations || [] };
  const strokes = runtime._collectTextStrokes(layout, [effects]);
  assert.equal(strokes.length, 2);
  assert.ok(strokes[0], "first annotation stroke must be collected");
  assert.equal(strokes[0].color, "#000");
  assert.equal(strokes[0].width, 2.0 * fontPixelScale);
  assert.ok(strokes[1], "second annotation stroke must be collected");
});

test("_polygonShapeIndices returns indices of polygon shapes in layout.shapes", async () => {
  const runtime = await loadRuntime(["plotly-scene-adapter.js"]);
  const polygonTable = Arrow.tableFromArrays({
    polygon_id: new Uint32Array([0, 0, 0]), ring_id: new Uint32Array([0, 0, 0]),
    vertex_index: new Uint32Array([0, 1, 2]),
    x: new Float64Array([0, 1, 0]), y: new Float64Array([0, 0, 1]),
  });
  const polygonLayer = layer("horizon", "polygon", 0, {
    edge_width: 1.5, edge_color: "#555", fill_color: "none",
  });
  // Use axes coordinate space so polygonTrace emits shapes (not scatter)
  polygonLayer.coordinate_space = "axes";
  const scene = {
    viewport: { data_bounds: { x_min: 0, x_max: 10, y_min: 0, y_max: 10 } },
    palettes: [], styles: [], clips: [],
  };
  const trace = runtime.layerToPlotlyTrace(polygonLayer, polygonTable, scene);
  const effects = runtime.layerToPlotlyLayoutEffects(trace);
  assert.ok(effects.shapes && effects.shapes.length > 0, "axes-space polygon must produce shapes");
  // Simulate layout.shapes with a pre-existing shape at index 0
  const layout = {
    shapes: [{ type: "rect", line: { width: 1 } }, ...(effects.shapes || [])],
  };
  const indices = runtime._polygonShapeIndices(layout, [effects]);
  assert.ok(indices.length > 0, "polygon shape indices must be found");
  // The polygon shapes start at index 1 (after the pre-existing rect)
  for (const idx of indices) assert.ok(idx >= 1, "indices must skip pre-existing shapes");
  // Verify the shape at that index has a line.width
  for (const idx of indices) assert.ok(layout.shapes[idx].line, "indexed shape must have line");
});

test("Fix 1: annotation strokes are re-applied with corrected scale after restyle", async () => {
  const runtime = await loadRuntime(["starplot-scene-loader.js", "plotly-scene-adapter.js"]);
  const { source } = scaleCorrectionScene({
    sourceAxesWidth: 3600, strokeWidth: 2.0,
  });
  const { Plotly, calls } = mockPlotly({
    layoutWidth: 1280, layoutHeight: 800,
    xDomain: [0.19, 0.81], // triggers scale correction
  });
  // Mock target with querySelectorAll
  const strokeNodes = [];
  const target = {
    _fullLayout: null,
    getBoundingClientRect() { return { width: 1280, height: 800 }; },
    querySelectorAll(sel) {
      if (sel === ".annotation-text") return strokeNodes;
      return [];
    },
  };
  // Create fake annotation text nodes
  strokeNodes.push({ style: {}, textContent: "M42" });
  await runtime.renderScene(target, source, { Plotly });
  // After restyle, the stroke must have been applied to the DOM node
  assert.ok(strokeNodes[0].style.stroke, "stroke color must be set");
  assert.ok(strokeNodes[0].style.strokeWidth, "stroke width must be set");
  assert.equal(strokeNodes[0].style.paintOrder, "stroke fill");
});

test("Fix 2: polygon shape line widths are restyled via relayout", async () => {
  const runtime = await loadRuntime(["starplot-scene-loader.js", "plotly-scene-adapter.js"]);
  const { source } = scaleCorrectionScene({
    sourceAxesWidth: 3600, polygonEdgeWidth: 2.0,
  });
  const { Plotly, calls } = mockPlotly({
    layoutWidth: 1280, layoutHeight: 800,
    // Deliberately differ from the 780px pre-render estimate so this test
    // exercises the post-render fallback rather than the normal no-op path.
    xDomain: [0.25, 0.75],
  });
  const target = {
    _fullLayout: null,
    getBoundingClientRect() { return { width: 1280, height: 800 }; },
    querySelectorAll() { return []; },
  };
  await runtime.renderScene(target, source, { Plotly });
  // Check that a relayout call contains shapes[N].line.width
  const shapeRelayout = calls.relayout.find(u =>
    Object.keys(u).some(k => k.startsWith("shapes[") && k.endsWith(".line.width")),
  );
  assert.ok(shapeRelayout, "polygon shape line widths must be restyled via relayout");
});

test("Fix 3: resize handler is registered and re-corrects on resize", async () => {
  const resizeListeners = [];
  // We need to inject a window with addEventListener into the VM context.
  // loadRuntime spreads extras into the context's `window`, so we add
  // addEventListener directly as a window property.
  const windowExtras = {
    addEventListener(event, handler) { if (event === "resize") resizeListeners.push(handler); },
  };
  const runtime = await loadRuntime(["starplot-scene-loader.js", "plotly-scene-adapter.js"], windowExtras);
  const { source } = scaleCorrectionScene({ sourceAxesWidth: 3600 });
  const { Plotly, calls } = mockPlotly({
    layoutWidth: 1280, layoutHeight: 800,
    xDomain: [0.19, 0.81],
  });
  const target = {
    _fullLayout: null,
    getBoundingClientRect() { return { width: 1280, height: 800 }; },
    querySelectorAll() { return []; },
  };
  await runtime.renderScene(target, source, { Plotly });
  assert.ok(resizeListeners.length > 0, "resize listener must be registered");
  assert.ok(target._starplotResizeHandler, "handler must be stored on target");
  // Simulate resize to a smaller window — should trigger more restyle calls
  const restyleCountBefore = calls.restyle.length;
  const initialFullLayout = target._fullLayout;
  // Update _fullLayout to reflect new smaller size
  target._fullLayout = {
    ...initialFullLayout,
    width: 800, height: 600,
    xaxis: { domain: [0.25, 0.75] }, // smaller axes
    annotations: initialFullLayout.annotations,
  };
  // Trigger resize (debounced — we need to wait)
  for (const listener of resizeListeners) listener();
  await new Promise(resolve => setTimeout(resolve, 200));
  assert.ok(calls.restyle.length > restyleCountBefore, "resize must trigger restyle");
});

test("Fix 4: sceneLayout uses xaxis.scaleanchor='y' matching Python adapter", async () => {
  const runtime = await loadRuntime(["starplot-scene-loader.js", "plotly-scene-adapter.js"]);
  const { source } = scaleCorrectionScene({ sourceAxesWidth: 3600 });
  const { Plotly, calls } = mockPlotly({ layoutWidth: 800, layoutHeight: 800 });
  const target = {
    _fullLayout: null,
    getBoundingClientRect() { return { width: 800, height: 800 }; },
    querySelectorAll() { return []; },
  };
  await runtime.renderScene(target, source, { Plotly });
  const layout = calls.react[0].layout;
  assert.equal(layout.xaxis.scaleanchor, "y", "xaxis must anchor to y (matching Python)");
  assert.equal(layout.xaxis.scaleratio, 1);
  assert.equal(layout.yaxis.scaleanchor, undefined, "yaxis must not have scaleanchor");
});

test("portrait container does not substitute vertical domain height for horizontal scale", async () => {
  const runtime = await loadRuntime(["starplot-scene-loader.js", "plotly-scene-adapter.js"]);
  const { source } = scaleCorrectionScene({ sourceAxesWidth: 3600 });
  // Portrait container 800x1200 with yDomain shrunk
  const { Plotly, calls } = mockPlotly({
    layoutWidth: 800, layoutHeight: 1200,
    xDomain: [0, 1], yDomain: [0.19, 0.81],
  });
  const target = {
    _fullLayout: null,
    getBoundingClientRect() { return { width: 800, height: 1200 }; },
    querySelectorAll() { return []; },
  };
  await runtime.renderScene(target, source, { Plotly });
  assert.equal(
    calls.restyle.length, 0,
    "vertical domain height alone must not trigger horizontal size correction",
  );
});

test("scale correction is skipped when container is already square (no restyle)", async () => {
  const runtime = await loadRuntime(["starplot-scene-loader.js", "plotly-scene-adapter.js"]);
  const { source } = scaleCorrectionScene({ sourceAxesWidth: 3600 });
  // Square container, axes fill the whole area
  const { Plotly, calls } = mockPlotly({
    layoutWidth: 3600, layoutHeight: 3600,
    xDomain: [0, 1], yDomain: [0, 1],
  });
  const target = {
    _fullLayout: null,
    getBoundingClientRect() { return { width: 3600, height: 3600 }; },
    querySelectorAll() { return []; },
  };
  await runtime.renderScene(target, source, { Plotly });
  // No restyle should be needed (difference < 0.01)
  assert.equal(calls.restyle.length, 0, "no restyle when scale is already correct");
  assert.equal(calls.relayout.length, 0, "no relayout when scale is already correct");
});

test("marker sizes are correctly rescaled by the corrected width scale", async () => {
  const runtime = await loadRuntime(["starplot-scene-loader.js", "plotly-scene-adapter.js"]);
  const markerSize = 20;
  const { source } = scaleCorrectionScene({ sourceAxesWidth: 3600, markerSize });
  const { Plotly, calls } = mockPlotly({
    layoutWidth: 1280, layoutHeight: 800,
    // Deliberately differ from the 780px pre-render estimate so this test
    // exercises the post-render fallback rather than the normal no-op path.
    xDomain: [0.25, 0.75],
  });
  const target = {
    _fullLayout: null,
    getBoundingClientRect() { return { width: 1280, height: 800 }; },
    querySelectorAll() { return []; },
  };
  await runtime.renderScene(target, source, { Plotly });
  // Find the marker.size restyle call
  const markerRestyle = calls.restyle.find(c =>
    c.update && c.update["marker.size"] !== undefined,
  );
  assert.ok(markerRestyle, "marker.size must be restyled");
  // The first scatter trace has 2 markers
  const sizes = markerRestyle.update["marker.size"][0];
  assert.ok(Array.isArray(sizes) || ArrayBuffer.isView(sizes), "sizes must be an array");
  // Verify the rescaled value matches the expected formula
  const correctedScale = ((1280 - 20) * 0.5) / 3600;
  // Initial marker size after scatterTrace uses the predicted axes scale.
  // But markerSize in the table is the raw mpl_size; calibrate happens in Python.
  // In JS, size[index] * markerScale is the rendered size.
  // After restyle the source marker size is multiplied by correctedWidthScale.
  // So the restyled value should be size[j] * correctedScale (clamped to >= 1)
  const expectedRaw = markerSize * correctedScale;
  const expected = Math.max(expectedRaw, 1);
  assert.ok(Math.abs(sizes[0] - expected) < 0.01, `marker ${sizes[0]} should match ${expected}`);
});
