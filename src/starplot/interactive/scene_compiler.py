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


def _validated_opacity_values(
    opacity,
    row_count: int,
    *,
    allow_scalar: bool,
) -> np.ndarray:
    raw_values = np.asarray(opacity)
    if raw_values.ndim == 0 and allow_scalar:
        raw_values = np.full(row_count, raw_values.item())
    elif raw_values.ndim != 1:
        shape_contract = (
            "scalar or one-dimensional" if allow_scalar else "one-dimensional"
        )
        raise ValueError(f"opacity must be {shape_contract}")
    if len(raw_values) != row_count:
        raise ValueError("opacity must have the same length as colors")

    try:
        finite = np.isfinite(raw_values)
        in_range = (raw_values >= 0.0) & (raw_values <= 1.0)
    except TypeError as error:
        raise ValueError("opacity values must be finite numbers") from error
    if not np.all(finite):
        raise ValueError("opacity values must be finite")
    if not np.all(in_range):
        raise ValueError("opacity values must be between 0 and 1")
    return np.asarray(raw_values, dtype=np.float32)


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
        if not all(isinstance(color, str) for color in palette):
            raise ValueError("palette must contain only RGB strings")

        raw_color_index = self.color_index
        if (
            not isinstance(raw_color_index, np.ndarray)
            or raw_color_index.ndim != 1
            or raw_color_index.dtype.kind not in {"i", "u"}
        ):
            raise ValueError("color_index must be a one-dimensional integer ndarray")
        invalid_index = (raw_color_index < 0) | (
            raw_color_index >= palette_size
        )
        if np.any(invalid_index):
            raise ValueError("color_index contains an entry outside the palette")

        opacity_values = _validated_opacity_values(
            self.opacity,
            len(raw_color_index),
            allow_scalar=False,
        )
        index_dtype = np.uint8 if palette_size <= 256 else np.uint16
        color_index = readonly_array(raw_color_index, dtype=index_dtype)
        opacity = readonly_array(opacity_values, dtype=np.float32)

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
        if x_min >= x_max or y_min >= y_max:
            raise ValueError("rectangle clip must have positive width and height")
        inside = (
            (x_array >= x_min)
            & (x_array <= x_max)
            & (y_array >= y_min)
            & (y_array <= y_max)
        )
    else:
        polygon = Polygon(clip.points)
        if polygon.is_empty or not polygon.is_valid or polygon.area <= 0:
            raise ValueError(
                "polygon clip must be non-empty, valid, positive-area geometry"
            )
        inside = shapely.contains_xy(polygon, x_array, y_array)

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


def encode_palette(colors, opacity) -> PaletteEncoding:
    """Encode colors once per unique value and retain numeric per-point alpha."""
    color_error = "colors must be a one-dimensional string array"
    try:
        color_values = np.asarray(colors)
    except (TypeError, ValueError) as error:
        raise ValueError(color_error) from error
    if (
        color_values.ndim == 1
        and color_values.size == 0
        and not isinstance(colors, np.ndarray)
    ):
        color_values = np.asarray([], dtype=str)
    if color_values.ndim != 1 or color_values.dtype.kind != "U":
        raise ValueError(color_error)

    opacity_values = _validated_opacity_values(
        opacity,
        len(color_values),
        allow_scalar=True,
    )

    unique_colors, inverse = np.unique(color_values, return_inverse=True)
    palette_size = len(unique_colors)
    if palette_size > 65_536:
        raise ValueError("palette cannot contain more than 65,536 colors")

    palette = []
    source_alpha = np.empty(palette_size, dtype=np.float32)
    for index, color in enumerate(unique_colors):
        try:
            red, green, blue, alpha = to_rgba(color)
        except (TypeError, ValueError) as error:
            raise ValueError(
                f"Invalid Matplotlib color spec {str(color)!r}"
            ) from error
        palette.append(to_hex((red, green, blue), keep_alpha=False))
        source_alpha[index] = alpha

    combined_opacity = opacity_values * source_alpha[inverse]
    index_dtype = np.uint8 if palette_size <= 256 else np.uint16
    color_index = inverse.astype(index_dtype, copy=True)
    return PaletteEncoding(tuple(palette), color_index, combined_opacity)
