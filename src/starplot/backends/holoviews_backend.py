import holoviews as hv
from holoviews import opts
from typing import Any, Optional

from starplot.backends import PlotBackend, register_backend

class HoloViewsBackend(PlotBackend):
    """HoloViews plotting backend"""

    def __init__(self):
        self.overlay = None
        self.backend = None
        self.scale = 1.0
        self.dpi = 100

    def initialize(self, backend: str = "matplotlib", dpi: int = 100, scale: float = 1.0, **kwargs):
        """Initialize the HoloViews backend with the specified rendering backend"""
        hv.extension(backend)
        self.backend = backend
        self.overlay = hv.Overlay([])
        self.dpi = dpi
        self.scale = scale

    def plot(self, x, y, **style_kwargs) -> Any:
        """Create a line plot using HoloViews"""
        style = self._convert_style(style_kwargs, 'Curve')
        curve = hv.Curve((x, y)).opts(**style)
        self._add_element(curve)
        return curve

    def marker(self, x, y, **style_kwargs) -> Any:
        """Create a marker/point plot using HoloViews"""
        style = self._convert_style(style_kwargs, 'Scatter')
        
        # Convert single points to lists
        x = [x] if isinstance(x, (int, float)) else x
        y = [y] if isinstance(y, (int, float)) else y
        
        scatter = hv.Scatter([(x_, y_) for x_, y_ in zip(x, y)]).opts(**style)
        self._add_element(scatter)
        return scatter

    def text(self, x, y, text, **style_kwargs) -> Any:
        """Create a text annotation using HoloViews"""
        style = self._convert_style(style_kwargs, 'Text')
        
        # Convert single points to lists
        x = [x] if isinstance(x, (int, float)) else x
        y = [y] if isinstance(y, (int, float)) else y
        text_element = hv.Text(x[0], y[0], text).opts(**style)
        self._add_element(text_element)
        return text_element

    def polygon(self, points, **style_kwargs) -> Any:
        """Create a polygon using HoloViews"""
        style = self._convert_style(style_kwargs, 'Polygons')
        
        polygon = hv.Polygons([{
            'x': [p[0] for p in points],
            'y': [p[1] for p in points]
        }]).opts(**style)
        self.overlay *= polygon
        return polygon

    def _add_element(self, element):
        """Add an element to the overlay"""
        self.overlay *= element

    def export(self, filename: str, **kwargs) -> None:
        """Export the plot to a file"""
        hv.save(self.overlay, filename, backend=self.backend)

    def get_figure(self) -> Any:
        """Get the current figure object"""
        return self.overlay

    def _convert_style(self, style_kwargs: dict, obj_type: str = None) -> dict:
        """Convert style kwargs to HoloViews style options"""
        style = style_kwargs.copy()
        
        # Remove unsupported options
        unsupported = [
            'clip_on', 'clip_path', 'gid', 'transform',
            'edge_line_dash', 'edge_line_width', 'closed', 'fontstyle',
            'fontname', 'fontfamily', 'fontweight', 'va', 'ha', 'xytext',
            'textcoords', 'path_effects', 'xycoords', 'z_index', 'fill_alpha',
            'zorder'
        ]
        for opt in unsupported:
            style.pop(opt, None)
            
        # Convert size to s for scatter plots
        if 'size' in style:
            style['s'] = style.pop('size')
            
        # Convert line_dash to linestyle for non-scatter plots
        if 'line_dash' in style and obj_type != 'Scatter':
            line_dash = style.pop('line_dash')
            style_map = {
                'solid': '-',
                'dashed': '--',
                'dashdot': '-.',
                'dotted': ':',
            }
            style['linestyle'] = style_map.get(line_dash, line_dash)
        elif 'line_dash' in style:
            style.pop('line_dash')
            
        # Convert linestyle for non-scatter plots
        if 'linestyle' in style and obj_type != 'Scatter':
            line_style = style['linestyle']
            style_map = {
                'solid': '-',
                'dashed': '--',
                'dashdot': '-.',
                'dotted': ':',
            }
            style['linestyle'] = style_map.get(line_style, line_style)
        elif 'linestyle' in style:
            style.pop('linestyle')
            
        # Convert edge_color to edgecolor
        if 'edge_color' in style:
            style['edgecolor'] = style.pop('edge_color')
            
        # Convert fill_color to facecolor
        if 'fill_color' in style:
            style['facecolor'] = style.pop('fill_color')
            
        return style

# Register the HoloViews backend
register_backend('holoviews', HoloViewsBackend) 