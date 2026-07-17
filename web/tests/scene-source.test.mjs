import test from "node:test";
import {
  Arrow, assert, bindManifestHash, loadRuntime, response, sceneFixture, sha256, tableWithSceneMetadata,
} from "./test-helpers.mjs";

test("all SceneSources expose one contract and yield validated Arrow RecordBatches", async () => {
  const fixture = await sceneFixture();
  const fetchCalls = [];
  const fetch = async (url) => {
    fetchCalls.push(String(url));
    return String(url).endsWith("manifest") || String(url).endsWith("manifest.json")
      ? response(fixture.manifestJson)
      : response(fixture.bytes);
  };
  const runtime = await loadRuntime(["starplot-scene-loader.js"], { fetch });
  const { InlineSceneSource, StaticSceneSource, ApiSceneSource } = runtime;
  const sources = [
    new InlineSceneSource({
      manifest: fixture.manifest,
      manifestJson: fixture.manifestJson,
      layers: { stars: Buffer.from(fixture.bytes).toString("base64") },
    }),
    new StaticSceneSource({ baseUrl: "https://example.test/chart.scene/", fetch }),
    new ApiSceneSource({ baseUrl: "https://example.test/api/scenes/test-scene", fetch }),
  ];

  for (const source of sources) {
    assert.equal(typeof source.loadManifest, "function");
    assert.equal(typeof source.loadLayer, "function");
    assert.equal(typeof source.loadObjectDetail, "function");
    const manifest = await source.loadManifest();
    const batches = [];
    for await (const batch of source.loadLayer(manifest.layers[0])) batches.push(batch);
    assert.equal(batches.length, 1);
    assert.ok(batches[0] instanceof Arrow.RecordBatch);
    assert.ok(batches[0].getChild("x").toArray() instanceof Float64Array);
    assert.ok(batches[0].getChild("size").toArray() instanceof Float32Array);
  }
  assert.ok(fetchCalls.some((url) => url.endsWith("chart.scene/manifest.json")));
  assert.ok(fetchCalls.some((url) => url.endsWith("api/scenes/test-scene/manifest")));
});

test("all SceneSources reject incompatible manifests and corrupt layer payloads", async () => {
  const fixture = await sceneFixture();
  const runtime = await loadRuntime(["starplot-scene-loader.js"]);
  const badVersion = structuredClone(fixture.manifest);
  badVersion.schema_version = "2.0";
  await assert.rejects(
    new runtime.InlineSceneSource({ manifest: badVersion, layers: {} }).loadManifest(),
    /schema major version/,
  );

  const corrupt = fixture.bytes.slice();
  corrupt[corrupt.length - 1] ^= 1;
  const source = new runtime.InlineSceneSource({
    manifest: fixture.manifest,
    manifestJson: fixture.manifestJson,
    layers: { stars: Buffer.from(corrupt).toString("base64") },
  });
  await source.loadManifest();
  await assert.rejects(async () => {
    for await (const _batch of source.loadLayer(fixture.layer)) { /* consume */ }
  }, /SHA-256/);
});

test("loadLayer combines no batches and preserves abort signals", async () => {
  const fixture = await sceneFixture();
  let receivedSignal;
  const controller = new AbortController();
  const fetch = async (_url, options) => {
    receivedSignal = options.signal;
    return response(fixture.bytes);
  };
  const runtime = await loadRuntime(["starplot-scene-loader.js"], { fetch });
  const source = new runtime.StaticSceneSource({ baseUrl: "https://example.test/", fetch });
  for await (const _batch of source.loadLayer(fixture.layer, {}, controller.signal)) { /* consume */ }
  assert.equal(receivedSignal, controller.signal);
});

test("loader rejects Arrow IPC File containers and streams without canonical EOS", async () => {
  const fixture = await sceneFixture();
  const runtime = await loadRuntime(["starplot-scene-loader.js"]);
  for (const bytes of [
    Arrow.tableToIPC(fixture.table, "file"),
    fixture.bytes.subarray(0, fixture.bytes.length - 8),
  ]) {
    const currentLayer = {
      ...fixture.layer,
      byte_length: bytes.byteLength,
      content_hash: await sha256(bytes),
    };
    const source = new runtime.InlineSceneSource({
      manifest: { ...fixture.manifest, layers: [currentLayer] },
      layers: { stars: Buffer.from(bytes).toString("base64") },
    });
    await assert.rejects(async () => {
      for await (const _batch of source.loadLayer(currentLayer)) { /* consume */ }
    }, /canonical Arrow IPC Stream/);
  }
});

function layerForTable(id, kind, table, coordinateEncoding = {}) {
  return {
    id, kind, group_id: id, required: true, zorder: 0, load_priority: 0,
    coordinate_space: "data", clip_id: null, style_id: null,
    interactive: false, interaction: "none", hover_fields: [],
    row_count: table.numRows, byte_length: 0, content_hash: `sha256:${"0".repeat(64)}`,
    coordinate_encoding: coordinateEncoding,
    data_source: { format: "arrow-ipc-stream", uri: `${id}.arrow` },
  };
}

async function inlineLayerFixture(id, kind, columns, coordinateEncoding = {}) {
  const table = tableWithSceneMetadata(columns, { id, kind, coordinateEncoding });
  const bytes = Arrow.tableToIPC(table, "stream");
  const layer = {
    ...layerForTable(id, kind, table, coordinateEncoding),
    byte_length: bytes.byteLength,
    content_hash: await sha256(bytes),
  };
  return { table, bytes, layer };
}

test("loader accepts canonical Task 6 schemas for every Scene kind", async () => {
  const runtime = await loadRuntime(["starplot-scene-loader.js"]);
  const dictionary = (values) => Arrow.vectorFromArray(
    values, new Arrow.Dictionary(new Arrow.Utf8(), new Arrow.Int32()),
  );
  const xy = {
    x: { kind: "absolute-f64", origin: 0, scale: 1, max_error_pixels: 0 },
    y: { kind: "absolute-f64", origin: 0, scale: 1, max_error_pixels: 0 },
  };
  const cases = [
    ["scatter", { x: new Float64Array([0]), y: new Float64Array([0]), size: new Float32Array([1]), color_index: new Uint8Array([0]), opacity: new Float32Array([1]) }, xy],
    ["line", { path_id: new Uint32Array([0]), vertex_index: new Uint32Array([0]), x: new Float64Array([0]), y: new Float64Array([0]) }, xy],
    ["line_collection", { path_id: new Uint32Array([0]), vertex_index: new Uint32Array([0]), x: new Float64Array([0]), y: new Float64Array([0]) }, xy],
    ["polygon", { polygon_id: new Uint32Array([0]), ring_id: new Uint32Array([0]), vertex_index: new Uint32Array([0]), x: new Float64Array([0]), y: new Float64Array([0]) }, xy],
    ["text", { x: new Float64Array([0]), y: new Float64Array([0]), text: dictionary(["A"]), rotation: new Float32Array([0]), x_offset: new Float32Array([0]), y_offset: new Float32Array([0]), style_id: new Uint16Array([0]) }, xy],
    ["gradient", {}, {}],
    ["info_table", { column: dictionary(["RA"]), value: dictionary(["1h"]), width: new Float32Array([1]) }, {}],
  ];
  for (const [kind, columns, encoding] of cases) {
    const fixture = await inlineLayerFixture(kind, kind, columns, encoding);
    const source = new runtime.InlineSceneSource({
      manifest: { schema_version: "1.0", minimum_loader_version: "1.0", content_hash: `sha256:${"0".repeat(64)}`, layers: [fixture.layer], styles: [], palettes: [], clips: [] },
      layers: { [kind]: Buffer.from(fixture.bytes).toString("base64") },
    });
    let rows = 0;
    for await (const batch of source.loadLayer(fixture.layer)) rows += batch.numRows;
    assert.equal(rows, fixture.table.numRows, kind);
  }
});

test("loader rejects wrong Arrow field order, type, and nullability", async () => {
  const runtime = await loadRuntime(["starplot-scene-loader.js"]);
  const xy = {
    x: { kind: "absolute-f64", origin: 0, scale: 1, max_error_pixels: 0 },
    y: { kind: "absolute-f64", origin: 0, scale: 1, max_error_pixels: 0 },
  };
  const invalidColumns = [
    { y: new Float64Array([0]), x: new Float64Array([0]), size: new Float32Array([1]), color_index: new Uint8Array([0]), opacity: new Float32Array([1]) },
    { x: new Float64Array([0]), y: new Float64Array([0]), size: new Float64Array([1]), color_index: new Uint8Array([0]), opacity: new Float32Array([1]) },
    { x: [0, null], y: new Float64Array([0, 1]), size: new Float32Array([1, 1]), color_index: new Uint8Array([0, 0]), opacity: new Float32Array([1, 1]) },
  ];
  for (const [index, columns] of invalidColumns.entries()) {
    const fixture = await inlineLayerFixture(`bad-${index}`, "scatter", columns, xy);
    const source = new runtime.InlineSceneSource({
      manifest: { schema_version: "1.0", minimum_loader_version: "1.0", content_hash: `sha256:${"0".repeat(64)}`, layers: [fixture.layer], styles: [], palettes: [], clips: [] },
      layers: { [fixture.layer.id]: Buffer.from(fixture.bytes).toString("base64") },
    });
    await assert.rejects(async () => {
      for await (const _batch of source.loadLayer(fixture.layer)) { /* consume */ }
    }, /Arrow (?:schema|field)/);
  }

  const valid = tableWithSceneMetadata({
    x: new Float64Array([0]), y: new Float64Array([0]),
    size: new Float32Array([1]), color_index: new Uint8Array([0]),
    opacity: new Float32Array([1]),
  }, {
    id: "bad-metadata", kind: "scatter", coordinateEncoding: xy,
  });
  const fields = valid.schema.fields.map((field) => new Arrow.Field(
    field.name,
    field.type,
    field.nullable,
    field.name === "size" ? new Map([["numpy_dtype", "<f8"]]) : field.metadata,
  ));
  const schema = new Arrow.Schema(fields, valid.schema.metadata);
  const wrongDtypeTable = new Arrow.Table(
    schema,
    valid.batches.map((batch) => new Arrow.RecordBatch(schema, batch.data)),
  );
  const bytes = Arrow.tableToIPC(wrongDtypeTable, "stream");
  const wrongDtypeLayer = {
    ...layerForTable("bad-metadata", "scatter", wrongDtypeTable, xy),
    byte_length: bytes.byteLength,
    content_hash: await sha256(bytes),
  };
  const source = new runtime.InlineSceneSource({
    manifest: {
      schema_version: "1.0", minimum_loader_version: "1.0",
      content_hash: `sha256:${"0".repeat(64)}`, layers: [wrongDtypeLayer],
      styles: [], palettes: [], clips: [],
    },
    layers: { "bad-metadata": Buffer.from(bytes).toString("base64") },
  });
  await assert.rejects(async () => {
    for await (const _batch of source.loadLayer(wrongDtypeLayer)) { /* consume */ }
  }, /does not match NumPy dtype/);
});

test("loader binds Arrow schema metadata to manifest layer identity and encoding", async () => {
  const fixture = await sceneFixture();
  const runtime = await loadRuntime(["starplot-scene-loader.js"]);
  for (const mutation of [
    (layer) => ({ ...layer, id: "other" }),
    (layer) => ({ ...layer, kind: "line" }),
    (layer) => ({
      ...layer,
      coordinate_encoding: {
        ...layer.coordinate_encoding,
        x: { kind: "relative-f32", origin: 10, scale: 2, max_error_pixels: 0.01 },
      },
    }),
  ]) {
    const layer = mutation(fixture.layer);
    const source = new runtime.InlineSceneSource({
      manifest: { ...fixture.manifest, layers: [layer] },
      layers: { [layer.id]: Buffer.from(fixture.bytes).toString("base64") },
    });
    await assert.rejects(async () => {
      for await (const _batch of source.loadLayer(layer)) { /* consume */ }
    }, /schema metadata/);
  }
});

test("manifest validation enforces the Python wire model and ordered self-hash", async () => {
  const fixture = await sceneFixture();
  const runtime = await loadRuntime(["starplot-scene-loader.js"]);
  for (const mutate of [
    (manifest) => { manifest.extra = true; },
    (manifest) => { delete manifest.capabilities.lod; },
    (manifest) => { manifest.layers[0].interaction = "hover"; },
    (manifest) => { manifest.layers[0].coordinate_encoding.x.scale = 0; },
    (manifest) => { manifest.extensions.future = true; },
    (manifest) => { manifest.styles[0].id = "other"; },
  ]) {
    const manifest = structuredClone(fixture.manifest);
    mutate(manifest);
    const manifestJson = await bindManifestHash(manifest);
    await assert.rejects(
      new runtime.InlineSceneSource({ manifest, manifestJson, layers: {} }).loadManifest(),
      /fields|interaction|encoding|extension|style id/,
    );
  }
  const stale = structuredClone(fixture.manifest);
  stale.layers[0].content_hash = `sha256:${"1".repeat(64)}`;
  const staleJson = fixture.manifestJson.replace(fixture.layer.content_hash, stale.layers[0].content_hash);
  await assert.rejects(
    new runtime.InlineSceneSource({ manifest: stale, manifestJson: staleJson, layers: {} }).loadManifest(),
    /scene content hash/,
  );
});

test("manifest text must be exact Python-canonical JSON before self-hashing", async () => {
  const fixture = await sceneFixture();
  const runtime = await loadRuntime(["starplot-scene-loader.js"]);
  assert.match(fixture.manifestJson, /"zorder":5\.0/);
  assert.match(fixture.manifestJson, /"origin":0\.0/);
  for (const mutation of [
    (text) => ` ${text}`,
    () => JSON.stringify(fixture.manifest),
    (text) => text.replace('"zorder":5.0', '"zorder":5'),
    (text) => text.replace('"load_priority":10', '"load_priority":10.0'),
  ]) {
    await assert.rejects(
      new runtime.InlineSceneSource({
        manifest: fixture.manifest,
        manifestJson: mutation(fixture.manifestJson),
        layers: {},
      }).loadManifest(),
      /Python-canonical manifest JSON/,
    );
  }

  const escaped = structuredClone(fixture.manifest);
  escaped.scene_id = "café";
  const escapedJson = await bindManifestHash(escaped);
  assert.match(escapedJson, /café/);
  await new runtime.InlineSceneSource({
    manifest: escaped,
    manifestJson: escapedJson,
    layers: {},
  }).loadManifest();
  await assert.rejects(
    new runtime.InlineSceneSource({
      manifest: escaped,
      manifestJson: escapedJson.replace("café", "caf\\u00e9"),
      layers: {},
    }).loadManifest(),
    /Python-canonical manifest JSON/,
  );

  const exponent = structuredClone(fixture.manifest);
  exponent.layers[0].coordinate_encoding.x.max_error_pixels = 1e-7;
  const exponentJson = await bindManifestHash(exponent);
  assert.match(exponentJson, /1e-07/);
  await assert.rejects(
    new runtime.InlineSceneSource({
      manifest: exponent,
      manifestJson: exponentJson.replace("1e-07", "1e-7"),
      layers: {},
    }).loadManifest(),
    /Python-canonical manifest JSON/,
  );
});

test("loader rejects a second valid Arrow stream and noncanonical metadata bytes", async () => {
  const fixture = await sceneFixture();
  const runtime = await loadRuntime(["starplot-scene-loader.js"]);
  const concatenated = new Uint8Array(fixture.bytes.length * 2);
  concatenated.set(fixture.bytes); concatenated.set(fixture.bytes, fixture.bytes.length);
  const layer = { ...fixture.layer, byte_length: concatenated.length, content_hash: await sha256(concatenated) };
  const source = new runtime.InlineSceneSource({ manifest: fixture.manifest, manifestJson: fixture.manifestJson, layers: { stars: Buffer.from(concatenated).toString("base64") } });
  await assert.rejects(async () => {
    for await (const _batch of source.loadLayer(layer)) { /* consume */ }
  }, /one exact canonical Arrow IPC Stream/);

  const schema = new Arrow.Schema(fixture.table.schema.fields, new Map([
    ...fixture.table.schema.metadata,
    ["coordinate_encoding", JSON.stringify(fixture.layer.coordinate_encoding)],
  ]));
  const table = new Arrow.Table(schema, fixture.table.batches.map((batch) => new Arrow.RecordBatch(schema, batch.data)));
  const bytes = Arrow.tableToIPC(table, "stream");
  const metadataLayer = { ...fixture.layer, byte_length: bytes.length, content_hash: await sha256(bytes) };
  const metadataSource = new runtime.InlineSceneSource({ manifest: fixture.manifest, manifestJson: fixture.manifestJson, layers: { stars: Buffer.from(bytes).toString("base64") } });
  await assert.rejects(async () => {
    for await (const _batch of metadataSource.loadLayer(metadataLayer)) { /* consume */ }
  }, /schema metadata/);
});

test("fetch sources resolve document, root, and manifest-relative URLs", async () => {
  const fixture = await sceneFixture();
  const calls = [];
  const fetch = async (url) => {
    calls.push(String(url));
    return String(url).endsWith("manifest.json") ? response(fixture.manifestJson) : response(fixture.bytes);
  };
  const runtime = await loadRuntime(["starplot-scene-loader.js"], { fetch });
  const source = new runtime.StaticSceneSource({ baseUrl: "../scene", documentBaseUrl: "https://example.test/charts/page.html", fetch });
  const manifest = await source.loadManifest();
  for await (const _batch of source.loadLayer(manifest.layers[0])) { /* consume */ }
  assert.deepEqual(calls, [
    "https://example.test/scene/manifest.json",
    "https://example.test/scene/layers/stars.arrow",
  ]);
  const root = new runtime.StaticSceneSource({ baseUrl: "/assets/scene", documentBaseUrl: "https://example.test/charts/page.html", fetch });
  await root.loadManifest();
  assert.equal(calls.at(-1), "https://example.test/assets/scene/manifest.json");
});

test("fetch sources resolve layer URLs from the final redirected manifest URL", async () => {
  const fixture = await sceneFixture();
  const calls = [];
  const fetch = async (url) => {
    calls.push(String(url));
    return calls.length === 1
      ? response(fixture.manifestJson, { url: "https://cdn.example.test/scenes/final/manifest.json" })
      : response(fixture.bytes);
  };
  const runtime = await loadRuntime(["starplot-scene-loader.js"], { fetch });
  const source = new runtime.StaticSceneSource({ baseUrl: "https://example.test/original/", fetch });
  const manifest = await source.loadManifest();
  for await (const _batch of source.loadLayer(manifest.layers[0])) { /* consume */ }
  assert.deepEqual(calls, [
    "https://example.test/original/manifest.json",
    "https://cdn.example.test/scenes/final/layers/stars.arrow",
  ]);
});
