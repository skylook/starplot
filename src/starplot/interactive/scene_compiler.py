"""Vectorized helpers for compiling high-volume interactive Scene layers."""

from __future__ import annotations

from dataclasses import dataclass
import math
from types import MappingProxyType
from typing import Any, Mapping

from matplotlib.colors import to_hex, to_rgba
import numpy as np
import shapely
from shapely.geometry import LineString, Polygon, box

from starplot.interactive.commands import CommandType, CoordinateSpace, DrawingCommand
from starplot.interactive.scene import (
    ClipGeometry,
    ColumnarData,
    CoordinateEncoding,
    CoordinateEncodingKind,
    InteractionPolicy,
    SceneKind,
    SceneLayer,
    ScenePackage,
    _seal_owned_array,
    readonly_array,
)
from starplot.interactive.style_converter import calibrate_marker_sizes_array


COMMAND_COMPILERS = {
    CommandType.SCATTER: "_compile_scatter",
    CommandType.LINE: "_compile_line",
    CommandType.LINE_COLLECTION: "_compile_line_collection",
    CommandType.POLYGON: "_compile_polygon",
    CommandType.TEXT: "_compile_text",
    CommandType.GRADIENT: "_compile_gradient",
    CommandType.INFO_TABLE: "_compile_info_table",
}


def _validated_opacity_values(
    opacity,
    row_count: int,
    *,
    allow_scalar: bool,
) -> np.ndarray:
    raw_values = np.asarray(opacity)
    if raw_values.ndim == 0 and allow_scalar:
        try:
            scalar_value = float(raw_values.item())
        except (TypeError, ValueError) as error:
            raise ValueError("opacity values must be finite numbers") from error
        if not np.isfinite(scalar_value):
            raise ValueError("opacity values must be finite")
        if not 0.0 <= scalar_value <= 1.0:
            raise ValueError("opacity values must be between 0 and 1")
        return np.full(row_count, scalar_value, dtype=np.float32)
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
        invalid_index = (raw_color_index < 0) | (raw_color_index >= palette_size)
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
        raise ValueError(
            "scatter x and y must contain finite numeric values"
        ) from error

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
            raise ValueError(f"Invalid Matplotlib color spec {str(color)!r}") from error
        palette.append(to_hex((red, green, blue), keep_alpha=False))
        source_alpha[index] = alpha

    combined_opacity = opacity_values * source_alpha[inverse]
    index_dtype = np.uint8 if palette_size <= 256 else np.uint16
    color_index = inverse.astype(index_dtype, copy=True)
    return PaletteEncoding(tuple(palette), color_index, combined_opacity)


def choose_coordinate_encoding(
    values,
    pixel_span,
    supported_zoom,
    max_pixel_error=0.05,
) -> CoordinateEncoding:
    """Select the only compact coordinate form that satisfies the pixel budget."""
    try:
        raw = np.asarray(values)
    except (TypeError, ValueError) as error:
        raise ValueError("values must be a one-dimensional numeric array") from error
    if raw.ndim != 1:
        raise ValueError("values must be one-dimensional")
    if raw.dtype.kind not in {"i", "u", "f"}:
        raise ValueError("values must be numeric")
    values_array = np.asarray(raw, dtype=np.float64)

    pixel_span = _positive_number(pixel_span, "pixel_span")
    supported_zoom = _positive_number(supported_zoom, "supported_zoom")
    if supported_zoom < 1:
        raise ValueError("supported_zoom must be greater than or equal to 1")
    max_pixel_error = _positive_number(max_pixel_error, "max_pixel_error")

    finite = np.isfinite(values_array)
    if not np.any(finite):
        return CoordinateEncoding(CoordinateEncodingKind.ABSOLUTE_F64)

    finite_values = values_array[finite]
    origin = float(np.min(finite_values))
    data_span = float(np.max(finite_values) - origin)
    if data_span == 0:
        return CoordinateEncoding(
            CoordinateEncodingKind.RELATIVE_F32,
            origin=origin,
            scale=1.0,
        )

    scale = data_span
    relative = ((finite_values - origin) / scale).astype(np.float32)
    reconstructed = relative.astype(np.float64) * scale + origin
    max_data_error = float(np.max(np.abs(reconstructed - finite_values)))
    error_pixels = max_data_error / data_span * pixel_span * supported_zoom
    kind = (
        CoordinateEncodingKind.RELATIVE_F32
        if error_pixels <= max_pixel_error
        else CoordinateEncodingKind.ABSOLUTE_F64
    )
    return CoordinateEncoding(
        kind,
        origin=origin if kind is CoordinateEncodingKind.RELATIVE_F32 else 0.0,
        scale=scale if kind is CoordinateEncodingKind.RELATIVE_F32 else 1.0,
        max_error_pixels=(
            error_pixels if kind is CoordinateEncodingKind.RELATIVE_F32 else 0.0
        ),
    )


def _positive_number(value, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be finite and greater than zero") from error
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{name} must be finite and greater than zero")
    return number


@dataclass(frozen=True)
class _CompileContext:
    width: float
    height: float
    supported_zoom: float
    projection_info: Mapping[str, Any]
    style_info: Mapping[str, Any]
    clips: Mapping[str, ClipGeometry]
    ignored_clip_ids: frozenset[str] = frozenset()


@dataclass(frozen=True)
class _CompiledParts:
    columns: Mapping[str, Any]
    style: Mapping[str, Any]
    coordinate_encoding: Mapping[str, CoordinateEncoding]
    interaction: InteractionPolicy = InteractionPolicy.NONE
    hover_fields: tuple[str, ...] = ()
    palette: tuple[str, ...] | None = None


class SceneCompiler:
    """Compile recorded Matplotlib-final primitives into one immutable Scene."""

    def compile(
        self,
        commands,
        projection_info,
        style_info,
        width: int,
        height: int,
        transparent: bool,
    ) -> ScenePackage:
        width_value = _positive_number(width, "width and height")
        height_value = _positive_number(height, "width and height")
        projection = dict(projection_info)
        style = dict(style_info)
        supported_zoom = _positive_number(
            style.get("supported_zoom", 1), "supported_zoom"
        )
        if supported_zoom < 1:
            raise ValueError("supported_zoom must be greater than or equal to 1")
        clips, ignored_clip_ids = _compile_clips(projection.get("clip_geometries", {}))
        context = _CompileContext(
            width=width_value,
            height=height_value,
            supported_zoom=supported_zoom,
            projection_info=projection,
            style_info=style,
            clips=clips,
            ignored_clip_ids=ignored_clip_ids,
        )

        indexed_layers = []
        palettes = {}
        for index, command in enumerate(commands):
            layer, assets = self._compile_command_with_assets(command, index, context)
            indexed_layers.append((index, layer))
            palettes.update(assets)
        indexed_layers.sort(key=lambda item: (item[1].zorder, item[0]))

        viewport = {
            "reference_width": int(width) if width_value.is_integer() else width_value,
            "reference_height": int(height)
            if height_value.is_integer()
            else height_value,
            "data_bounds": {
                key: projection.get(key) for key in ("x_min", "x_max", "y_min", "y_max")
            },
            "paper_background": style.get("figure_background_color", "#ffffff"),
            "axes_background": style.get("background_color", "#ffffff"),
            "transparent": bool(transparent),
        }
        return ScenePackage(
            layers=tuple(layer for _, layer in indexed_layers),
            projection_info=projection,
            style_info=style,
            viewport=viewport,
            clips=clips,
            palettes=palettes,
        )

    def compile_command(self, command: DrawingCommand, index: int) -> SceneLayer:
        context = _CompileContext(
            width=1000.0,
            height=1000.0,
            supported_zoom=1.0,
            projection_info={},
            style_info={"resolution": 4096, "dpi": 100},
            clips={},
        )
        layer, _ = self._compile_command_with_assets(command, index, context)
        return layer

    def _compile_command_with_assets(
        self,
        command: DrawingCommand,
        index: int,
        context: _CompileContext,
    ) -> tuple[SceneLayer, Mapping[str, tuple[str, ...]]]:
        if not isinstance(command, DrawingCommand):
            raise TypeError("command must be a DrawingCommand")
        method_name = COMMAND_COMPILERS[command.kind]
        parts = getattr(self, method_name)(command, context, index)
        kind = SceneKind(command.kind.value)
        clip_id = (
            None if command.clip_id in context.ignored_clip_ids else command.clip_id
        )
        layer = SceneLayer(
            id=f"layer-{index:04d}-{kind.value}",
            kind=kind,
            zorder=float(command.zorder if command.zorder is not None else 0),
            load_priority=_load_priority(
                kind, len(next(iter(parts.columns.values()), ()))
            ),
            space=command.space,
            clip_id=clip_id,
            style=parts.style,
            data=ColumnarData.from_mapping(parts.columns),
            interaction=parts.interaction,
            hover_fields=parts.hover_fields,
            required=True,
            coordinate_encoding=parts.coordinate_encoding,
        )
        assets = (
            {f"palette-{index:04d}": parts.palette} if parts.palette is not None else {}
        )
        return layer, assets

    def _compile_scatter(
        self, command: DrawingCommand, context: _CompileContext, index: int
    ) -> _CompiledParts:
        x, y = _numeric_aligned(
            command.data.get("x", ()), command.data.get("y", ()), "scatter"
        )
        row_count = len(x)
        sizes = _aligned_column(
            command.data.get("sizes", ()), row_count, "scatter sizes"
        )
        colors = _aligned_column(
            command.data.get("colors", ()), row_count, "scatter colors"
        )
        alphas = _aligned_column(
            command.data.get("alphas", ()), row_count, "scatter alphas"
        )
        metadata = tuple(command.metadata)
        if metadata and len(metadata) != row_count:
            raise ValueError("scatter metadata must have the same row count as data")

        clip = _command_clip(command, context)
        if clip is not None:
            mask = scatter_clip_mask(x, y, clip)
            x, y, sizes, colors, alphas = (
                values[mask] for values in (x, y, sizes, colors, alphas)
            )
            if metadata:
                metadata = tuple(item for item, keep in zip(metadata, mask) if keep)
            row_count = int(np.count_nonzero(mask))

        palette = encode_palette(colors, alphas)
        source_width = context.style_info.get(
            "source_axes_width",
            context.projection_info.get("axes_pixels", (None,))[0]
            if context.projection_info.get("axes_pixels")
            else context.style_info.get("resolution", 4096),
        )
        sizes = calibrate_marker_sizes_array(
            sizes,
            dpi=context.style_info.get("dpi", 100),
            target_width=context.width,
            source_axes_width=source_width,
        )
        columns = {
            "x": x,
            "y": y,
            "size": sizes,
            "color_index": palette.color_index,
            "opacity": palette.opacity,
        }
        interaction, hover_fields, metadata_columns = _scatter_interaction(
            metadata, row_count
        )
        columns.update(metadata_columns)
        coordinate_encoding = _encode_xy(columns, context)
        style = dict(command.style)
        style["palette_id"] = f"palette-{index:04d}"
        return _CompiledParts(
            columns,
            style,
            coordinate_encoding,
            interaction,
            hover_fields,
            palette.palette,
        )

    def _compile_line(
        self, command: DrawingCommand, context: _CompileContext, index: int
    ) -> _CompiledParts:
        paths = _split_xy_paths(
            command.data.get("x", ()),
            command.data.get("y", ()),
            command.data.get("breaks"),
        )
        clip = _command_clip(command, context)
        if clip is not None:
            paths = _clip_line_paths(paths, clip)
        columns = _path_columns(paths)
        coordinate_encoding = _encode_xy(columns, context)
        return _CompiledParts(columns, command.style, coordinate_encoding)

    def _compile_line_collection(
        self, command: DrawingCommand, context: _CompileContext, index: int
    ) -> _CompiledParts:
        paths = []
        for line in command.data.get("lines", ()):
            points = np.asarray(line, dtype=object)
            if points.ndim != 2 or points.shape[1] != 2:
                raise ValueError("line_collection segments must contain x/y points")
            paths.extend(_split_xy_paths(points[:, 0], points[:, 1]))
        clip = _command_clip(command, context)
        if clip is not None:
            paths = _clip_line_paths(paths, clip)
        columns = _path_columns(paths)
        coordinate_encoding = _encode_xy(columns, context)
        return _CompiledParts(columns, command.style, coordinate_encoding)

    def _compile_polygon(
        self, command: DrawingCommand, context: _CompileContext, index: int
    ) -> _CompiledParts:
        polygons = _polygon_groups(command.data)
        clip = _command_clip(command, context)
        if clip is not None:
            polygons = _clip_polygons(polygons, clip)
        columns = _polygon_columns(polygons)
        coordinate_encoding = _encode_xy(columns, context)
        return _CompiledParts(columns, command.style, coordinate_encoding)

    def _compile_text(
        self, command: DrawingCommand, context: _CompileContext, index: int
    ) -> _CompiledParts:
        offset = command.data.get("offset_points", (0.0, 0.0))
        if len(offset) != 2:
            raise ValueError("text offset_points must contain two values")
        columns = {
            "x": np.array([command.data.get("x")], dtype=np.float64),
            "y": np.array([command.data.get("y")], dtype=np.float64),
            "text": np.array([str(command.data.get("text", ""))]),
            "rotation": np.array(
                [command.style.get("rotation", 0.0)], dtype=np.float32
            ),
            "x_offset": np.array([offset[0]], dtype=np.float32),
            "y_offset": np.array([offset[1]], dtype=np.float32),
            "style_id": np.array([0], dtype=np.uint16),
        }
        coordinate_encoding = _encode_xy(columns, context)
        return _CompiledParts(columns, command.style, coordinate_encoding)

    def _compile_gradient(
        self, command: DrawingCommand, context: _CompileContext, index: int
    ) -> _CompiledParts:
        style = dict(command.style)
        style["direction"] = command.data.get("direction")
        style["color_stops"] = tuple(
            tuple(stop) for stop in command.data.get("color_stops", ())
        )
        return _CompiledParts({}, style, {})

    def _compile_info_table(
        self, command: DrawingCommand, context: _CompileContext, index: int
    ) -> _CompiledParts:
        columns = {
            "column": np.asarray(command.data.get("columns", ())),
            "value": np.asarray(command.data.get("values", ())),
            "width": np.asarray(command.data.get("widths", ()), dtype=np.float32),
        }
        lengths = {len(value) for value in columns.values()}
        if len(lengths) > 1:
            raise ValueError("info_table columns, values, and widths must align")
        return _CompiledParts(columns, command.style, {})


def _load_priority(kind: SceneKind, row_count: int) -> int:
    if kind in {SceneKind.GRADIENT, SceneKind.POLYGON}:
        return 0
    if kind in {SceneKind.TEXT, SceneKind.INFO_TABLE}:
        return 10
    if kind is SceneKind.SCATTER:
        return 100 if row_count >= 100_000 else 20
    return 30


def _compile_clips(recorded_clips) -> tuple[dict[str, ClipGeometry], frozenset[str]]:
    clips = {}
    ignored = set()
    for clip_id, clip in recorded_clips.items():
        if clip is None or getattr(clip, "kind", None) == "none":
            ignored.add(clip_id)
            continue
        clips[clip_id] = ClipGeometry(kind=clip.kind, points=clip.points)
    return clips, frozenset(ignored)


def _command_clip(
    command: DrawingCommand, context: _CompileContext
) -> ClipGeometry | None:
    if command.space is not CoordinateSpace.DATA or command.clip_id is None:
        return None
    return context.clips.get(command.clip_id)


def _aligned_column(values, row_count: int, name: str) -> np.ndarray:
    array = np.asarray(values)
    if array.ndim != 1:
        raise ValueError(f"{name} must be one-dimensional")
    if len(array) != row_count:
        raise ValueError(f"{name} must have the same row count as coordinates")
    return array


def _numeric_aligned(x, y, name: str) -> tuple[np.ndarray, np.ndarray]:
    try:
        x_array = np.asarray(x, dtype=np.float64)
        y_array = np.asarray(y, dtype=np.float64)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} x and y must be numeric") from error
    if x_array.ndim != 1 or y_array.ndim != 1:
        raise ValueError(f"{name} x and y must be one-dimensional")
    if len(x_array) != len(y_array):
        raise ValueError(f"{name} x and y must have the same length")
    return x_array, y_array


def _encode_xy(
    columns: dict[str, Any], context: _CompileContext
) -> dict[str, CoordinateEncoding]:
    encodings = {}
    for name, pixel_span in (("x", context.width), ("y", context.height)):
        if name not in columns:
            continue
        encoding = choose_coordinate_encoding(
            columns[name], pixel_span, context.supported_zoom
        )
        columns[name] = encoding.encode(columns[name])
        encodings[name] = encoding
    return encodings


def _scatter_interaction(metadata, row_count: int):
    if row_count >= 100_000 or not metadata:
        return InteractionPolicy.NONE, (), {}
    safe_names = ("name", "magnitude", "type", "object_id")
    columns = {}
    for name in safe_names:
        if not any(isinstance(item, Mapping) and name in item for item in metadata):
            continue
        values = []
        safe = True
        for item in metadata:
            value = item.get(name) if isinstance(item, Mapping) else None
            if not _safe_metadata_scalar(value):
                safe = False
                break
            values.append(value)
        if safe:
            columns[name] = np.asarray(values)
    hover_fields = tuple(name for name in safe_names if name in columns)
    if "object_id" in columns:
        interaction = InteractionPolicy.HOVER_AND_DETAIL
    elif hover_fields:
        interaction = InteractionPolicy.HOVER
    else:
        interaction = InteractionPolicy.NONE
    return interaction, hover_fields, columns


def _safe_metadata_scalar(value) -> bool:
    return value is None or isinstance(
        value,
        (
            str,
            int,
            float,
            bool,
            np.str_,
            np.integer,
            np.floating,
            np.bool_,
        ),
    )


def _break_indices(breaks, row_count: int) -> set[int]:
    if breaks is None:
        return set()
    values = np.asarray(breaks)
    if values.dtype == np.bool_:
        if values.ndim != 1 or len(values) != row_count:
            raise ValueError("boolean line breaks must align with coordinates")
        return set(np.flatnonzero(values).tolist())
    if values.ndim != 1 or values.dtype.kind not in {"i", "u"}:
        raise ValueError("line breaks must be boolean flags or integer indices")
    result = {int(value) for value in values}
    if any(value < 0 or value >= row_count for value in result):
        raise ValueError("line break index is outside the coordinate rows")
    return result


def _split_xy_paths(x, y, breaks=None) -> list[list[tuple[float, float]]]:
    x_values = np.asarray(x, dtype=object)
    y_values = np.asarray(y, dtype=object)
    if x_values.ndim != 1 or y_values.ndim != 1:
        raise ValueError("line x and y must be one-dimensional")
    if len(x_values) != len(y_values):
        raise ValueError("line x and y must have the same length")
    explicit_breaks = _break_indices(breaks, len(x_values))
    paths = []
    current = []
    for index, (x_value, y_value) in enumerate(zip(x_values, y_values)):
        if index in explicit_breaks and current:
            paths.append(current)
            current = []
        if x_value is None or y_value is None:
            if current:
                paths.append(current)
                current = []
            continue
        try:
            point = (float(x_value), float(y_value))
        except (TypeError, ValueError) as error:
            raise ValueError("line coordinates must be numeric or None") from error
        if not math.isfinite(point[0]) or not math.isfinite(point[1]):
            if current:
                paths.append(current)
                current = []
            continue
        current.append(point)
    if current:
        paths.append(current)
    return paths


def _clip_shape(clip: ClipGeometry):
    points = np.asarray(clip.points, dtype=np.float64)
    if clip.kind == "rect":
        x_min, y_min = np.min(points, axis=0)
        x_max, y_max = np.max(points, axis=0)
        if x_min >= x_max or y_min >= y_max:
            raise ValueError("rectangle clip must have positive width and height")
        geometry = box(x_min, y_min, x_max, y_max)
    else:
        geometry = Polygon(clip.points)
    if geometry.is_empty or not geometry.is_valid or geometry.area <= 0:
        raise ValueError("clip must be non-empty, valid, positive-area geometry")
    return geometry


def _clip_line_paths(paths, clip: ClipGeometry):
    clip_shape = _clip_shape(clip)
    result = []
    for path in paths:
        if len(path) < 2:
            continue
        clipped = LineString(path).intersection(clip_shape)
        result.extend(_line_geometry_paths(clipped))
    return result


def _line_geometry_paths(geometry):
    if geometry.is_empty:
        return []
    if geometry.geom_type in {"LineString", "LinearRing"}:
        return [[(float(x), float(y)) for x, y in geometry.coords]]
    if hasattr(geometry, "geoms"):
        paths = []
        for part in geometry.geoms:
            paths.extend(_line_geometry_paths(part))
        return paths
    return []


def _path_columns(paths):
    path_ids = []
    vertex_indices = []
    x_values = []
    y_values = []
    for path_id, path in enumerate(paths):
        for vertex_index, (x, y) in enumerate(path):
            path_ids.append(path_id)
            vertex_indices.append(vertex_index)
            x_values.append(x)
            y_values.append(y)
    return {
        "path_id": np.asarray(path_ids, dtype=np.uint32),
        "vertex_index": np.asarray(vertex_indices, dtype=np.uint32),
        "x": np.asarray(x_values, dtype=np.float64),
        "y": np.asarray(y_values, dtype=np.float64),
    }


def _is_point(value) -> bool:
    return (
        isinstance(value, (list, tuple, np.ndarray))
        and len(value) == 2
        and all(np.isscalar(item) for item in value)
    )


def _polygon_groups(data) -> list[list[list[tuple[float, float]]]]:
    if "polygons" in data:
        raw_polygons = data["polygons"]
    elif data.get("rings"):
        raw_polygons = [data["rings"]]
    else:
        raw_polygons = [[data.get("points", ())]]
    polygons = []
    for raw_polygon in raw_polygons:
        if raw_polygon and _is_point(raw_polygon[0]):
            raw_polygon = [raw_polygon]
        rings = []
        for raw_ring in raw_polygon:
            ring = []
            for point in raw_ring:
                if not _is_point(point):
                    raise ValueError("polygon rings must contain x/y points")
                x, y = float(point[0]), float(point[1])
                if not math.isfinite(x) or not math.isfinite(y):
                    raise ValueError("polygon coordinates must be finite")
                ring.append((x, y))
            if len(ring) >= 3:
                if ring[0] == ring[-1]:
                    ring.pop()
                if len(ring) >= 3:
                    rings.append(ring)
        if rings:
            polygons.append(rings)
    return polygons


def _clip_polygons(polygons, clip: ClipGeometry):
    clip_shape = _clip_shape(clip)
    result = []
    for rings in polygons:
        polygon = Polygon(rings[0], holes=rings[1:])
        if polygon.is_empty or not polygon.is_valid or polygon.area <= 0:
            raise ValueError("polygon must be non-empty, valid, positive-area geometry")
        clipped = polygon.intersection(clip_shape)
        result.extend(_polygon_geometry_groups(clipped))
    return result


def _polygon_geometry_groups(geometry):
    if geometry.is_empty:
        return []
    if geometry.geom_type == "Polygon":
        rings = [_open_ring(geometry.exterior.coords)]
        rings.extend(_open_ring(ring.coords) for ring in geometry.interiors)
        return [rings]
    if hasattr(geometry, "geoms"):
        polygons = []
        for part in geometry.geoms:
            polygons.extend(_polygon_geometry_groups(part))
        return polygons
    return []


def _open_ring(coordinates):
    points = [(float(x), float(y)) for x, y in coordinates]
    if len(points) > 1 and points[0] == points[-1]:
        points.pop()
    return points


def _polygon_columns(polygons):
    polygon_ids = []
    ring_ids = []
    vertex_indices = []
    x_values = []
    y_values = []
    for polygon_id, rings in enumerate(polygons):
        for ring_id, ring in enumerate(rings):
            for vertex_index, (x, y) in enumerate(ring):
                polygon_ids.append(polygon_id)
                ring_ids.append(ring_id)
                vertex_indices.append(vertex_index)
                x_values.append(x)
                y_values.append(y)
    return {
        "polygon_id": np.asarray(polygon_ids, dtype=np.uint32),
        "ring_id": np.asarray(ring_ids, dtype=np.uint32),
        "vertex_index": np.asarray(vertex_indices, dtype=np.uint32),
        "x": np.asarray(x_values, dtype=np.float64),
        "y": np.asarray(y_values, dtype=np.float64),
    }
