"""Interactive plot classes — drop-in replacements for starplot plots that
additionally support Plotly HTML export.

Usage::

    from starplot.interactive import InteractiveMapPlot
    from starplot import Miller, _

    p = InteractiveMapPlot(projection=Miller(), ra_min=60, ra_max=120, ...)
    p.stars(where=[_.magnitude < 8])
    p.constellations()
    p.export("chart.png")        # static matplotlib export (unchanged)
    p.export_html("chart.html")  # interactive Plotly HTML
    fig = p.to_plotly()          # Plotly Figure for further customisation
"""

from __future__ import annotations

from starplot.interactive.recording_mixin import RecordingMixin
from starplot.interactive.plotly_renderer import PlotlyRenderer
from starplot.plots import MapPlot, ZenithPlot, HorizonPlot, OpticPlot


class _InteractiveMixin:
    """Common export methods shared by all Interactive*Plot classes."""

    def export_html(self, filename: str, width: int = None, height: int = None, **kwargs):
        """Export as an interactive Plotly HTML file.

        Args:
            filename: Output HTML file path.
            width: Chart width in pixels (default depends on plot type).
            height: Chart height in pixels (default depends on plot type).
            **kwargs: Passed to ``plotly.io.write_html``.
        """
        fig = self.to_plotly()
        if width or height:
            fig.update_layout(
                width=width or fig.layout.width,
                height=height or fig.layout.height,
            )
        fig.write_html(filename, **kwargs)

    def to_plotly(self):
        """Return a Plotly Figure object for further customisation.

        Returns:
            ``plotly.graph_objects.Figure``
        """
        renderer = PlotlyRenderer(
            projection_info=self._recorder.projection_info,
            style_info=self._recorder.style_info,
        )
        return renderer.render(self._recorder.commands)


class InteractiveMapPlot(_InteractiveMixin, RecordingMixin, MapPlot):
    """MapPlot with interactive Plotly export.

    API is identical to :class:`~starplot.MapPlot`, with two additions:

    - :meth:`export_html` — export interactive HTML
    - :meth:`to_plotly` — return ``plotly.graph_objects.Figure``

    Example::

        p = InteractiveMapPlot(projection=Miller(), ra_min=60, ra_max=120,
                               dec_min=-10, dec_max=30)
        p.stars(where=[_.magnitude < 8])
        p.constellations()
        p.export("chart.png")
        p.export_html("chart.html", width=1400, height=900)
    """

    def export_html(self, filename: str, width: int = 1200, height: int = 900, **kwargs):
        super().export_html(filename, width=width, height=height, **kwargs)


class InteractiveZenithPlot(_InteractiveMixin, RecordingMixin, ZenithPlot):
    """ZenithPlot with interactive Plotly export.  API same as ZenithPlot."""

    def export_html(self, filename: str, width: int = 1000, height: int = 1000, **kwargs):
        super().export_html(filename, width=width, height=height, **kwargs)


class InteractiveHorizonPlot(_InteractiveMixin, RecordingMixin, HorizonPlot):
    """HorizonPlot with interactive Plotly export.  API same as HorizonPlot."""

    def export_html(self, filename: str, width: int = 1200, height: int = 600, **kwargs):
        super().export_html(filename, width=width, height=height, **kwargs)


class InteractiveOpticPlot(_InteractiveMixin, RecordingMixin, OpticPlot):
    """OpticPlot with interactive Plotly export.  API same as OpticPlot."""

    def export_html(self, filename: str, width: int = 1000, height: int = 1000, **kwargs):
        super().export_html(filename, width=width, height=height, **kwargs)
