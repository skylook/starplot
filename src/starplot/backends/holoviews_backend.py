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

    def _convert_style(self, style_kwargs: dict) -> dict:
        """Convert style kwargs to HoloViews style options"""
        style = style_kwargs.copy()
        
        # Convert line_width to linewidth
        if 'line_width' in style:
            style['linewidth'] = style.pop('line_width')
        
        # Convert marker style
        if 'marker' in style:
            marker_map = {
                'o': 'o',
                'circle': 'o',
                's': 's',
                'square': 's',
                '^': '^',
                'triangle': '^',
                'D': 'd',
                'diamond': 'd',
                '*': '*',
                'star': '*',
                '+': '+',
                'plus': '+',
                'x': 'x',
                'cross': 'x'
            }
            style['marker'] = marker_map.get(style['marker'], 'o')
        
        # Convert size to s (scatter size)
        if 'size' in style:
            style['s'] = style.pop('size')
        
        # Convert text font size
        if 'text_font_size' in style:
            style['fontsize'] = style.pop('text_font_size').rstrip('pt')
        
        # Convert fill_color to facecolor
        if 'fill_color' in style:
            style['facecolor'] = style.pop('fill_color')
        
        # Convert edge_color to edgecolor
        if 'edge_color' in style:
            style['edgecolor'] = style.pop('edge_color')
        
        # Convert edge_line_width to linewidth
        if 'edge_line_width' in style:
            style['linewidth'] = style.pop('edge_line_width')
        
        # Convert line style
        if 'line_dash' in style:
            style_map = {
                'solid': '-',
                'dashed': '--',
                'dashdot': '-.',
                'dotted': ':',
            }
            if isinstance(style['line_dash'], str):
                style['linestyle'] = style_map.get(style['line_dash'], '-')
            else:
                style['linestyle'] = style['line_dash']
            style.pop('line_dash')
        
        # Remove unsupported options
        unsupported = [
            'z_index', 'clip_on', 'clip_path', 'gid', 'transform',
            'edge_line_dash', 'edge_line_width', 'closed', 'fontstyle',
            'fontname', 'fontfamily', 'fontweight', 'va', 'ha', 'xytext',
            'textcoords', 'path_effects', 'zorder', 'xycoords'
        ]
        for opt in unsupported:
            if opt in style:
                style.pop(opt)
        
        return style

    def plot(self, x, y, **style_kwargs) -> Any:
        """Create a line plot using HoloViews"""
        style = self._convert_style(style_kwargs)
        curve = hv.Curve((x, y)).opts(**style)
        self._add_element(curve)
        return curve

    def marker(self, x, y, **style_kwargs) -> Any:
        """Create a marker/point plot using HoloViews"""
        style = self._convert_style(style_kwargs)
        
        # Convert single points to lists
        x = [x] if isinstance(x, (int, float)) else x
        y = [y] if isinstance(y, (int, float)) else y
        
        scatter = hv.Scatter([(x_, y_) for x_, y_ in zip(x, y)]).opts(**style)
        self._add_element(scatter)
        return scatter

    def text(self, x, y, text, **style_kwargs) -> Any:
        """Create a text annotation using HoloViews"""
        style = self._convert_style(style_kwargs)
        # Convert single points to lists
        x = [x] if isinstance(x, (int, float)) else x
        y = [y] if isinstance(y, (int, float)) else y
        text_element = hv.Text(x[0], y[0], text).opts(**style)
        self._add_element(text_element)
        return text_element

    def polygon(self, points, **style_kwargs) -> Any:
        """Create a polygon using HoloViews"""
        style = self._convert_style(style_kwargs)
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

# Register the HoloViews backend
register_backend('holoviews', HoloViewsBackend) 