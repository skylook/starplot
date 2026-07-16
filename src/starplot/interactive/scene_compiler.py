"""Vectorized helpers for compiling high-volume interactive Scene layers."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from matplotlib.colors import to_hex, to_rgba
import numpy as np
import shapely
from shapely.geometry import Polygon

from starplot.interactive.scene import (
    ClipGeometry,
    ColumnarData,
    _seal_owned_array,
    readonly_array,
)


@dataclass(frozen=True)
class PaletteEncoding:
    """Compact per-point color references with separate numeric opacity."""

    palette: tuple[str, ...]
    color_index: np.ndarray
    opacity: np.ndarray

    def __post_init__(self):
        palette = tuple(self.palette)
        palette_size = len(palette)
        if palette_size > 65_536:
            raise ValueError("palette cannot contain more than 65,536 colors")

        raw_color_index = np.asarray(self.color_index)
        raw_opacity = np.asarray(self.opacity)
        if raw_color_index.ndim != 1 or raw_opacity.ndim != 1:
            raise ValueError("palette arrays must be one-dimensional")
        try:
            invalid_index = (raw_color_index < 0) | (
                raw_color_index >= palette_size
            )
        except TypeError as error:
            raise ValueError("color_index must contain numeric indices") from error
        if np.any(invalid_index):
            raise ValueError("color_index contains an entry outside the palette")

        index_dtype = np.uint8 if palette_size <= 256 else np.uint16
        color_index = readonly_array(raw_color_index, dtype=index_dtype)
        opacity = readonly_array(raw_opacity, dtype=np.float32)

        if len(color_index) != len(opacity):
            raise ValueError("color_index and opacity must have the same length")
        if not np.all(np.isfinite(opacity)):
            raise ValueError("opacity values must be finite")

        object.__setattr__(self, "palette", palette)
        object.__setattr__(self, "color_index", color_index)
        object.__setattr__(self, "opacity", opacity)


def _aligned_xy(x, y) -> tuple[np.ndarray, np.ndarray]:
    x_array = np.asarray(x)
    y_array = np.asarray(y)
    if x_array.ndim != 1 or y_array.ndim != 1:
        raise ValueError("scatter x and y must be one-dimensional")
    if len(x_array) != len(y_array):
        raise ValueError("scatter x and y must have the same length")
    return x_array, y_array


def scatter_clip_mask(x, y, clip: ClipGeometry) -> np.ndarray:
    """Return a vectorized mask for aligned scatter coordinates."""
    if not isinstance(clip, ClipGeometry):
        raise TypeError("clip must be a Scene ClipGeometry")

    x_array, y_array = _aligned_xy(x, y)
    try:
        finite = np.isfinite(x_array) & np.isfinite(y_array)
    except TypeError as error:
        raise ValueError("scatter x and y must contain finite numeric values") from error

    if clip.kind == "rect":
        points = np.asarray(clip.points, dtype=np.float64)
        x_min = np.min(points[:, 0])
        x_max = np.max(points[:, 0])
        y_min = np.min(points[:, 1])
        y_max = np.max(points[:, 1])
        inside = (
            (x_array >= x_min)
            & (x_array <= x_max)
            & (y_array >= y_min)
            & (y_array <= y_max)
        )
    else:
        inside = shapely.contains_xy(Polygon(clip.points), x_array, y_array)

    return np.asarray(inside & finite, dtype=np.bool_)


def filter_columns(data: ColumnarData, mask) -> ColumnarData:
    """Apply one validated boolean mask without recopying selected columns."""
    if not isinstance(data, ColumnarData):
        raise TypeError("data must be an existing ColumnarData")

    mask_array = np.asarray(mask)
    if mask_array.dtype != np.bool_:
        raise TypeError("mask must be a boolean array")
    if mask_array.ndim != 1:
        raise ValueError("mask must be one-dimensional")
    if len(mask_array) != data.row_count:
        raise ValueError("mask length must match the ColumnarData row count")

    columns = {}
    for name, column in data.columns.items():
        selected = column[mask_array]
        columns[name] = _seal_owned_array(selected)

    instance = object.__new__(ColumnarData)
    object.__setattr__(instance, "columns", MappingProxyType(columns))
    object.__setattr__(instance, "row_count", int(np.count_nonzero(mask_array)))
    return instance


def _opacity_values(opacity, row_count: int) -> np.ndarray:
    values = np.asarray(opacity, dtype=np.float32)
    if values.ndim == 0:
        values = np.full(row_count, values.item(), dtype=np.float32)
    elif values.ndim != 1:
        raise ValueError("opacity must be scalar or one-dimensional")
    elif len(values) != row_count:
        raise ValueError("opacity must have the same length as colors")
    if not np.all(np.isfinite(values)):
        raise ValueError("opacity values must be finite")
    return values


def encode_palette(colors, opacity) -> PaletteEncoding:
    """Encode colors once per unique value and retain numeric per-point alpha."""
    color_values = np.asarray(colors)
    if color_values.ndim != 1:
        raise ValueError("colors must be one-dimensional")

    unique_colors, inverse = np.unique(color_values, return_inverse=True)
    palette_size = len(unique_colors)
    if palette_size > 65_536:
        raise ValueError("palette cannot contain more than 65,536 colors")

    palette = []
    source_alpha = np.empty(palette_size, dtype=np.float32)
    for index, color in enumerate(unique_colors):
        red, green, blue, alpha = to_rgba(color)
        palette.append(to_hex((red, green, blue), keep_alpha=False))
        source_alpha[index] = alpha

    opacity_values = _opacity_values(opacity, len(color_values))
    combined_opacity = opacity_values * source_alpha[inverse]
    index_dtype = np.uint8 if palette_size <= 256 else np.uint16
    color_index = inverse.astype(index_dtype, copy=True)
    return PaletteEncoding(tuple(palette), color_index, combined_opacity)
