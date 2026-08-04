"""Compatibility facade routing recorded commands through the shared Scene."""

from __future__ import annotations

from starplot.interactive.plotly_adapter import PlotlySceneAdapter
from starplot.interactive.scene_compiler import SceneCompiler


class PlotlyRenderer:
    """Compile DrawingCommands once and render the resulting Scene once."""

    def __init__(
        self,
        projection_info: dict,
        style_info: dict,
        width: float | None = None,
        height: float | None = None,
        transparent: bool = False,
    ):
        self.projection_info = projection_info
        self.style_info = style_info
        self.width = width
        self.height = height
        self.transparent = transparent
        self.fig = None

    def _reference_dimensions(self) -> tuple[float, float]:
        figure_pixels = self.projection_info.get("figure_pixels") or ()
        axes_pixels = self.projection_info.get("axes_pixels") or ()
        fallback_width = (
            figure_pixels[0]
            if len(figure_pixels) >= 1 and figure_pixels[0]
            else axes_pixels[0]
            if len(axes_pixels) >= 1 and axes_pixels[0]
            else self.style_info.get("source_axes_width")
            or self.style_info.get("resolution")
            or 1000
        )
        fallback_height = (
            figure_pixels[1]
            if len(figure_pixels) >= 2 and figure_pixels[1]
            else axes_pixels[1]
            if len(axes_pixels) >= 2 and axes_pixels[1]
            else self.style_info.get("source_axes_height")
            or self.style_info.get("resolution")
            or fallback_width
        )
        return float(self.width or fallback_width), float(
            self.height or fallback_height
        )

    def render(self, commands):
        reference_width, reference_height = self._reference_dimensions()
        scene = SceneCompiler().compile(
            commands,
            self.projection_info,
            self.style_info,
            reference_width,
            reference_height,
            self.transparent,
        )
        figure = PlotlySceneAdapter().render(scene)
        if self.width is not None and self.height is not None:
            figure.update_layout(
                width=int(round(self.width)),
                height=int(round(self.height)),
                autosize=False,
            )
        else:
            figure.update_layout(width=None, height=None, autosize=True)
        self.fig = figure
        return figure
