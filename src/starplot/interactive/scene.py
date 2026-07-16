"""Immutable, backend-neutral primitives for compiled interactive scenes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
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


def readonly_array(value, dtype=None) -> np.ndarray:
    """Copy into owned, contiguous storage that cannot be written through."""
    array = np.array(
        value,
        dtype=dtype,
        copy=True,
        order="C",
        subok=False,
    )
    array.setflags(write=False)
    return array


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
        columns = {
            name: readonly_array(value)
            for name, value in self.columns.items()
        }
        lengths = {len(column) for column in columns.values()}
        if len(lengths) > 1:
            raise ValueError("ColumnarData columns must have the same row count")
        actual_row_count = next(iter(lengths), 0)
        if self.row_count != actual_row_count:
            raise ValueError(
                "ColumnarData row_count must match the column row count"
            )
        object.__setattr__(self, "columns", MappingProxyType(columns))

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "ColumnarData":
        columns = {
            name: readonly_array(value)
            for name, value in values.items()
        }
        lengths = {len(column) for column in columns.values()}
        if len(lengths) > 1:
            raise ValueError("ColumnarData columns must have the same row count")
        return cls(MappingProxyType(columns), lengths.pop() if lengths else 0)

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

    def __post_init__(self):
        if not self.id:
            raise ValueError("SceneLayer id must be non-empty")

        kind = SceneKind(self.kind)
        space = CoordinateSpace(self.space)
        interaction = InteractionPolicy(self.interaction)
        hover_fields = tuple(self.hover_fields)

        if interaction is InteractionPolicy.NONE and hover_fields:
            raise ValueError(
                "hover_fields must be empty when interaction is NONE"
            )
        unknown_fields = set(hover_fields).difference(self.data.columns)
        if unknown_fields:
            raise ValueError("hover_fields must reference data columns")

        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "space", space)
        object.__setattr__(self, "style", _freeze_value(self.style))
        object.__setattr__(self, "interaction", interaction)
        object.__setattr__(self, "hover_fields", hover_fields)


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

        object.__setattr__(self, "layers", layers)
        object.__setattr__(self, "projection_info", _freeze_value(self.projection_info))
        object.__setattr__(self, "style_info", _freeze_value(self.style_info))
        object.__setattr__(self, "viewport", _freeze_value(self.viewport))
        object.__setattr__(self, "clips", _freeze_value(self.clips))
        object.__setattr__(self, "palettes", _freeze_value(self.palettes))
