import test from "node:test";
import {
  assert, bindManifestHash, loadRuntime, response, sceneFixture,
} from "./test-helpers.mjs";

async function detailSource(detailFetch, options = {}) {
  const fixture = await sceneFixture();
  fixture.manifest.capabilities.catalog_detail = true;
  const manifestJson = await bindManifestHash(fixture.manifest);
  const fetch = async (url, requestOptions) => String(url).endsWith("/manifest")
    ? response(manifestJson, { url: String(url) })
    : detailFetch(String(url), requestOptions);
  const runtime = await loadRuntime(["starplot-scene-loader.js"], { fetch });
  return new runtime.ApiSceneSource({
    baseUrl: "https://example.test/api/scenes/example/",
    fetch,
    ...options,
  });
}

function detailResponse(url, value = {}) {
  return {
    ok: true,
    status: 200,
    url,
    headers: { get() { return null; } },
    async text() { return JSON.stringify(value); },
    async json() { return value; },
  };
}

test("object detail loads a bounded JSON response from an allowed endpoint", async () => {
  const requested = [];
  const source = await detailSource((url, options) => {
    requested.push({ url, redirect: options.redirect });
    return detailResponse(url, { id: "M31" });
  }, {
    catalogBaseUrl: "https://catalog.test/objects/",
    allowedDataOrigins: ["https://catalog.test"],
  });
  assert.equal((await source.loadObjectDetail("M31")).id, "M31");
  assert.deepEqual(requested, [{
    url: "https://catalog.test/objects/M31", redirect: "manual",
  }]);
});

test("object detail cannot escape its endpoint through a dot segment", async () => {
  let detailRequests = 0;
  const source = await detailSource((url) => { detailRequests += 1; return detailResponse(url); });
  for (const objectId of ["..", "a/../b", "a\\..\\b", "%2e%2e"]) {
    await assert.rejects(source.loadObjectDetail(objectId), /object detail (URL|ID)/);
  }
  assert.equal(detailRequests, 0);
});

test("object detail rejects unlisted origins and redirects", async () => {
  let detailRequests = 0;
  const external = await detailSource((url) => { detailRequests += 1; return detailResponse(url); }, {
    catalogBaseUrl: "https://elsewhere.test/catalog/objects/",
  });
  await assert.rejects(external.loadObjectDetail("M31"), /origin is not allowed/);
  assert.equal(detailRequests, 0);

  const redirected = await detailSource((_url, options) => {
    assert.equal(options.redirect, "manual");
    return { ok: false, status: 302, type: "opaqueredirect" };
  });
  await assert.rejects(redirected.loadObjectDetail("M31"), /redirect/i);
});

test("object detail enforces a response byte limit before reading", async () => {
  let bodyRead = false;
  const source = await detailSource((url) => ({
    ok: true,
    status: 200,
    url,
    headers: { get(name) { return name === "content-length" ? String(4 * 1024 * 1024 + 1) : null; } },
    async text() { bodyRead = true; return "{}"; },
  }));
  await assert.rejects(source.loadObjectDetail("M31"), /configured byte limit/);
  assert.equal(bodyRead, false);
});

test("object detail caps streamed bodies without a content-length", async () => {
  let canceled = false;
  const source = await detailSource((url) => ({
    ok: true,
    status: 200,
    url,
    headers: { get() { return null; } },
    body: {
      getReader() {
        return {
          async read() { return { done: false, value: new Uint8Array(4 * 1024 * 1024 + 1) }; },
          async cancel() { canceled = true; },
        };
      },
    },
    async text() { throw new Error("streaming response must not fall back to text()"); },
  }));
  await assert.rejects(source.loadObjectDetail("M31"), /configured byte limit/);
  assert.equal(canceled, true);
});
