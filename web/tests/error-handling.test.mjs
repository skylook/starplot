import test from "node:test";
import { assert, loadRuntime, sceneFixture } from "./test-helpers.mjs";

test("loader applies manifest and layer limits before decoding", async () => {
  const fixture = await sceneFixture();
  const runtime = await loadRuntime(["starplot-scene-loader.js"]);
  await assert.rejects(
    new runtime.InlineSceneSource({
      manifest: fixture.manifest, manifestJson: fixture.manifestJson,
      layers: { stars: Buffer.from(fixture.bytes).toString("base64") },
      loaderLimits: { max_manifest_bytes: 1 },
    }).loadManifest(),
    /byte limit/,
  );
  const source = new runtime.InlineSceneSource({
    manifest: fixture.manifest, manifestJson: fixture.manifestJson,
    layers: { stars: Buffer.from(fixture.bytes).toString("base64") },
    loaderLimits: { max_layer_rows: 1 },
  });
  await assert.rejects(source.loadManifest(), /row limit/);
});

test("direct file loads provide safe actionable remediation", async () => {
  const runtime = await loadRuntime(["starplot-scene-loader.js"], { fetch: async () => { throw new Error("must not fetch"); } });
  const source = new runtime.StaticSceneSource({ baseUrl: "file:///tmp/chart.scene/" });
  await assert.rejects(source.loadManifest(), /starplot serve <directory>.*data_mode="inline"/);
});
