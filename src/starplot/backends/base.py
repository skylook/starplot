"""
Base abstract interface for plotting backends
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple, Union
import numpy as np


class PlotBackend(ABC):
    """Abstract base class for plotting backends"""
    
    def __init__(self, **kwargs):
        self.figure = None
        self.ax = None
        self._style_cache = {}
        
    @abstractmethod
    def create_figure(self, width: int, height: int, **kwargs) -> Any:
        """Create a new figure with specified dimensions"""
        pass
    
    @abstractmethod
    def create_subplot(self, projection=None, **kwargs) -> Any:
        """Create a subplot with optional projection"""
        pass
    
    @abstractmethod
    def set_xlim(self, xmin: float, xmax: float):
        """Set x-axis limits"""
        pass
    
    @abstractmethod
    def set_ylim(self, ymin: float, ymax: float):
        """Set y-axis limits"""
        pass
    
    @abstractmethod
    def set_extent(self, extent: List[float], crs=None):
        """Set plot extent [xmin, xmax, ymin, ymax]"""
        pass
    
    @abstractmethod
    def set_background_color(self, color: str):
        """Set background color"""
        pass
    
    @abstractmethod
    def set_title(self, title: str, **kwargs):
        """Set plot title"""
        pass
    
    @abstractmethod
    def scatter(self, x: np.ndarray, y: np.ndarray, 
                sizes: np.ndarray = None, 
                colors: Union[str, np.ndarray] = None,
                alpha: Union[float, np.ndarray] = None,
                marker: str = 'o',
                **kwargs) -> Any:
        """Create scatter plot for stars"""
        pass
    
    @abstractmethod
    def plot_lines(self, x: np.ndarray, y: np.ndarray, 
                   color: str = 'blue', 
                   linewidth: float = 1.0,
                   linestyle: str = '-',
                   **kwargs) -> Any:
        """Plot lines for constellations"""
        pass
    
    @abstractmethod
    def add_text(self, x: float, y: float, text: str,
                 fontsize: float = 12,
                 color: str = 'black',
                 ha: str = 'center',
                 va: str = 'center',
                 **kwargs) -> Any:
        """Add text annotation"""
        pass
    
    @abstractmethod
    def add_polygon(self, points: List[Tuple[float, float]],
                    fill_color: str = None,
                    edge_color: str = None,
                    alpha: float = 1.0,
                    **kwargs) -> Any:
        """Add polygon shape"""
        pass
    
    @abstractmethod
    def set_axis_off(self):
        """Turn off axis display"""
        pass
    
    @abstractmethod
    def set_aspect_equal(self):
        """Set equal aspect ratio"""
        pass
    
    @abstractmethod
    def export(self, filename: str, dpi: int = 300, **kwargs):
        """Export figure to file"""
        pass
    
    @abstractmethod
    def show(self):
        """Display the plot"""
        pass
    
    @abstractmethod
    def close(self):
        """Close the figure"""
        pass
    
    def get_figure(self) -> Any:
        """Get the current figure object"""
        return self.figure
    
    def get_axes(self) -> Any:
        """Get the current axes object"""
        return self.ax