"""Immutable, backend-neutral primitives for compiled interactive scenes."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import math
from types import MappingProxyType
from typing import Any, Mapping

import numpy as np

from starplot.interactive.commands import CoordinateSpace


class SceneKind(StrEnum):
    SCATTER = "scatter"
    LINE = "line"
    LINE_COLLECTION = "line_collection"
    POLYGON = "polygon"
    TEXT = "text"
    GRADIENT = "gradient"
    INFO_TABLE = "info_table"


class InteractionPolicy(StrEnum):
    NONE = "none"
    HOVER = "hover"
    HOVER_AND_DETAIL = "hover-and-detail"


class CoordinateEncodingKind(StrEnum):
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
    """Copy into owned, contiguous storage that cannot be written through."""
    array = np.array(
        value,
        dtype=dtype,
        copy=True,
        order="C",
        subok=False,
    )
    return _seal_owned_array(array)


def _seal_owned_array(array: np.ndarray) -> np.ndarray:
    """Seal newly allocated owned storage without making another copy."""
    if not isinstance(array, np.ndarray):
        raise TypeError("owned array must be a NumPy ndarray")
    if not array.flags.owndata or not array.flags.c_contiguous:
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


def _freeze_value(value):
    """Recursively freeze values retained by the Scene boundary."""
    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: _freeze_value(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_value(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze_value(item) for item in value)
    if isinstance(value, np.ndarray):
        return readonly_array(value)
    return value


@dataclass(frozen=True)
class ColumnarData:
    columns: Mapping[str, np.ndarray]
    row_count: int

    def __post_init__(self):
        columns = {name: readonly_array(value) for name, value in self.columns.items()}
        _validated_row_count(columns, self.row_count)
        object.__setattr__(self, "columns", MappingProxyType(columns))

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "ColumnarData":
        columns = {name: readonly_array(value) for name, value in values.items()}
        for column in columns.values():
            if (
                not isinstance(column, np.ndarray)
                or not column.flags.owndata
                or not column.flags.c_contiguous
                or column.flags.writeable
            ):
                raise ValueError(
                    "owned columns must be C-contiguous, read-only NumPy arrays"
                )

        row_count = _validated_row_count(columns)
        instance = object.__new__(cls)
        object.__setattr__(instance, "columns", MappingProxyType(dict(columns)))
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
class SceneLayer:
    id: str
    kind: SceneKind
    zorder: float
    load_priority: int
    space: CoordinateSpace
    clip_id: str | None
    style: Mapping[str, Any]
    data: ColumnarData
    interaction: InteractionPolicy = InteractionPolicy.NONE
    hover_fields: tuple[str, ...] = ()
    required: bool = True
    coordinate_encoding: Mapping[str, CoordinateEncoding] = field(default_factory=dict)
    palette: tuple[str, ...] | None = None

    def __post_init__(self):
        if not self.id:
            raise ValueError("SceneLayer id must be non-empty")

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
