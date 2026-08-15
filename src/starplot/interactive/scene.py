"""Immutable, backend-neutral primitives for compiled interactive scenes."""

from __future__ import annotations

from dataclasses import astuple, dataclass, field
from enum import Enum
import math
from types import MappingProxyType
from typing import Any, Mapping, Protocol

import numpy as np

from starplot.interactive.commands import (
    ClipGeometry as RecordedClipGeometry,
    CoordinateSpace,
)


class _StringEnum(str, Enum):
    """Python 3.10-compatible string enum with ``StrEnum`` string behavior."""

    __str__ = str.__str__


class SceneKind(_StringEnum):
    SCATTER = "scatter"
    LINE = "line"
    LINE_COLLECTION = "line_collection"
    POLYGON = "polygon"
    TEXT = "text"
    GRADIENT = "gradient"
    INFO_TABLE = "info_table"


class InteractionPolicy(_StringEnum):
    NONE = "none"
    HOVER = "hover"
    HOVER_AND_DETAIL = "hover-and-detail"


class CoordinateEncodingKind(_StringEnum):
    ABSOLUTE_F64 = "absolute-f64"
    RELATIVE_F32 = "relative-f32"


@dataclass(frozen=True)
class CoordinateEncoding:
    kind: CoordinateEncodingKind
    origin: float = 0.0
    scale: float = 1.0
    max_error_pixels: float = 0.0

    def __post_init__(self):
        kind = CoordinateEncodingKind(self.kind)
        try:
            origin = float(self.origin)
            scale = float(self.scale)
            max_error_pixels = float(self.max_error_pixels)
        except (TypeError, ValueError) as error:
            raise ValueError("CoordinateEncoding values must be numeric") from error
        if not math.isfinite(origin):
            raise ValueError("CoordinateEncoding origin must be finite")
        if not math.isfinite(scale) or scale <= 0:
            raise ValueError(
                "CoordinateEncoding scale must be finite and greater than zero"
            )
        if not math.isfinite(max_error_pixels) or max_error_pixels < 0:
            raise ValueError(
                "CoordinateEncoding max_error_pixels must be finite and non-negative"
            )
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "origin", origin)
        object.__setattr__(self, "scale", scale)
        object.__setattr__(self, "max_error_pixels", max_error_pixels)

    def encode(self, values) -> np.ndarray:
        array = _coordinate_array(values)
        if self.kind is CoordinateEncodingKind.RELATIVE_F32:
            encoded = (array - self.origin) / self.scale
            return readonly_array(encoded, dtype=np.float32)
        return readonly_array(array, dtype=np.float64)

    def decode(self, values) -> np.ndarray:
        array = _coordinate_array(values)
        if self.kind is CoordinateEncodingKind.RELATIVE_F32:
            decoded = array.astype(np.float64, copy=False) * self.scale + self.origin
            return readonly_array(decoded, dtype=np.float64)
        return readonly_array(array, dtype=np.float64)


def _coordinate_array(values) -> np.ndarray:
    try:
        array = np.asarray(values, dtype=np.float64)
    except (TypeError, ValueError) as error:
        raise ValueError("coordinate values must be numeric") from error
    if array.ndim != 1:
        raise ValueError("coordinate values must be one-dimensional")
    return array


@dataclass(frozen=True)
class ClipGeometry:
    """Serializable clip geometry retained by a compiled Scene."""

    kind: str
    points: tuple[tuple[float, float], ...]

    def __post_init__(self):
        if not isinstance(self.kind, str) or self.kind not in {"rect", "polygon"}:
            raise ValueError("ClipGeometry kind must be rect or polygon")

        try:
            points = tuple(tuple(point) for point in self.points)
        except TypeError as error:
            raise ValueError(
                "ClipGeometry points must be two-value coordinates"
            ) from error

        minimum_points = 2 if self.kind == "rect" else 3
        if len(points) < minimum_points:
            raise ValueError(
                f"{self.kind} ClipGeometry requires at least {minimum_points} points"
            )

        frozen_points = []
        for point in points:
            if len(point) != 2:
                raise ValueError("ClipGeometry points must contain exactly two values")
            try:
                x, y = float(point[0]), float(point[1])
            except (TypeError, ValueError) as error:
                raise ValueError(
                    "ClipGeometry points must be finite numbers"
                ) from error
            if not math.isfinite(x) or not math.isfinite(y):
                raise ValueError("ClipGeometry points must be finite numbers")
            frozen_points.append((x, y))

        object.__setattr__(self, "points", tuple(frozen_points))


def readonly_array(value, dtype=None) -> np.ndarray:
    """Snapshot into storage ordinary NumPy operations cannot make writeable.

    Non-object arrays are backed by an immutable ``bytes`` snapshot, so neither
    ``np.ndarray.setflags(array, write=True)`` nor ordinary view/buffer escape
    routes can restore write access.  Object arrays cannot use byte-backed
    storage: NumPy deliberately rejects object arrays from raw buffers because
    the buffer would not safely own Python references.  Their values are deeply
    frozen into a sealed owner and exposed through a view, which also rejects a
    direct base-class ``setflags`` call on the public result.  NumPy still
    exposes that owner through ``array.base``; a caller that deliberately
    re-enables its write flag can replace object slots, which pure NumPy cannot
    prevent safely.
    """
    source = np.asarray(value, dtype=dtype, order="C")
    if source.dtype.hasobject:
        owner = _seal_owned_array(_deep_frozen_object_array(source))
        return owner.view(_ImmutableArray)
    return _readonly_buffer_array(source)


def _readonly_buffer_array(source: np.ndarray) -> np.ndarray:
    """Return an immutable, C-contiguous snapshot of a non-object array."""
    payload = source.tobytes(order="C")
    array = np.frombuffer(payload, dtype=source.dtype).reshape(source.shape)
    return array.view(_ImmutableArray)


class _ImmutableArray(np.ndarray):
    """An ndarray whose public API cannot restore write access."""

    def __new__(cls, shape, dtype):
        return super().__new__(cls, shape=shape, dtype=dtype, order="C")

    def setflags(self, write=None, align=None, uic=None):
        if write:
            raise ValueError("Scene arrays cannot be made writeable")
        return super().setflags(write=write, align=align, uic=uic)

    def __getitem__(self, key):
        result = super().__getitem__(key)
        if isinstance(result, np.ndarray):
            return readonly_array(result)
        return result


def _deep_frozen_object_array(source: np.ndarray) -> np.ndarray:
    """Snapshot Python objects retained by an object-dtype column."""
    frozen = np.empty(source.shape, dtype=object, order="C")
    for index in np.ndindex(source.shape):
        frozen[index] = _freeze_value(source[index])
    return frozen


def _seal_owned_array(array: np.ndarray) -> np.ndarray:
    """Seal owned storage or retain an already sealed Scene snapshot."""
    if not isinstance(array, np.ndarray):
        raise TypeError("owned array must be a NumPy ndarray")
    if not array.flags.c_contiguous:
        raise ValueError("owned array must own C-contiguous storage")
    if not array.flags.owndata:
        if isinstance(array, _ImmutableArray) and not array.flags.writeable:
            return array
        raise ValueError("owned array must own C-contiguous storage")
    array.setflags(write=False)
    return array


def _validated_row_count(
    columns: Mapping[str, np.ndarray],
    expected_row_count: int | None = None,
) -> int:
    lengths = {len(column) for column in columns.values()}
    if len(lengths) > 1:
        raise ValueError("ColumnarData columns must have the same row count")
    row_count = next(iter(lengths), 0)
    if expected_row_count is not None and expected_row_count != row_count:
        raise ValueError("ColumnarData row_count must match the column row count")
    return row_count


class _ColumnMapping(Mapping[str, np.ndarray]):
    """Expose object columns as snapshots so their owner never escapes the Scene."""

    def __init__(self, columns: Mapping[str, np.ndarray]):
        self.__columns = MappingProxyType(dict(columns))

    def __getitem__(self, name: str) -> np.ndarray:
        column = self.__columns[name]
        if column.dtype.hasobject:
            return readonly_array(column)
        return column

    def __iter__(self):
        return iter(self.__columns)

    def __len__(self) -> int:
        return len(self.__columns)

    def _stored_items(self):
        """Return trusted internal storage for Scene implementation code only."""
        return self.__columns.items()


def _column_mapping(columns: Mapping[str, np.ndarray]) -> Mapping[str, np.ndarray]:
    return _ColumnMapping(columns)


def _stored_column_items(columns: Mapping[str, np.ndarray]):
    if isinstance(columns, _ColumnMapping):
        return columns._stored_items()
    return columns.items()


def _freeze_value(value):
    """Recursively freeze values retained by the Scene boundary."""
    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: _freeze_value(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_value(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze_value(item) for item in value)
    if isinstance(value, (bytearray, memoryview)):
        return bytes(value)
    if isinstance(value, np.ndarray):
        return readonly_array(value)
    if isinstance(value, (ClipGeometry, RecordedClipGeometry)):
        return value
    if isinstance(
        value,
        (str, bytes, int, float, complex, bool, type(None), Enum, np.generic),
    ):
        return value
    raise TypeError(
        f"Scene values cannot retain mutable {type(value).__name__} instances"
    )


@dataclass(frozen=True)
class ColumnarData:
    columns: Mapping[str, np.ndarray]
    row_count: int

    def __post_init__(self):
        columns = {name: readonly_array(value) for name, value in self.columns.items()}
        _validated_row_count(columns, self.row_count)
        object.__setattr__(self, "columns", _column_mapping(columns))

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "ColumnarData":
        columns = {name: readonly_array(value) for name, value in values.items()}
        for column in columns.values():
            if (
                not isinstance(column, np.ndarray)
                or not column.flags.c_contiguous
                or column.flags.writeable
            ):
                raise ValueError(
                    "columns must be C-contiguous, read-only NumPy arrays"
                )

        row_count = _validated_row_count(columns)
        instance = object.__new__(cls)
        object.__setattr__(instance, "columns", _column_mapping(columns))
        object.__setattr__(instance, "row_count", row_count)
        return instance

    def __getitem__(self, name: str) -> np.ndarray:
        return self.columns[name]


@dataclass(frozen=True)
class SceneCapabilities:
    viewport_query: bool = False
    lod: bool = False
    magnitude_filter: bool = False
    catalog_detail: bool = False
    max_batch_rows: int = 250_000

    def __post_init__(self):
        if self.max_batch_rows <= 0:
            raise ValueError("max_batch_rows must be greater than zero")


@dataclass(frozen=True)
class ViewportRequest:
    """A renderer-neutral request expressed in final Scene coordinates."""

    x_min: float | None = None
    x_max: float | None = None
    y_min: float | None = None
    y_max: float | None = None
    pixel_width: int | None = None
    pixel_height: int | None = None
    lod: int | None = None
    magnitude_max: float | None = None
    point_budget: int | None = None

    def __post_init__(self):
        for name in ("x_min", "x_max", "y_min", "y_max", "magnitude_max"):
            value = getattr(self, name)
            if value is not None and (
                not isinstance(value, (int, float)) or not math.isfinite(value)
            ):
                raise ValueError(f"{name} must be a finite number or None")
            if value is not None:
                object.__setattr__(self, name, float(value))
        for lower, upper in (("x_min", "x_max"), ("y_min", "y_max")):
            if (
                getattr(self, lower) is not None
                and getattr(self, upper) is not None
                and getattr(self, lower) > getattr(self, upper)
            ):
                raise ValueError(f"{lower} must be less than or equal to {upper}")
        for name in ("pixel_width", "pixel_height", "lod", "point_budget"):
            value = getattr(self, name)
            if value is not None and (
                not isinstance(value, int) or isinstance(value, bool) or value < 0
            ):
                raise ValueError(f"{name} must be a non-negative integer or None")
        if self.pixel_width == 0 or self.pixel_height == 0:
            raise ValueError("pixel dimensions must be greater than zero")

    @classmethod
    def full(cls) -> "ViewportRequest":
        return cls()

    @property
    def is_full(self) -> bool:
        return all(value is None for value in astuple(self))

    def cache_key_parts(self) -> tuple[object, ...]:
        """Canonical, data-independent request identity for provider caches."""

        def quantize(value: object) -> object:
            return round(value, 8) if isinstance(value, float) else value

        return tuple(quantize(value) for value in astuple(self))


class LodPolicy(Protocol):
    """Select rows from a final, compiled Scene layer for one request."""

    def select(self, layer: "SceneLayer", request: ViewportRequest) -> np.ndarray: ...


def viewport_mask(x: np.ndarray, y: np.ndarray, request: ViewportRequest) -> np.ndarray:
    """Filter only final Scene coordinates; never catalog RA/Dec or projection data."""
    mask = np.ones(len(x), dtype=np.bool_)
    if request.x_min is not None:
        mask &= x >= request.x_min
    if request.x_max is not None:
        mask &= x <= request.x_max
    if request.y_min is not None:
        mask &= y >= request.y_min
    if request.y_max is not None:
        mask &= y <= request.y_max
    return mask


def final_scene_coordinates(layer: "SceneLayer") -> tuple[np.ndarray, np.ndarray]:
    """Decode transport columns into final projected Scene coordinates."""
    try:
        return (
            layer.coordinate_encoding["x"].decode(layer.data["x"]),
            layer.coordinate_encoding["y"].decode(layer.data["y"]),
        )
    except KeyError as error:
        raise ValueError("viewport filtering requires x/y Scene coordinates") from error


class FullResolutionPolicy:
    """Crop a final-coordinate layer but never apply data reduction."""

    def select(self, layer: "SceneLayer", request: ViewportRequest) -> np.ndarray:
        if (
            request.is_full
            or "x" not in layer.data.columns
            or "y" not in layer.data.columns
        ):
            return np.ones(layer.data.row_count, dtype=np.bool_)
        x, y = final_scene_coordinates(layer)
        return viewport_mask(x, y, request)


class MagnitudeLodPolicy:
    """Crop then retain a stable bright-first subset of a scatter layer."""

    def select(self, layer: "SceneLayer", request: ViewportRequest) -> np.ndarray:
        if "x" not in layer.data.columns or "y" not in layer.data.columns:
            return np.ones(layer.data.row_count, dtype=np.bool_)
        if "magnitude" not in layer.data.columns:
            raise ValueError("MagnitudeLodPolicy requires a magnitude Scene column")
        x, y = final_scene_coordinates(layer)
        visible = viewport_mask(x, y, request)
        magnitude = layer.data["magnitude"]
        if request.magnitude_max is not None:
            visible &= magnitude <= request.magnitude_max
        if request.point_budget is None or visible.sum() <= request.point_budget:
            return visible
        candidates = np.flatnonzero(visible)
        # mergesort preserves original row order for equal magnitudes. Non-finite
        # values sort last, so an unknown magnitude is never promoted as bright.
        ordering = np.argsort(
            np.where(np.isfinite(magnitude[candidates]), magnitude[candidates], np.inf),
            kind="stable",
        )
        selected = np.zeros(layer.data.row_count, dtype=np.bool_)
        selected[candidates[ordering[: request.point_budget]]] = True
        return selected


@dataclass(frozen=True)
class SceneLayer:
    id: str
    kind: SceneKind
    zorder: float
    load_priority: int
    space: CoordinateSpace
    clip_id: str | None
    style: Mapping[str, Any]
    data: ColumnarData
    group_id: str = ""
    interaction: InteractionPolicy = InteractionPolicy.NONE
    hover_fields: tuple[str, ...] = ()
    required: bool = True
    coordinate_encoding: Mapping[str, CoordinateEncoding] = field(default_factory=dict)
    palette: tuple[str, ...] | None = None

    def __post_init__(self):
        if not self.id:
            raise ValueError("SceneLayer id must be non-empty")
        if not isinstance(self.group_id, str):
            raise ValueError("SceneLayer group_id must be a string")

        kind = SceneKind(self.kind)
        space = CoordinateSpace(self.space)
        interaction = InteractionPolicy(self.interaction)
        hover_fields = tuple(self.hover_fields)

        if interaction is InteractionPolicy.NONE and hover_fields:
            raise ValueError("hover_fields must be empty when interaction is NONE")
        unknown_fields = set(hover_fields).difference(self.data.columns)
        if unknown_fields:
            raise ValueError("hover_fields must reference data columns")
        coordinate_encoding = {
            name: (
                value
                if isinstance(value, CoordinateEncoding)
                else CoordinateEncoding(**value)
            )
            for name, value in self.coordinate_encoding.items()
        }
        unknown_encoding = set(coordinate_encoding).difference(self.data.columns)
        if unknown_encoding:
            raise ValueError("coordinate_encoding must reference data columns")
        palette = None if self.palette is None else tuple(self.palette)
        if palette is not None and not all(isinstance(color, str) for color in palette):
            raise ValueError("SceneLayer palette must contain only strings")

        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "space", space)
        object.__setattr__(self, "style", _freeze_value(self.style))
        object.__setattr__(self, "interaction", interaction)
        object.__setattr__(self, "hover_fields", hover_fields)
        object.__setattr__(
            self,
            "coordinate_encoding",
            MappingProxyType(coordinate_encoding),
        )
        object.__setattr__(self, "palette", palette)


@dataclass(frozen=True)
class ScenePackage:
    layers: tuple[SceneLayer, ...]
    projection_info: Mapping[str, Any]
    style_info: Mapping[str, Any]
    viewport: Mapping[str, Any]
    clips: Mapping[str, Any]
    palettes: Mapping[str, tuple[str, ...]]
    capabilities: SceneCapabilities = SceneCapabilities()

    def __post_init__(self):
        layers = tuple(self.layers)
        layer_ids = [layer.id for layer in layers]
        if len(layer_ids) != len(set(layer_ids)):
            raise ValueError("ScenePackage contains a duplicate layer id")
        palettes = {
            palette_id: value if isinstance(value, tuple) else tuple(value)
            for palette_id, value in self.palettes.items()
        }
        if any(
            not all(isinstance(color, str) for color in palette)
            for palette in palettes.values()
        ):
            raise ValueError("ScenePackage palettes must contain only strings")
        for layer in layers:
            if layer.palette is None:
                continue
            palette_id = layer.style.get("palette_id")
            if not isinstance(palette_id, str) or palettes.get(palette_id) != layer.palette:
                raise ValueError(
                    "ScenePackage palette asset must match the layer palette"
                )

        object.__setattr__(self, "layers", layers)
        object.__setattr__(self, "projection_info", _freeze_value(self.projection_info))
        object.__setattr__(self, "style_info", _freeze_value(self.style_info))
        object.__setattr__(self, "viewport", _freeze_value(self.viewport))
        object.__setattr__(self, "clips", _freeze_value(self.clips))
        object.__setattr__(self, "palettes", MappingProxyType(palettes))
