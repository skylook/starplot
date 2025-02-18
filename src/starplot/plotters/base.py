from typing import Any

from starplot.backends import get_backend

class BasePlotter:
    """Base class for all plotters"""
    
    def __init__(self):
        self.backend = None
        self.scale = 1.0
        self.dpi = 100
        
    def _initialize_backend(self, backend_name: str = "holoviews", **kwargs):
        """Initialize the plotting backend"""
        backend_class = get_backend(backend_name)
        self.backend = backend_class()
        self.backend.initialize(**kwargs)
        
    def _plot(self, x, y, **style_kwargs) -> Any:
        """Create a line plot"""
        return self.backend.plot(x, y, **style_kwargs)
        
    def _marker(self, x, y, **style_kwargs) -> Any:
        """Create a marker/point plot"""
        return self.backend.marker(x, y, **style_kwargs)
        
    def _text(self, x, y, text, **style_kwargs) -> Any:
        """Create a text annotation"""
        return self.backend.text(x, y, text, **style_kwargs)
        
    def _polygon(self, points, **style_kwargs) -> Any:
        """Create a polygon"""
        return self.backend.polygon(points, **style_kwargs)
        
    def _legend(self, handles: list, **style_kwargs) -> Any:
        """Create a legend"""
        return self.backend.legend(handles, **style_kwargs)
        
    def _export(self, filename: str, format: str = "png", **kwargs):
        """Export the plot to a file"""
        self.backend.export(filename, format, **kwargs)
        
    def _get_figure(self) -> Any:
        """Get the current figure object"""
        return self.backend.get_figure()
        
    def _close(self):
        """Close the current figure"""
        self.backend.close()