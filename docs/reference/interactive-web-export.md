# Interactive web export

`starplot.interactive` keeps Matplotlib as the geometry authority, then records its
final projected coordinates and styles. The same recorded drawing commands drive
`to_plotly()`, the `ScenePackage` compiled by `export_html()`, inline HTML,
external bundles, and remote API responses.

Install the optional dependency before using Plotly output:

```bash
pip install "starplot[interactive]"
```

## Quick start

All interactive plot classes (`InteractiveMapPlot`, `InteractiveZenithPlot`,
`InteractiveHorizonPlot`, `InteractiveOpticPlot`) are drop-in replacements for
their Matplotlib counterparts and add two methods:

- `to_plotly()` — return a `plotly.graph_objects.Figure` for notebooks or
  further customisation.
- `export_html()` — write a self-contained or backend-driven HTML file.

```python
from starplot import Miller, _
from starplot.interactive import InteractiveMapPlot
from starplot.styles import PlotStyle, extensions

p = InteractiveMapPlot(
    projection=Miller(),
    ra_min=60, ra_max=120,
    dec_min=-10, dec_max=30,
    style=PlotStyle().extend(extensions.BLUE_LIGHT, extensions.MAP),
)
p.stars(where=[_.magnitude < 8])
p.constellations()

# Static Matplotlib PNG (unchanged)
p.export("chart.png")

# Plotly Figure for a notebook
fig = p.to_plotly()

# Interactive HTML — see sections below for mode details
p.export_html("chart.html")
```

## 1. Notebook use with `to_plotly()`

`to_plotly()` returns a standard `plotly.graph_objects.Figure` rendered from the
same recorded drawing commands used by `export_html()`. You can call `fig.show()`
in a Jupyter notebook, add traces, or save it with Plotly's own `write_html()`.

```python
from starplot.interactive import InteractiveMapPlot

p = InteractiveMapPlot(...)
p.stars(where=[_.magnitude < 8])
p.constellations()

fig = p.to_plotly(width=1400, height=900)
fig.show()
```

## 2. External bundle — default

`export_html("chart.html")` writes two items:

- `chart.html` — a small HTML shell.
- `chart.scene/` — a directory with `manifest.json`, `palettes.json`, and
  content-hashed Arrow IPC Stream layer files.

The HTML must be served over HTTP. Use the bundled CLI:

```bash
starplot serve . --port 8000
```

Then open `http://127.0.0.1:8000/chart.html`. `starplot serve` is only a local
development convenience; in production, copy `chart.scene/` to your static
assets directory and serve it with any HTTP server.

```python
p.export_html("chart.html", width=1400, height=900)
```

## 3. Inline single file

If you need one file that can be opened directly from `file://`, or emailed, or
placed in a static directory without a sidecar `.scene/` directory, use
`data_mode="inline"`.

```python
p.export_html("chart.html", data_mode="inline", width=1400, height=900)
```

This embeds the manifest and all Arrow layer bytes as inert base64 `<script>`
tags. The file is larger but self-contained and offline-capable.

## 4. Library loading modes

The Plotly and Arrow JavaScript can be delivered in three ways. The choice is
independent of the data mode.

| `library_mode` | Data mode | Needs network | Use case |
|---|---|---|---|
| `cdn` | any | Yes, on first open | Smallest file, fast local tests, served sites with internet |
| `directory` | `external` only | No | External bundle that includes vendored libraries beside `.scene/` |
| `inline` | any | No | Largest, fully offline, works behind air-gaps or strict CSPs |

```python
# External bundle with local libraries (chart.scene/ also contains vendor files)
p.export_html("chart.html", data_mode="external", library_mode="directory")

# Inline data + inline libraries: one completely self-contained file
p.export_html("chart.html", data_mode="inline", library_mode="inline")

# Remote data + CDN libraries: small HTML shell, live data from your API
p.export_html(
    "chart.html",
    data_mode="remote",
    data_url="https://api.example.com/scenes/orion/manifest.json",
    library_mode="cdn",
)
```

If you do not pass `library_mode`, `external` and `remote` default to `cdn`, and
`inline` defaults to `inline`.

## 5. Embedding in a web page

The generated HTML is a full page, so the simplest and safest integration is an
`<iframe>`:

```html
<iframe
  src="/starplot/orion.html"
  width="100%"
  height="600"
  style="border: none;"
  allow="fullscreen"
></iframe>
```

For `external` mode, the parent page and the iframe must share the same origin
or you must serve `Access-Control-Allow-Origin` headers for the `.scene/`
directory. For `inline` mode, no extra origin rules apply.

## 6. Remote backend integration

`data_mode="remote"` keeps the HTML shell small and fetches the manifest and
layers from a `data_url` you control. This is the right choice when:

- The scene is large and you want to cache layers separately.
- You want to serve detail data on demand.
- You want to reuse one manifest URL from many pages.

### 6.1 Export the client HTML

```python
p.export_html(
    "orion-remote.html",
    data_mode="remote",
    data_url="https://api.example.com/scenes/orion/manifest.json",
    allowed_data_origins=(),  # only the manifest origin is allowed by default
)
```

The `data_url` must be an absolute `http(s)` URL and end with the manifest
filename, for example `.../scenes/orion/manifest.json`. Layer URLs are resolved
relative to that manifest URL.

`allowed_data_origins` is an optional tuple of extra origins if your layer files
are hosted on a CDN or a separate asset domain. The manifest origin is always
allowed automatically.

### 6.2 Serve the Scene with a minimal Flask app

The Python side is framework-neutral: `SceneProvider` returns status, headers,
and body bytes. The example below uses Flask, but the same pattern works in
FastAPI, Django, or any WSGI/ASGI server.

```python
from flask import Flask, request, Response
from starplot import Miller, _
from starplot.interactive import (
    InteractiveMapPlot,
    SceneProvider,
    ViewportRequest,
    parse_scene_manifest,
)
from starplot.styles import PlotStyle, extensions

app = Flask(__name__)


def build_scene_provider():
    p = InteractiveMapPlot(
        projection=Miller(),
        ra_min=3.6 * 15, ra_max=7.8 * 15,
        dec_min=-15, dec_max=25,
        style=PlotStyle().extend(extensions.BLUE_LIGHT, extensions.MAP),
        resolution=4096,
        autoscale=True,
    )
    p.stars(where=[_.magnitude < 8])
    p.constellations()

    # Export to get canonical manifest and layer bytes. data_mode is external
    # only because that gives us the bundle bytes; the client HTML is remote.
    export = p.export_html("orion.html", data_mode="external")
    manifest = parse_scene_manifest(export.manifest_bytes)
    provider = SceneProvider(manifest, export.manifest_bytes, export.layer_bytes)

    # Build a uri -> layer_id lookup. The JavaScript loader requests
    # layer files by their manifest data_source.uri.
    uri_to_id = {layer.data_source.uri: layer.id for layer in manifest.layers}

    return provider, uri_to_id


PROVIDER, URI_TO_ID = build_scene_provider()


def _viewport_request(args):
    """Convert the JavaScript loader's query string into a ViewportRequest."""
    def maybe(name, conv):
        v = args.get(name)
        return conv(v) if v is not None else None

    try:
        req = ViewportRequest(
            x_min=maybe("x_min", float),
            x_max=maybe("x_max", float),
            y_min=maybe("y_min", float),
            y_max=maybe("y_max", float),
            pixel_width=maybe("pixel_width", int),
            pixel_height=maybe("pixel_height", int),
            lod=maybe("lod", int),
            magnitude_max=maybe("magnitude_max", float),
            point_budget=maybe("point_budget", int),
        )
    except (ValueError, TypeError):
        return None

    return None if req.is_full else req


@app.route("/scenes/<scene_id>/manifest.json")
def manifest(scene_id):
    if scene_id != "orion":
        return Response("Not found", status=404)
    resp = PROVIDER.manifest(request.headers.get("If-None-Match"))
    return Response(resp.body_bytes(), status=resp.status, headers=dict(resp.headers))


@app.route("/scenes/<scene_id>/<path:layer_uri>")
def layer(scene_id, layer_uri):
    if scene_id != "orion":
        return Response("Not found", status=404)
    layer_id = URI_TO_ID.get(layer_uri)
    if layer_id is None:
        return Response("Layer not found", status=404)

    viewport = _viewport_request(request.args)
    resp = PROVIDER.layer(
        layer_id,
        viewport,
        request.headers.get("If-None-Match"),
    )
    return Response(resp.body_bytes(), status=resp.status, headers=dict(resp.headers))


@app.route("/scenes/<scene_id>/detail/<object_id>")
def detail(scene_id, object_id):
    if scene_id != "orion":
        return Response("Not found", status=404)
    resp = PROVIDER.object_detail(object_id)
    return Response(resp.body_bytes(), status=resp.status, headers=dict(resp.headers))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000)
```

Three things to notice:

1. **Manifest origin is always allowed.** The JavaScript loader rejects layer
   URLs that are not on the manifest origin or in `allowed_data_origins`.
2. **Viewport query parameters.** When the Scene advertises viewport support,
   the loader appends `x_min`, `x_max`, `y_min`, `y_max`, `pixel_width`,
   `pixel_height`, `lod`, `magnitude_max`, and `point_budget`. Pass the subset
   your `LodPolicy` uses to `SceneProvider.layer()`. If no query parameters are
   present, pass `None` to receive the complete layer.
3. **Bytes, not JSON.** `SceneResponse.body_bytes()` is already the correct
   bytes for the response. Do not `json.dumps()` the manifest again; that would
   break the canonical byte contract.

### 6.3 CORS

If the client HTML and the API live on different origins, add CORS headers to
all three endpoints. For example with `flask-cors`:

```python
from flask_cors import CORS

CORS(app, origins=["https://your-frontend.example.com"])
```

You can also set the headers manually:

```python
headers = dict(resp.headers)
headers["Access-Control-Allow-Origin"] = "https://your-frontend.example.com"
```

## 7. Security and CSP

The exported HTML includes a `Content-Security-Policy` meta tag. With the
default `library_mode="cdn"` it is approximately:

```
default-src 'self';
script-src 'self' 'nonce-<nonce>' 'unsafe-eval' https://cdn.jsdelivr.net;
style-src 'self' 'unsafe-inline';
img-src 'self' blob:;
connect-src 'self' https://cdn.jsdelivr.net <your-data-origins>;
```

`style-src 'unsafe-inline'` is required by Plotly 6.x for the mode bar and hover
labels. If you need a stricter CSP, use `library_mode="inline"` so all
JavaScript and CSS are embedded and served from your own origin, then tighten
`script-src` and `style-src` accordingly.

For `data_mode="remote"`, make sure `connect-src` includes the manifest origin
and any `allowed_data_origins`.

## 8. API reference

### `Interactive*Plot.export_html(...)`

```python
plot.export_html(
    filename: str,
    width: int | None = None,
    height: int | None = None,
    transparent: bool = False,
    data_mode: str = "external",          # "external" | "inline" | "remote"
    library_mode: str | None = None,       # "cdn" | "directory" | "inline"
    data_url: str | None = None,             # required for remote
    allowed_data_origins: tuple[str, ...] = (), # extra layer origins for remote
)
```

Returns an `ExportResult` with `html_path`, `bundle_path`, `manifest_bytes`,
`layer_bytes`, and `scene_hash`.

### `export_scene_html(...)`

If you already have a `ScenePackage` (for example, one shared by a CLI tool and
a web API), call `export_scene_html()` directly:

```python
from starplot.interactive.web_export import export_scene_html

result = export_scene_html(
    scene,
    "chart.html",
    data_mode="remote",
    data_url="https://api.example.com/scenes/orion/manifest.json",
)
```

### `SceneProvider`

```python
from starplot.interactive import SceneProvider, parse_scene_manifest

provider = SceneProvider(manifest, manifest_bytes, layer_bytes)
provider.manifest(if_none_match=None)
provider.layer(layer_id, request=None, if_none_match=None)
provider.object_detail(object_id)
```

Use `parse_scene_manifest()` to turn `manifest_bytes` into the Pydantic model
`SceneProvider` expects.

## 9. Complete end-to-end examples

The repository includes two runnable examples that cover all the modes above:

- `examples/interactive/export_html_modes.py` — generates `external`,
  `inline`, `remote`, and Plotly Figure outputs from the same Orion scene.
- `examples/interactive/remote_provider_server.py` — a self-contained
  `http.server` remote provider that serves the `remote` client HTML, manifest,
  and layers.

The existing 22 examples under `examples/interactive/` show every supported plot
family (`map`, `horizon`, `optic`, `zenith`) and are kept visually in sync with
their Matplotlib counterparts.

## 10. Common issues

| Symptom | Cause | Fix |
|---|---|---|
| Blank page, `file://` with external mode | External bundles cannot be loaded from `file://` because of `fetch()` CORS | Use `data_mode="inline"` or serve over HTTP |
| Plotly/Arrow libraries fail to load from their CDN | `script-src` CSP missing the library CDN origin | Add the CDN origin to `script-src`, or use `library_mode="inline"` / `library_mode="directory"` |
| `data_url` rejected | It must be absolute `http(s)` with no fragment or userinfo | Use `https://host/path/manifest.json` |
| Remote layer data fails to load from a separate origin | `connect-src` CSP missing data origin or the origin is not in `allowed_data_origins` | Add the data origin to `allowed_data_origins` and to `connect-src` |
| Remote layers 404 | The requested URI does not match any `data_source.uri` | Map the URL path to the correct layer id using the manifest |
| Hover not working | The layer uses `InteractionPolicy.NONE` | Use `hover` or `hover-and-detail` when building the Scene; this is automatic for star/object layers in `Interactive*Plot` |
