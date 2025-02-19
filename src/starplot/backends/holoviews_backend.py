import holoviews as hv
from holoviews import opts
from typing import Any, Optional, Union

from starplot.backends import PlotBackend, register_backend

class HoloViewsBackend(PlotBackend):
    """HoloViews plotting backend"""

    def __init__(self):
        self.overlay = None
        self.backend = None
        self.scale = 1.0
        self.dpi = 100
        self.ax = None

    def initialize(self, backend: str = "matplotlib", dpi: int = 100, scale: float = 1.0, **kwargs):
        """Initialize the HoloViews backend with the specified rendering backend"""
        # Handle backend parameter from kwargs first
        if 'backend_kwargs' in kwargs and 'backend' in kwargs['backend_kwargs']:
            backend = kwargs['backend_kwargs']['backend']
        elif 'backend' in kwargs:
            backend = kwargs.pop('backend')

        # Initialize HoloViews with the specified backend
        backend = backend.lower()  # Ensure backend name is lowercase
        hv.extension(backend)
        self.backend = backend
        self.overlay = hv.Overlay([])
        self.dpi = dpi
        self.scale = scale
        self.ax = self.overlay
        
        # Set default options for the backend
        if self.backend == 'bokeh':
            hv.opts.defaults(
                hv.opts.Scatter(tools=['hover']),
                hv.opts.Curve(tools=['hover']),
                hv.opts.Text(tools=['hover']),
                hv.opts.Polygons(tools=['hover'])
            )
        elif self.backend == 'matplotlib':
            hv.opts.defaults(
                hv.opts.Scatter(),
                hv.opts.Curve(),
                hv.opts.Text(),
                hv.opts.Polygons()
            )

    def set_xlim(self, xmin: float, xmax: float):
        """Set x-axis limits using HoloViews options"""
        self.overlay = self.overlay.opts(xlim=(xmin, xmax))

    def set_ylim(self, ymin: float, ymax: float):
        """Set y-axis limits using HoloViews options"""
        self.overlay = self.overlay.opts(ylim=(ymin, ymax))

    def set_xlabel(self, xlabel: str):
        """Set x-axis label using HoloViews options"""
        self.overlay = self.overlay.opts(xlabel=xlabel)

    def set_ylabel(self, ylabel: str):
        """Set y-axis label using HoloViews options"""
        self.overlay = self.overlay.opts(ylabel=ylabel)

    def set_title(self, title: str):
        """Set plot title using HoloViews options"""
        self.overlay = self.overlay.opts(title=title)

    def set_facecolor(self, color: str):
        """Set plot background color using HoloViews options"""
        self.overlay = self.overlay.opts(bgcolor=color)

    def set_aspect(self, aspect: Union[str, float]):
        """Set plot aspect ratio using HoloViews options"""
        if isinstance(aspect, str) and aspect == 'equal':
            self.overlay = self.overlay.opts(aspect='equal')
        else:
            self.overlay = self.overlay.opts(aspect=aspect)

    def plot(self, x, y, **style_kwargs) -> Any:
        """Create a line plot using HoloViews"""
        # Create curve element with additional features
        curve = hv.Curve((x, y))
        if style_kwargs:
            curve = curve.opts(**self._convert_style(style_kwargs, 'Curve'))
        
        self._add_element(curve)
        return curve

    def marker(self, x, y, **style_kwargs) -> Any:
        """Create a marker/point plot using HoloViews"""
        # Convert single points to lists
        x = [x] if isinstance(x, (int, float)) else x
        y = [y] if isinstance(y, (int, float)) else y
        
        # Create data points
        data = [(x_, y_) for x_, y_ in zip(x, y)]
        
        # Handle label separately
        label = style_kwargs.get('label')
        scatter = hv.Scatter(data, label=label) if label else hv.Scatter(data)
        
        # Apply style options
        if style_kwargs:
            scatter = scatter.opts(**self._convert_style(style_kwargs, 'Scatter'))
        
        self._add_element(scatter)
        return scatter

    def text(self, x, y, text, **style_kwargs) -> Any:
        """Create a text annotation using HoloViews"""
        # Convert single points to lists
        x = [x] if isinstance(x, (int, float)) else x
        y = [y] if isinstance(y, (int, float)) else y
        
        # Create text element
        text_element = hv.Text(x[0], y[0], text)
        if style_kwargs:
            style = self._convert_style(style_kwargs, 'Text')
            text_element = text_element.opts(
                color=style.get('color', 'black'),
                alpha=style.get('alpha', 1.0),
                fontsize=style.get('fontsize', '12pt')
            )
        
        self._add_element(text_element)
        return text_element

    def polygon(self, points, **style_kwargs) -> Any:
        """Create a polygon using HoloViews"""
        # Create polygon data
        polygon_data = [{
            'x': [p[0] for p in points],
            'y': [p[1] for p in points]
        }]
        
        # Create polygon element
        polygon = hv.Polygons(polygon_data)
        if style_kwargs:
            style = self._convert_style(style_kwargs, 'Polygons')
            polygon = polygon.opts(
                facecolor=style.get('facecolor', None),
                edgecolor=style.get('edgecolor', None),
                linewidth=style.get('linewidth', 1.0),
                alpha=style.get('alpha', 1.0),
                linestyle=style.get('linestyle', '-')
            )
        
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
            # Remove unsupported options
            style.pop('linestyle', None)
            style.pop('fill_alpha', None)
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
            style.pop('fill_alpha', None)
            
        # Remove unsupported options
        unsupported = [
            'clip_on', 'clip_path', 'gid', 'transform',
            'path_effects', 'xycoords', 'z_index',
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
            elif location == 'outside_right':
                style_kwargs['legend_position'] = 'right'
            elif location == 'outside_left':
                style_kwargs['legend_position'] = 'left'
            else:
                style_kwargs['legend_position'] = 'right'

        # Apply legend options to the overlay
        self.overlay = self.overlay.opts(
            show_legend=True,
            legend_opts={
                'click_policy': 'hide',
                'background_fill_alpha': 0.6
            },
            **style_kwargs
        )

        return self.overlay

# Register the HoloViews backend
register_backend('holoviews', HoloViewsBackend)