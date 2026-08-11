"""Demonstrate all interactive HTML export modes from one scene.

This example writes four artefacts into the current working directory:

- ``orion.html`` + ``orion.scene/`` — external bundle (default). Serve with
  ``starplot serve . --port 8000`` or any HTTP server.
- ``orion-inline.html`` — single-file inline mode, works from ``file://``.
- ``orion-remote.html`` — remote client shell that fetches data from a
  ``SceneProvider`` backend. Run ``remote_provider_server.py`` to serve it.
- ``orion-plotly.html`` — a plain Plotly HTML written by the returned
  ``plotly.graph_objects.Figure``.

The Orion field is the same one used by ``map_orion_interactive.py``.
"""

from starplot import Miller, _
from starplot.interactive import InteractiveMapPlot
from starplot.styles import PlotStyle, extensions

style = PlotStyle().extend(extensions.BLUE_LIGHT, extensions.MAP)

p = InteractiveMapPlot(
    projection=Miller(),
    ra_min=3.6 * 15,
    ra_max=7.8 * 15,
    dec_min=-15,
    dec_max=25,
    style=style,
    resolution=4096,
    autoscale=True,
)

p.gridlines()
p.constellations()
p.stars(where=[_.magnitude < 8], where_labels=[_.magnitude < 4])
p.constellation_labels()

# 1. External bundle (default): small HTML + chart.scene/ directory.
#    Serve the directory over HTTP; ``file://`` will not work.
p.export_html("orion.html")

# 2. Inline single file: all data is embedded, works from ``file://``.
p.export_html("orion-inline.html", data_mode="inline")

# 3. Remote client shell: data comes from a SceneProvider backend.
#    Start ``remote_provider_server.py`` first, then open orion-remote.html
#    from the same server (or add CORS if served elsewhere).
p.export_html(
    "orion-remote.html",
    data_mode="remote",
    data_url="http://127.0.0.1:8765/scenes/orion/manifest.json",
    allowed_data_origins=(),
)

# 4. Plotly Figure for notebooks or further Plotly customisation.
fig = p.to_plotly()
fig.write_html("orion-plotly.html")

print("Generated:")
print("  orion.html + orion.scene/   (external bundle)")
print("  orion-inline.html           (inline single file)")
print("  orion-remote.html           (remote client)")
print("  orion-plotly.html           (Plotly Figure export)")
