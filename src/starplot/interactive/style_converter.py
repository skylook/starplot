"""Style conversion utilities: starplot styles → Plotly equivalents."""

# Marker symbol mapping (matplotlib/starplot → Plotly)
MARKER_SYMBOL_MAP = {
    "point": "circle",
    "circle": "circle",
    "square": "square",
    "star": "star",
    "diamond": "diamond",
    "triangle": "triangle-up",
    "plus": "cross",
    "circle_plus": "circle-cross",
    "circle_cross": "circle-x",
    "circle_dot": "circle-dot",
    "comet": "star-diamond",
    "star_4": "star-square",
    "star_8": "star",
    "ellipse": "circle",  # approximation
    ".": "circle",
    "o": "circle",
    "s": "square",
    "*": "star",
    "D": "diamond",
    "^": "triangle-up",
    "+": "cross",
}

# Line style mapping (matplotlib/starplot → Plotly dash)
LINE_STYLE_MAP = {
    "solid": "solid",
    "dashed": "dash",
    "dotted": "dot",
    "dashdot": "dashdot",
    "-": "solid",
    "--": "dash",
    ":": "dot",
    "-.": "dashdot",
}

# Text anchor mapping: matplotlib (va, ha) → Plotly (yanchor, xanchor)
# Note: starplot x-axis is flipped (RA increases right-to-left)
ANCHOR_MAP = {
    ("top", "left"): ("top", "right"),
    ("top", "right"): ("top", "left"),
    ("bottom", "left"): ("bottom", "right"),
    ("bottom", "right"): ("bottom", "left"),
    ("center", "center"): ("middle", "center"),
    ("center", "left"): ("middle", "right"),
    ("center", "right"): ("middle", "left"),
    ("top", "center"): ("top", "center"),
    ("bottom", "center"): ("bottom", "center"),
    ("baseline", "left"): ("bottom", "right"),
    ("baseline", "right"): ("bottom", "left"),
    ("baseline", "center"): ("bottom", "center"),
}


def calibrate_marker_size(
    mpl_size: float,
    resolution: int = 4096,
    width: float = 1000.0,
    dpi: float = 100.0,
    source_axes_width: float = None,
    min_size: float = 1.5,
) -> float:
    """Convert matplotlib scatter s parameter (points²) to Plotly marker size (px).

    matplotlib marker area `s` is in points²; Plotly marker size is the diameter
    in pixels.  The resulting figure width (in pixels) is used to scale the
    diameter so the marker has the same apparent size as the matplotlib output.
    """
    import math
    if mpl_size <= 0:
        return float(min_size)

    source_width = source_axes_width or resolution
    diameter = (
        2.0
        * math.sqrt(mpl_size / math.pi)
        * (dpi / 72.0)
        * (width / source_width)
    )
    return max(float(min_size), diameter)


def convert_marker_style(style_dict: dict, scale: float = 1.0, resolution: int = 4096, width: float = 1000.0) -> dict:
    """Convert starplot marker style dict to Plotly marker dict."""
    size = style_dict.get("size", 10)
    # matplotlib scatter s is area in points²; size is diameter in points
    s = (size * scale) ** 2
    return {
        "symbol": MARKER_SYMBOL_MAP.get(style_dict.get("symbol", "circle"), "circle"),
        "size": calibrate_marker_size(s, resolution=resolution, width=width),
        "color": style_dict.get("color"),
        "opacity": style_dict.get("alpha", 1.0),
        "line": {
            "color": style_dict.get("edge_color", "rgba(0,0,0,0)"),
            "width": style_dict.get("edge_width", 0) * 0.3,
        },
    }


def convert_line_style(style_dict: dict, scale: float = 1.0) -> dict:
    """Convert starplot line style dict to Plotly line dict."""
    return {
        "color": style_dict.get("color", "#777"),
        "width": max(1, style_dict.get("width", 1) * 0.3 * scale),
        "dash": LINE_STYLE_MAP.get(str(style_dict.get("line_style", "solid")), "solid"),
    }


def convert_text_style(style_dict: dict, scale: float = 1.0) -> dict:
    """Convert starplot label style dict to Plotly annotation font dict."""
    va = style_dict.get("va", "center")
    ha = style_dict.get("ha", "center")
    yanchor, xanchor = ANCHOR_MAP.get((va, ha), ("middle", "center"))
    return {
        "font": {
            "size": max(8, style_dict.get("font_size", 12) * 0.4 * scale),
            "color": style_dict.get("font_color", "#000"),
            "family": style_dict.get("font_name", "Inter, Arial, sans-serif"),
        },
        "xanchor": xanchor,
        "yanchor": yanchor,
        "opacity": style_dict.get("alpha", 1.0),
    }


def convert_polygon_style(style_dict: dict, scale: float = 1.0) -> dict:
    """Convert starplot polygon style dict to Plotly fill/line dicts."""
    return {
        "fill": "toself" if style_dict.get("fill_color") else None,
        "fillcolor": style_dict.get("fill_color"),
        "line": {
            "color": style_dict.get("edge_color", "rgba(0,0,0,0)"),
            "width": style_dict.get("edge_width", 0) * 0.3,
            "dash": LINE_STYLE_MAP.get(str(style_dict.get("line_style", "solid")), "solid"),
        },
        "opacity": style_dict.get("alpha", 1.0),
    }
