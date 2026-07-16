"""Strict, versioned manifests for transport-neutral interactive scenes."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
import hashlib
import json
import re
from types import MappingProxyType
from typing import Any, Literal, Mapping, Sequence

import numpy as np
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from starplot.interactive.commands import CoordinateSpace
from starplot.interactive.scene import (
    CoordinateEncoding,
    CoordinateEncodingKind,
    InteractionPolicy,
    SceneKind,
    SceneLayer,
)


SCENE_SCHEMA_VERSION = "1.0"
_SUPPORTED_SCHEMA_MAJOR = 1
_CURRENT_LOADER_VERSION = (1, 0)
_VERSION_PATTERN = re.compile(r"^(?P<major>0|[1-9][0-9]*)\.(?P<minor>0|[1-9][0-9]*)$")
_HASH_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_COMPATIBLE_EXTENSION_KEYS = frozenset({"description", "attribution"})
_COORDINATE_KINDS = frozenset(
    {
        SceneKind.SCATTER,
        SceneKind.LINE,
        SceneKind.LINE_COLLECTION,
        SceneKind.POLYGON,
        SceneKind.TEXT,
    }
)


class _FrozenMapping(Mapping[str, Any]):
    """Owned, recursively frozen mapping that is never a mutable ``dict``."""

    __slots__ = ("_data",)

    def __init__(self, value: Mapping[str, Any]):
        object.__setattr__(self, "_data", MappingProxyType(dict(value)))

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __setitem__(self, _key, _value) -> None:
        raise TypeError("wire manifest mappings are immutable")

    def __copy__(self):
        return self

    def __deepcopy__(self, _memo):
        return self

    def __repr__(self) -> str:
        return repr(dict(self._data))


class _WireModel(BaseModel):
    """Frozen wire models: unrecognized fields never affect decoded output."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    @classmethod
    def model_construct(cls, _fields_set=None, **values):
        raise TypeError(
            "model_construct bypasses wire validation; use model_validate instead"
        )

    def model_copy(self, *, update=None, deep: bool = False):
        if update:
            raise TypeError(
                "model_copy(update=...) bypasses wire validation; use model_dump "
                "and model_validate instead"
            )
        return super().model_copy(deep=deep)


class CoordinateEncodingModel(_WireModel):
    kind: CoordinateEncodingKind
    origin: float
    scale: float
    max_error_pixels: float

    @model_validator(mode="after")
    def _scene_coordinate_contract(self) -> "CoordinateEncodingModel":
        # Reuse the Scene authority for finite, positive-scale, and error checks.
        self.to_scene()
        return self

    @classmethod
    def from_scene(cls, value: CoordinateEncoding) -> "CoordinateEncodingModel":
        return cls(
            kind=value.kind,
            origin=value.origin,
            scale=value.scale,
            max_error_pixels=value.max_error_pixels,
        )

    def to_scene(self) -> CoordinateEncoding:
        return CoordinateEncoding(
            kind=self.kind,
            origin=self.origin,
            scale=self.scale,
            max_error_pixels=self.max_error_pixels,
        )


class DataSourceModel(_WireModel):
    format: Literal["arrow-ipc-stream"]
    uri: str = Field(min_length=1)


class CapabilitiesModel(_WireModel):
    viewport_query: bool
    lod: bool
    magnitude_filter: bool
    catalog_detail: bool
    max_batch_rows: int = Field(gt=0)


class StyleAssetModel(_WireModel):
    id: str = Field(min_length=1)
    value: Mapping[str, Any]

    @field_validator("value", mode="before")
    @classmethod
    def _plain_style_value(cls, value):
        return _plain_json_value(value)

    @field_validator("value")
    @classmethod
    def _freeze_style_value(cls, value):
        return _deep_freeze(value)

    @field_serializer("value")
    def _serialize_style_value(self, value, info):
        return _serialize_wire_value(value, info.mode)


class PaletteAssetModel(_WireModel):
    id: str = Field(min_length=1)
    colors: tuple[str, ...]


class LayerManifestModel(_WireModel):
    id: str = Field(min_length=1)
    kind: SceneKind
    group_id: str
    required: bool
    zorder: float
    load_priority: int
    coordinate_space: CoordinateSpace
    clip_id: str | None
    style_id: str | None
    interactive: bool
    interaction: InteractionPolicy
    hover_fields: tuple[str, ...]
    row_count: int = Field(ge=0)
    byte_length: int = Field(ge=0)
    content_hash: str
    coordinate_encoding: Mapping[str, CoordinateEncodingModel]
    data_source: DataSourceModel

    @field_validator("content_hash")
    @classmethod
    def _valid_content_hash(cls, value: str) -> str:
        return _validate_hash(value)

    @field_validator("coordinate_encoding")
    @classmethod
    def _freeze_coordinate_encoding(cls, value):
        return _deep_freeze(value)

    @field_serializer("coordinate_encoding")
    def _serialize_coordinate_encoding(self, value, info):
        return _serialize_wire_value(value, info.mode)

    @model_validator(mode="after")
    def _layer_contract(self) -> "LayerManifestModel":
        if not self.interactive and self.hover_fields:
            raise ValueError("hover_fields must be empty for a noninteractive layer")
        expected_interactive = self.interaction is not InteractionPolicy.NONE
        if self.interactive is not expected_interactive:
            raise ValueError("interactive must match the exact interaction policy")
        expected_coordinates = {"x", "y"} if self.kind in _COORDINATE_KINDS else set()
        actual_coordinates = set(self.coordinate_encoding)
        if actual_coordinates != expected_coordinates:
            raise ValueError(
                "coordinate_encoding must contain exactly x and y for "
                "coordinate-bearing layers and be empty otherwise"
            )
        return self

    @classmethod
    def from_layer(
        cls,
        layer: SceneLayer,
        *,
        byte_length: int,
        content_hash: str,
        data_source: DataSourceModel | Mapping[str, Any],
        style_id: str | None,
    ) -> "LayerManifestModel":
        if not isinstance(layer, SceneLayer):
            raise TypeError("layer must be a SceneLayer")
        return cls(
            id=layer.id,
            kind=layer.kind,
            group_id=layer.group_id,
            required=layer.required,
            zorder=layer.zorder,
            load_priority=layer.load_priority,
            coordinate_space=layer.space,
            clip_id=layer.clip_id,
            style_id=style_id,
            interactive=layer.interaction is not InteractionPolicy.NONE,
            interaction=layer.interaction,
            hover_fields=layer.hover_fields,
            row_count=layer.data.row_count,
            byte_length=byte_length,
            content_hash=content_hash,
            coordinate_encoding={
                name: CoordinateEncodingModel.from_scene(encoding)
                for name, encoding in layer.coordinate_encoding.items()
            },
            data_source=data_source,
        )


@dataclass(frozen=True)
class _ResolvedLayerContext:
    wire: LayerManifestModel
    style: Mapping[str, Any]
    palette: tuple[str, ...] | None

    def __post_init__(self):
        object.__setattr__(self, "style", _freeze_mapping(self.style))
        if self.palette is not None:
            object.__setattr__(self, "palette", tuple(self.palette))


class SceneManifestModel(_WireModel):
    schema_version: str
    scene_id: str = Field(min_length=1)
    content_hash: str
    minimum_loader_version: str
    viewport: Mapping[str, Any]
    coordinate_spaces: Mapping[str, Any]
    clips: tuple[Mapping[str, Any], ...]
    styles: tuple[StyleAssetModel, ...]
    palettes: tuple[PaletteAssetModel, ...]
    layers: tuple[LayerManifestModel, ...]
    capabilities: CapabilitiesModel
    extensions: Mapping[str, Any] = Field(default_factory=dict)

    @field_validator("viewport", "coordinate_spaces", "extensions", mode="before")
    @classmethod
    def _plain_mapping_assets(cls, value):
        return _plain_json_value(value)

    @field_validator("viewport", "coordinate_spaces", "extensions")
    @classmethod
    def _freeze_mapping_assets(cls, value):
        return _deep_freeze(value)

    @field_validator("clips", mode="before")
    @classmethod
    def _plain_clip_assets(cls, value):
        return _plain_json_value(value)

    @field_validator("clips")
    @classmethod
    def _freeze_clip_assets(cls, value):
        return tuple(_deep_freeze(item) for item in value)

    @field_serializer("viewport", "coordinate_spaces", "clips", "extensions")
    def _serialize_nested_assets(self, value, info):
        return _serialize_wire_value(value, info.mode)

    @field_validator("schema_version")
    @classmethod
    def _supported_schema_version(cls, value: str) -> str:
        major, _ = _parse_version(value, "schema_version")
        if major != _SUPPORTED_SCHEMA_MAJOR:
            raise ValueError(
                f"unsupported Scene schema major version {major}; "
                f"supported major version is {_SUPPORTED_SCHEMA_MAJOR}"
            )
        return value

    @field_validator("minimum_loader_version")
    @classmethod
    def _compatible_minimum_loader_version(cls, value: str) -> str:
        parsed = _parse_version(value, "minimum_loader_version")
        if parsed > _CURRENT_LOADER_VERSION:
            raise ValueError(
                f"minimum loader version {value} exceeds current loader "
                f"{SCENE_SCHEMA_VERSION}"
            )
        return value

    @field_validator("content_hash")
    @classmethod
    def _valid_scene_hash(cls, value: str) -> str:
        return _validate_hash(value)

    @field_validator("extensions")
    @classmethod
    def _compatible_extensions(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        unknown = sorted(set(value) - _COMPATIBLE_EXTENSION_KEYS)
        if unknown:
            raise ValueError(f"unsupported compatible extension keys: {unknown}")
        return value

    @model_validator(mode="after")
    def _asset_and_layer_contract(self) -> "SceneManifestModel":
        _require_unique((layer.id for layer in self.layers), "layer")
        _require_unique((style.id for style in self.styles), "style")
        _require_unique((palette.id for palette in self.palettes), "palette")
        style_ids = {style.id for style in self.styles}
        palette_ids = {palette.id for palette in self.palettes}
        for layer in self.layers:
            if layer.style_id is not None and layer.style_id not in style_ids:
                raise ValueError(f"layer {layer.id!r} references an unknown style id")
        for style in self.styles:
            palette_id = style.value.get("palette_id")
            if palette_id is not None and palette_id not in palette_ids:
                raise ValueError(f"style {style.id!r} references an unknown palette id")
        return self

    @model_validator(mode="after")
    def _content_hash_contract(self) -> "SceneManifestModel":
        if self.content_hash != _declared_scene_hash(self):
            raise ValueError("scene content hash does not match canonical manifest")
        return self

    def resolve_layer(self, layer_id: str) -> _ResolvedLayerContext:
        try:
            layer = next(layer for layer in self.layers if layer.id == layer_id)
        except StopIteration as error:
            raise KeyError(f"unknown Scene layer id: {layer_id}") from error
        styles = {asset.id: asset.value for asset in self.styles}
        palettes = {asset.id: asset.colors for asset in self.palettes}
        style = {} if layer.style_id is None else styles[layer.style_id]
        palette_id = style.get("palette_id")
        palette = None if palette_id is None else palettes[palette_id]
        return _ResolvedLayerContext(
            wire=layer,
            style=style,
            palette=palette,
        )


def build_scene_manifest(
    *,
    scene_id: str,
    layers: Sequence[SceneLayer],
    layer_bytes: Mapping[str, bytes],
    viewport: Mapping[str, Any],
    coordinate_spaces: Mapping[str, Any],
    clips: Sequence[Mapping[str, Any]],
    capabilities: CapabilitiesModel,
    data_sources: Mapping[str, DataSourceModel | Mapping[str, Any]] | None = None,
    minimum_loader_version: str = SCENE_SCHEMA_VERSION,
) -> SceneManifestModel:
    """Build a strict final manifest from resolved Scene assets and exact bytes."""
    layers = tuple(layers)
    layer_ids = {layer.id for layer in layers}
    if set(layer_bytes) != layer_ids:
        raise ValueError("layer_bytes keys must exactly match Scene layer ids")
    if data_sources is not None and set(data_sources) != layer_ids:
        raise ValueError("data_sources keys must exactly match Scene layer ids")

    style_assets = []
    palette_assets: dict[str, tuple[str, ...]] = {}
    manifest_layers = []
    for layer in layers:
        style_id = f"style-{layer.id}" if layer.style else None
        if style_id is not None:
            style_assets.append(StyleAssetModel(id=style_id, value=layer.style))
        palette_id = layer.style.get("palette_id")
        if layer.palette is None:
            if palette_id is not None:
                raise ValueError(
                    "style palette_id must be absent when the layer has no palette"
                )
        else:
            if not isinstance(palette_id, str) or not palette_id:
                raise ValueError(
                    "a layer palette requires a hash-bound style palette_id"
                )
            existing = palette_assets.setdefault(palette_id, layer.palette)
            if existing != layer.palette:
                raise ValueError("palette ids must reference identical colors")
        payload = layer_bytes[layer.id]
        source = (
            data_sources[layer.id]
            if data_sources is not None
            else DataSourceModel(format="arrow-ipc-stream", uri=f"{layer.id}.arrow")
        )
        manifest_layers.append(
            LayerManifestModel.from_layer(
                layer,
                byte_length=len(payload),
                content_hash=_bytes_hash(payload),
                data_source=source,
                style_id=style_id,
            )
        )

    raw_values = {
        "schema_version": SCENE_SCHEMA_VERSION,
        "scene_id": scene_id,
        "content_hash": "sha256:" + "0" * 64,
        "minimum_loader_version": minimum_loader_version,
        "viewport": _plain_json_value(viewport),
        "coordinate_spaces": _plain_json_value(coordinate_spaces),
        "clips": _plain_json_value(tuple(clips)),
        "styles": [asset.model_dump(mode="python") for asset in style_assets],
        "palettes": [
            PaletteAssetModel(id=palette_id, colors=colors).model_dump(mode="python")
            for palette_id, colors in sorted(palette_assets.items())
        ],
        "layers": [layer.model_dump(mode="python") for layer in manifest_layers],
        "capabilities": capabilities.model_dump(mode="python"),
        "extensions": {},
    }
    ordered_hashes = tuple(layer.content_hash for layer in manifest_layers)
    raw_values["content_hash"] = _declared_scene_hash(raw_values, ordered_hashes)
    manifest = SceneManifestModel.model_validate(raw_values)
    # A final manifest must never bless opaque or cross-wired payload bytes.
    # The local import avoids an import cycle while keeping validation shared.
    from starplot.interactive.arrow_transport import decode_layer_stream

    for layer in layers:
        decoded_layer = decode_layer_stream(
            layer_bytes[layer.id], manifest.resolve_layer(layer.id)
        )
        if not _scene_layers_equal(layer, decoded_layer):
            raise ValueError(
                f"Arrow payload data does not match supplied SceneLayer {layer.id!r}"
            )
    if scene_content_hash(manifest, layer_bytes) != manifest.content_hash:
        raise ValueError("scene content hash does not match canonical manifest")
    return manifest


def canonical_manifest_bytes(
    manifest: SceneManifestModel | LayerManifestModel | Mapping[str, Any],
    *,
    exclude_content_hash: bool = False,
) -> bytes:
    """Return compact, key-sorted UTF-8 JSON for hashing and transport."""
    if isinstance(manifest, BaseModel):
        exclude = {"content_hash"} if exclude_content_hash else None
        value = manifest.model_dump(mode="python", exclude=exclude)
    else:
        value = dict(manifest)
        if exclude_content_hash:
            value.pop("content_hash", None)
    return json.dumps(
        _plain_json_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def scene_content_hash(
    manifest: SceneManifestModel,
    layers: Mapping[str, bytes | str] | Sequence[bytes | str],
) -> str:
    """Hash a manifest only after every ordered layer identity is verified."""
    expected_ids = tuple(layer.id for layer in manifest.layers)
    if isinstance(layers, Mapping):
        supplied_ids = set(layers)
        missing = sorted(set(expected_ids) - supplied_ids)
        extra = sorted(supplied_ids - set(expected_ids))
        if missing:
            raise ValueError(f"missing layer hashes for: {missing}")
        if extra:
            raise ValueError(f"extra layer hashes for: {extra}")
        values = tuple(layers[layer_id] for layer_id in expected_ids)
    else:
        values = tuple(layers)
        if len(values) != len(expected_ids):
            raise ValueError("layer hash count must match manifest layer count")

    ordered_hashes = []
    for manifest_layer, value in zip(manifest.layers, values):
        supplied_hash = (
            _bytes_hash(value) if isinstance(value, bytes) else _validate_hash(value)
        )
        if supplied_hash != manifest_layer.content_hash:
            raise ValueError(
                f"layer {manifest_layer.id!r} hash does not match its manifest declaration"
            )
        ordered_hashes.append(supplied_hash)

    return _declared_scene_hash(manifest, ordered_hashes)


def _declared_scene_hash(
    manifest: SceneManifestModel | Mapping[str, Any],
    ordered_hashes: Sequence[str] | None = None,
) -> str:
    if ordered_hashes is None:
        if not isinstance(manifest, SceneManifestModel):
            raise TypeError("raw manifest hashing requires ordered layer hashes")
        ordered_hashes = tuple(layer.content_hash for layer in manifest.layers)
    digest = hashlib.sha256()
    digest.update(canonical_manifest_bytes(manifest, exclude_content_hash=True))
    for layer_hash in ordered_hashes:
        digest.update(layer_hash.encode("ascii"))
    return "sha256:" + digest.hexdigest()


def _parse_version(value: str, name: str) -> tuple[int, int]:
    if not isinstance(value, str):
        raise ValueError(f"{name} must use major.minor syntax")
    match = _VERSION_PATTERN.fullmatch(value)
    if match is None:
        raise ValueError(f"{name} must use major.minor syntax")
    return int(match.group("major")), int(match.group("minor"))


def _validate_hash(value: str) -> str:
    if not isinstance(value, str) or _HASH_PATTERN.fullmatch(value) is None:
        raise ValueError("content hash must be a sha256: prefixed SHA-256 hex digest")
    return value


def _bytes_hash(value: bytes) -> str:
    if not isinstance(value, bytes):
        raise TypeError("layer payloads must be bytes")
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _require_unique(values, name: str) -> None:
    values = tuple(values)
    if len(values) != len(set(values)):
        raise ValueError(f"Scene manifest contains a duplicate {name} id")


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return _deep_freeze(value)


def _deep_freeze(value):
    if isinstance(value, Mapping):
        return _FrozenMapping({key: _deep_freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(item) for item in value)
    return value


def _serialize_wire_value(value, mode: str):
    if isinstance(value, BaseModel):
        return value.model_dump(mode=mode)
    if isinstance(value, Mapping):
        return {key: _serialize_wire_value(item, mode) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        items = [_serialize_wire_value(item, mode) for item in value]
        return tuple(items) if mode == "python" else items
    return value


def _plain_json_value(value):
    if isinstance(value, BaseModel):
        return _plain_json_value(value.model_dump(mode="python"))
    if isinstance(value, Mapping):
        return {key: _plain_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_json_value(item) for item in value]
    return value


def _scene_layers_equal(expected: SceneLayer, actual: SceneLayer) -> bool:
    semantic_fields = (
        "id",
        "kind",
        "group_id",
        "zorder",
        "load_priority",
        "space",
        "clip_id",
        "style",
        "interaction",
        "hover_fields",
        "required",
        "coordinate_encoding",
        "palette",
    )
    if any(
        getattr(expected, field) != getattr(actual, field) for field in semantic_fields
    ):
        return False
    if expected.data.row_count != actual.data.row_count:
        return False
    if set(expected.data.columns) != set(actual.data.columns):
        return False
    for name, expected_values in expected.data.columns.items():
        actual_values = actual.data[name]
        if expected_values.dtype != actual_values.dtype:
            return False
        if expected_values.dtype.kind in {"f", "c"}:
            equal = np.array_equal(expected_values, actual_values, equal_nan=True)
        else:
            equal = np.array_equal(expected_values, actual_values)
        if not equal:
            return False
    return True
