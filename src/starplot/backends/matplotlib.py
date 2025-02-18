import matplotlib.pyplot as plt
from matplotlib.patches import Polygon
from matplotlib.path import Path
from matplotlib.transforms import Bbox
from typing import Any, Optional

from . import PlotBackend, register_backend

class MatplotlibBackend(PlotBackend):
    def __init__(self):
        self.fig = None
        self.ax = None

    def initialize(self, **kwargs):
        """Initialize the matplotlib backend with given parameters"""
        self.fig = plt.figure(**kwargs)
        if 'projection' in kwargs:
            self.ax = plt.axes(projection=kwargs['projection'])
        else:
            self.ax = plt.axes()

    def plot(self, x, y, **style_kwargs) -> Any:
        """Create a line plot"""
        return self.ax.plot(x, y, **style_kwargs)

    def marker(self, x, y, **style_kwargs) -> Any:
        """Create a marker/point plot"""
        return self.ax.scatter(x, y, **style_kwargs)

    def text(self, x, y, text, **style_kwargs) -> Any:
        """Create a text annotation"""
        return self.ax.text(x, y, text, **style_kwargs)

    def polygon(self, points, **style_kwargs) -> Any:
        """Create a polygon"""
        poly = Polygon(points, **style_kwargs)
        return self.ax.add_patch(poly)

    def export(self, filename: str, format: str = "png", **kwargs):
        """Export the plot to a file"""
        self.fig.savefig(filename, format=format, **kwargs)

    def get_figure(self) -> Any:
        """Get the current figure object"""
        return self.fig

    def set_axis_off(self):
        """Turn off axis display"""
        if self.ax:
            self.ax.axis('off')

    def set_limits(self, xlim=None, ylim=None):
        """Set axis limits"""
        if xlim is not None:
            self.ax.set_xlim(xlim)
        if ylim is not None:
            self.ax.set_ylim(ylim)

    def set_projection(self, projection):
        """Set the projection for the plot"""
        if self.ax:
            self.ax.projection = projection

register_backend('matplotlib', MatplotlibBackend)