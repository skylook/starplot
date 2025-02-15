import json

from enum import Enum
from pathlib import Path
from typing import Optional, Union, List

import yaml

from pydantic import BaseModel, Field
from pydantic.color import Color
from pydantic.functional_serializers import PlainSerializer
from matplotlib import patheffects
from typing_extensions import Annotated

from starplot.models.dso import DsoType
from starplot.styles.helpers import merge_dict
from starplot.styles.markers import (
    ellipse,
    circle_cross,
    circle_crosshair,
    circle_line,
    circle_dot,
    circle_dotted_rings,
)


ColorStr = Annotated[
    Color,
    PlainSerializer(
        lambda c: c.as_hex() if c and c != "none" else None,
        return_type=str,
    ),
]


HERE = Path(__file__).resolve().parent

PI = 3.141592653589793
SQR_2 = 1.41421356237


class BaseStyle(BaseModel):
    __hash__ = object.__hash__

    class Config:
        extra = "forbid"
        use_enum_values = True
        validate_assignment = True

    def matplot_kwargs(self, scale: float = 1.0) -> dict:
        """Convert style to matplotlib kwargs"""
        raise NotImplementedError

    def holoviews_kwargs(self, scale: float = 1.0) -> dict:
        """Convert style to HoloViews kwargs"""
        # By default, we'll convert matplotlib kwargs to HoloViews kwargs
        # This provides backward compatibility
        matplot_kw = self.matplot_kwargs(scale)
        converted = {}
        
        # Convert common matplotlib properties to HoloViews properties
        if 'color' in matplot_kw:
            converted['color'] = matplot_kw['color']
        if 'alpha' in matplot_kw:
            converted['alpha'] = matplot_kw['alpha']
        if 'linewidth' in matplot_kw:
            converted['line_width'] = matplot_kw['linewidth']
        if 'linestyle' in matplot_kw:
            converted['line_dash'] = matplot_kw['linestyle']
        if 'marker' in matplot_kw:
            converted['marker'] = matplot_kw['marker']
        if 'markersize' in matplot_kw:
            converted['size'] = matplot_kw['markersize']
        if 'fontsize' in matplot_kw:
            converted['text_font_size'] = f"{matplot_kw['fontsize']}pt"
        if 'fontfamily' in matplot_kw:
            converted['text_font'] = matplot_kw['fontfamily']
        if 'zorder' in matplot_kw:
            converted['z_index'] = matplot_kw['zorder']
            
        return converted


class FillStyleEnum(str, Enum):
    """Constants that represent the possible fill styles for markers."""

    FULL = "full"
    """Fill the marker completely"""

    LEFT = "left"
    """Fill the left half of the marker"""

    RIGHT = "right"
    """Fill the right half of the marker"""

    BOTTOM = "bottom"
    """Fill the bottom half"""

    TOP = "top"
    """Fill the top half"""

    NONE = "none"
    """Do not fill the marker. It'll still have an edge, but the inside will be transparent."""


class FontWeightEnum(str, Enum):
    """Options for font weight."""

    NORMAL = "normal"
    BOLD = "bold"
    HEAVY = "heavy"
    LIGHT = "light"
    ULTRA_BOLD = "ultrabold"
    ULTRA_LIGHT = "ultralight"


class FontStyleEnum(str, Enum):
    NORMAL = "normal"
    ITALIC = "italic"
    OBLIQUE = "oblique"


class MarkerSymbolEnum(str, Enum):
    """Options for marker symbols"""

    POINT = "point"
    """\u00B7"""

    PLUS = "plus"
    """+"""

    CIRCLE = "circle"
    """\u25CF"""

    SQUARE = "square"
    """\u25A0"""

    SQUARE_STRIPES_DIAGONAL = "square_stripes_diagonal"
    """\u25A8"""

    STAR = "star"
    """\u2605"""

    SUN = "sun"
    """\u263C"""

    DIAMOND = "diamond"
    """\u25C6"""

    TRIANGLE = "triangle"
    """\u23F6"""

    CIRCLE_PLUS = "circle_plus"
    """\u2295"""

    CIRCLE_CROSS = "circle_cross"
    """\u1AA0"""

    CIRCLE_CROSSHAIR = "circle_crosshair"
    """No preview available, but this is the standard symbol for planetary nebulae"""

    CIRCLE_DOT = "circle_dot"
    """\u29BF"""

    CIRCLE_DOTTED_EDGE = "circle_dotted_edge"
    """\u25CC"""

    CIRCLE_DOTTED_RINGS = "circle_dotted_rings"

    CIRCLE_LINE = "circle_line"
    """\u29B5  the standard symbol for double stars"""

    COMET = "comet"
    """\u2604"""

    STAR_4 = "star_4"
    """\u2726"""

    STAR_8 = "star_8"
    """\u2734"""

    ELLIPSE = "ellipse"
    """\u2B2D"""

    CROSS = "cross"
    """x"""

    HEXAGON = "hexagon"
    """h"""

    PENTAGON = "pentagon"
    """p"""

    def as_holoviews(self) -> str:
        """Convert marker symbol to HoloViews format"""
        symbol_map = {
            self.POINT: ".",
            self.CIRCLE: "o",
            self.SQUARE: "s",
            self.TRIANGLE: "^",
            self.STAR: "*",
            self.CROSS: "x",
            self.PLUS: "+",
            self.DIAMOND: "d",
            self.HEXAGON: "h",
            self.PENTAGON: "p",
            self.CIRCLE_PLUS: "P",
            self.CIRCLE_CROSS: "X",
            self.CIRCLE_DOT: "o",
            self.CIRCLE_DOTTED_EDGE: "o",
            self.CIRCLE_DOTTED_RINGS: "o",
            self.CIRCLE_LINE: "o",
            self.CIRCLE_CROSSHAIR: "o",
            self.COMET: "*",
            self.STAR_4: "*",
            self.STAR_8: "*",
            self.ELLIPSE: "o",
            self.SQUARE_STRIPES_DIAGONAL: "s",
            self.SUN: "o",
        }
        return symbol_map[self]  # 直接返回映射结果,不需要再次检查


class LineStyleEnum(str, Enum):
    SOLID = "solid"
    DASHED = "dashed"
    DASHED_DOTS = "dashdot"
    DOTTED = "dotted"

    def as_holoviews(self) -> str:
        """Convert line style to HoloViews format"""
        style_map = {
            self.SOLID: "-",
            self.DASHED: "--",
            self.DASHED_DOTS: "-.",
            self.DOTTED: ":",
        }
        return style_map[self]


class DashCapStyleEnum(str, Enum):
    BUTT = "butt"
    PROJECTING = "projecting"
    ROUND = "round"


class LegendLocationEnum(str, Enum):
    """Options for the location of the map legend"""

    INSIDE_TOP = "upper center"
    INSIDE_TOP_LEFT = "upper left"
    INSIDE_TOP_RIGHT = "upper right"
    INSIDE_BOTTOM = "lower center"
    INSIDE_BOTTOM_RIGHT = "lower right"
    INSIDE_BOTTOM_LEFT = "lower left"
    OUTSIDE_TOP = "outside upper center"
    OUTSIDE_BOTTOM = "outside lower center"


class AnchorPointEnum(str, Enum):
    """Options for the anchor point of labels"""

    CENTER = "center"
    LEFT_CENTER = "left center"
    RIGHT_CENTER = "right center"
    TOP_LEFT = "top left"
    TOP_RIGHT = "top right"
    TOP_CENTER = "top center"
    BOTTOM_LEFT = "bottom left"
    BOTTOM_RIGHT = "bottom right"
    BOTTOM_CENTER = "bottom center"

    def as_matplot(self) -> dict:
        style = {}
        # the values below look wrong, but they're inverted because the map coords are inverted
        if self.value == AnchorPointEnum.BOTTOM_LEFT:
            style["va"] = "top"
            style["ha"] = "right"
        elif self.value == AnchorPointEnum.BOTTOM_RIGHT:
            style["va"] = "top"
            style["ha"] = "left"
        elif self.value == AnchorPointEnum.BOTTOM_CENTER:
            style["va"] = "top"
            style["ha"] = "center"
        elif self.value == AnchorPointEnum.TOP_LEFT:
            style["va"] = "bottom"
            style["ha"] = "right"
        elif self.value == AnchorPointEnum.TOP_RIGHT:
            style["va"] = "bottom"
            style["ha"] = "left"
        elif self.value == AnchorPointEnum.TOP_CENTER:
            style["va"] = "bottom"
            style["ha"] = "center"
        elif self.value == AnchorPointEnum.CENTER:
            style["va"] = "center"
            style["ha"] = "center"
        elif self.value == AnchorPointEnum.LEFT_CENTER:
            style["va"] = "center"
            style["ha"] = "right"
        elif self.value == AnchorPointEnum.RIGHT_CENTER:
            style["va"] = "center"
            style["ha"] = "left"

        return style

    @staticmethod
    def from_str(value: str) -> "AnchorPointEnum":
        options = {ap.value: ap for ap in AnchorPointEnum}
        return options.get(value)


class ZOrderEnum(int, Enum):
    """
    Z Order presets for managing layers
    """

    LAYER_1 = -2_000
    """Bottom layer"""

    LAYER_2 = -1_000

    LAYER_3 = 0
    """Middle layer"""

    LAYER_4 = 1_000

    LAYER_5 = 2_000
    """Top layer"""


class MarkerStyle(BaseStyle):
    """
    Styling properties for markers.
    """

    color: Optional[ColorStr] = ColorStr("#000")
    """Fill color of marker. Can be a hex, rgb, hsl, or word string."""

    edge_color: Optional[ColorStr] = ColorStr("#000")
    """Edge color of marker. Can be a hex, rgb, hsl, or word string."""

    edge_width: float = 1
    """Edge width of marker, in points. Not available for all marker symbols."""

    line_style: Union[LineStyleEnum, tuple] = LineStyleEnum.SOLID
    """Edge line style. Can be a predefined value in `LineStyleEnum` or a [Matplotlib linestyle tuple](https://matplotlib.org/stable/gallery/lines_bars_and_markers/linestyles.html)."""

    dash_capstyle: DashCapStyleEnum = DashCapStyleEnum.PROJECTING
    """Style of dash endpoints"""

    symbol: MarkerSymbolEnum = MarkerSymbolEnum.POINT
    """Symbol for marker"""

    size: float = 22
    """Size of marker in points"""

    fill: FillStyleEnum = FillStyleEnum.NONE
    """Fill style of marker"""

    alpha: float = 1.0
    """Alpha value (controls transparency)"""

    zorder: int = ZOrderEnum.LAYER_2
    """Zorder of marker"""

    @property
    def symbol_matplot(self) -> str:
        """Convert marker symbol to matplotlib format"""
        symbol_map = {
            'point': ".",
            'circle': "o",
            'square': "s",
            'triangle': "^",
            'star': "*",
            'cross': "x",
            'plus': "+",
            'diamond': "d",
            'hexagon': "h",
            'pentagon': "p",
            'circle_plus': "P",
            'circle_cross': "X",
            'circle_dot': "o",
            'circle_dotted_edge': "o",
            'circle_dotted_rings': "o",
            'circle_line': "o",
            'circle_crosshair': "o",
            'comet': "*",
            'star_4': "*",
            'star_8': "*",
            'ellipse': "o",
            'square_stripes_diagonal': "s",
            'sun': "o",
        }
        return symbol_map.get(self.symbol, "o")  # Default to circle if symbol not found

    def matplot_kwargs(self, scale: float = 1.0) -> dict:
        return dict(
            color=self.color.as_hex() if self.color else "none",
            markeredgecolor=self.edge_color.as_hex() if self.edge_color else "none",
            marker=self.symbol_matplot,
            markersize=self.size * scale,
            fillstyle=self.fill,
            alpha=self.alpha,
            zorder=self.zorder,
        )

    def matplot_scatter_kwargs(self, scale: float = 1.0) -> dict:
        plot_kwargs = self.matplot_kwargs(scale)
        plot_kwargs["edgecolors"] = plot_kwargs.pop("markeredgecolor")

        # matplotlib's plot() function takes the marker size in points diameter
        # and the scatter() function takes it in points squared
        plot_kwargs["s"] = ((plot_kwargs.pop("markersize") / scale) ** 2) * (scale**2)

        plot_kwargs["c"] = plot_kwargs.pop("color")
        plot_kwargs["linewidths"] = self.edge_width * scale
        plot_kwargs["linestyle"] = self.line_style
        plot_kwargs["capstyle"] = self.dash_capstyle

        plot_kwargs.pop("fillstyle")

        return plot_kwargs

    def to_polygon_style(self):
        return PolygonStyle(
            fill_color=self.color.as_hex() if self.color else None,
            edge_color=self.edge_color.as_hex() if self.edge_color else None,
            edge_width=self.edge_width,
            alpha=self.alpha,
            zorder=self.zorder,
            line_style=self.line_style,
        )

    def holoviews_kwargs(self, scale: float = 1.0) -> dict:
        """Convert marker style to HoloViews kwargs"""
        # Get marker symbol
        marker = "o"  # Default to circle
        if isinstance(self.symbol, MarkerSymbolEnum):
            marker = self.symbol.as_holoviews()
        elif isinstance(self.symbol, str):
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
            marker = marker_map.get(self.symbol, 'o')
            
        style = {
            'marker': marker,
            's': ((self.size / scale) ** 2) * (scale**2),  # Convert to area
            'color': self.color.as_hex() if self.color else None,
            'edgecolor': self.edge_color.as_hex() if self.edge_color else None,
            'linewidth': self.edge_width * scale if self.edge_width else 0,
            'alpha': self.alpha,
            'fill_alpha': self.alpha if self.fill == FillStyleEnum.FULL else 0,
        }
        
        # Handle line style
        if isinstance(self.line_style, LineStyleEnum):
            style['linestyle'] = self.line_style.as_holoviews()
        else:
            style['linestyle'] = self.line_style
            
        # Ensure full color format
        if style['color'] and len(style['color']) == 4:  # #rgb format
            r = style['color'][1]
            g = style['color'][2]
            b = style['color'][3]
            style['color'] = f"#{r}{r}{g}{g}{b}{b}"
            
        if style['edgecolor'] and len(style['edgecolor']) == 4:  # #rgb format
            r = style['edgecolor'][1]
            g = style['edgecolor'][2]
            b = style['edgecolor'][3]
            style['edgecolor'] = f"#{r}{r}{g}{g}{b}{b}"
            
        return style


class LineStyle(BaseStyle):
    """
    Styling properties for lines.
    """

    width: float = 4
    """Width of line in points"""

    color: ColorStr = ColorStr("#000")
    """Color of the line. Can be a hex, rgb, hsl, or word string."""

    style: Union[LineStyleEnum, tuple] = LineStyleEnum.SOLID
    """Style of the line (e.g. solid, dashed, etc). Can be a predefined value in `LineStyleEnum` or a [Matplotlib linestyle tuple](https://matplotlib.org/stable/gallery/lines_bars_and_markers/linestyles.html)."""

    dash_capstyle: DashCapStyleEnum = DashCapStyleEnum.PROJECTING
    """Style of dash endpoints"""

    alpha: float = 1.0
    """Alpha value (controls transparency)"""

    zorder: int = ZOrderEnum.LAYER_2
    """Zorder of the line"""

    edge_width: int = 0
    """Width of the line's edge in points. _If the width or color is falsey then the line will NOT be drawn with an edge._"""

    edge_color: Optional[ColorStr] = None
    """Edge color of the line. _If the width or color is falsey then the line will NOT be drawn with an edge._"""

    def matplot_kwargs(self, scale: float = 1.0) -> dict:
        line_width = self.width * scale

        result = dict(
            color=self.color.as_hex(),
            linestyle=self.style,
            linewidth=line_width,
            # dash_capstyle=self.dash_capstyle,
            alpha=self.alpha,
            zorder=self.zorder,
        )

        if self.edge_width and self.edge_color:
            result["path_effects"] = [
                patheffects.withStroke(
                    linewidth=line_width + 2 * self.edge_width * scale,
                    foreground=self.edge_color.as_hex(),
                )
            ]

        return result

    def matplot_line_collection_kwargs(self, scale: float = 1.0) -> dict:
        plot_kwargs = self.matplot_kwargs(scale)
        plot_kwargs["linewidths"] = plot_kwargs.pop("linewidth")
        plot_kwargs["colors"] = plot_kwargs.pop("color")
        return plot_kwargs

    def holoviews_kwargs(self, scale: float = 1.0) -> dict:
        """Convert line style to HoloViews kwargs"""
        style = {
            'color': self.color.as_hex() if self.color else None,
            'linewidth': self.width * scale,
            'alpha': self.alpha,
        }
        
        # Handle line style
        style_map = {
            'solid': '-',
            'dashed': '--',
            'dashdot': '-.',
            'dotted': ':',
        }
        if isinstance(self.style, str):
            style['linestyle'] = style_map.get(self.style, self.style)
        else:
            style['linestyle'] = self.style
            
        # Add edge effects if specified
        if self.edge_width and self.edge_color:
            style['edgecolor'] = self.edge_color.as_hex()
            style['edge_linewidth'] = self.edge_width * scale
            
        # Ensure full color format
        if style['color'] and len(style['color']) == 4:  # #rgb format
            r = style['color'][1]
            g = style['color'][2]
            b = style['color'][3]
            style['color'] = f"#{r}{r}{g}{g}{b}{b}"
            
        return style


class PolygonStyle(BaseStyle):
    """
    Styling properties for polygons.
    """

    edge_width: float = 1
    """Width of the polygon's edge in points"""

    color: Optional[ColorStr] = None
    """If specified, this will be the fill color AND edge color of the polygon"""

    edge_color: Optional[ColorStr] = None
    """Edge color of the polygon"""

    fill_color: Optional[ColorStr] = None
    """Fill color of the polygon"""

    line_style: Union[LineStyleEnum, tuple] = LineStyleEnum.SOLID
    """Edge line style. Can be a predefined value in `LineStyleEnum` or a [Matplotlib linestyle tuple](https://matplotlib.org/stable/gallery/lines_bars_and_markers/linestyles.html)."""

    alpha: float = 1.0
    """Alpha value (controls transparency)"""

    zorder: int = -1
    """Zorder of the polygon"""

    def matplot_kwargs(self, scale: float = 1.0) -> dict:
        styles = dict(
            edgecolor=self.edge_color.as_hex() if self.edge_color else "none",
            facecolor=self.fill_color.as_hex() if self.fill_color else "none",
            fill=True if self.fill_color or self.color else False,
            linewidth=self.edge_width * scale,
            linestyle=self.line_style,
            alpha=self.alpha,
            zorder=self.zorder,
            capstyle="round",
        )
        if self.color:
            styles["color"] = self.color.as_hex()

        return styles

    def to_marker_style(self, symbol: MarkerSymbolEnum):
        color = self.color.as_hex() if self.color else None
        fill_color = self.fill_color.as_hex() if self.fill_color else None
        fill_style = FillStyleEnum.FULL if color or fill_color else FillStyleEnum.NONE
        return MarkerStyle(
            symbol=symbol,
            color=color or fill_color,
            fill=fill_style,
            edge_color=self.edge_color.as_hex() if self.edge_color else None,
            edge_width=self.edge_width,
            alpha=self.alpha,
            zorder=self.zorder,
            line_style=self.line_style,
        )

    def holoviews_kwargs(self, scale: float = 1.0) -> dict:
        """Convert polygon style to HoloViews kwargs"""
        style = {
            'facecolor': self.fill_color.as_hex() if self.fill_color else None,
            'edgecolor': self.edge_color.as_hex() if self.edge_color else None,
            'linewidth': self.edge_width * scale,
            'alpha': self.alpha,
            'zorder': self.zorder,
        }
        
        # Use color as both fill and edge color if specified
        if self.color:
            style['facecolor'] = self.color.as_hex()
            style['edgecolor'] = self.color.as_hex()
            
        # Handle line style
        if isinstance(self.line_style, LineStyleEnum):
            style['linestyle'] = self.line_style.as_holoviews()
        else:
            style['linestyle'] = self.line_style
            
        # Ensure full color format for fill color
        if style['facecolor'] and len(style['facecolor']) == 4:  # #rgb format
            r = style['facecolor'][1]
            g = style['facecolor'][2]
            b = style['facecolor'][3]
            style['facecolor'] = f"#{r}{r}{g}{g}{b}{b}"
            
        # Ensure full color format for edge color
        if style['edgecolor'] and len(style['edgecolor']) == 4:  # #rgb format
            r = style['edgecolor'][1]
            g = style['edgecolor'][2]
            b = style['edgecolor'][3]
            style['edgecolor'] = f"#{r}{r}{g}{g}{b}{b}"
            
        return style


class LabelStyle(BaseStyle):
    """
    Styling properties for a label.
    """

    font_size: float = 15
    """Font size of the label, in points"""

    font_weight: FontWeightEnum = FontWeightEnum.NORMAL
    """Font weight (e.g. normal, bold, ultra bold, etc)"""

    font_color: ColorStr = ColorStr("#000")
    """Font's color"""

    font_alpha: float = 1
    """Font's alpha (transparency)"""

    font_style: FontStyleEnum = FontStyleEnum.NORMAL
    """Style of the label (e.g. normal, italic, etc)"""

    font_name: Optional[str] = "Inter"
    """Name of the font to use"""

    font_family: Optional[str] = None
    """Font family (e.g. 'monospace', 'sans-serif', 'serif', etc)"""

    line_spacing: Optional[float] = None
    """Spacing between lines of text"""

    anchor_point: AnchorPointEnum = AnchorPointEnum.BOTTOM_RIGHT
    """Anchor point of label"""

    border_width: float = 0
    """Width of border (also known as 'halos') around the text, in points"""

    border_color: Optional[ColorStr] = None
    """Color of border (also known as 'halos') around the text"""

    offset_x: Union[float, int, str] = 0
    """
    Horizontal offset of the label, in points. Negative values supported.
    
    
    **Auto Mode** (_experimental_): If the label is plotted as part of a marker (e.g. stars, via `marker()`, etc), then you can also
    specify the offset as `"auto"` which will calculate the offset automatically based on the marker's size and place
    the label just outside the marker (avoiding overlapping). To enable "auto" mode you have to specify BOTH offsets (x and y) as "auto."
    """

    offset_y: Union[float, int, str] = 0
    """
    Vertical offset of the label, in points. Negative values supported.
    
    **Auto Mode** (_experimental_): If the label is plotted as part of a marker (e.g. stars, via `marker()`, etc), then you can also
    specify the offset as `"auto"` which will calculate the offset automatically based on the marker's size and place
    the label just outside the marker (avoiding overlapping). To enable "auto" mode you have to specify BOTH offsets (x and y) as "auto."
    """

    zorder: int = ZOrderEnum.LAYER_4
    """Zorder of the label"""

    def matplot_kwargs(self, scale: float = 1.0) -> dict:
        style = dict(
            color=self.font_color.as_hex(),
            fontsize=self.font_size * scale,
            fontstyle=self.font_style,
            fontname=self.font_name,
            weight=self.font_weight,
            alpha=self.font_alpha,
            zorder=self.zorder,
        )

        if self.font_family:
            style["family"] = self.font_family
        if self.line_spacing:
            style["linespacing"] = self.line_spacing

        if self.border_width != 0 and self.border_color is not None:
            style["path_effects"] = [
                patheffects.withStroke(
                    linewidth=self.border_width * scale,
                    foreground=self.border_color.as_hex(),
                )
            ]

        style.update(AnchorPointEnum(self.anchor_point).as_matplot())

        return style

    def offset_from_marker(self, marker_symbol, marker_size, scale: float = 1.0):
        if self.offset_x != "auto" or self.offset_y != "auto":
            return self

        new_style = self.model_copy()

        x_direction = -1 if new_style.anchor_point.endswith("left") else 1
        y_direction = -1 if new_style.anchor_point.startswith("bottom") else 1

        offset = (marker_size**0.5 / 2) / scale

        # matplotlib seems to use marker size differently depending on symbol (for scatter)
        # it is NOT strictly the area of the bounding box of the marker
        if marker_symbol in [MarkerSymbolEnum.POINT]:
            offset /= PI

        elif marker_symbol != MarkerSymbolEnum.SQUARE:
            offset /= SQR_2
            offset *= scale

        offset += 1.1

        new_style.offset_x = offset * float(x_direction)
        new_style.offset_y = offset * float(y_direction)

        return new_style

    def holoviews_kwargs(self, scale: float = 1.0) -> dict:
        """Convert label style to HoloViews kwargs"""
        style = {
            'text_font_size': f"{self.font_size * scale}pt",
            'text_font': self.font_name,
            'text_font_family': self.font_family,
            'text_font_style': self.font_style,
            'text_font_weight': self.font_weight,
            'color': self.font_color.as_hex() if self.font_color else None,
            'alpha': self.font_alpha,
            'z_index': self.zorder,
        }
        
        # Handle text alignment based on anchor point
        anchor_map = {
            AnchorPointEnum.CENTER: ('middle', 'center'),
            AnchorPointEnum.LEFT_CENTER: ('middle', 'left'),
            AnchorPointEnum.RIGHT_CENTER: ('middle', 'right'),
            AnchorPointEnum.TOP_LEFT: ('top', 'left'),
            AnchorPointEnum.TOP_RIGHT: ('top', 'right'),
            AnchorPointEnum.TOP_CENTER: ('top', 'center'),
            AnchorPointEnum.BOTTOM_LEFT: ('bottom', 'left'),
            AnchorPointEnum.BOTTOM_RIGHT: ('bottom', 'right'),
            AnchorPointEnum.BOTTOM_CENTER: ('bottom', 'center'),
        }
        baseline, align = anchor_map.get(self.anchor_point, ('middle', 'center'))
        style['text_baseline'] = baseline
        style['text_align'] = align
        
        # Handle line spacing
        if self.line_spacing:
            style['line_spacing'] = self.line_spacing
            
        # Handle text border/halo effect
        if self.border_width and self.border_color:
            style['text_border_width'] = self.border_width * scale
            style['text_border_color'] = self.border_color.as_hex()
            
        # Handle offsets
        if isinstance(self.offset_x, (int, float)):
            style['x_offset'] = self.offset_x * scale
        if isinstance(self.offset_y, (int, float)):
            style['y_offset'] = self.offset_y * scale
            
        # Ensure full color format
        if style['color'] and len(style['color']) == 4:  # #rgb format
            r = style['color'][1]
            g = style['color'][2]
            b = style['color'][3]
            style['color'] = f"#{r}{r}{g}{g}{b}{b}"
            
        return style


class ObjectStyle(BaseStyle):
    """Defines the style for a sky object (e.g. star, DSO)"""

    marker: MarkerStyle = MarkerStyle()
    """Style for the object's marker (see [MarkerStyle][starplot.styles.MarkerStyle])"""

    label: LabelStyle = LabelStyle()
    """Style for the object's label (see [LabelStyle][starplot.styles.LabelStyle])"""


class PathStyle(BaseStyle):
    """Defines the style for a path (e.g. constellation lines)"""

    line: LineStyle = LineStyle()
    """Style for the line (see [LineStyle][starplot.styles.LineStyle])"""

    label: LabelStyle = LabelStyle()
    """Style for the path's label (see [LabelStyle][starplot.styles.LabelStyle])"""


class LegendStyle(BaseStyle):
    """Defines the style for the map legend. *Only applies to map plots.*"""

    location: LegendLocationEnum = LegendLocationEnum.OUTSIDE_BOTTOM
    """Location of the legend, relative to the map area (inside or outside)"""

    background_color: ColorStr = ColorStr("#fff")
    """Background color of the legend box"""

    background_alpha: float = 1.0
    """Background's alpha (transparency)"""

    expand: bool = False
    """If True, the legend will be expanded to fit the full width of the map"""

    num_columns: int = 8
    """Number of columns in the legend"""

    label_padding: float = 1.6
    """Padding between legend labels"""

    symbol_size: int = 34
    """Size of symbols in the legend, in points"""

    symbol_padding: float = 0.2
    """Padding between each symbol and its label"""

    border_padding: float = 1.28
    """Padding around legend border"""

    font_size: int = 23
    """Font size of the legend labels, in points"""

    font_color: ColorStr = ColorStr("#000")
    """Font color for legend labels"""

    zorder: int = ZOrderEnum.LAYER_5
    """Zorder of the legend"""

    def matplot_kwargs(self, scale: float = 1.0) -> dict:
        return dict(
            loc=self.location,
            ncols=self.num_columns,
            framealpha=self.background_alpha,
            fontsize=self.font_size * scale,
            labelcolor=self.font_color.as_hex(),
            borderpad=self.border_padding,
            labelspacing=self.label_padding,
            handletextpad=self.symbol_padding,
            mode="expand" if self.expand else None,
            facecolor=self.background_color.as_hex(),
        )

    def holoviews_kwargs(self, scale: float = 1.0) -> dict:
        """Convert legend style to HoloViews kwargs"""
        style = {
            'location': self.location,
            'legend_cols': self.num_columns,
            'legend_alpha': self.background_alpha,
            'legend_font_size': self.font_size * scale,
            'legend_text_color': self.font_color.as_hex(),
            'legend_padding': self.border_padding,
            'legend_spacing': self.label_padding,
            'legend_handle_padding': self.symbol_padding,
            'legend_mode': 'expand' if self.expand else None,
            'legend_bgcolor': self.background_color.as_hex(),
        }
        
        return style


class PlotStyle(BaseStyle):
    """
    Defines the styling for a plot
    """

    background_color: ColorStr = ColorStr("#fff")
    """Background color of the map region"""

    figure_background_color: ColorStr = ColorStr("#fff")

    text_border_width: int = 2
    """Text border (aka halos) width. This will apply to _all_ text labels on the plot. If you'd like to control these borders by object type, then set this global width to `0` and refer to the label style's `border_width` and `border_color` properties."""

    text_border_color: ColorStr = ColorStr("#fff")

    text_anchor_fallbacks: List[AnchorPointEnum] = [
        AnchorPointEnum.BOTTOM_RIGHT,
        AnchorPointEnum.TOP_LEFT,
        AnchorPointEnum.TOP_RIGHT,
        AnchorPointEnum.BOTTOM_LEFT,
        AnchorPointEnum.BOTTOM_CENTER,
        AnchorPointEnum.TOP_CENTER,
        AnchorPointEnum.RIGHT_CENTER,
        AnchorPointEnum.LEFT_CENTER,
    ]
    """If a label's preferred anchor point results in a collision, then these fallbacks will be tried in sequence until a collision-free position is found."""

    # Borders
    border_font_size: int = 18
    border_font_weight: FontWeightEnum = FontWeightEnum.BOLD
    border_font_color: ColorStr = ColorStr("#000")
    border_line_color: ColorStr = ColorStr("#000")
    border_bg_color: ColorStr = ColorStr("#fff")

    # Title
    title: LabelStyle = LabelStyle(
        font_size=20,
        font_weight=FontWeightEnum.BOLD,
        zorder=ZOrderEnum.LAYER_5,
        line_spacing=48,
        anchor_point=AnchorPointEnum.BOTTOM_CENTER,
    )
    """Styling for info text (only applies to zenith and optic plots)"""

    # Info text
    info_text: LabelStyle = LabelStyle(
        font_size=30,
        zorder=ZOrderEnum.LAYER_5,
        font_family="Inter",
        line_spacing=1.2,
        anchor_point=AnchorPointEnum.BOTTOM_CENTER,
    )
    """Styling for info text (only applies to zenith and optic plots)"""

    # Stars
    star: ObjectStyle = ObjectStyle(
        marker=MarkerStyle(
            fill=FillStyleEnum.FULL,
            zorder=ZOrderEnum.LAYER_3 + 1,
            size=40,
            edge_color=None,
        ),
        label=LabelStyle(
            font_size=24,
            font_weight=FontWeightEnum.BOLD,
            zorder=ZOrderEnum.LAYER_3 + 2,
            offset_x="auto",
            offset_y="auto",
        ),
    )
    """Styling for stars *(see [`ObjectStyle`][starplot.styles.ObjectStyle])*"""

    bayer_labels: LabelStyle = LabelStyle(
        font_size=21,
        font_weight=FontWeightEnum.LIGHT,
        font_name="GFS Didot",
        zorder=ZOrderEnum.LAYER_4,
        anchor_point=AnchorPointEnum.TOP_LEFT,
        offset_x="auto",
        offset_y="auto",
    )
    """Styling for Bayer labels of stars"""

    flamsteed_labels: LabelStyle = LabelStyle(
        font_size=13,
        font_weight=FontWeightEnum.NORMAL,
        zorder=ZOrderEnum.LAYER_4,
        anchor_point=AnchorPointEnum.BOTTOM_LEFT,
        offset_x="auto",
        offset_y="auto",
    )
    """Styling for Flamsteed number labels of stars"""

    planets: ObjectStyle = ObjectStyle(
        marker=MarkerStyle(
            symbol=MarkerSymbolEnum.CIRCLE,
            size=28,
            fill=FillStyleEnum.LEFT,
            zorder=ZOrderEnum.LAYER_3,
            alpha=1,
        ),
        label=LabelStyle(
            font_size=28,
            font_weight=FontWeightEnum.BOLD,
            offset_x="auto",
            offset_y="auto",
        ),
    )
    """Styling for planets"""

    moon: ObjectStyle = ObjectStyle(
        marker=MarkerStyle(
            symbol=MarkerSymbolEnum.CIRCLE,
            size=50,
            fill=FillStyleEnum.FULL,
            color="#c8c8c8",
            alpha=1,
            zorder=ZOrderEnum.LAYER_4,
        ),
        label=LabelStyle(
            font_size=28,
            font_weight=FontWeightEnum.BOLD,
            offset_x="auto",
            offset_y="auto",
        ),
    )
    """Styling for the moon"""

    sun: ObjectStyle = ObjectStyle(
        marker=MarkerStyle(
            symbol=MarkerSymbolEnum.SUN,
            size=80,
            fill=FillStyleEnum.FULL,
            color="#000",
            zorder=ZOrderEnum.LAYER_4 - 100,
        ),
        label=LabelStyle(
            font_size=28,
            font_weight=FontWeightEnum.BOLD,
        ),
    )
    """Styling for the Sun"""

    # Deep Sky Objects (DSOs)
    dso_open_cluster: ObjectStyle = ObjectStyle(
        marker=MarkerStyle(
            symbol=MarkerSymbolEnum.CIRCLE,
            fill=FillStyleEnum.FULL,
            line_style=(0, (1, 2)),
            edge_width=1.3,
            zorder=ZOrderEnum.LAYER_3 - 1,
        ),
        label=LabelStyle(offset_x="auto", offset_y="auto"),
    )
    """Styling for open star clusters"""

    dso_association_stars: ObjectStyle = ObjectStyle(
        marker=MarkerStyle(
            symbol=MarkerSymbolEnum.CIRCLE,
            fill=FillStyleEnum.FULL,
            line_style=(0, (1, 2)),
            edge_width=1.3,
            zorder=ZOrderEnum.LAYER_3 - 1,
        ),
        label=LabelStyle(offset_x="auto", offset_y="auto"),
    )
    """Styling for associations of stars"""

    dso_globular_cluster: ObjectStyle = ObjectStyle(
        marker=MarkerStyle(
            symbol=MarkerSymbolEnum.CIRCLE_CROSS,
            fill=FillStyleEnum.FULL,
            color="#555",
            alpha=0.8,
            edge_width=1.2,
            zorder=ZOrderEnum.LAYER_3 - 1,
        ),
        label=LabelStyle(offset_x="auto", offset_y="auto"),
    )
    """Styling for globular star clusters"""

    dso_galaxy: ObjectStyle = ObjectStyle(
        marker=MarkerStyle(
            symbol=MarkerSymbolEnum.ELLIPSE,
            fill=FillStyleEnum.FULL,
            zorder=ZOrderEnum.LAYER_3 - 1,
        ),
        label=LabelStyle(offset_x="auto", offset_y="auto"),
    )
    """Styling for galaxies"""

    dso_nebula: ObjectStyle = ObjectStyle(
        marker=MarkerStyle(
            symbol=MarkerSymbolEnum.SQUARE,
            fill=FillStyleEnum.FULL,
            zorder=ZOrderEnum.LAYER_3 - 1,
        ),
        label=LabelStyle(offset_x="auto", offset_y="auto"),
    )
    """Styling for nebulas"""

    dso_planetary_nebula: ObjectStyle = ObjectStyle(
        marker=MarkerStyle(
            symbol=MarkerSymbolEnum.CIRCLE_CROSSHAIR,
            fill=FillStyleEnum.FULL,
            edge_width=1.6,
            size=26,
            zorder=ZOrderEnum.LAYER_3 - 1,
        ),
        label=LabelStyle(offset_x="auto", offset_y="auto"),
    )
    """Styling for planetary nebulas"""

    dso_double_star: ObjectStyle = ObjectStyle(
        marker=MarkerStyle(
            symbol=MarkerSymbolEnum.CIRCLE_LINE,
            fill=FillStyleEnum.TOP,
            zorder=ZOrderEnum.LAYER_3 - 1,
        ),
        label=LabelStyle(offset_x=1, offset_y=-1),
    )
    """Styling for double stars"""

    dso_dark_nebula: ObjectStyle = ObjectStyle(
        marker=MarkerStyle(
            symbol=MarkerSymbolEnum.SQUARE,
            fill=FillStyleEnum.TOP,
            color="#000",
            zorder=ZOrderEnum.LAYER_3 - 1,
        ),
        label=LabelStyle(),
    )
    """Styling for dark nebulas"""

    dso_hii_ionized_region: ObjectStyle = ObjectStyle(
        marker=MarkerStyle(
            symbol=MarkerSymbolEnum.SQUARE,
            fill=FillStyleEnum.TOP,
            color="#000",
            zorder=ZOrderEnum.LAYER_3 - 1,
        ),
        label=LabelStyle(),
    )
    """Styling for HII Ionized regions"""

    dso_supernova_remnant: ObjectStyle = ObjectStyle(
        marker=MarkerStyle(
            symbol=MarkerSymbolEnum.SQUARE,
            fill=FillStyleEnum.TOP,
            color="#000",
            zorder=ZOrderEnum.LAYER_3 - 1,
        ),
        label=LabelStyle(),
    )
    """Styling for supernova remnants"""

    dso_nova_star: ObjectStyle = ObjectStyle(
        marker=MarkerStyle(
            symbol=MarkerSymbolEnum.SQUARE,
            fill=FillStyleEnum.TOP,
            color="#000",
            zorder=ZOrderEnum.LAYER_3 - 1,
        ),
        label=LabelStyle(),
    )
    """Styling for nova stars"""

    dso_nonexistant: ObjectStyle = ObjectStyle(
        marker=MarkerStyle(
            symbol=MarkerSymbolEnum.SQUARE,
            fill=FillStyleEnum.TOP,
            color="#000",
            zorder=ZOrderEnum.LAYER_3 - 1,
        ),
        label=LabelStyle(),
    )
    """Styling for 'nonexistent' (as designated by OpenNGC) deep sky objects"""

    dso_unknown: ObjectStyle = ObjectStyle(
        marker=MarkerStyle(
            symbol=MarkerSymbolEnum.SQUARE,
            fill=FillStyleEnum.TOP,
            color="#000",
            zorder=ZOrderEnum.LAYER_3 - 1,
        ),
        label=LabelStyle(),
    )
    """Styling for 'unknown' (as designated by OpenNGC) types of deep sky objects"""

    dso_duplicate: ObjectStyle = ObjectStyle(
        marker=MarkerStyle(
            symbol=MarkerSymbolEnum.SQUARE,
            fill=FillStyleEnum.TOP,
            color="#000",
            zorder=ZOrderEnum.LAYER_3 - 1,
        ),
        label=LabelStyle(),
    )
    """Styling for 'duplicate record' (as designated by OpenNGC) types of deep sky objects"""

    constellation_lines: LineStyle = LineStyle(color="#c8c8c8")
    """Styling for constellation lines"""

    constellation_borders: LineStyle = LineStyle(
        color="#000",
        width=1.5,
        style=LineStyleEnum.DASHED,
        alpha=0.4,
        zorder=ZOrderEnum.LAYER_3,
    )
    """Styling for constellation borders"""

    constellation_labels: LabelStyle = LabelStyle(
        font_size=21,
        font_weight=FontWeightEnum.NORMAL,
        zorder=ZOrderEnum.LAYER_3,
        anchor_point=AnchorPointEnum.CENTER,
    )
    """Styling for constellation labels"""

    # Milky Way
    milky_way: PolygonStyle = PolygonStyle(
        fill_color="#d9d9d9",
        alpha=0.36,
        edge_width=0,
        zorder=ZOrderEnum.LAYER_1,
    )
    """Styling for the Milky Way (only applies to map plots)"""

    # Legend
    legend: LegendStyle = LegendStyle()
    """Styling for legend"""

    # Gridlines
    gridlines: PathStyle = PathStyle(
        line=LineStyle(
            color="#888",
            width=1,
            style=LineStyleEnum.SOLID,
            alpha=0.8,
            zorder=ZOrderEnum.LAYER_2,
        ),
        label=LabelStyle(
            font_size=20,
            font_color="#000",
            font_alpha=1,
            anchor_point=AnchorPointEnum.BOTTOM_CENTER,
        ),
    )
    """Styling for gridlines (including Right Ascension / Declination labels). *Only applies to map plots*."""

    # Ecliptic
    ecliptic: PathStyle = PathStyle(
        line=LineStyle(
            color="#777",
            width=3,
            style=LineStyleEnum.DOTTED,
            dash_capstyle=DashCapStyleEnum.ROUND,
            alpha=1,
            zorder=ZOrderEnum.LAYER_3 - 1,
        ),
        label=LabelStyle(
            font_size=22,
            font_color="#777",
            font_alpha=1,
            zorder=ZOrderEnum.LAYER_3,
        ),
    )
    """Styling for the Ecliptic"""

    # Celestial Equator
    celestial_equator: PathStyle = PathStyle(
        line=LineStyle(
            color="#999",
            width=3,
            style=LineStyleEnum.DASHED_DOTS,
            alpha=0.65,
            zorder=ZOrderEnum.LAYER_3,
        ),
        label=LabelStyle(
            font_size=22,
            font_color="#999",
            font_weight=FontWeightEnum.LIGHT,
            font_alpha=0.65,
            zorder=ZOrderEnum.LAYER_3,
        ),
    )
    """Styling for the Celestial Equator"""

    horizon: PathStyle = PathStyle(
        line=LineStyle(
            color="#fff",
            width=80,
            edge_width=4,
            edge_color="#000",
            style=LineStyleEnum.SOLID,
            dash_capstyle=DashCapStyleEnum.BUTT,
            alpha=1,
            zorder=ZOrderEnum.LAYER_5,
        ),
        label=LabelStyle(
            anchor_point=AnchorPointEnum.CENTER,
            font_color="#000",
            font_size=64,
            font_weight=FontWeightEnum.BOLD,
            zorder=ZOrderEnum.LAYER_5,
        ),
    )
    """Styling for the horizon"""

    zenith: ObjectStyle = ObjectStyle(
        marker=MarkerStyle(
            symbol=MarkerSymbolEnum.TRIANGLE,
            size=24,
            fill=FillStyleEnum.FULL,
            color="#000",
            alpha=0.8,
        ),
        label=LabelStyle(font_size=14, font_weight=FontWeightEnum.BOLD),
    )
    """Styling for the zenith marker"""

    def get_dso_style(self, dso_type: DsoType):
        """Returns the style for a DSO type"""
        styles_by_type = {
            # Star Clusters ----------
            DsoType.OPEN_CLUSTER: self.dso_open_cluster,
            DsoType.GLOBULAR_CLUSTER: self.dso_globular_cluster,
            # Galaxies ----------
            DsoType.GALAXY: self.dso_galaxy,
            DsoType.GALAXY_PAIR: self.dso_galaxy,
            DsoType.GALAXY_TRIPLET: self.dso_galaxy,
            DsoType.GROUP_OF_GALAXIES: self.dso_galaxy,
            # Nebulas ----------
            DsoType.NEBULA: self.dso_nebula,
            DsoType.PLANETARY_NEBULA: self.dso_planetary_nebula,
            DsoType.EMISSION_NEBULA: self.dso_nebula,
            DsoType.STAR_CLUSTER_NEBULA: self.dso_nebula,
            DsoType.REFLECTION_NEBULA: self.dso_nebula,
            # Stars ----------
            DsoType.STAR: self.star,
            DsoType.DOUBLE_STAR: self.dso_double_star,
            DsoType.ASSOCIATION_OF_STARS: self.dso_association_stars,
            # Others ----------
            DsoType.DARK_NEBULA: self.dso_dark_nebula,
            DsoType.HII_IONIZED_REGION: self.dso_hii_ionized_region,
            DsoType.SUPERNOVA_REMNANT: self.dso_supernova_remnant,
            DsoType.NOVA_STAR: self.dso_nova_star,
            DsoType.NONEXISTENT: self.dso_nonexistant,
            DsoType.UNKNOWN: self.dso_unknown,
            DsoType.DUPLICATE_RECORD: self.dso_duplicate,
        }
        return styles_by_type.get(dso_type)

    @staticmethod
    def load_from_file(filename: str) -> "PlotStyle":
        """
        Load a style from a YAML file. The returned style is an extension of the default PlotStyle
        (see [`PlotStyle.extend`][starplot.styles.PlotStyle.extend]), so you only need to define
        properties you want to override from the default.

        Args:
            filename: Filename of style file

        Returns:
            PlotStyle: A new instance of a PlotStyle
        """
        with open(filename, "r") as sfile:
            style = yaml.safe_load(sfile)
            return PlotStyle().extend(style)

    def dump_to_file(self, filename: str) -> None:
        """
        Save the style to a YAML file. ALL style properties will be written to the file.

        Args:
            filename: Filename of style file
        """
        with open(filename, "w") as outfile:
            style_json = self.model_dump_json()
            style_yaml = yaml.dump(json.loads(style_json))
            outfile.write(style_yaml)

    def extend(self, *args, **kwargs) -> "PlotStyle":
        """
        Adds one or more dicts of style overrides to the style and returns a new instance with
        those overrides.

        Styles are added in sequential order, so if the first style arg has a property
        that is also in the last style arg, then the resulting style will have the value
        from the last style (similar to how CSS works).

        ???- tip "Example Usage"
            Create an extension of the default style with the light blue color scheme, map optimizations,
            and change the constellation line color to red:

            ```python

            new_style = PlotStyle().extend(
                styles.extensions.BLUE_LIGHT,
                styles.extensions.MAP,
                {
                    "constellation": {"line": {"color": "#e12d2d"}},
                },
            )
            ```

        Args:
            args: One or more dicts of styles to add

        Returns:
            PlotStyle: A new instance of a PlotStyle
        """
        style_json = self.model_dump_json()
        style_dict = json.loads(style_json)
        for a in args:
            if not isinstance(a, dict):
                raise TypeError("Style overrides must be dictionary types.")
            merge_dict(style_dict, a)
        return PlotStyle.parse_obj(style_dict)
