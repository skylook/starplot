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
        
        # Create curve element with additional features
        curve = hv.Curve((x, y)).opts(**style)
        
        self._add_element(curve)
        return curve

    def marker(self, x, y, **style_kwargs) -> Any:
        """Create a marker/point plot using HoloViews"""
        style = self._convert_style(style_kwargs, 'Scatter')
        
        # Convert single points to lists
        x = [x] if isinstance(x, (int, float)) else x
        y = [y] if isinstance(y, (int, float)) else y
        
        # Create data points
        data = [(x_, y_) for x_, y_ in zip(x, y)]
        
        # Handle label separately
        label = style_kwargs.get('label')
        scatter = hv.Scatter(data, label=label) if label else hv.Scatter(data)
        
        # Apply style options
        scatter = scatter.opts(**style)
        
        self._add_element(scatter)
        return scatter

    def text(self, x, y, text, **style_kwargs) -> Any:
        """Create a text annotation using HoloViews"""
        style = self._convert_style(style_kwargs, 'Text')
        
        # Convert single points to lists
        x = [x] if isinstance(x, (int, float)) else x
        y = [y] if isinstance(y, (int, float)) else y
        
        # Create text element
        text_element = hv.Text(x[0], y[0], text).opts(
            color=style.get('color', 'black'),
            alpha=style.get('alpha', 1.0),
            rotation=style.get('rotation', 0),
            fontsize=style.get('fontsize', '12pt')
        )
        
        self._add_element(text_element)
        return text_element

    def polygon(self, points, **style_kwargs) -> Any:
        """Create a polygon using HoloViews"""
        style = self._convert_style(style_kwargs, 'Polygons')
        
        # Create polygon data
        polygon_data = [{
            'x': [p[0] for p in points],
            'y': [p[1] for p in points]
        }]
        
        # Create polygon element
        polygon = hv.Polygons(polygon_data).opts(**style)
        
        self._add_element(polygon)
        return polygon

    def _add_element(self, element):
        """Add an element to the overlay"""
        self.overlay *= element

    def export(self, filename: str, format: str = "png", dpi: int = None, **kwargs) -> None:
        """Export the plot to a file
        
        Args:
            filename: The filename to save to
            format: The format to save as (png, svg, html, etc)
            dpi: The DPI to use for raster formats
            **kwargs: Additional keyword arguments to pass to hv.save
        """
        # Set default DPI if not provided
        if dpi is None:
            dpi = self.dpi
            
        # Configure save options
        save_opts = {
            'backend': self.backend,
            'dpi': dpi
        }
        
        # Add any additional options
        save_opts.update(kwargs)
        
        # Save the plot
        hv.save(self.overlay, filename, **save_opts)

    def get_figure(self) -> Any:
        """Get the current figure object"""
        return self.overlay

    def close(self):
        """Close the current figure"""
        self.overlay = hv.Overlay([])

    def _convert_style(self, style_kwargs: dict, obj_type: str = None) -> dict:
        """Convert style kwargs to HoloViews style options"""
        # Create a copy to avoid modifying the original
        style = style_kwargs.copy()
        
        # Convert style parameters to HoloViews format
        if obj_type == 'Scatter':
            # Convert size to area
            if 'size' in style:
                style['s'] = style.pop('size') ** 2
            # Convert edge parameters
            if 'edge_color' in style:
                style['edgecolor'] = style.pop('edge_color')
            if 'edge_width' in style:
                style['linewidth'] = style.pop('edge_width')
            # Remove line style for scatter plots
            style.pop('linestyle', None)
        elif obj_type == 'Curve':
            # Convert line parameters
            if 'line_color' in style:
                style['color'] = style.pop('line_color')
            if 'line_width' in style:
                style['linewidth'] = style.pop('line_width')
            if 'line_alpha' in style:
                style['alpha'] = style.pop('line_alpha')
            if 'line_dash' in style:
                style['linestyle'] = style.pop('line_dash')
        elif obj_type == 'Polygons':
            # Convert polygon parameters
            if 'edge_color' in style:
                style['edgecolor'] = style.pop('edge_color')
            if 'edge_width' in style:
                style['linewidth'] = style.pop('edge_width')
            if 'fill_color' in style:
                style['facecolor'] = style.pop('fill_color')
            # Remove tools option for polygons
            style.pop('tools', None)
            style.pop('active_tools', None)
            style.pop('closed', None)
            
        # Remove unsupported options
        unsupported = [
            'clip_on', 'clip_path', 'gid', 'transform',
            'path_effects', 'xycoords', 'z_index', 'fill_alpha',
            'zorder', 'label', 'tools', 'active_tools', 'closed'
        ]
        for opt in unsupported:
            style.pop(opt, None)
            
        return style

    def legend(self, handles: list, **style_kwargs) -> Any:
        """Create a legend"""
        # Convert location to HoloViews format
        if 'location' in style_kwargs:
            location = style_kwargs.pop('location')
            if location == 'outside_bottom':
                style_kwargs['legend_position'] = 'bottom'
            elif location == 'outside_top':
                style_kwargs['legend_position'] = 'top'
            elif location == 'inside_top':
                style_kwargs['legend_position'] = 'top_center'
            elif location == 'inside_top_left':
                style_kwargs['legend_position'] = 'top_left'
            elif location == 'inside_top_right':
                style_kwargs['legend_position'] = 'top_right'
            elif location == 'inside_bottom':
                style_kwargs['legend_position'] = 'bottom_center'
            elif location == 'inside_bottom_left':
                style_kwargs['legend_position'] = 'bottom_left'
            elif location == 'inside_bottom_right':
                style_kwargs['legend_position'] = 'bottom_right'
                
        # Create a new overlay with legend options
        new_overlay = self.overlay.opts(
            show_legend=True,
            **style_kwargs
        )
        
        # Update the current overlay
        self.overlay = new_overlay
        
        return new_overlay

# Register the HoloViews backend
register_backend('holoviews', HoloViewsBackend) 