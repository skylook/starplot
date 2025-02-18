import holoviews as hv
import numpy as np
from typing import Any, Optional

from . import PlotBackend, register_backend

class HoloviewsBackend(PlotBackend):
    def __init__(self):
        self.fig = None
        self.ax = None
        self._overlay = hv.Overlay([])
        self._current_extent = None
        self._current_projection = None
        self.backend = 'matplotlib'  # default backend

    @property
    def backend(self):
        return self._backend

    @backend.setter
    def backend(self, value):
        self._backend = value
        if value == 'bokeh':
            hv.extension('bokeh')
        else:
            hv.extension('matplotlib')

    def initialize(self, **kwargs):
        """Initialize the holoviews backend with given parameters"""
        if 'backend_kwargs' in kwargs and 'backend' in kwargs['backend_kwargs']:
            self.backend = kwargs['backend_kwargs']['backend']
        if 'projection' in kwargs:
            self._current_projection = kwargs['projection']
        self._overlay = hv.Overlay([])
        self.ax = self._overlay

    def plot(self, x, y, **style_kwargs) -> Any:
        """Create a line plot"""
        curve = hv.Curve((x, y)).opts(**style_kwargs)
        self._overlay = self._overlay * curve
        self.ax = self._overlay
        return curve

    def marker(self, x, y, **style_kwargs) -> Any:
        """Create a marker/point plot"""
        points = hv.Points((x, y)).opts(**style_kwargs)
        self._overlay = self._overlay * points
        self.ax = self._overlay
        return points

    def text(self, x, y, text, **style_kwargs) -> Any:
        """Create a text annotation"""
        text_obj = hv.Text(x, y, text).opts(**style_kwargs)
        self._overlay = self._overlay * text_obj
        self.ax = self._overlay
        return text_obj

    def polygon(self, points, **style_kwargs) -> Any:
        """Create a polygon"""
        poly = hv.Polygons([points]).opts(**style_kwargs)
        self._overlay = self._overlay * poly
        self.ax = self._overlay
        return poly

    def export(self, filename: str, format: str = "png", **kwargs):
        """Export the plot to a file"""
        hv.save(self._overlay, filename, fmt=format, **kwargs)

    def get_figure(self) -> Any:
        """Get the current figure object"""
        return self._overlay

    def set_axis_off(self):
        """Turn off axis display"""
        self._overlay = self._overlay.opts(show_frame=False)
        self.ax = self._overlay

    def set_limits(self, xlim=None, ylim=None):
        """Set axis limits"""
        opts = {}
        if xlim is not None:
            opts['xlim'] = xlim
        if ylim is not None:
            opts['ylim'] = ylim
        if opts:
            self._overlay = self._overlay.opts(**opts)
            self.ax = self._overlay

    def set_projection(self, projection):
        """Set the projection for the plot"""
        self._current_projection = projection

    def set_extent(self, bounds, **kwargs):
        """Set the extent of the plot"""
        self._current_extent = bounds
        self._overlay = self._overlay.opts(
            xlim=(bounds[0], bounds[1]),
            ylim=(bounds[2], bounds[3])
        )
        self.ax = self._overlay

    def set_global(self):
        """Set the plot to show global extent"""
        self._overlay = self._overlay.opts(
            xlim=(-180, 180),
            ylim=(-90, 90)
        )
        self.ax = self._overlay

register_backend('holoviews', HoloviewsBackend)