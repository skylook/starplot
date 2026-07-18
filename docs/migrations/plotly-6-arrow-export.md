# Migrating to Plotly 6 and Arrow Scene export

Interactive Starplot output now requires `plotly>=6.0`. There is no Plotly 5
fallback: Plotly 6 typed arrays and the shared Arrow Scene transport are part
of the supported contract.

## Default export behavior

`Interactive*Plot.export_html("chart.html")` now defaults to an external
bundle: `chart.html` plus `chart.scene/` containing a manifest and content-
hashed Arrow IPC Stream layers. Serve it using HTTP, for example:

```bash
starplot serve . --port 8000
```

If an existing workflow needs the former direct-open, one-file behavior,
request it explicitly:

```python
plot.export_html("chart-inline.html", data_mode="inline")
```

`include_plotlyjs=True` remains a deprecated compatibility request and selects
the inline mode when the caller did not choose a data mode.

## Packaging and licensing

The browser runtime includes the pinned Apache Arrow JavaScript 21.1 asset and
its third-party notices in both wheel and source distributions. No JavaScript
bundler is required. The normal optional install remains:

```bash
pip install "starplot[interactive]"
```

## Application integrations

For server delivery use `data_mode="remote"` and point `data_url` at a
`SceneProvider` manifest endpoint. Preserve the provider's response bytes and
headers in the web framework. See the [interactive web export reference](../reference/interactive-web-export.md)
for a minimal adapter, caching behavior, allowed-origin rules, and the
hover/detail data contract.
