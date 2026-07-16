"""starplot.interactive — Plotly interactive backend for starplot.

Install the optional dependencies::

    pip install starplot[interactive]

Basic usage::

    from starplot.interactive import InteractiveMapPlot, InteractiveZenithPlot

    # InteractiveMapPlot is a drop-in replacement for MapPlot
    p = InteractiveMapPlot(projection=Miller(), ra_min=60, ra_max=120,
                           dec_min=-10, dec_max=30)
    p.stars(where=[_.magnitude < 8])
    p.constellations()
    p.export("chart.png")           # static matplotlib PNG (unchanged)
    p.export_html("chart.html")     # interactive Plotly HTML
    fig = p.to_plotly()             # plotly.graph_objects.Figure
"""

from starplot.interactive.plots import (
    InteractiveMapPlot,
    InteractiveZenithPlot,
    InteractiveHorizonPlot,
    InteractiveOpticPlot,
)
from starplot.interactive.commands import DrawingCommand
from starplot.interactive.recorder import DrawingRecorder
from starplot.interactive.scene import (
    ColumnarData,
    InteractionPolicy,
    SceneCapabilities,
    SceneKind,
    SceneLayer,
    ScenePackage,
    readonly_array,
)
from starplot.interactive.recording_mixin import RecordingMixin
from starplot.interactive.plotly_renderer import PlotlyRenderer
from starplot.interactive.plotly_adapter import PlotlySceneAdapter
from starplot.interactive.scene_manifest import (
    CapabilitiesModel,
    DataSourceModel,
    LayerManifestModel,
    SceneManifestModel,
    canonical_manifest_bytes,
    scene_content_hash,
)
from starplot.interactive.arrow_transport import (
    decode_layer_stream,
    encode_layer_stream,
    encode_table_stream,
    layer_content_hash,
    layer_to_table,
)

__all__ = [
    "InteractiveMapPlot",
    "InteractiveZenithPlot",
    "InteractiveHorizonPlot",
    "InteractiveOpticPlot",
    "DrawingCommand",
    "DrawingRecorder",
    "readonly_array",
    "ColumnarData",
    "InteractionPolicy",
    "SceneCapabilities",
    "SceneKind",
    "SceneLayer",
    "ScenePackage",
    "RecordingMixin",
    "PlotlyRenderer",
    "PlotlySceneAdapter",
    "CapabilitiesModel",
    "DataSourceModel",
    "LayerManifestModel",
    "SceneManifestModel",
    "canonical_manifest_bytes",
    "scene_content_hash",
    "decode_layer_stream",
    "encode_layer_stream",
    "encode_table_stream",
    "layer_content_hash",
    "layer_to_table",
]
