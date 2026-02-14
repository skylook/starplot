"""
Plotly backend implementation
"""
import numpy as np
from typing import Any, Dict, List, Optional, Tuple, Union
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.express as px
from .base import PlotBackend


class PlotlyBackend(PlotBackend):
    """Plotly backend for starplot"""
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.traces = []
        self.layout_updates = {}
        self.width = kwargs.get('width', 800)
        self.height = kwargs.get('height', 800)
        
    def create_figure(self, width: int, height: int, **kwargs) -> go.Figure:
        """Create plotly figure"""
        self.width = width
        self.height = height
        self.figure = go.Figure()
        
        # Set basic layout
        self.figure.update_layout(
            width=width,
            height=height,
            showlegend=False,
            **kwargs
        )
        return self.figure
    
    def create_subplot(self, projection=None, **kwargs) -> go.Figure:
        """Create plotly subplot (just return figure for now)"""
        # Plotly doesn't have direct cartopy equivalent, 
        # but we can handle projections in coordinate transformation
        return self.figure
    
    def set_xlim(self, xmin: float, xmax: float):
        """Set x-axis limits"""
        self.figure.update_layout(
            xaxis=dict(range=[xmin, xmax])
        )
    
    def set_ylim(self, ymin: float, ymax: float):
        """Set y-axis limits"""
        self.figure.update_layout(
            yaxis=dict(range=[ymin, ymax])
        )
    
    def set_extent(self, extent: List[float], crs=None):
        """Set plot extent"""
        # For plotly, we ignore crs for now and just set axis ranges
        self.figure.update_layout(
            xaxis=dict(range=[extent[0], extent[1]]),
            yaxis=dict(range=[extent[2], extent[3]])
        )
    
    def set_background_color(self, color: str):
        """Set background color"""
        self.figure.update_layout(
            plot_bgcolor=color,
            paper_bgcolor=color
        )
    
    def set_title(self, title: str, **kwargs):
        """Set plot title"""
        self.figure.update_layout(title=title)
    
    def scatter(self, x: np.ndarray, y: np.ndarray, 
                sizes: np.ndarray = None, 
                colors: Union[str, np.ndarray] = None,
                alpha: Union[float, np.ndarray] = None,
                marker: str = 'o',
                edgecolors: str = None,
                **kwargs) -> go.Scatter:
        """Create scatter plot for stars"""
        # Convert matplotlib marker to plotly symbol
        plotly_symbol = self._convert_marker_symbol(marker)
        
        # Handle sizes
        if sizes is not None:
            # Scale sizes for plotly (plotly uses different size scale)
            sizes = np.array(sizes) * 2  # Adjust scaling as needed
        
        # Handle colors
        if isinstance(colors, str):
            marker_color = colors
        elif isinstance(colors, np.ndarray):
            marker_color = colors
        else:
            marker_color = 'blue'
        
        # Handle alpha
        if alpha is not None:
            if isinstance(alpha, (int, float)):
                opacity = alpha
            else:
                opacity = np.mean(alpha)  # Use mean for now
        else:
            opacity = 1.0
        
        # Handle edge colors
        edge_line = dict(width=0)
        if edgecolors and edgecolors != 'none':
            edge_line = dict(color=edgecolors, width=1)
        
        trace = go.Scatter(
            x=x,
            y=y,
            mode='markers',
            marker=dict(
                size=sizes if sizes is not None else 6,
                color=marker_color,
                opacity=opacity,
                symbol=plotly_symbol,
                line=edge_line
            ),
            hoverinfo='none',
            showlegend=False
        )
        
        self.figure.add_trace(trace)
        return trace
    
    def plot_lines(self, x: np.ndarray, y: np.ndarray, 
                   color: str = 'blue', 
                   linewidth: float = 1.0,
                   linestyle: str = '-',
                   **kwargs) -> go.Scatter:
        """Plot lines for constellations"""
        # Convert matplotlib linestyle to plotly
        plotly_dash = self._convert_linestyle(linestyle)
        
        trace = go.Scatter(
            x=x,
            y=y,
            mode='lines',
            line=dict(
                color=color,
                width=linewidth,
                dash=plotly_dash
            ),
            hoverinfo='none',
            showlegend=False,
            **kwargs
        )
        
        self.figure.add_trace(trace)
        return trace
    
    def add_text(self, x: float, y: float, text: str,
                 fontsize: float = 12,
                 color: str = 'black',
                 ha: str = 'center',
                 va: str = 'center',
                 **kwargs) -> go.Scatter:
        """Add text annotation"""
        # Convert matplotlib alignment to plotly
        plotly_ha = self._convert_text_alignment(ha)
        plotly_va = self._convert_text_valignment(va)
        
        annotation = dict(
            x=x,
            y=y,
            text=text,
            showarrow=False,
            font=dict(size=fontsize, color=color),
            xanchor=plotly_ha,
            yanchor=plotly_va,
            **kwargs
        )
        
        # Add to layout annotations
        current_annotations = list(self.figure.layout.annotations or [])
        current_annotations.append(annotation)
        self.figure.update_layout(annotations=current_annotations)
        
        return annotation
    
    def add_polygon(self, points: List[Tuple[float, float]],
                    fill_color: str = None,
                    edge_color: str = None,
                    alpha: float = 1.0,
                    **kwargs) -> go.Scatter:
        """Add polygon shape"""
        # Close the polygon by adding first point at the end
        if points and points[0] != points[-1]:
            points = points + [points[0]]
        
        x_coords = [p[0] for p in points]
        y_coords = [p[1] for p in points]
        
        trace = go.Scatter(
            x=x_coords,
            y=y_coords,
            mode='lines',
            fill='toself' if fill_color else None,
            fillcolor=fill_color,
            line=dict(color=edge_color or 'black', width=1),
            opacity=alpha,
            hoverinfo='none',
            showlegend=False,
            **kwargs
        )
        
        self.figure.add_trace(trace)
        return trace
    
    def set_axis_off(self):
        """Turn off axis display"""
        self.figure.update_layout(
            xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            yaxis=dict(showgrid=False, zeroline=False, showticklabels=False)
        )
    
    def set_aspect_equal(self):
        """Set equal aspect ratio"""
        self.figure.update_layout(
            yaxis=dict(
                scaleanchor="x",
                scaleratio=1,
            )
        )
    
    def export(self, filename: str, dpi: int = 300, format: str = "html", padding: float = 0, **kwargs):
        """Export figure to file"""
        if not self.figure:
            print("Warning: No figure to export")
            return
            
        # Determine format from filename or format parameter
        if filename.endswith('.html'):
            self.figure.write_html(filename, **kwargs)
        elif filename.endswith('.png'):
            try:
                # Try to export as PNG with kaleido
                self.figure.write_image(filename, width=self.width, height=self.height, **kwargs)
            except Exception as e:
                print(f"Warning: PNG export failed ({e}). Falling back to HTML.")
                html_filename = filename.replace('.png', '.html')
                self.figure.write_html(html_filename, **kwargs)
        elif filename.endswith('.svg'):
            try:
                self.figure.write_image(filename, **kwargs)
            except Exception as e:
                print(f"Warning: SVG export failed ({e}). Falling back to HTML.")
                html_filename = filename.replace('.svg', '.html')
                self.figure.write_html(html_filename, **kwargs)
        elif filename.endswith('.pdf'):
            try:
                self.figure.write_image(filename, **kwargs)
            except Exception as e:
                print(f"Warning: PDF export failed ({e}). Falling back to HTML.")
                html_filename = filename.replace('.pdf', '.html')
                self.figure.write_html(html_filename, **kwargs)
        else:
            # Use format parameter or default to HTML
            if format == "html":
                self.figure.write_html(filename, **kwargs)
            elif format in ["png", "svg", "pdf"]:
                try:
                    self.figure.write_image(filename, **kwargs)
                except Exception as e:
                    print(f"Warning: {format} export failed ({e}). Falling back to HTML.")
                    self.figure.write_html(filename + '.html', **kwargs)
            else:
                # Default to HTML
                self.figure.write_html(filename + '.html', **kwargs)
    
    def show(self):
        """Display the plot"""
        self.figure.show()
    
    def close(self):
        """Close the figure"""
        # Plotly doesn't need explicit closing
        pass
    
    def _convert_marker_symbol(self, matplotlib_marker: str) -> str:
        """Convert matplotlib marker to plotly symbol"""
        marker_map = {
            'o': 'circle',
            's': 'square',
            '^': 'triangle-up',
            'v': 'triangle-down',
            '<': 'triangle-left',
            '>': 'triangle-right',
            'd': 'diamond',
            '*': 'star',
            '+': 'cross',
            'x': 'x',
            '|': 'line-ns',
            '_': 'line-ew',
        }
        return marker_map.get(matplotlib_marker, 'circle')
    
    def _convert_linestyle(self, matplotlib_linestyle: str) -> str:
        """Convert matplotlib linestyle to plotly dash"""
        linestyle_map = {
            '-': 'solid',
            '--': 'dash',
            '-.': 'dashdot',
            ':': 'dot',
            'solid': 'solid',
            'dashed': 'dash',
            'dashdot': 'dashdot',
            'dotted': 'dot',
        }
        return linestyle_map.get(matplotlib_linestyle, 'solid')
    
    def _convert_text_alignment(self, matplotlib_ha: str) -> str:
        """Convert matplotlib horizontal alignment to plotly"""
        ha_map = {
            'center': 'center',
            'left': 'left',
            'right': 'right',
        }
        return ha_map.get(matplotlib_ha, 'center')
    
    def _convert_text_valignment(self, matplotlib_va: str) -> str:
        """Convert matplotlib vertical alignment to plotly"""
        va_map = {
            'center': 'middle',
            'top': 'top',
            'bottom': 'bottom',
            'baseline': 'bottom',
        }
        return va_map.get(matplotlib_va, 'middle')