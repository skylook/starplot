"""Versioned JSON manifest models for transport-neutral interactive scenes."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
_VERSION_PATTERN = re.compile(r"^(?P<major>0|[1-9][0-9]*)\.(?P<minor>0|[1-9][0-9]*)$")
_HASH_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


class _ManifestModel(BaseModel):
    """Frozen wire models that tolerate forward, optional minor fields."""

    model_config = ConfigDict(extra="ignore", frozen=True)


class CoordinateEncodingModel(_ManifestModel):
    kind: CoordinateEncodingKind
    origin: float = 0.0
    scale: float = 1.0
    max_error_pixels: float = 0.0

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


class DataSourceModel(_ManifestModel):
    format: Literal["arrow-ipc-stream"] = "arrow-ipc-stream"
    uri: str

    @field_validator("uri")
    @classmethod
    def _nonempty_uri(cls, value: str) -> str:
        if not value:
            raise ValueError("data source uri must be non-empty")
        return value


class CapabilitiesModel(_ManifestModel):
    viewport_query: bool = False
    lod: bool = False
    magnitude_filter: bool = False
    catalog_detail: bool = False
    max_batch_rows: int = Field(default=250_000, gt=0)


class LayerManifestModel(_ManifestModel):
    id: str = Field(min_length=1)
    kind: SceneKind
    required: bool
    zorder: float
    load_priority: int
    coordinate_space: CoordinateSpace
    clip_id: str | None
    style_id: str | None
    interactive: bool
    hover_fields: tuple[str, ...] = ()
    row_count: int = Field(ge=0)
    byte_length: int = Field(ge=0)
    content_hash: str
    coordinate_encoding: Mapping[str, CoordinateEncodingModel] = Field(
        default_factory=dict
    )
    data_source: DataSourceModel

    # These are runtime resolver context, not wire fields. Top-level manifest
    # style/palette assets remain the sole canonical wire representation.
    resolved_group_id: str = Field(default="", exclude=True, repr=False)
    resolved_style: Mapping[str, Any] = Field(
        default_factory=dict, exclude=True, repr=False
    )
    resolved_interaction: InteractionPolicy | None = Field(
        default=None, exclude=True, repr=False
    )
    resolved_palette: tuple[str, ...] | None = Field(
        default=None, exclude=True, repr=False
    )

    @field_validator("content_hash")
    @classmethod
    def _valid_content_hash(cls, value: str) -> str:
        return _validate_hash(value)

    @model_validator(mode="after")
    def _interaction_contract(self) -> "LayerManifestModel":
        if not self.interactive and self.hover_fields:
            raise ValueError("hover_fields must be empty for a noninteractive layer")
        return self

    @classmethod
    def from_layer(
        cls,
        layer: SceneLayer,
        *,
        byte_length: int,
        content_hash: str,
        data_source: DataSourceModel | Mapping[str, Any],
        style_id: str | None = None,
    ) -> "LayerManifestModel":
        if not isinstance(layer, SceneLayer):
            raise TypeError("layer must be a SceneLayer")
        if style_id is None and layer.style:
            style_id = f"style-{layer.id}"
        return cls(
            id=layer.id,
            kind=layer.kind,
            required=layer.required,
            zorder=layer.zorder,
            load_priority=layer.load_priority,
            coordinate_space=layer.space,
            clip_id=layer.clip_id,
            style_id=style_id,
            interactive=layer.interaction is not InteractionPolicy.NONE,
            hover_fields=layer.hover_fields,
            row_count=layer.data.row_count,
            byte_length=byte_length,
            content_hash=content_hash,
            coordinate_encoding={
                name: CoordinateEncodingModel.from_scene(encoding)
                for name, encoding in layer.coordinate_encoding.items()
            },
            data_source=data_source,
            resolved_group_id=layer.group_id,
            resolved_style=layer.style,
            resolved_interaction=layer.interaction,
            resolved_palette=layer.palette,
        )


class SceneManifestModel(_ManifestModel):
    schema_version: str = SCENE_SCHEMA_VERSION
    scene_id: str = Field(min_length=1)
    content_hash: str | None = None
    minimum_loader_version: str = SCENE_SCHEMA_VERSION
    viewport: Mapping[str, Any]
    coordinate_spaces: Mapping[str, Any]
    clips: tuple[Mapping[str, Any], ...]
    styles: tuple[Mapping[str, Any], ...]
    palettes: tuple[Mapping[str, Any], ...]
    layers: tuple[LayerManifestModel, ...]
    capabilities: CapabilitiesModel = CapabilitiesModel()

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
    def _valid_minimum_loader_version(cls, value: str) -> str:
        _parse_version(value, "minimum_loader_version")
        return value

    @field_validator("content_hash")
    @classmethod
    def _valid_scene_hash(cls, value: str | None) -> str | None:
        return None if value is None else _validate_hash(value)

    @model_validator(mode="after")
    def _unique_layer_ids(self) -> "SceneManifestModel":
        layer_ids = [layer.id for layer in self.layers]
        if len(layer_ids) != len(set(layer_ids)):
            raise ValueError("Scene manifest contains a duplicate layer id")
        return self


def canonical_manifest_bytes(
    manifest: SceneManifestModel | LayerManifestModel | Mapping[str, Any],
    *,
    exclude_content_hash: bool = False,
) -> bytes:
    """Return compact, key-sorted UTF-8 JSON for hashing and transport."""
    if isinstance(manifest, BaseModel):
        exclude = {"content_hash"} if exclude_content_hash else None
        value = manifest.model_dump(mode="json", exclude=exclude)
    else:
        value = dict(manifest)
        if exclude_content_hash:
            value.pop("content_hash", None)
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def scene_content_hash(
    manifest: SceneManifestModel,
    layers: Mapping[str, bytes | str] | Sequence[bytes | str],
) -> str:
    """Hash canonical scene structure followed by ordered layer hashes."""
    digest = hashlib.sha256()
    digest.update(canonical_manifest_bytes(manifest, exclude_content_hash=True))
    values: Sequence[bytes | str]
    if isinstance(layers, Mapping):
        missing = [layer.id for layer in manifest.layers if layer.id not in layers]
        if missing:
            raise ValueError(f"missing layer hashes for: {missing}")
        values = tuple(layers[layer.id] for layer in manifest.layers)
    else:
        values = tuple(layers)
        if len(values) != len(manifest.layers):
            raise ValueError("layer hash count must match manifest layer count")
    for value in values:
        layer_hash = (
            "sha256:" + hashlib.sha256(value).hexdigest()
            if isinstance(value, bytes)
            else _validate_hash(value)
        )
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
