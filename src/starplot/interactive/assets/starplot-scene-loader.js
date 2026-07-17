(function (global) {
  "use strict";

  const CURRENT_LOADER_VERSION = [1, 0];
  const HASH_PATTERN = /^sha256:[0-9a-f]{64}$/;
  const STREAM_PREFIX = [255, 255, 255, 255];
  const STREAM_EOS = [255, 255, 255, 255, 0, 0, 0, 0];
  const CANONICAL_COLUMNS = Object.freeze({
    scatter: ["x", "y", "size", "color_index", "opacity", "symbol_index", "object_id", "name", "magnitude", "ra", "dec"],
    line: ["path_id", "vertex_index", "x", "y", "style_id", "object_id"],
    line_collection: ["path_id", "vertex_index", "x", "y", "style_id", "object_id"],
    polygon: ["polygon_id", "ring_id", "vertex_index", "x", "y"],
    text: ["x", "y", "text", "rotation", "x_offset", "y_offset", "style_id", "object_id"],
    gradient: [],
    info_table: ["column", "value", "width", "object_id"],
  });
  const REQUIRED_COLUMNS = Object.freeze({
    scatter: ["x", "y", "size", "color_index", "opacity"],
    line: ["path_id", "vertex_index", "x", "y"],
    line_collection: ["path_id", "vertex_index", "x", "y"],
    polygon: ["polygon_id", "ring_id", "vertex_index", "x", "y"],
    text: ["x", "y", "text", "rotation", "x_offset", "y_offset", "style_id"],
    gradient: [],
    info_table: ["column", "value", "width"],
  });
  const FIELD_TYPES = Object.freeze({
    size: ["Float32"], color_index: ["Uint8", "Uint16"], opacity: ["Float32"],
    symbol_index: ["Uint8"], magnitude: ["Float32"], ra: ["Float64"], dec: ["Float64"],
    path_id: ["Uint32"], vertex_index: ["Uint32"], style_id: ["Uint16"],
    polygon_id: ["Uint32"], ring_id: ["Uint32"], rotation: ["Float32"],
    x_offset: ["Float32"], y_offset: ["Float32"], width: ["Float32"],
    object_id: ["Utf8", "Dictionary<Int32, Utf8>"],
    name: ["Dictionary<Int32, Utf8>"], text: ["Dictionary<Int32, Utf8>"],
    column: ["Dictionary<Int32, Utf8>"], value: ["Dictionary<Int32, Utf8>"],
  });

  function typesForNumpyDtype(dtype) {
    if (typeof dtype !== "string") return null;
    if (/^[<>=|]?[USO][0-9]*$/.test(dtype)) {
      return ["Utf8", "Dictionary<Int32, Utf8>"];
    }
    const match = /^[<>=|]?([biuf])(1|2|4|8)$/.exec(dtype);
    if (!match) return null;
    const [, kind, bytes] = match;
    if (kind === "b" && bytes === "1") return ["Bool"];
    const bits = Number(bytes) * 8;
    if (kind === "i") return [`Int${bits}`];
    if (kind === "u") return [`Uint${bits}`];
    if (kind === "f" && [16, 32, 64].includes(bits)) return [`Float${bits}`];
    return null;
  }

  function arrow() {
    const value = global.Arrow;
    if (!value || !value.RecordBatchReader || !value.Table) {
      throw new Error("Apache Arrow JS 21.1 must be loaded before Starplot Scene");
    }
    return value;
  }

  function parseVersion(value, name) {
    const match = /^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$/.exec(value);
    if (!match) throw new Error(`${name} must use major.minor syntax`);
    return [Number(match[1]), Number(match[2])];
  }

  function validateManifest(manifest) {
    if (!manifest || typeof manifest !== "object" || Array.isArray(manifest)) {
      throw new Error("Scene manifest must be an object");
    }
    const schema = parseVersion(manifest.schema_version, "schema_version");
    if (schema[0] !== 1) {
      throw new Error(`unsupported Scene schema major version ${schema[0]}`);
    }
    const minimum = parseVersion(
      manifest.minimum_loader_version,
      "minimum_loader_version",
    );
    if (
      minimum[0] > CURRENT_LOADER_VERSION[0]
      || (minimum[0] === CURRENT_LOADER_VERSION[0]
        && minimum[1] > CURRENT_LOADER_VERSION[1])
    ) {
      throw new Error(
        `minimum loader version ${manifest.minimum_loader_version} exceeds current loader 1.0`,
      );
    }
    if (!HASH_PATTERN.test(manifest.content_hash)) {
      throw new Error("manifest content hash must be a sha256: digest");
    }
    for (const name of ["layers", "styles", "palettes", "clips"]) {
      if (!Array.isArray(manifest[name])) throw new Error(`manifest ${name} must be an array`);
    }
    const layerIds = new Set();
    for (const layer of manifest.layers) {
      validateLayer(layer);
      if (layerIds.has(layer.id)) throw new Error(`duplicate Scene layer id: ${layer.id}`);
      layerIds.add(layer.id);
    }
    return manifest;
  }

  function validateLayer(layer) {
    if (!layer || typeof layer !== "object") throw new Error("Scene layer must be an object");
    if (typeof layer.id !== "string" || !layer.id) throw new Error("Scene layer id is required");
    if (!Number.isSafeInteger(layer.byte_length) || layer.byte_length < 0) {
      throw new Error(`layer ${layer.id} byte_length must be a nonnegative integer`);
    }
    if (!Number.isSafeInteger(layer.row_count) || layer.row_count < 0) {
      throw new Error(`layer ${layer.id} row_count must be a nonnegative integer`);
    }
    if (!HASH_PATTERN.test(layer.content_hash)) {
      throw new Error(`layer ${layer.id} content hash must be a sha256: digest`);
    }
    if (
      !layer.data_source
      || layer.data_source.format !== "arrow-ipc-stream"
      || typeof layer.data_source.uri !== "string"
      || !layer.data_source.uri
    ) {
      throw new Error(`layer ${layer.id} must declare an Arrow IPC Stream source`);
    }
    return layer;
  }

  async function sha256(bytes) {
    if (!global.crypto || !global.crypto.subtle) {
      throw new Error("Web Crypto SHA-256 is required to validate Scene data");
    }
    const digest = await global.crypto.subtle.digest(
      "SHA-256",
      bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength),
    );
    return "sha256:" + Array.from(new Uint8Array(digest), (value) =>
      value.toString(16).padStart(2, "0")).join("");
  }

  function asBytes(value) {
    if (value instanceof Uint8Array) return value;
    if (value instanceof ArrayBuffer) return new Uint8Array(value);
    if (ArrayBuffer.isView(value)) {
      return new Uint8Array(value.buffer, value.byteOffset, value.byteLength);
    }
    throw new Error("Arrow layer payload must be binary bytes");
  }

  function hasBytesAt(bytes, expected, offset) {
    if (offset < 0 || offset + expected.length > bytes.length) return false;
    return expected.every((value, index) => bytes[offset + index] === value);
  }

  function canonicalJson(value) {
    if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
    if (value && typeof value === "object") {
      return `{${Object.keys(value).sort().map((key) =>
        `${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(",")}}`;
    }
    return JSON.stringify(value);
  }

  function validateSchemaMetadata(schema, layer) {
    const metadata = schema && schema.metadata;
    if (!metadata || typeof metadata.get !== "function" || typeof metadata.size !== "number") {
      throw new Error(`Arrow schema metadata is missing for layer ${layer.id}`);
    }
    const expected = new Map([
      ["starplot_schema_version", "1.0"],
      ["layer_id", layer.id],
      ["kind", layer.kind],
    ]);
    expected.set("coordinate_encoding", layer.coordinate_encoding || {});
    for (const axis of ["x", "y"]) {
      const encoding = layer.coordinate_encoding && layer.coordinate_encoding[axis];
      if (encoding && encoding.kind === "relative-f32") {
        expected.set(`origin_${axis}`, Number(encoding.origin));
        expected.set(`scale_${axis}`, Number(encoding.scale));
      }
    }
    if (metadata.size !== expected.size) {
      throw new Error(`Arrow schema metadata does not match manifest for layer ${layer.id}`);
    }
    for (const [name, expectedValue] of expected) {
      const actual = metadata.get(name);
      let matches;
      if (name === "coordinate_encoding") {
        try {
          matches = canonicalJson(JSON.parse(actual)) === canonicalJson(expectedValue);
        } catch (_error) {
          matches = false;
        }
      } else {
        matches = name.startsWith("origin_") || name.startsWith("scale_")
          ? Number(actual) === expectedValue
          : actual === expectedValue;
      }
      if (!matches) {
        throw new Error(`Arrow schema metadata does not match manifest for layer ${layer.id}: ${name}`);
      }
    }
  }

  function validateArrowSchema(schema, layer) {
    const canonical = CANONICAL_COLUMNS[layer.kind];
    const required = REQUIRED_COLUMNS[layer.kind];
    if (!canonical || !required) throw new Error(`unsupported Scene kind ${layer.kind}`);
    const fields = schema.fields || [];
    const names = fields.map((field) => field.name);
    for (const name of required) {
      if (!names.includes(name)) throw new Error(`Arrow schema for ${layer.kind} is missing ${name}`);
    }
    const known = new Set(canonical);
    const allowedExtensions = new Set(layer.hover_fields || []);
    for (const name of names) {
      if (!known.has(name) && !allowedExtensions.has(name)) {
        throw new Error(`Arrow schema for ${layer.kind} has unsupported field ${name}`);
      }
    }
    const expectedNames = [
      ...canonical.filter((name) => names.includes(name)),
      ...names.filter((name) => !known.has(name)).sort(),
    ];
    if (names.length !== expectedNames.length || names.some((name, index) => name !== expectedNames[index])) {
      throw new Error(`Arrow schema fields are not in canonical ${layer.kind} order`);
    }
    for (const field of fields) {
      const type = String(field.type);
      let expectedTypes = FIELD_TYPES[field.name];
      if (field.name === "x" || field.name === "y") {
        const encoding = layer.coordinate_encoding[field.name];
        expectedTypes = [encoding.kind === "relative-f32" ? "Float32" : "Float64"];
      }
      if (expectedTypes && !expectedTypes.includes(type)) {
        throw new Error(`Arrow schema field ${field.name} has type ${type}; expected ${expectedTypes.join(" or ")}`);
      }
      const metadata = field.metadata;
      if (!metadata || metadata.size !== 1 || typeof metadata.get !== "function" || !metadata.get("numpy_dtype")) {
        throw new Error(`Arrow schema field ${field.name} must contain only numpy_dtype metadata`);
      }
      const numpyDtype = metadata.get("numpy_dtype");
      const numpyTypes = typesForNumpyDtype(numpyDtype);
      if (!numpyTypes || !numpyTypes.includes(type)) {
        throw new Error(
          `Arrow schema field ${field.name} type ${type} does not match NumPy dtype ${numpyDtype}`,
        );
      }
      if (field.nullable && !String(numpyDtype).includes("O")) {
        throw new Error(`Arrow schema field ${field.name} cannot be nullable for dtype ${numpyDtype}`);
      }
      if (!expectedTypes && !/^(Bool|U?Int(8|16|32|64)|Float(16|32|64)|Utf8|Dictionary<Int32, Utf8>)$/.test(type)) {
        throw new Error(`Arrow schema extension field ${field.name} has unsupported type ${type}`);
      }
    }
  }

  function decodeBase64(value) {
    if (typeof value !== "string") throw new Error("inline Arrow payload must be base64 text");
    const decoded = global.atob(value);
    const bytes = new Uint8Array(decoded.length);
    for (let index = 0; index < decoded.length; index += 1) {
      bytes[index] = decoded.charCodeAt(index);
    }
    return bytes;
  }

  function checkedResponse(response, url) {
    if (!response || !response.ok) {
      const status = response && response.status;
      throw new Error(`Scene request failed${status ? ` (${status})` : ""}: ${url}`);
    }
    return response;
  }

  function appendRequest(url, request) {
    if (!request) return url;
    const result = new URL(url);
    for (const [name, value] of Object.entries(request)) {
      if (value !== undefined && value !== null) result.searchParams.set(name, String(value));
    }
    return result.href;
  }

  class BaseSceneSource {
    constructor(options) {
      this.options = options || {};
      this._manifest = null;
    }

    async loadManifest(_signal) {
      throw new Error("loadManifest must be implemented");
    }

    async *_readLayer(_layer, _request, _signal) {
      throw new Error("_readLayer must be implemented");
    }

    async *loadLayer(layer, request, signal) {
      validateLayer(layer);
      const bytes = asBytes(await this._readLayer(layer, request, signal));
      if (bytes.byteLength !== layer.byte_length) {
        throw new Error(`Arrow byte length does not match manifest for layer ${layer.id}`);
      }
      if (await sha256(bytes) !== layer.content_hash) {
        throw new Error(`Arrow SHA-256 does not match manifest for layer ${layer.id}`);
      }
      if (
        !hasBytesAt(bytes, STREAM_PREFIX, 0)
        || !hasBytesAt(bytes, STREAM_EOS, bytes.length - STREAM_EOS.length)
      ) {
        throw new Error(`payload is not a canonical Arrow IPC Stream for layer ${layer.id}`);
      }
      let reader;
      try {
        reader = await arrow().RecordBatchReader.from(bytes);
        await reader.open();
      } catch (error) {
        throw new Error(`invalid Arrow IPC Stream for layer ${layer.id}`, { cause: error });
      }
      validateSchemaMetadata(reader.schema, layer);
      validateArrowSchema(reader.schema, layer);
      let rows = 0;
      for await (const batch of reader) {
        rows += batch.numRows;
        yield batch;
      }
      if (rows !== layer.row_count) {
        throw new Error(`Arrow row count does not match manifest for layer ${layer.id}`);
      }
    }

    async loadObjectDetail(_objectId, _signal) {
      return null;
    }
  }

  class InlineSceneSource extends BaseSceneSource {
    constructor(options) {
      super(options);
      this._layers = (options && options.layers) || {};
    }

    async loadManifest(_signal) {
      if (!this._manifest) this._manifest = validateManifest(this.options.manifest);
      return this._manifest;
    }

    async _readLayer(layer, _request, _signal) {
      if (!Object.prototype.hasOwnProperty.call(this._layers, layer.id)) {
        throw new Error(`inline Arrow payload is missing for layer ${layer.id}`);
      }
      return decodeBase64(this._layers[layer.id]);
    }
  }

  class FetchSceneSource extends BaseSceneSource {
    constructor(options) {
      super(options);
      if (!options || typeof options.baseUrl !== "string" || !options.baseUrl) {
        throw new Error("baseUrl is required");
      }
      this.baseUrl = options.baseUrl.endsWith("/") ? options.baseUrl : `${options.baseUrl}/`;
      this.fetch = options.fetch || global.fetch;
      if (typeof this.fetch !== "function") throw new Error("fetch is required");
    }

    async _fetchManifest(url, signal) {
      const response = checkedResponse(await this.fetch(url, { signal }), url);
      this._manifest = validateManifest(await response.json());
      return this._manifest;
    }

    async _readLayer(layer, request, signal) {
      const url = appendRequest(new URL(layer.data_source.uri, this.baseUrl).href, request);
      const response = checkedResponse(await this.fetch(url, { signal }), url);
      return new Uint8Array(await response.arrayBuffer());
    }
  }

  class StaticSceneSource extends FetchSceneSource {
    async loadManifest(signal) {
      return this._manifest || this._fetchManifest(new URL("manifest.json", this.baseUrl).href, signal);
    }
  }

  class ApiSceneSource extends FetchSceneSource {
    async loadManifest(signal) {
      return this._manifest || this._fetchManifest(new URL("manifest", this.baseUrl).href, signal);
    }

    async loadObjectDetail(objectId, signal) {
      const manifest = await this.loadManifest(signal);
      if (!manifest.capabilities || !manifest.capabilities.catalog_detail) return null;
      const catalogBase = this.options.catalogBaseUrl || new URL("../../catalog/objects/", this.baseUrl).href;
      const url = new URL(encodeURIComponent(objectId), catalogBase).href;
      const response = checkedResponse(await this.fetch(url, { signal }), url);
      return response.json();
    }
  }

  async function collectLayerTable(source, layer, request, signal) {
    const batches = [];
    for await (const batch of source.loadLayer(layer, request, signal)) batches.push(batch);
    return new (arrow().Table)(batches);
  }

  global.StarplotScene = Object.assign(global.StarplotScene || {}, {
    BaseSceneSource,
    InlineSceneSource,
    StaticSceneSource,
    ApiSceneSource,
    collectLayerTable,
    validateManifest,
  });
})(typeof window !== "undefined" ? window : globalThis);
