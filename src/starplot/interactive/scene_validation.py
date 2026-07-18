"""Resource and trust-boundary validation shared by Scene transports.

The manifest model and Arrow decoder remain the authority for wire correctness.
This module adds the limits that must be applied *before* those decoders are
asked to allocate data, so file, inline, and framework-hosted scenes have the
same failure boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from typing import TYPE_CHECKING, Any, Mapping
from urllib.parse import urljoin, urlparse

if TYPE_CHECKING:  # pragma: no cover - imports would otherwise form a cycle
    from starplot.interactive.scene_manifest import LayerManifestModel, SceneManifestModel


@dataclass(frozen=True)
class LoaderLimits:
    """Hard upper bounds for one untrusted Scene payload."""

    max_manifest_bytes: int = 4 * 1024 * 1024
    max_layer_bytes: int = 512 * 1024 * 1024
    max_layer_rows: int = 10_000_000
    max_string_bytes: int = 64 * 1024
    max_geometry_depth: int = 8

    def __post_init__(self) -> None:
        if any(not isinstance(value, int) or value <= 0 for value in self.__dict__.values()):
            raise ValueError("LoaderLimits values must be positive integers")


DEFAULT_LOADER_LIMITS = LoaderLimits()


def validate_manifest_bytes(
    payload: bytes, limits: LoaderLimits = DEFAULT_LOADER_LIMITS
) -> "SceneManifestModel":
    """Decode a manifest only after its byte, JSON, and nested-value limits pass."""
    if not isinstance(payload, bytes):
        raise TypeError("manifest payload must be bytes")
    if len(payload) > limits.max_manifest_bytes:
        raise ValueError("Scene manifest exceeds the configured byte limit")
    try:
        text = payload.decode("utf-8")
        value = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Scene manifest is not valid UTF-8 JSON") from error
    _validate_json_value(value, limits)
    from starplot.interactive.scene_manifest import SceneManifestModel

    return SceneManifestModel.model_validate(value)


def validate_layer_declaration(
    layer: "LayerManifestModel", limits: LoaderLimits = DEFAULT_LOADER_LIMITS
) -> None:
    """Reject oversized declarations before fetching or opening Arrow bytes."""
    if layer.byte_length > limits.max_layer_bytes:
        raise ValueError(f"layer {layer.id!r} exceeds the configured byte limit")
    if layer.row_count > limits.max_layer_rows:
        raise ValueError(f"layer {layer.id!r} exceeds the configured row limit")


def validate_layer_bytes(
    data: bytes,
    layer: "LayerManifestModel",
    limits: LoaderLimits = DEFAULT_LOADER_LIMITS,
) -> None:
    """Apply pre-allocation limits; canonical Arrow validation follows separately."""
    validate_layer_declaration(layer, limits)
    if not isinstance(data, bytes):
        raise TypeError("layer payload must be bytes")
    if len(data) > limits.max_layer_bytes:
        raise ValueError(f"layer {layer.id!r} exceeds the configured byte limit")


def validate_data_url(
    uri: str,
    *,
    manifest_url: str,
    allowed_origins: tuple[str, ...] = (),
) -> str:
    """Resolve a layer URL under the same-origin-by-default transport policy."""
    if not isinstance(uri, str) or not uri:
        raise ValueError("layer data URL is required")
    resolved = urljoin(manifest_url, uri)
    parsed = urlparse(resolved)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("layer data URL must resolve to absolute HTTP(S)")
    manifest = urlparse(manifest_url)
    manifest_origin = f"{manifest.scheme}://{manifest.netloc}"
    origins = {manifest_origin}
    for origin in allowed_origins:
        candidate = urlparse(origin)
        if candidate.scheme not in {"http", "https"} or not candidate.netloc:
            raise ValueError("allowed origins must be absolute HTTP(S) origins")
        origins.add(f"{candidate.scheme}://{candidate.netloc}")
    if f"{parsed.scheme}://{parsed.netloc}" not in origins:
        raise ValueError("layer URL origin is not allowed")
    return resolved


def _validate_json_value(value: Any, limits: LoaderLimits, depth: int = 0) -> None:
    if depth > limits.max_geometry_depth:
        raise ValueError("Scene manifest exceeds the configured geometry depth")
    if isinstance(value, str):
        if len(value.encode("utf-8")) > limits.max_string_bytes:
            raise ValueError("Scene manifest contains a string exceeding the configured byte limit")
        return
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Scene manifest contains non-finite numeric bounds")
    if isinstance(value, Mapping):
        for key, item in value.items():
            _validate_json_value(key, limits, depth + 1)
            _validate_json_value(item, limits, depth + 1)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _validate_json_value(item, limits, depth + 1)
