# Interactive web export

`starplot.interactive` keeps Matplotlib as the geometry authority, then
compiles its final projected coordinates and styles into an immutable Scene.
The same Scene drives `to_plotly()`, inline HTML, external bundles, and remote
API responses. Install the optional dependency before using Plotly output:

```bash
pip install "starplot[interactive]"
```

## Export modes

Use an interactive plot class and draw it normally. `to_plotly()` returns a
`plotly.graph_objects.Figure`; `export_html()` writes a browser chart.

```python
plot.export_html("chart.html")  # chart.html + chart.scene/, serve over HTTP
plot.export_html("chart-inline.html", data_mode="inline")  # direct file://
plot.export_html(
    "chart-api.html",
    data_mode="remote",
    data_url="https://example.org/api/scenes/orion",
)
figure = plot.to_plotly()
```

`external` is the default. It places `manifest.json` and content-hashed Arrow
IPC Stream layer files in `chart.scene/`, leaving the HTML shell small. Serve a
directory containing an external export locally with:

```bash
starplot serve . --port 8000
```

The server binds to `127.0.0.1` by default. Pass `--no-open` for scripts or
CI. `inline` embeds the same manifest and Arrow stream bytes in inert script
tags, so it is the appropriate explicit single-file choice. `remote` fetches a
manifest URL; its layer URLs are allowed only from the manifest origin unless
you explicitly pass `allowed_data_origins`.

## Remote providers

`SceneProvider` is framework-neutral. Construct it from an exported Scene and
copy its bytes-oriented response into your framework response without JSON
re-encoding the manifest or Arrow stream:

```python
from starplot.interactive import SceneProvider, parse_scene_manifest

manifest = parse_scene_manifest(export_result.manifest_bytes)
provider = SceneProvider(manifest, export_result.manifest_bytes, export_result.layer_bytes)

def manifest_endpoint(request):
    scene_response = provider.manifest(request.headers.get("If-None-Match"))
    return Response(
        scene_response.body_bytes(),
        status=scene_response.status,
        headers=dict(scene_response.headers),
    )
```

Route layer and detail endpoints similarly with `provider.layer(layer_id,
request, if_none_match)` and `provider.object_detail(object_id)`. Preserve
status, headers, and body exactly: `ETag`, `Content-Length`, content type,
schema version, and cache policy are part of the transport contract.

## Coordinates, hover, and detail

Catalog RA/Dec remains semantic catalog authority. Scene `x`/`y` are the final
projected coordinates and are the only browser rendering authority; clients do
not reproject catalog coordinates.

Interaction is declared per layer:

- `none` has no per-row hover or detail data.
- `hover` exposes only compact manifest-declared hover fields.
- `hover-and-detail` adds a stable `object_id`; full catalog detail is resolved
  lazily through the provider's detail callback.

This prevents a rendered chart from retaining or leaking whole catalog rows.

## Viewport and failure behavior

When a manifest advertises viewport support, the loader debounces requests,
cancels obsolete requests, and accepts only the latest response. The provider
filters final Scene x/y and applies declared LOD policies; full-resolution
requests return the exact complete-layer bytes.

The loader enforces manifest, layer, row, string, and geometry-depth limits;
checks hashes and lengths before rendering; rejects unsafe URLs and unexpected
origins; and renders text as text rather than HTML. A failed required layer is
shown as a visible error. Optional-layer failures remain warnings with a retry
action rather than silently changing the chart.

Static and remote delivery use the same browser loader and Plotly adapter, so
their decoded Scene values and rendering semantics remain identical.
