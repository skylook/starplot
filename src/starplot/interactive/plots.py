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

import warnings

from starplot.interactive.recording_mixin import RecordingMixin
from starplot.interactive.plotly_renderer import PlotlyRenderer
from starplot.interactive.scene_compiler import SceneCompiler
from starplot.interactive.web_export import export_scene_html
from starplot.plots import MapPlot, ZenithPlot, HorizonPlot, OpticPlot


class _InteractiveMixin:
    """Common export methods shared by all Interactive*Plot classes."""

    def _compile_scene(self, width: int = None, height: int = None,
                       transparent: bool = False):
        """Compile once using the same final geometry authority as ``to_plotly``."""
        if hasattr(self, "_record_plot_info"):
            self._record_plot_info()
        renderer = PlotlyRenderer(
            projection_info=self._recorder.projection_info,
            style_info=self._recorder.style_info,
            width=width,
            height=height,
            transparent=transparent,
        )
        reference_width, reference_height = renderer._reference_dimensions()
        return SceneCompiler().compile(
            self._recorder.coalesced_scatter_commands(),
            self._recorder.projection_info,
            self._recorder.style_info,
            reference_width,
            reference_height,
            transparent,
        )

    def export_html(self, filename: str, width: int = None, height: int = None,
                    transparent: bool = False, data_mode="external",
                    library_mode=None, data_url=None, allowed_data_origins=(), **kwargs):
        """Export as an interactive Plotly HTML file.

        Args:
            filename: Output HTML file path.
            width: Chart width in pixels (default depends on plot type).
            height: Chart height in pixels (default depends on plot type).
            transparent: If True, the figure and plot background will be
                transparent (matching matplotlib's ``transparent=True``).
            data_mode: ``external`` (default), ``inline``, or ``remote``.
            library_mode: ``cdn``, ``directory``, or ``inline``.
            data_url: Required manifest URL for ``remote`` mode.
            allowed_data_origins: Explicit remote layer-origin allow-list.
        """
        include_plotlyjs = kwargs.pop("include_plotlyjs", None)
        for legacy_name in ("full_html", "auto_open", "config", "post_script"):
            if legacy_name in kwargs:
                kwargs.pop(legacy_name)
                warnings.warn(
                    f"export_html({legacy_name}=...) is ignored by the Scene exporter; "
                    "use data_mode and library_mode instead",
                    DeprecationWarning,
                    stacklevel=2,
                )
        if include_plotlyjs is not None:
            if library_mode is None:
                library_mode = "inline" if include_plotlyjs is True else "cdn"
            if include_plotlyjs is True and data_mode == "external":
                warnings.warn(
                    "include_plotlyjs=True requested the former direct-open single-file "
                    "behavior; using data_mode='inline' instead",
                    DeprecationWarning,
                    stacklevel=2,
                )
                data_mode = "inline"
        if kwargs:
            unknown = ", ".join(sorted(kwargs))
            raise TypeError(f"unsupported export_html options: {unknown}")
        scene = self._compile_scene(width=width, height=height, transparent=transparent)
        return export_scene_html(
            scene, filename, data_mode=data_mode, library_mode=library_mode,
            data_url=data_url, allowed_data_origins=tuple(allowed_data_origins),
        )

    def to_plotly(self, width: int = None, height: int = None,
                  transparent: bool = False):
        """Return a Plotly Figure object for further customisation.

        Args:
            width: Optional chart width in pixels; used to scale marker sizes.
            height: Optional chart height in pixels; used to scale marker sizes.
            transparent: If True, the figure and plot background will be
                transparent (matching matplotlib's ``transparent=True``).

        Returns:
            ``plotly.graph_objects.Figure``
        """
        # Axis limits and style-related values can change after __init__
        # (e.g. OpticPlot.info() adjusts x/y limits). Refresh metadata before
        # rendering so Plotly uses the final matplotlib state.
        if hasattr(self, "_record_plot_info"):
            self._record_plot_info()

        renderer = PlotlyRenderer(
            projection_info=self._recorder.projection_info,
            style_info=self._recorder.style_info,
            width=width,
            height=height,
            transparent=transparent,
        )
        return renderer.render(self._recorder.coalesced_scatter_commands())


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

    def export_html(self, filename: str, width: int = None, height: int = None,
                    transparent: bool = False, **kwargs):
        return super().export_html(filename, width=width, height=height,
                                   transparent=transparent, **kwargs)


class InteractiveZenithPlot(_InteractiveMixin, RecordingMixin, ZenithPlot):
    """ZenithPlot with interactive Plotly export.  API same as ZenithPlot."""

    def export_html(self, filename: str, width: int = None, height: int = None,
                    transparent: bool = False, **kwargs):
        return super().export_html(filename, width=width, height=height,
                                   transparent=transparent, **kwargs)


class InteractiveHorizonPlot(_InteractiveMixin, RecordingMixin, HorizonPlot):
    """HorizonPlot with interactive Plotly export.  API same as HorizonPlot."""

    def export_html(self, filename: str, width: int = None, height: int = None,
                    transparent: bool = False, **kwargs):
        return super().export_html(filename, width=width, height=height,
                                   transparent=transparent, **kwargs)


class InteractiveOpticPlot(_InteractiveMixin, RecordingMixin, OpticPlot):
    """OpticPlot with interactive Plotly export.  API same as OpticPlot."""

    def export_html(self, filename: str, width: int = None, height: int = None,
                    transparent: bool = False, **kwargs):
        return super().export_html(filename, width=width, height=height,
                                   transparent=transparent, **kwargs)
