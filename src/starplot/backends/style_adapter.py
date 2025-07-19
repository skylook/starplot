"""
Style adapter for converting starplot styles to backend-specific styles
"""
from typing import Dict, Any, Union
import numpy as np
from starplot.styles import PlotStyle, ObjectStyle, LabelStyle, PathStyle, MarkerStyle


class StyleAdapter:
    """Adapter for converting starplot styles to backend-specific formats"""
    
    @staticmethod
    def convert_color(color) -> str:
        """Convert color to hex string"""
        if hasattr(color, 'as_hex'):
            return color.as_hex()
        elif isinstance(color, str):
            return color
        else:
            return str(color)
    
    @staticmethod
    def matplotlib_star_style(style: ObjectStyle) -> Dict[str, Any]:
        """Convert ObjectStyle to matplotlib scatter kwargs"""
        return {
            'c': StyleAdapter.convert_color(style.marker.color),
            'edgecolors': StyleAdapter.convert_color(style.marker.edge_color) if style.marker.edge_color else 'none',
            'alpha': style.marker.alpha,
            'marker': style.marker.symbol_matplot,
            'zorder': style.marker.zorder,
        }
    
    @staticmethod
    def plotly_star_style(style: ObjectStyle) -> Dict[str, Any]:
        """Convert ObjectStyle to plotly scatter kwargs"""
        return {
            'mode': 'markers',
            'marker': {
                'color': StyleAdapter.convert_color(style.marker.color),
                'opacity': style.marker.alpha,
                'symbol': StyleAdapter.convert_marker_symbol(style.marker.symbol_matplot),
                'line': {
                    'color': StyleAdapter.convert_color(style.marker.edge_color) if style.marker.edge_color else None,
                    'width': 0 if not style.marker.edge_color else 1,
                }
            },
            'showlegend': False,
            'hoverinfo': 'none',
        }
    
    @staticmethod
    def matplotlib_line_style(style: PathStyle) -> Dict[str, Any]:
        """Convert PathStyle to matplotlib line kwargs"""
        return {
            'color': StyleAdapter.convert_color(style.color),
            'linewidth': style.width,
            'linestyle': style.style,
            'alpha': style.alpha,
            'zorder': style.zorder,
        }
    
    @staticmethod
    def plotly_line_style(style: PathStyle) -> Dict[str, Any]:
        """Convert PathStyle to plotly line kwargs"""
        return {
            'mode': 'lines',
            'line': {
                'color': StyleAdapter.convert_color(style.color),
                'width': style.width,
                'dash': StyleAdapter.convert_linestyle(style.style),
            },
            'opacity': style.alpha,
            'showlegend': False,
            'hoverinfo': 'none',
        }
    
    @staticmethod
    def matplotlib_text_style(style: LabelStyle) -> Dict[str, Any]:
        """Convert LabelStyle to matplotlib text kwargs"""
        return {
            'fontsize': style.font_size,
            'color': StyleAdapter.convert_color(style.color),
            'fontfamily': style.font_family,
            'fontweight': style.font_weight,
            'ha': style.anchor_point.value if hasattr(style.anchor_point, 'value') else 'center',
            'va': 'center',
            'alpha': style.alpha,
            'zorder': style.zorder,
        }
    
    @staticmethod
    def plotly_text_style(style: LabelStyle) -> Dict[str, Any]:
        """Convert LabelStyle to plotly text kwargs"""
        return {
            'font': {
                'size': style.font_size,
                'color': StyleAdapter.convert_color(style.color),
                'family': style.font_family,
            },
            'opacity': style.alpha,
            'xanchor': StyleAdapter.convert_text_anchor(style.anchor_point),
            'yanchor': 'middle',
        }
    
    @staticmethod
    def convert_marker_symbol(matplotlib_symbol: str) -> str:
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
        return marker_map.get(matplotlib_symbol, 'circle')
    
    @staticmethod
    def convert_linestyle(matplotlib_style: str) -> str:
        """Convert matplotlib linestyle to plotly dash"""
        style_map = {
            '-': 'solid',
            '--': 'dash',
            '-.': 'dashdot',
            ':': 'dot',
            'solid': 'solid',
            'dashed': 'dash',
            'dashdot': 'dashdot',
            'dotted': 'dot',
        }
        return style_map.get(matplotlib_style, 'solid')
    
    @staticmethod
    def convert_text_anchor(anchor_point) -> str:
        """Convert starplot anchor point to plotly text anchor"""
        if hasattr(anchor_point, 'value'):
            anchor_value = anchor_point.value
        else:
            anchor_value = str(anchor_point)
        
        anchor_map = {
            'center': 'center',
            'left': 'left',
            'right': 'right',
            'bottom': 'left',
            'top': 'right',
        }
        return anchor_map.get(anchor_value, 'center')