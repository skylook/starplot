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

    def holoviews_kwargs(self, scale: float = 1.0) -> dict:
        """Convert style to HoloViews kwargs"""
        raise NotImplementedError


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
            's': (self.size * scale) ** 2,  # Convert to area
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
            
        # Ensure full hex color format
        for color_key in ['color', 'edgecolor']:
            if style[color_key] and len(style[color_key]) == 4:  # #rgb format
                r = style[color_key][1]
                g = style[color_key][2]
                b = style[color_key][3]
                style[color_key] = f"#{r}{r}{g}{g}{b}{b}"
            
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
    """Text border (aka halos) width. This will apply to _all_ text labels on the plot."""

    text_border_color: ColorStr = ColorStr("#fff")

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

    # Info text
    info_text: LabelStyle = LabelStyle(
        font_size=30,
        zorder=ZOrderEnum.LAYER_5,
        font_family="Inter",
        line_spacing=1.2,
        anchor_point=AnchorPointEnum.BOTTOM_CENTER,
    )

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

    # DSOs
    dso_open_cluster: ObjectStyle = ObjectStyle(
        marker=MarkerStyle(
            symbol=MarkerSymbolEnum.CIRCLE,
            size=40,
            color="#000",
            edge_color=None,
            fill=FillStyleEnum.FULL,
            zorder=ZOrderEnum.LAYER_3,
        ),
        label=LabelStyle(
            font_size=24,
            font_weight=FontWeightEnum.BOLD,
            zorder=ZOrderEnum.LAYER_3 + 1,
            offset_x="auto",
            offset_y="auto",
        ),
    )

    dso_globular_cluster: ObjectStyle = ObjectStyle(
        marker=MarkerStyle(
            symbol=MarkerSymbolEnum.CIRCLE,
            size=40,
            color="#000",
            edge_color=None,
            fill=FillStyleEnum.FULL,
            zorder=ZOrderEnum.LAYER_3,
        ),
        label=LabelStyle(
            font_size=24,
            font_weight=FontWeightEnum.BOLD,
            zorder=ZOrderEnum.LAYER_3 + 1,
            offset_x="auto",
            offset_y="auto",
        ),
    )

    dso_galaxy: ObjectStyle = ObjectStyle(
        marker=MarkerStyle(
            symbol=MarkerSymbolEnum.ELLIPSE,
            size=40,
            color="#000",
            edge_color=None,
            fill=FillStyleEnum.FULL,
            zorder=ZOrderEnum.LAYER_3,
        ),
        label=LabelStyle(
            font_size=24,
            font_weight=FontWeightEnum.BOLD,
            zorder=ZOrderEnum.LAYER_3 + 1,
            offset_x="auto",
            offset_y="auto",
        ),
    )

    dso_nebula: ObjectStyle = ObjectStyle(
        marker=MarkerStyle(
            symbol=MarkerSymbolEnum.CIRCLE,
            size=40,
            color="#000",
            edge_color=None,
            fill=FillStyleEnum.FULL,
            zorder=ZOrderEnum.LAYER_3,
        ),
        label=LabelStyle(
            font_size=24,
            font_weight=FontWeightEnum.BOLD,
            zorder=ZOrderEnum.LAYER_3 + 1,
            offset_x="auto",
            offset_y="auto",
        ),
    )

    dso_planetary_nebula: ObjectStyle = ObjectStyle(
        marker=MarkerStyle(
            symbol=MarkerSymbolEnum.CIRCLE_CROSSHAIR,
            size=40,
            color="#000",
            edge_color=None,
            fill=FillStyleEnum.FULL,
            zorder=ZOrderEnum.LAYER_3,
        ),
        label=LabelStyle(
            font_size=24,
            font_weight=FontWeightEnum.BOLD,
            zorder=ZOrderEnum.LAYER_3 + 1,
            offset_x="auto",
            offset_y="auto",
        ),
    )

    dso_double_star: ObjectStyle = ObjectStyle(
        marker=MarkerStyle(
            symbol=MarkerSymbolEnum.CIRCLE_LINE,
            size=40,
            color="#000",
            edge_color=None,
            fill=FillStyleEnum.FULL,
            zorder=ZOrderEnum.LAYER_3,
        ),
        label=LabelStyle(
            font_size=24,
            font_weight=FontWeightEnum.BOLD,
            zorder=ZOrderEnum.LAYER_3 + 1,
            offset_x="auto",
            offset_y="auto",
        ),
    )

    dso_association_stars: ObjectStyle = ObjectStyle(
        marker=MarkerStyle(
            symbol=MarkerSymbolEnum.CIRCLE,
            size=40,
            color="#000",
            edge_color=None,
            fill=FillStyleEnum.FULL,
            zorder=ZOrderEnum.LAYER_3,
        ),
        label=LabelStyle(
            font_size=24,
            font_weight=FontWeightEnum.BOLD,
            zorder=ZOrderEnum.LAYER_3 + 1,
            offset_x="auto",
            offset_y="auto",
        ),
    )

    dso_dark_nebula: ObjectStyle = ObjectStyle(
        marker=MarkerStyle(
            symbol=MarkerSymbolEnum.CIRCLE,
            size=40,
            color="#000",
            edge_color=None,
            fill=FillStyleEnum.FULL,
            zorder=ZOrderEnum.LAYER_3,
        ),
        label=LabelStyle(
            font_size=24,
            font_weight=FontWeightEnum.BOLD,
            zorder=ZOrderEnum.LAYER_3 + 1,
            offset_x="auto",
            offset_y="auto",
        ),
    )

    dso_hii_ionized_region: ObjectStyle = ObjectStyle(
        marker=MarkerStyle(
            symbol=MarkerSymbolEnum.CIRCLE,
            size=40,
            color="#000",
            edge_color=None,
            fill=FillStyleEnum.FULL,
            zorder=ZOrderEnum.LAYER_3,
        ),
        label=LabelStyle(
            font_size=24,
            font_weight=FontWeightEnum.BOLD,
            zorder=ZOrderEnum.LAYER_3 + 1,
            offset_x="auto",
            offset_y="auto",
        ),
    )

    dso_supernova_remnant: ObjectStyle = ObjectStyle(
        marker=MarkerStyle(
            symbol=MarkerSymbolEnum.CIRCLE,
            size=40,
            color="#000",
            edge_color=None,
            fill=FillStyleEnum.FULL,
            zorder=ZOrderEnum.LAYER_3,
        ),
        label=LabelStyle(
            font_size=24,
            font_weight=FontWeightEnum.BOLD,
            zorder=ZOrderEnum.LAYER_3 + 1,
            offset_x="auto",
            offset_y="auto",
        ),
    )

    dso_nova_star: ObjectStyle = ObjectStyle(
        marker=MarkerStyle(
            symbol=MarkerSymbolEnum.STAR,
            size=40,
            color="#000",
            edge_color=None,
            fill=FillStyleEnum.FULL,
            zorder=ZOrderEnum.LAYER_3,
        ),
        label=LabelStyle(
            font_size=24,
            font_weight=FontWeightEnum.BOLD,
            zorder=ZOrderEnum.LAYER_3 + 1,
            offset_x="auto",
            offset_y="auto",
        ),
    )

    dso_nonexistant: ObjectStyle = ObjectStyle(
        marker=MarkerStyle(
            symbol=MarkerSymbolEnum.CIRCLE,
            size=40,
            color="#000",
            edge_color=None,
            fill=FillStyleEnum.FULL,
            zorder=ZOrderEnum.LAYER_3,
        ),
        label=LabelStyle(
            font_size=24,
            font_weight=FontWeightEnum.BOLD,
            zorder=ZOrderEnum.LAYER_3 + 1,
            offset_x="auto",
            offset_y="auto",
        ),
    )

    dso_unknown: ObjectStyle = ObjectStyle(
        marker=MarkerStyle(
            symbol=MarkerSymbolEnum.CIRCLE,
            size=40,
            color="#000",
            edge_color=None,
            fill=FillStyleEnum.FULL,
            zorder=ZOrderEnum.LAYER_3,
        ),
        label=LabelStyle(
            font_size=24,
            font_weight=FontWeightEnum.BOLD,
            zorder=ZOrderEnum.LAYER_3 + 1,
            offset_x="auto",
            offset_y="auto",
        ),
    )

    dso_duplicate: ObjectStyle = ObjectStyle(
        marker=MarkerStyle(
            symbol=MarkerSymbolEnum.CIRCLE,
            size=40,
            color="#000",
            edge_color=None,
            fill=FillStyleEnum.FULL,
            zorder=ZOrderEnum.LAYER_3,
        ),
        label=LabelStyle(
            font_size=24,
            font_weight=FontWeightEnum.BOLD,
            zorder=ZOrderEnum.LAYER_3 + 1,
            offset_x="auto",
            offset_y="auto",
        ),
    )

    # Legend
    legend: LegendStyle = LegendStyle()

    # Constellation
    constellation_lines: LineStyle = LineStyle()
    constellation_labels: LabelStyle = LabelStyle()

    # Additional fields
    bayer_labels: LabelStyle = LabelStyle()
    flamsteed_labels: LabelStyle = LabelStyle()
    planets: ObjectStyle = ObjectStyle()
    ecliptic: PathStyle = PathStyle()
    celestial_equator: PathStyle = PathStyle()

    # Text anchor fallbacks
    text_anchor_fallbacks: list[str] = [
        "bottom right",
        "top right",
        "top left",
        "bottom left",
    ]

    class Config:
        validate_assignment = True
        extra = "forbid"  # 不允许额外的字段

    def extend(self, extension: dict) -> "PlotStyle":
        """Extend the current style with additional settings from a dictionary.
        
        Args:
            extension: Dictionary containing additional style settings
            
        Returns:
            A new PlotStyle instance with the combined settings
        """
        from starplot.styles.helpers import merge_dict
        
        # Create a copy of current style as dict
        current = self.model_dump()
        
        # Merge the extension with current style
        merged = merge_dict(current, extension)
        
        # Create new style instance with merged settings
        return PlotStyle.model_validate(merged)

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
