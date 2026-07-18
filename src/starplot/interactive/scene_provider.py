"""Framework-neutral responses for serving canonical Scene transport bytes."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, replace
import hashlib
import json
from types import MappingProxyType
from typing import Protocol

import numpy as np

from starplot.interactive.arrow_transport import (
    decode_layer_stream,
    encode_layer_stream,
)
from starplot.interactive.scene import (
    ColumnarData,
    FullResolutionPolicy,
    InteractionPolicy,
    LodPolicy,
    ViewportRequest,
)
from starplot.interactive.scene_manifest import (
    SceneManifestModel,
    canonical_manifest_bytes,
    scene_content_hash,
)


class CatalogDetailProvider(Protocol):
    def get_object(self, object_id: str) -> Mapping[str, object] | None: ...


class LayerRequest(Protocol):
    def cache_key_parts(self) -> tuple[object, ...]: ...


@dataclass(frozen=True)
class SceneResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes | Iterable[bytes] = b""

    def __post_init__(self):
        object.__setattr__(self, "headers", MappingProxyType(dict(self.headers)))

    def iter_body(self) -> Iterator[bytes]:
        if isinstance(self.body, bytes):
            yield self.body
        else:
            yield from self.body

    def body_bytes(self) -> bytes:
        return b"".join(self.iter_body())


class SceneProvider:
    """Serve prevalidated manifest/layer bytes without selecting a web framework."""

    def __init__(
        self,
        manifest: SceneManifestModel,
        manifest_bytes: bytes,
        layer_bytes: Mapping[str, bytes],
        detail_provider: CatalogDetailProvider | None = None,
        lod_policies: Mapping[str, LodPolicy] | None = None,
    ):
        if not isinstance(manifest, SceneManifestModel):
            raise TypeError("manifest must be a SceneManifestModel")
        if not isinstance(manifest_bytes, bytes):
            raise TypeError("manifest_bytes must be bytes")
        expected_layers = {layer.id for layer in manifest.layers}
        if set(layer_bytes) != expected_layers or not all(
            isinstance(value, bytes) for value in layer_bytes.values()
        ):
            raise ValueError("layer_bytes must contain exactly the manifest layer ids")
        if canonical_manifest_bytes(manifest) != manifest_bytes:
            raise ValueError("manifest_bytes must be exact canonical manifest bytes")
        if scene_content_hash(manifest, layer_bytes) != manifest.content_hash:
            raise ValueError("layer_bytes do not match the manifest content hash")
        self.manifest_model = manifest
        self._manifest_bytes = manifest_bytes
        self._layer_bytes = MappingProxyType(dict(layer_bytes))
        self._detail_provider = detail_provider
        policies = dict(lod_policies or {})
        unknown_policy_layers = set(policies).difference(expected_layers)
        if unknown_policy_layers:
            raise ValueError("lod_policies reference unknown manifest layers")
        if not all(hasattr(policy, "select") for policy in policies.values()):
            raise TypeError("lod_policies values must implement select(layer, request)")
        self._lod_policies = MappingProxyType(policies)
        self._full_resolution_policy = FullResolutionPolicy()
        self._dynamic_cache: dict[tuple[object, ...], bytes] = {}
        self._validate_interaction_policy()

    @staticmethod
    def _etag(payload: bytes) -> str:
        return f'"sha256:{hashlib.sha256(payload).hexdigest()}"'

    def _headers(
        self, payload: bytes, content_type: str, *, immutable: bool
    ) -> Mapping[str, str]:
        return {
            "Content-Type": content_type,
            "Content-Length": str(len(payload)),
            "ETag": self._etag(payload),
            "Cache-Control": (
                "public, max-age=31536000, immutable" if immutable else "no-cache"
            ),
            "X-Starplot-Schema-Version": self.manifest_model.schema_version,
        }

    @staticmethod
    def _not_modified(headers: Mapping[str, str], if_none_match: str | None) -> bool:
        return if_none_match is not None and if_none_match == headers["ETag"]

    def _validate_interaction_policy(self) -> None:
        for wire_layer in self.manifest_model.layers:
            decoded = decode_layer_stream(
                self._layer_bytes[wire_layer.id],
                self.manifest_model.resolve_layer(wire_layer.id),
            )
            names = set(decoded.data.columns)
            if wire_layer.interaction is InteractionPolicy.NONE:
                forbidden = names.intersection(
                    {"object_id", "name", "magnitude", "ra", "dec"}
                )
                if forbidden:
                    raise ValueError(
                        "NONE interaction layers cannot retain hover or object metadata"
                    )
            if (
                wire_layer.interaction is InteractionPolicy.HOVER_AND_DETAIL
                and "object_id" not in names
            ):
                raise ValueError("HOVER_AND_DETAIL layers require object_id")

    def manifest(self, if_none_match: str | None = None) -> SceneResponse:
        headers = self._headers(
            self._manifest_bytes, "application/json", immutable=False
        )
        if self._not_modified(headers, if_none_match):
            return SceneResponse(304, headers)
        return SceneResponse(200, headers, self._manifest_bytes)

    def layer(
        self,
        layer_id: str,
        request: LayerRequest | None = None,
        if_none_match: str | None = None,
    ) -> SceneResponse:
        try:
            payload = self._layer_bytes[layer_id]
        except KeyError:
            return SceneResponse(404, {"Cache-Control": "no-cache"})
        if request is not None and not isinstance(request, ViewportRequest):
            raise TypeError("request must be a ViewportRequest or None")
        # The original Stream bytes are canonical transport identity.  Do not
        # decode/re-encode this path: even a lossless encoder round-trip is not
        # entitled to preserve IPC byte layout.
        is_complete = request is None or request.is_full
        if not is_complete:
            payload = self._viewport_payload(layer_id, request)
        headers = self._headers(
            payload,
            "application/vnd.apache.arrow.stream",
            immutable=is_complete,
        )
        if self._not_modified(headers, if_none_match):
            return SceneResponse(304, headers)
        return SceneResponse(200, headers, payload)

    def _viewport_payload(self, layer_id: str, request: ViewportRequest) -> bytes:
        wire_layer = self.manifest_model.resolve_layer(layer_id).wire
        cache_key = (
            self.manifest_model.content_hash,
            wire_layer.content_hash,
            *request.cache_key_parts(),
            self.manifest_model.schema_version,
        )
        cached = self._dynamic_cache.get(cache_key)
        if cached is not None:
            return cached
        layer = decode_layer_stream(
            self._layer_bytes[layer_id], self.manifest_model.resolve_layer(layer_id)
        )
        policy = self._lod_policies.get(layer_id, self._full_resolution_policy)
        selected = np.asarray(policy.select(layer, request), dtype=np.bool_)
        if selected.ndim != 1 or len(selected) != layer.data.row_count:
            raise ValueError(
                "LOD policy must return one boolean selection per Scene row"
            )
        selected_layer = replace(
            layer,
            data=ColumnarData.from_mapping(
                {name: values[selected] for name, values in layer.data.columns.items()}
            ),
        )
        payload = encode_layer_stream(selected_layer)
        self._dynamic_cache[cache_key] = payload
        return payload

    def object_detail(self, object_id: str) -> SceneResponse:
        if (
            not any(
                layer.interaction is InteractionPolicy.HOVER_AND_DETAIL
                for layer in self.manifest_model.layers
            )
            or self._detail_provider is None
        ):
            return SceneResponse(404, {"Cache-Control": "no-cache"})
        value = self._detail_provider.get_object(object_id)
        if value is None:
            return SceneResponse(404, {"Cache-Control": "no-cache"})
        if value.get("object_id") != object_id:
            raise ValueError("catalog detail object_id must match the requested id")
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        return SceneResponse(
            200, self._headers(payload, "application/json", immutable=False), payload
        )
