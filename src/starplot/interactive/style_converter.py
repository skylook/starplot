"""Style conversion utilities: starplot styles → Plotly equivalents."""

import math

import numpy as np

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
    # ``asterisk`` is a compact native starburst accepted by both plotly.py
    # and plotly.js, unlike a custom SVG marker path.
    "star_8": "asterisk",
    # plotly.py 5.24.1 does not validate arbitrary SVG path marker strings, so
    # the Python adapter keeps the circle approximation. The browser JS adapter
    # overrides this with the actual rotated ellipse SVG path.
    "ellipse": "circle",
    "circle_crosshair": "circle-cross",  # approximation
    "circle_line": "circle",  # approximation
    "circle_dotted_edge": "circle",  # approximation
    "circle_dotted_rings": "circle-dot",  # approximation
    "square_stripes_diagonal": "square",  # approximation
    "sun": "star",  # approximation
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
    symbol: str | None = None,
) -> float:
    """Convert matplotlib scatter s parameter (points²) to Plotly marker size (px).

    Matplotlib's default circle marker is normalized to a one-point diameter,
    so an area parameter ``s`` yields a ``sqrt(s)``-point extent. Plotly uses
    a diameter in pixels; scale that extent to the target viewport.
    """
    if mpl_size <= 0:
        return float(min_size)

    source_width = source_axes_width or resolution
    diameter = math.sqrt(mpl_size) * _marker_extent_factor(symbol) * _marker_scale(
        dpi=dpi,
        target_width=width,
        source_axes_width=source_width,
        kaleido_scale=1.0,
    )
    return max(float(min_size), diameter)


def _marker_scale(
    *,
    dpi: float,
    target_width: float,
    source_axes_width: float,
    kaleido_scale: float,
) -> float:
    """Shared unit conversion used by scalar and array marker calibration."""
    return (
        (float(dpi) / 72.0)
        * (float(target_width) / float(source_axes_width))
        * float(kaleido_scale)
    )


def _marker_extent_factor(symbol: str | None) -> float:
    """Map Matplotlib marker-path extents to the equivalent Plotly diameter."""
    # Plotly renders these compact Starplot glyphs at roughly twice the visual
    # diameter of Matplotlib's corresponding marker path for the same scatter
    # area. Ordinary circles and squares already agree directly.
    if symbol in {"point", "star_4", "star_8"}:
        return 0.5
    # Matplotlib scales custom paths so the bounding-box width equals sqrt(s).
    # The ellipse path's major axis is 2.0 units while its bbox width is ~1.9488,
    # so the rendered major axis is 2/1.9488 times the sqrt(s) extent.
    if symbol == "ellipse":
        return 2.0 / 1.948776650870625
    return 1.0


def calibrate_marker_sizes_array(
    mpl_sizes,
    *,
    dpi: float,
    target_width: float,
    source_axes_width: float,
    min_size: float = 1.5,
    kaleido_scale: float = 1.15,
    symbol: str | None = None,
) -> np.ndarray:
    """Vectorized Matplotlib default-circle extent to Plotly diameter conversion."""
    sizes = np.asarray(mpl_sizes, dtype=np.float32)
    if sizes.ndim != 1:
        raise ValueError("mpl_sizes must be one-dimensional")
    if not np.all(np.isfinite(sizes)):
        raise ValueError("mpl_sizes must be finite")

    dimensions = {
        "dpi": dpi,
        "target_width": target_width,
        "source_axes_width": source_axes_width,
    }
    normalized_dimensions = {}
    for name, value in dimensions.items():
        try:
            numeric_value = float(value)
        except (TypeError, ValueError) as error:
            raise ValueError(
                f"{name} must be finite and greater than zero"
            ) from error
        if not math.isfinite(numeric_value) or numeric_value <= 0:
            raise ValueError(f"{name} must be finite and greater than zero")
        normalized_dimensions[name] = numeric_value
    if not np.isfinite(min_size) or min_size < 0:
        raise ValueError("min_size must be finite and non-negative")
    if not np.isfinite(kaleido_scale) or kaleido_scale <= 0:
        raise ValueError("kaleido_scale must be finite and greater than zero")

    scale = np.float32(
        _marker_scale(
            **normalized_dimensions,
            kaleido_scale=1.0,
        )
    )
    diameters = (
        np.sqrt(np.maximum(sizes, np.float32(0.0)))
        * np.float32(_marker_extent_factor(symbol))
        * scale
    )
    result = (
        np.maximum(np.float32(min_size), diameters)
        * np.float32(kaleido_scale)
    ).astype(np.float32, copy=False)
    if not result.flags.c_contiguous or not result.flags.owndata:
        result = np.array(result, dtype=np.float32, copy=True, order="C")
    result.setflags(write=False)
    return result


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
