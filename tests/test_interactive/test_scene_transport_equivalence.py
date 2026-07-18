"""The three delivery modes retain the exact canonical Scene representation."""

from __future__ import annotations

import json

import numpy as np

from starplot.interactive import (
    ColumnarData, InteractionPolicy, SceneKind, SceneLayer, ScenePackage,
    SceneProvider, export_scene_html,
)
from starplot.interactive.commands import CoordinateSpace
from starplot.interactive.scene import CoordinateEncoding, CoordinateEncodingKind
from starplot.interactive.scene_manifest import parse_scene_manifest


def _scene() -> ScenePackage:
    layer = SceneLayer(
        id="stars", kind=SceneKind.SCATTER, group_id="stars", zorder=1,
        load_priority=1, space=CoordinateSpace.DATA, clip_id=None,
        style={"palette_id": "stars"}, palette=("#fff",),
        interaction=InteractionPolicy.HOVER, hover_fields=("name",),
        coordinate_encoding={
            "x": CoordinateEncoding(CoordinateEncodingKind.ABSOLUTE_F64),
            "y": CoordinateEncoding(CoordinateEncodingKind.ABSOLUTE_F64),
        },
        data=ColumnarData.from_mapping({
            "x": np.array([1.0]), "y": np.array([2.0]),
            "size": np.array([3.0], dtype=np.float32),
            "color_index": np.array([0], dtype=np.uint8),
            "opacity": np.array([1.0], dtype=np.float32), "name": np.array(["Rigel"]),
        }),
    )
    return ScenePackage(
        layers=(layer,), projection_info={}, style_info={},
        viewport={"reference_width": 100, "reference_height": 100}, clips={},
        palettes={"stars": ("#fff",)},
    )


def test_inline_static_and_provider_preserve_manifest_and_arrow_bytes(tmp_path):
    scene = _scene()
    inline = export_scene_html(scene, tmp_path / "inline.html", data_mode="inline")
    static = export_scene_html(scene, tmp_path / "static.html", data_mode="external")
    provider = SceneProvider(
        parse_scene_manifest(inline.manifest_bytes), inline.manifest_bytes, inline.layer_bytes
    )
    assert inline.manifest_bytes == static.manifest_bytes == provider.manifest().body_bytes()
    manifest = json.loads(static.manifest_bytes)
    for layer in manifest["layers"]:
        assert inline.layer_bytes[layer["id"]] == (static.bundle_path / layer["data_source"]["uri"]).read_bytes()
        assert inline.layer_bytes[layer["id"]] == provider.layer(layer["id"]).body_bytes()
