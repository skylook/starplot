"""Framework-neutral byte-serving contracts for compiled Scenes."""

from __future__ import annotations

import json

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
from starplot.interactive.scene import CoordinateEncoding, CoordinateEncodingKind
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


@pytest.fixture
def exported(tmp_path):
    result = export_scene_html(_scene(), tmp_path / "chart.html")
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


def test_none_policy_cannot_serve_hidden_hover_or_object_metadata(tmp_path):
    result = export_scene_html(_scene(InteractionPolicy.NONE, include_object_id=True), tmp_path / "chart.html")
    manifest = SceneManifestModel.model_validate_json(result.manifest_bytes)
    with pytest.raises(ValueError, match="NONE interaction"):
        SceneProvider(manifest, result.manifest_bytes, result.layer_bytes)


def test_detail_policy_requires_a_stable_object_id(tmp_path):
    result = export_scene_html(_scene(InteractionPolicy.HOVER_AND_DETAIL, include_object_id=False), tmp_path / "chart.html")
    manifest = SceneManifestModel.model_validate_json(result.manifest_bytes)
    with pytest.raises(ValueError, match="object_id"):
        SceneProvider(manifest, result.manifest_bytes, result.layer_bytes)
