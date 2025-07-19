"""
Matplotlib backend implementation
"""
import numpy as np
from typing import Any, Dict, List, Optional, Tuple, Union
from matplotlib import pyplot as plt
from matplotlib.figure import Figure
from matplotlib.axes import Axes
from cartopy import crs as ccrs
from .base import PlotBackend


class MatplotlibBackend(PlotBackend):
    """Matplotlib backend for starplot"""
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.dpi = kwargs.get('dpi', 100)
        
    def create_figure(self, width: int, height: int, **kwargs) -> Figure:
        """Create matplotlib figure"""
        px = 1 / self.dpi
        figsize = (width * px, height * px)
        
        self.figure = plt.figure(figsize=figsize, dpi=self.dpi, **kwargs)
        return self.figure
    
    def set_figure(self, figure: Figure):
        """Set the matplotlib figure and extract the first axes"""
        self.figure = figure
        # Get the first axes from the figure
        if figure.axes:
            self.ax = figure.axes[0]
        else:
            # Create default axes if none exist
            self.ax = figure.add_subplot(111)
    
    def create_subplot(self, projection=None, **kwargs) -> Axes:
        """Create matplotlib subplot with optional cartopy projection"""
        if projection:
            self.ax = self.figure.add_subplot(111, projection=projection, **kwargs)
        else:
            self.ax = self.figure.add_subplot(111, **kwargs)
        return self.ax
    
    def set_xlim(self, xmin: float, xmax: float):
        """Set x-axis limits"""
        self.ax.set_xlim(xmin, xmax)
    
    def set_ylim(self, ymin: float, ymax: float):
        """Set y-axis limits"""
        self.ax.set_ylim(ymin, ymax)
    
    def set_extent(self, extent: List[float], crs=None):
        """Set plot extent using cartopy"""
        if hasattr(self.ax, 'set_extent'):
            self.ax.set_extent(extent, crs=crs)
        else:
            self.ax.set_xlim(extent[0], extent[1])
            self.ax.set_ylim(extent[2], extent[3])
    
    def set_background_color(self, color: str):
        """Set background color"""
        self.ax.set_facecolor(color)
    
    def set_title(self, title: str, **kwargs):
        """Set plot title"""
        self.ax.set_title(title, **kwargs)
    
    def scatter(self, x: np.ndarray, y: np.ndarray, 
                sizes: np.ndarray = None, 
                colors: Union[str, np.ndarray] = None,
                alpha: Union[float, np.ndarray] = None,
                marker: str = 'o',
                edgecolors: str = None,
                **kwargs) -> Any:
        """Create scatter plot"""
        if edgecolors is not None:
            kwargs['edgecolors'] = edgecolors
        return self.ax.scatter(x, y, s=sizes, c=colors, alpha=alpha, 
                              marker=marker, **kwargs)
    
    def plot_lines(self, x: np.ndarray, y: np.ndarray, 
                   color: str = 'blue', 
                   linewidth: float = 1.0,
                   linestyle: str = '-',
                   **kwargs) -> Any:
        """Plot lines"""
        return self.ax.plot(x, y, color=color, linewidth=linewidth, 
                           linestyle=linestyle, **kwargs)
    
    def add_text(self, x: float, y: float, text: str,
                 fontsize: float = 12,
                 color: str = 'black',
                 ha: str = 'center',
                 va: str = 'center',
                 **kwargs) -> Any:
        """Add text annotation"""
        return self.ax.text(x, y, text, fontsize=fontsize, color=color,
                           ha=ha, va=va, **kwargs)
    
    def add_polygon(self, points: List[Tuple[float, float]],
                    fill_color: str = None,
                    edge_color: str = None,
                    alpha: float = 1.0,
                    **kwargs) -> Any:
        """Add polygon shape"""
        from matplotlib.patches import Polygon
        poly = Polygon(points, facecolor=fill_color, edgecolor=edge_color,
                      alpha=alpha, **kwargs)
        return self.ax.add_patch(poly)
    
    def set_axis_off(self):
        """Turn off axis display"""
        self.ax.set_axis_off()
    
    def set_aspect_equal(self):
        """Set equal aspect ratio"""
        self.ax.set_aspect('equal')
    
    def export(self, filename: str, dpi: int = 300, format: str = "png", padding: float = 0, **kwargs):
        """Export figure to file"""
        # Set matplotlib-specific parameters
        matplotlib_kwargs = {
            'format': format,
            'bbox_inches': 'tight',
            'pad_inches': padding,
            'dpi': dpi,
            **kwargs
        }
        
        if self.figure:
            self.figure.savefig(filename, **matplotlib_kwargs)
        else:
            # If no figure is set, try to get current figure
            import matplotlib.pyplot as plt
            current_fig = plt.gcf()
            if current_fig:
                current_fig.savefig(filename, **matplotlib_kwargs)
    
    def set_figure(self, figure):
        """Set the matplotlib figure object"""
        self.figure = figure
    
    def show(self):
        """Display the plot"""
        plt.show()
    
    def close(self):
        """Close the figure"""
        plt.close(self.figure)