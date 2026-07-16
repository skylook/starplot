"""Versioning and hashing contracts for the JSON Scene manifest."""

from __future__ import annotations

import hashlib

import pytest

from starplot.interactive.scene_manifest import (
    CapabilitiesModel,
    DataSourceModel,
    LayerManifestModel,
    SceneManifestModel,
    canonical_manifest_bytes,
    scene_content_hash,
)


def _layer(**overrides) -> LayerManifestModel:
    values = {
        "id": "stars",
        "kind": "scatter",
        "required": True,
        "zorder": 10.0,
        "load_priority": 20,
        "coordinate_space": "data",
        "clip_id": "plot",
        "style_id": "style-stars",
        "interactive": True,
        "hover_fields": ("name",),
        "row_count": 2,
        "byte_length": 12,
        "content_hash": "sha256:" + "1" * 64,
        "coordinate_encoding": {},
        "data_source": {"format": "arrow-ipc-stream", "uri": "stars.arrow"},
        "resolved_group_id": "stars",
        "resolved_style": {"marker": {"line_width": 0}},
        "resolved_interaction": "hover",
        "resolved_palette": ("#fff", "#f00"),
    }
    values.update(overrides)
    return LayerManifestModel.model_validate(values)


def _manifest(**overrides) -> SceneManifestModel:
    values = {
        "schema_version": "1.0",
        "scene_id": "test-scene",
        "content_hash": None,
        "minimum_loader_version": "1.0",
        "viewport": {"reference_width": 1200, "reference_height": 800},
        "coordinate_spaces": {"data": {"authority": "projected-x-y"}},
        "clips": [],
        "styles": [],
        "palettes": [],
        "layers": [_layer()],
        "capabilities": CapabilitiesModel(max_batch_rows=250_000),
    }
    values.update(overrides)
    return SceneManifestModel.model_validate(values)


def test_manifest_rejects_unknown_major_version():
    with pytest.raises(ValueError, match="major version"):
        _manifest(schema_version="2.0")


@pytest.mark.parametrize("value", ["1", "1.x", "v1.0", "1.0.0", ""])
def test_manifest_rejects_malformed_schema_version(value):
    with pytest.raises(ValueError, match="schema_version"):
        _manifest(schema_version=value)


def test_manifest_rejects_unknown_scene_kind_and_invalid_hash():
    with pytest.raises(ValueError, match="kind"):
        _layer(kind="scattergl")
    with pytest.raises(ValueError, match="SHA-256"):
        _layer(content_hash="not-a-hash")


def test_manifest_canonical_json_is_stable_across_mapping_insertion_order():
    first = _manifest(
        viewport={"reference_height": 800, "reference_width": 1200},
        coordinate_spaces={
            "paper": {"units": "normalized", "authority": "scene"},
            "data": {"authority": "projected-x-y"},
        },
    )
    second = _manifest(
        viewport={"reference_width": 1200, "reference_height": 800},
        coordinate_spaces={
            "data": {"authority": "projected-x-y"},
            "paper": {"authority": "scene", "units": "normalized"},
        },
    )

    assert canonical_manifest_bytes(first) == canonical_manifest_bytes(second)
    assert canonical_manifest_bytes(first).startswith(b'{"capabilities":')
    assert b" " not in canonical_manifest_bytes(first)


def test_canonical_layer_json_omits_runtime_resolved_style_and_palette():
    payload = canonical_manifest_bytes(_manifest())

    assert b"resolved_style" not in payload
    assert b"resolved_palette" not in payload
    assert b"marker" not in payload
    assert b"#fff" not in payload


def test_scene_hash_omits_self_hash_and_appends_layer_hashes_in_manifest_order():
    second_layer = _layer(
        id="labels",
        kind="text",
        content_hash="sha256:" + "2" * 64,
        data_source={"format": "arrow-ipc-stream", "uri": "labels.arrow"},
    )
    manifest = _manifest(
        content_hash="sha256:" + "f" * 64,
        layers=[_layer(), second_layer],
    )
    layer_hashes = {
        "labels": "sha256:" + "2" * 64,
        "stars": "sha256:" + "1" * 64,
    }
    canonical_without_self = canonical_manifest_bytes(
        manifest.model_copy(update={"content_hash": None}),
        exclude_content_hash=True,
    )
    expected = hashlib.sha256()
    expected.update(canonical_without_self)
    expected.update(layer_hashes["stars"].encode("ascii"))
    expected.update(layer_hashes["labels"].encode("ascii"))

    assert (
        scene_content_hash(manifest, layer_hashes) == "sha256:" + expected.hexdigest()
    )


def test_manifest_ignores_forward_optional_minor_fields_but_required_fields_remain_required():
    raw = _manifest().model_dump(mode="json")
    raw["future_optional_hint"] = {"safe_to_ignore": True}
    raw["layers"][0]["future_optional_hint"] = "ignored"

    restored = SceneManifestModel.model_validate(raw)

    assert not hasattr(restored, "future_optional_hint")
    assert not hasattr(restored.layers[0], "future_optional_hint")
    del raw["scene_id"]
    with pytest.raises(ValueError, match="scene_id"):
        SceneManifestModel.model_validate(raw)


def test_data_source_is_arrow_stream_only():
    assert DataSourceModel(uri="stars.arrow").format == "arrow-ipc-stream"
    with pytest.raises(ValueError, match="format"):
        DataSourceModel(format="json", uri="stars.json")


def test_manifest_rejects_duplicate_layer_ids():
    with pytest.raises(ValueError, match="duplicate layer id"):
        _manifest(layers=[_layer(), _layer()])


def test_noninteractive_manifest_layer_rejects_hover_fields():
    with pytest.raises(ValueError, match="hover_fields"):
        _layer(interactive=False, hover_fields=("name",))
