"""Versioning and hashing contracts for the JSON Scene manifest."""

from __future__ import annotations

import hashlib

import pytest

from starplot.interactive.scene_manifest import (
    CapabilitiesModel,
    DataSourceModel,
    LayerManifestModel,
    PaletteAssetModel,
    SceneManifestModel,
    StyleAssetModel,
    canonical_manifest_bytes,
    scene_content_hash,
)


def _layer(**overrides) -> LayerManifestModel:
    values = {
        "id": "stars",
        "kind": "scatter",
        "group_id": "stars",
        "required": True,
        "zorder": 10.0,
        "load_priority": 20,
        "coordinate_space": "data",
        "clip_id": "plot",
        "style_id": "style-stars",
        "interactive": True,
        "interaction": "hover",
        "hover_fields": ("name",),
        "row_count": 2,
        "byte_length": 12,
        "content_hash": "sha256:" + "1" * 64,
        "coordinate_encoding": {
            "x": {
                "kind": "absolute-f64",
                "origin": 0.0,
                "scale": 1.0,
                "max_error_pixels": 0.0,
            },
            "y": {
                "kind": "absolute-f64",
                "origin": 0.0,
                "scale": 1.0,
                "max_error_pixels": 0.0,
            },
        },
        "data_source": {"format": "arrow-ipc-stream", "uri": "stars.arrow"},
    }
    values.update(overrides)
    return LayerManifestModel.model_validate(values)


def _manifest(**overrides) -> SceneManifestModel:
    values = {
        "schema_version": "1.0",
        "scene_id": "test-scene",
        "content_hash": "sha256:" + "f" * 64,
        "minimum_loader_version": "1.0",
        "viewport": {"reference_width": 1200, "reference_height": 800},
        "coordinate_spaces": {"data": {"authority": "projected-x-y"}},
        "clips": [],
        "styles": [{"id": "style-stars", "value": {"marker": {"line_width": 0}}}],
        "palettes": [],
        "layers": [_layer()],
        "capabilities": CapabilitiesModel(
            viewport_query=False,
            lod=False,
            magnitude_filter=False,
            catalog_detail=False,
            max_batch_rows=250_000,
        ),
    }
    values.update(overrides)
    values["clips"] = tuple(values["clips"])
    values["styles"] = tuple(
        (
            value
            if isinstance(value, StyleAssetModel)
            else StyleAssetModel.model_validate(value)
        )
        for value in values["styles"]
    )
    values["palettes"] = tuple(
        (
            value
            if isinstance(value, PaletteAssetModel)
            else PaletteAssetModel.model_validate(value)
        )
        for value in values["palettes"]
    )
    values["layers"] = tuple(values["layers"])
    draft = SceneManifestModel.model_construct(**values)
    layer_hashes = {layer.id: layer.content_hash for layer in values["layers"]}
    values["content_hash"] = scene_content_hash(draft, layer_hashes)
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
    payload = canonical_manifest_bytes(_layer())

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
        manifest, exclude_content_hash=True
    )
    expected = hashlib.sha256()
    expected.update(canonical_without_self)
    expected.update(layer_hashes["stars"].encode("ascii"))
    expected.update(layer_hashes["labels"].encode("ascii"))

    assert (
        scene_content_hash(manifest, layer_hashes) == "sha256:" + expected.hexdigest()
    )


def test_scene_hash_rejects_missing_extra_and_mismatched_layer_identity():
    second_layer = _layer(
        id="labels",
        kind="text",
        group_id="labels",
        content_hash="sha256:" + "2" * 64,
        data_source={"format": "arrow-ipc-stream", "uri": "labels.arrow"},
    )
    manifest = _manifest(layers=[_layer(), second_layer])
    correct = {
        "stars": "sha256:" + "1" * 64,
        "labels": "sha256:" + "2" * 64,
    }

    with pytest.raises(ValueError, match="missing"):
        scene_content_hash(manifest, {"stars": correct["stars"]})
    with pytest.raises(ValueError, match="extra"):
        scene_content_hash(manifest, {**correct, "attacker": correct["stars"]})
    with pytest.raises(ValueError, match="does not match"):
        scene_content_hash(
            manifest,
            {"stars": correct["labels"], "labels": correct["stars"]},
        )
    with pytest.raises(ValueError, match="does not match"):
        scene_content_hash(manifest, [correct["labels"], correct["stars"]])


def test_manifest_uses_explicit_compatible_extension_container_and_rejects_unknown_fields():
    raw = _manifest(extensions={"description": "safe optional prose"}).model_dump(
        mode="json"
    )

    restored = SceneManifestModel.model_validate(raw)

    assert restored.extensions == {"description": "safe optional prose"}
    raw["future_optional_hint"] = {"safe_to_ignore": True}
    with pytest.raises(ValueError, match="future_optional_hint"):
        SceneManifestModel.model_validate(raw)
    del raw["future_optional_hint"]
    raw["extensions"] = {"exec": "not allowlisted"}
    with pytest.raises(ValueError, match="extension"):
        SceneManifestModel.model_validate(raw)
    raw["extensions"] = {}
    del raw["scene_id"]
    with pytest.raises(ValueError, match="scene_id"):
        SceneManifestModel.model_validate(raw)


def test_data_source_is_arrow_stream_only():
    assert (
        DataSourceModel(format="arrow-ipc-stream", uri="stars.arrow").format
        == "arrow-ipc-stream"
    )
    with pytest.raises(ValueError, match="format"):
        DataSourceModel(format="json", uri="stars.json")


def test_manifest_rejects_duplicate_layer_ids():
    with pytest.raises(ValueError, match="duplicate layer id"):
        _manifest(layers=[_layer(), _layer()])


def test_noninteractive_manifest_layer_rejects_hover_fields():
    with pytest.raises(ValueError, match="hover_fields"):
        _layer(interactive=False, hover_fields=("name",))


@pytest.mark.parametrize(
    "missing",
    [
        "schema_version",
        "scene_id",
        "content_hash",
        "minimum_loader_version",
        "viewport",
        "coordinate_spaces",
        "clips",
        "styles",
        "palettes",
        "layers",
        "capabilities",
    ],
)
def test_strict_wire_manifest_requires_every_final_field(missing):
    raw = _manifest().model_dump(mode="json")
    del raw[missing]

    with pytest.raises(ValueError, match=missing):
        SceneManifestModel.model_validate(raw)


def test_manifest_rejects_loader_newer_than_current_implementation():
    with pytest.raises(ValueError, match="loader version"):
        _manifest(minimum_loader_version="99.0")


@pytest.mark.parametrize(
    "coordinate_encoding",
    [
        {
            "x": {
                "kind": "relative-f32",
                "origin": float("nan"),
                "scale": 1,
                "max_error_pixels": 0,
            }
        },
        {
            "x": {
                "kind": "relative-f32",
                "origin": 0,
                "scale": 0,
                "max_error_pixels": 0,
            }
        },
        {
            "x": {
                "kind": "absolute-f64",
                "origin": 0,
                "scale": 1,
                "max_error_pixels": -1,
            }
        },
    ],
)
def test_coordinate_encoding_model_rejects_nonfinite_or_nonpositive_values(
    coordinate_encoding,
):
    with pytest.raises(ValueError):
        _layer(coordinate_encoding=coordinate_encoding)


def test_layer_wire_rejects_runtime_context_injection():
    raw = _layer().model_dump(mode="json")
    raw["resolved_style"] = {"color": "attacker-controlled"}
    raw["resolved_palette"] = ["javascript:alert(1)"]

    with pytest.raises(ValueError, match="resolved_style|resolved_palette"):
        LayerManifestModel.model_validate(raw)


def test_hash_bound_top_level_style_cannot_change_before_resolution():
    raw = _manifest().model_dump(mode="json")
    raw["styles"][0]["value"]["marker"]["line_width"] = 999

    with pytest.raises(ValueError, match="scene content hash"):
        SceneManifestModel.model_validate(raw)
