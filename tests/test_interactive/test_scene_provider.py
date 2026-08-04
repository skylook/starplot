"""Framework-neutral byte-serving contracts for compiled Scenes."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from threading import Barrier

import numpy as np
import pytest

from starplot.interactive import (
    ColumnarData,
    InteractionPolicy,
    SceneKind,
    SceneLayer,
    ScenePackage,
    export_scene_html,
)
from starplot.interactive.commands import CoordinateSpace
from starplot.interactive.scene import (
    CoordinateEncoding,
    CoordinateEncodingKind,
    ViewportRequest,
)
from starplot.interactive.scene_manifest import SceneManifestModel
from starplot.interactive.scene_provider import SceneProvider


class DetailCatalog:
    def get_object(self, object_id):
        return {"object_id": object_id, "designation": "Rigel"} if object_id == "star:rigel" else None


def _scene(interaction=InteractionPolicy.HOVER_AND_DETAIL, include_object_id=True):
    columns = {
        "x": np.array([1.0]), "y": np.array([2.0]),
        "size": np.array([3.0], dtype=np.float32),
        "color_index": np.array([0], dtype=np.uint8),
        "opacity": np.array([1.0], dtype=np.float32), "name": np.array(["Rigel"]),
    }
    if include_object_id:
        columns["object_id"] = np.array(["star:rigel"])
    layer = SceneLayer(
        id="stars", kind=SceneKind.SCATTER, zorder=1, load_priority=1,
        space=CoordinateSpace.DATA, clip_id=None,
        style={"marker": {"symbol": "circle"}}, interaction=interaction,
        hover_fields=("name",) if interaction is not InteractionPolicy.NONE else (),
        coordinate_encoding={
            "x": CoordinateEncoding(CoordinateEncodingKind.ABSOLUTE_F64),
            "y": CoordinateEncoding(CoordinateEncodingKind.ABSOLUTE_F64),
        }, data=ColumnarData.from_mapping(columns),
    )
    return ScenePackage(
        layers=(layer,), projection_info={}, style_info={},
        viewport={"reference_width": 100, "reference_height": 100}, clips={}, palettes={},
    )


@pytest.fixture(autouse=True)
def _chdir(tmp_path, monkeypatch):
    """Make every test run with ``tmp_path`` as the current working directory."""
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def exported():
    result = export_scene_html(_scene(), "chart.html")
    manifest = SceneManifestModel.model_validate_json(result.manifest_bytes)
    return manifest, result


@pytest.fixture
def provider(exported):
    manifest, result = exported
    return SceneProvider(manifest, result.manifest_bytes, result.layer_bytes, DetailCatalog())


def test_complete_scene_provider_preserves_exported_bytes(provider, exported):
    manifest, result = exported
    response = provider.manifest()
    assert response.status == 200
    assert response.body_bytes() == result.manifest_bytes
    assert response.headers["Content-Type"] == "application/json"
    for layer in manifest.layers:
        body = provider.layer(layer.id).body_bytes()
        assert body == result.layer_bytes[layer.id]


def test_etags_unknown_ids_and_detail_policy(provider):
    manifest = provider.manifest()
    assert provider.manifest(manifest.headers["ETag"]).status == 304
    layer = provider.layer("stars")
    assert provider.layer("stars", if_none_match=layer.headers["ETag"]).status == 304
    assert provider.layer("unknown").status == 404
    detail = provider.object_detail("star:rigel")
    assert detail.status == 200
    assert json.loads(detail.body_bytes())["object_id"] == "star:rigel"
    assert provider.object_detail("unknown").status == 404


def test_provider_rejects_noncanonical_or_crosswired_transport(exported):
    manifest, result = exported
    with pytest.raises(ValueError, match="canonical manifest"):
        SceneProvider(manifest, result.manifest_bytes + b" ", result.layer_bytes)
    corrupted = {**result.layer_bytes, "stars": result.layer_bytes["stars"] + b"x"}
    with pytest.raises(ValueError, match="hash does not match"):
        SceneProvider(manifest, result.manifest_bytes, corrupted)


def test_none_policy_cannot_serve_hidden_hover_or_object_metadata():
    result = export_scene_html(_scene(InteractionPolicy.NONE, include_object_id=True), "chart.html")
    manifest = SceneManifestModel.model_validate_json(result.manifest_bytes)
    with pytest.raises(ValueError, match="NONE interaction"):
        SceneProvider(manifest, result.manifest_bytes, result.layer_bytes)


def test_detail_policy_requires_a_stable_object_id():
    result = export_scene_html(_scene(InteractionPolicy.HOVER_AND_DETAIL, include_object_id=False), "chart.html")
    manifest = SceneManifestModel.model_validate_json(result.manifest_bytes)
    with pytest.raises(ValueError, match="object_id"):
        SceneProvider(manifest, result.manifest_bytes, result.layer_bytes)


class _CountingPolicy:
    def __init__(self):
        self.calls = 0

    def select(self, layer, request):
        self.calls += 1
        return np.asarray(layer.data["x"] >= (request.x_min or 0), dtype=np.bool_)


class _BarrierPolicy(_CountingPolicy):
    def __init__(self):
        super().__init__()
        self._selection_barrier = Barrier(2)

    def select(self, layer, request):
        self.calls += 1
        self._selection_barrier.wait(timeout=5)
        return np.asarray(layer.data["x"] >= (request.x_min or 0), dtype=np.bool_)


def _provider_with_cache(exported, policy, cache_bytes):
    manifest, result = exported
    return SceneProvider(
        manifest,
        result.manifest_bytes,
        result.layer_bytes,
        lod_policies={"stars": policy},
        viewport_cache_bytes=cache_bytes,
    )


def test_viewport_cache_is_byte_bounded_and_evicts_least_recently_used(exported):
    sizing_policy = _CountingPolicy()
    sizing = _provider_with_cache(exported, sizing_policy, 1_000_000)
    first = ViewportRequest(x_min=0)
    second = ViewportRequest(x_min=2)
    first_size = len(sizing.layer("stars", first).body_bytes())
    second_size = len(sizing.layer("stars", second).body_bytes())

    policy = _CountingPolicy()
    provider = _provider_with_cache(exported, policy, max(first_size, second_size))
    provider.layer("stars", first)
    provider.layer("stars", second)
    provider.layer("stars", second)
    provider.layer("stars", first)

    assert policy.calls == 3
    assert provider._dynamic_cache_bytes <= max(first_size, second_size)
    assert len(provider._dynamic_cache) == 1


def test_oversized_viewport_payload_is_not_cached(exported):
    policy = _CountingPolicy()
    provider = _provider_with_cache(exported, policy, 1)
    request = ViewportRequest(x_min=0)

    provider.layer("stars", request)
    provider.layer("stars", request)

    assert policy.calls == 2
    assert provider._dynamic_cache_bytes == 0
    assert not provider._dynamic_cache


def test_concurrent_same_viewport_cache_fill_keeps_exact_byte_accounting(exported):
    request = ViewportRequest(x_min=0)
    sizing = _provider_with_cache(exported, _CountingPolicy(), 1_000_000)
    payload_size = len(sizing.layer("stars", request).body_bytes())
    policy = _BarrierPolicy()
    provider = _provider_with_cache(exported, policy, payload_size * 2)

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = [
            future.result(timeout=5)
            for future in (
                pool.submit(provider.layer, "stars", request),
                pool.submit(provider.layer, "stars", request),
            )
        ]

    bodies = [response.body_bytes() for response in responses]
    assert bodies[0] == bodies[1]
    assert policy.calls == 2
    assert len(provider._dynamic_cache) == 1
    assert provider._dynamic_cache_bytes == payload_size
    assert provider._dynamic_cache_bytes == sum(
        len(payload) for payload in provider._dynamic_cache.values()
    )


def test_viewport_cache_rejects_invalid_byte_limit(exported):
    with pytest.raises(ValueError, match="viewport_cache_bytes"):
        _provider_with_cache(exported, _CountingPolicy(), -1)
