"""
Backend factory for creating plotting backends
"""
from typing import Type, Dict, Any
from .base import PlotBackend
from .matplotlib_backend import MatplotlibBackend
from .plotly_backend import PlotlyBackend


class BackendFactory:
    """Factory class for creating plotting backends"""
    
    _backends: Dict[str, Type[PlotBackend]] = {
        'matplotlib': MatplotlibBackend,
        'plotly': PlotlyBackend,
    }
    
    @classmethod
    def create(cls, backend_name: str, **kwargs) -> PlotBackend:
        """Create a backend instance
        
        Args:
            backend_name: Name of the backend ('matplotlib' or 'plotly')
            **kwargs: Additional arguments to pass to the backend constructor
            
        Returns:
            PlotBackend: Instance of the requested backend
            
        Raises:
            ValueError: If backend_name is not supported
        """
        if backend_name not in cls._backends:
            available = ', '.join(cls._backends.keys())
            raise ValueError(f"Backend '{backend_name}' not supported. Available: {available}")
        
        backend_class = cls._backends[backend_name]
        return backend_class(**kwargs)
    
    @classmethod
    def register_backend(cls, name: str, backend_class: Type[PlotBackend]):
        """Register a new backend
        
        Args:
            name: Name of the backend
            backend_class: Backend class that inherits from PlotBackend
        """
        cls._backends[name] = backend_class
    
    @classmethod
    def list_backends(cls) -> list:
        """List all available backends
        
        Returns:
            list: List of available backend names
        """
        return list(cls._backends.keys())