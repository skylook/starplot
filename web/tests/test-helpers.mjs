import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";
import { webcrypto } from "node:crypto";
import * as Arrow from "apache-arrow";

export { Arrow, assert };

const PYTHON_FLOAT_FIELDS = new Set([
  "zorder", "origin", "scale", "max_error_pixels",
  "x_min", "x_max", "y_min", "y_max",
]);

function pythonFloat(value) {
  if (Object.is(value, -0)) return "-0.0";
  const source = String(value).toLowerCase();
  let sign = "";
  let unsigned = source;
  if (unsigned.startsWith("-")) { sign = "-"; unsigned = unsigned.slice(1); }
  let digits;
  let exponent;
  if (unsigned.includes("e")) {
    const [coefficient, rawExponent] = unsigned.split("e");
    const [whole, fraction = ""] = coefficient.split(".");
    digits = (whole + fraction).replace(/^0+/, "") || "0";
    exponent = Number(rawExponent) + whole.length - 1;
  } else {
    const [whole, fraction = ""] = unsigned.split(".");
    const combined = whole + fraction;
    const first = combined.search(/[1-9]/);
    if (first < 0) return `${sign}0.0`;
    digits = combined.slice(first).replace(/0+$/, "");
    exponent = whole.length - first - 1;
  }
  if (exponent < -4 || exponent >= 16) {
    const coefficient = digits.length === 1 ? digits : `${digits[0]}.${digits.slice(1)}`;
    return `${sign}${coefficient}e${exponent >= 0 ? "+" : "-"}${String(Math.abs(exponent)).padStart(2, "0")}`;
  }
  const decimal = exponent + 1;
  if (decimal <= 0) return `${sign}0.${"0".repeat(-decimal)}${digits}`;
  if (decimal >= digits.length) return `${sign}${digits}${"0".repeat(decimal - digits.length)}.0`;
  return `${sign}${digits.slice(0, decimal)}.${digits.slice(decimal)}`;
}

function canonicalJson(value, field = null) {
  if (Array.isArray(value)) return `[${value.map((item) => canonicalJson(item)).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key], key)}`).join(",")}}`;
  }
  if (typeof value === "number" && PYTHON_FLOAT_FIELDS.has(field)) return pythonFloat(value);
  return JSON.stringify(value);
}

export async function bindManifestHash(manifest) {
  const value = structuredClone(manifest);
  delete value.content_hash;
  const payload = new TextEncoder().encode(canonicalJson(value) + manifest.layers.map((layer) => layer.content_hash).join(""));
  manifest.content_hash = await sha256(payload);
  return canonicalJson(manifest);
}

function canonicalEncodingJson(value) {
  const number = (item) => Number.isInteger(item) ? `${item}.0` : String(item);
  return `{${Object.keys(value).sort().map((axis) => {
    const item = value[axis];
    return `${JSON.stringify(axis)}:{"kind":${JSON.stringify(item.kind)},"max_error_pixels":${number(item.max_error_pixels)},"origin":${number(item.origin)},"scale":${number(item.scale)}}`;
  }).join(",")}}`;
}

export function tableWithSceneMetadata(columns, { id, kind, coordinateEncoding = {} }) {
  const plainTable = Arrow.tableFromArrays(columns);
  const numpyDtype = (type) => ({
    Float64: "<f8", Float32: "<f4", Uint32: "<u4", Uint16: "<u2", Uint8: "|u1",
  })[String(type)] || (String(type).includes("Utf8") ? "<U1" : "|O");
  const fields = plainTable.schema.fields.map((field, index) => new Arrow.Field(
    field.name,
    field.type,
    plainTable.getChildAt(index).nullCount > 0,
    new Map([["numpy_dtype", numpyDtype(field.type)]]),
  ));
  const schema = new Arrow.Schema(fields, new Map([
    ["starplot_schema_version", "1.0"],
    ["layer_id", id],
    ["kind", kind],
    ["coordinate_encoding", canonicalEncodingJson(coordinateEncoding)],
    ...Object.entries(coordinateEncoding).flatMap(([axis, encoding]) =>
      encoding.kind === "relative-f32"
        ? [[`origin_${axis}`, Number.isInteger(encoding.origin) ? `${encoding.origin}.0` : String(encoding.origin)], [`scale_${axis}`, Number.isInteger(encoding.scale) ? `${encoding.scale}.0` : String(encoding.scale)]]
        : []),
  ]));
  return new Arrow.Table(
    schema,
    plainTable.batches.map((batch) => new Arrow.RecordBatch(schema, batch.data)),
  );
}

export async function loadRuntime(files, extras = {}) {
  const atob = (value) => Buffer.from(value, "base64").toString("binary");
  const btoa = (value) => Buffer.from(value, "binary").toString("base64");
  const window = { Arrow, crypto: webcrypto, atob, btoa, setTimeout, clearTimeout, ...extras };
  window.window = window;
  window.globalThis = window;
  const context = vm.createContext({
    window,
    globalThis: window,
    Arrow,
    crypto: webcrypto,
    TextEncoder,
    TextDecoder,
    URL,
    URLSearchParams,
    Uint8Array,
    Float32Array,
    Float64Array,
    Uint16Array,
    Uint32Array,
    setTimeout,
    clearTimeout,
    atob,
    btoa,
    console,
    ...extras,
  });
  for (const file of files) {
    const source = await readFile(new URL(`../../src/starplot/interactive/assets/${file}`, import.meta.url), "utf8");
    vm.runInContext(source, context, { filename: file });
  }
  return window.StarplotScene;
}

export async function sha256(bytes) {
  const digest = await webcrypto.subtle.digest("SHA-256", bytes);
  return `sha256:${Buffer.from(digest).toString("hex")}`;
}

export async function sceneFixture(columns = {
  x: new Float64Array([1, 2]),
  y: new Float64Array([3, 4]),
  size: new Float32Array([2, 3]),
  color_index: new Uint8Array([0, 1]),
  opacity: new Float32Array([1, 0.5]),
}) {
  const coordinateEncoding = {
    x: { kind: "absolute-f64", origin: 0, scale: 1, max_error_pixels: 0 },
    y: { kind: "absolute-f64", origin: 0, scale: 1, max_error_pixels: 0 },
  };
  const table = tableWithSceneMetadata(columns, {
    id: "stars", kind: "scatter", coordinateEncoding,
  });
  const bytes = Arrow.tableToIPC(table, "stream");
  const layer = {
    id: "stars",
    kind: "scatter",
    group_id: "stars",
    required: true,
    zorder: 5,
    load_priority: 10,
    coordinate_space: "data",
    clip_id: null,
    style_id: "style-stars",
    interactive: false,
    interaction: "none",
    hover_fields: [],
    row_count: table.numRows,
    byte_length: bytes.byteLength,
    content_hash: await sha256(bytes),
    coordinate_encoding: coordinateEncoding,
    data_source: { format: "arrow-ipc-stream", uri: "layers/stars.arrow" },
  };
  const manifest = {
    schema_version: "1.0",
    scene_id: "test-scene",
    content_hash: `sha256:${"0".repeat(64)}`,
    minimum_loader_version: "1.0",
    viewport: { data_bounds: { x_min: 0, x_max: 10, y_min: 0, y_max: 10 } },
    coordinate_spaces: {},
    clips: [],
    styles: [{ id: "style-stars", value: { palette_id: "palette-stars" } }],
    palettes: [{ id: "palette-stars", colors: ["#fff", "#aaa"] }],
    layers: [layer],
    capabilities: {
      viewport_query: false,
      lod: false,
      magnitude_filter: false,
      catalog_detail: false,
      max_batch_rows: 250000,
    },
    extensions: {},
  };
  const manifestJson = await bindManifestHash(manifest);
  return { table, bytes, layer, manifest, manifestJson };
}

export function response(body, { json = false, url = "" } = {}) {
  return {
    ok: true,
    status: 200,
    url,
    async json() { return json ? body : JSON.parse(new TextDecoder().decode(body)); },
    async text() { return typeof body === "string" ? body : JSON.stringify(body); },
    async arrayBuffer() {
      const bytes = body instanceof Uint8Array ? body : new TextEncoder().encode(JSON.stringify(body));
      return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
    },
  };
}
