from abc import ABC, abstractmethod
from typing import Dict, Union, Optional, Any, Type

class PlotBackend(ABC):
    @abstractmethod
    def initialize(self, **kwargs):
        """Initialize the backend with given parameters"""
        pass

    @abstractmethod
    def plot(self, x, y, **style_kwargs) -> Any:
        """Create a line plot"""
        pass

    @abstractmethod
    def marker(self, x, y, **style_kwargs) -> Any:
        """Create a marker/point plot"""
        pass

    @abstractmethod
    def text(self, x, y, text, **style_kwargs) -> Any:
        """Create a text annotation"""
        pass

    @abstractmethod
    def polygon(self, points, **style_kwargs) -> Any:
        """Create a polygon"""
        pass

    @abstractmethod
    def export(self, filename: str, format: str = "png", **kwargs):
        """Export the plot to a file"""
        pass

    @abstractmethod
    def get_figure(self) -> Any:
        """Get the current figure object"""
        pass

_registered_backends: Dict[str, Type[PlotBackend]] = {}

def register_backend(name: str, backend_class: Type[PlotBackend]):
    """Register a new plotting backend"""
    _registered_backends[name] = backend_class

def get_backend(name: str) -> Type[PlotBackend]:
    """Get a registered backend by name"""
    if name not in _registered_backends:
        raise ValueError(f"Backend {name} not found. Available backends: {list(_registered_backends.keys())}")
    return _registered_backends[name] 