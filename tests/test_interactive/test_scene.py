"""Contracts for the immutable, backend-neutral Scene boundary."""

from collections.abc import Mapping
from types import MappingProxyType

import numpy as np
import pytest

import starplot.interactive.scene as scene_module
from starplot.interactive.commands import CommandType, CoordinateSpace
from starplot.interactive.scene import (
    ClipGeometry,
    ColumnarData,
    CoordinateEncodingKind,
    InteractionPolicy,
    SceneCapabilities,
    SceneKind,
    SceneLayer,
    ScenePackage,
    readonly_array,
)


@pytest.mark.parametrize(
    ("kind", "points", "expected"),
    [
        ("rect", [[0, 0], [1, 1]], ((0.0, 0.0), (1.0, 1.0))),
        (
            "polygon",
            [[0, 0], [1, 0], [0, 1]],
            ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0)),
        ),
    ],
)
def test_clip_geometry_freezes_finite_two_dimensional_points(
    kind, points, expected
):
    clip = ClipGeometry(kind=kind, points=points)

    assert clip.kind == kind
    assert clip.points == expected
    assert isinstance(clip.points, tuple)
    assert all(isinstance(point, tuple) for point in clip.points)


@pytest.mark.parametrize(
    ("kind", "points", "message"),
    [
        ("none", (), "rect or polygon"),
        ("rect", ((0, 0),), "at least 2"),
        ("polygon", ((0, 0), (1, 0)), "at least 3"),
        ("polygon", ((0, 0), (1, 0), (0, 1, 2)), "two values"),
        ("polygon", ((0, 0), (1, 0), (0, float("nan"))), "finite"),
    ],
)
def test_clip_geometry_rejects_invalid_kind_shape_and_coordinates(
    kind, points, message
):
    with pytest.raises(ValueError, match=message):
        ClipGeometry(kind=kind, points=points)


def _layer(**overrides):
    values = {
        "id": "stars",
        "kind": SceneKind.SCATTER,
        "zorder": 10,
        "load_priority": 1,
        "space": CoordinateSpace.DATA,
        "clip_id": "plot",
        "style": {"marker": {"colors": ["#fff", "#000"]}},
        "data": ColumnarData.from_mapping({"x": [1.0, 2.0], "name": ["A", "B"]}),
        "interaction": InteractionPolicy.HOVER,
        "hover_fields": ("name",),
        "required": True,
    }
    values.update(overrides)
    return SceneLayer(**values)


def test_readonly_array_is_contiguous_read_only_and_honors_dtype():
    source = np.array([1.0, 2.0], dtype=np.float64)[::-1]

    result = readonly_array(source, dtype=np.float32)

    assert result.dtype == np.float32
    assert result.flags.c_contiguous
    assert not result.flags.writeable
    with pytest.raises(ValueError):
        result[0] = 9


def test_readonly_array_snapshots_without_mutating_contiguous_input():
    source = np.array([1.0, 2.0], dtype=np.float32)

    result = readonly_array(source)

    assert source.flags.writeable
    assert result.dtype == source.dtype
    assert not np.shares_memory(result, source)
    source[0] = 99
    np.testing.assert_array_equal(result, [1.0, 2.0])


def test_readonly_array_detaches_from_non_contiguous_view_and_base():
    base = np.array([1.0, 99.0, 2.0, 99.0], dtype=np.float64)
    source = base[::2]

    result = readonly_array(source)

    assert source.flags.writeable
    assert result.flags.c_contiguous
    assert not np.shares_memory(result, source)
    base[0] = 42
    np.testing.assert_array_equal(result, [1.0, 2.0])


def test_readonly_array_cannot_be_made_writeable_again():
    result = readonly_array([1.0, 2.0])

    with pytest.raises(ValueError):
        result.setflags(write=True)


@pytest.mark.parametrize(
    "escape",
    [
        lambda array: array,
        lambda array: array.view(np.ndarray),
        np.asarray,
        lambda array: np.frombuffer(memoryview(array), dtype=array.dtype),
    ],
    ids=("array", "view", "asarray", "buffer"),
)
@pytest.mark.parametrize(
    "values",
    ([1.0, 2.0], ["A", "B"]),
    ids=("numeric", "string"),
)
def test_readonly_array_rejects_base_class_writeability_escapes(escape, values):
    escaped = escape(readonly_array(values))

    with pytest.raises(ValueError):
        np.ndarray.setflags(escaped, write=True)


def test_columnar_data_deeply_snapshots_object_columns():
    retained = {"aliases": ["M31"]}
    columns = ColumnarData.from_mapping(
        {"metadata": np.array([retained], dtype=object)}
    )

    retained["aliases"].append("NGC 224")

    assert columns["metadata"][0]["aliases"] == ("M31",)
    with pytest.raises(ValueError):
        columns["metadata"].setflags(write=True)
    with pytest.raises(ValueError):
        np.ndarray.setflags(columns["metadata"], write=True)


def test_object_column_base_escape_cannot_mutate_scene_storage():
    columns = ColumnarData.from_mapping(
        {"metadata": np.array([{"aliases": ["M31"]}], dtype=object)}
    )
    exposed = columns["metadata"]

    exposed.base.setflags(write=True)
    exposed.base[0] = {"aliases": ("tampered",)}

    assert exposed[0]["aliases"] == ("tampered",)
    assert columns["metadata"][0]["aliases"] == ("M31",)


def test_columnar_data_is_contiguous_read_only_and_aligned():
    columns = ColumnarData.from_mapping({
        "x": [1.0, 2.0],
        "y": np.array([3.0, 4.0], dtype=np.float32)[::-1],
    })

    assert columns.row_count == 2
    assert columns["x"].flags.c_contiguous
    assert not columns["x"].flags.writeable
    assert isinstance(columns.columns, Mapping)
    with pytest.raises(ValueError):
        columns["x"][0] = 9
    with pytest.raises(TypeError):
        columns.columns["z"] = np.array([5.0, 6.0])


def test_columnar_data_detaches_from_caller_owned_arrays():
    source = np.array([1.0, 2.0], dtype=np.float32)

    columns = ColumnarData.from_mapping({"x": source})

    assert source.flags.writeable
    assert not np.shares_memory(columns["x"], source)
    source[0] = 99
    np.testing.assert_array_equal(columns["x"], [1.0, 2.0])


def test_columnar_data_direct_constructor_copies_caller_read_only_owned_array():
    source = np.array([1.0, 2.0], dtype=np.float32)
    source.setflags(write=False)

    columns = ColumnarData({"x": source}, row_count=2)

    assert not np.shares_memory(columns["x"], source)
    assert not columns["x"].flags.writeable


def test_columnar_data_exposes_no_owned_construction_bypass():
    assert not hasattr(scene_module, "_OWNED_COLUMNS_TOKEN")
    assert not hasattr(ColumnarData, "_from_owned_columns")


def test_columnar_data_from_mapping_snapshots_each_column_once(monkeypatch):
    original_snapshot = scene_module._readonly_buffer_array
    snapshots = []

    def snapshot_spy(source):
        result = original_snapshot(source)
        snapshots.append(result)
        return result

    monkeypatch.setattr(scene_module, "_readonly_buffer_array", snapshot_spy)
    columns = ColumnarData.from_mapping({"x": [1, 2], "y": [3, 4]})
    monkeypatch.setattr(scene_module, "_readonly_buffer_array", original_snapshot)

    assert len(snapshots) == 2
    assert columns["x"] is snapshots[0]
    assert columns["y"] is snapshots[1]
    assert all(not column.flags.writeable for column in snapshots)


def test_columnar_data_rejects_misaligned_columns():
    with pytest.raises(ValueError, match="same row count"):
        ColumnarData.from_mapping({"x": [1, 2], "y": [3]})


def test_scene_layer_recursively_freezes_style_and_hover_fields():
    layer = _layer(hover_fields=["name"])

    assert layer.hover_fields == ("name",)
    assert isinstance(layer.style, MappingProxyType)
    assert layer.style["marker"]["colors"] == ("#fff", "#000")
    with pytest.raises(TypeError):
        layer.style["marker"]["new"] = "value"


def test_scene_layer_preserves_backend_neutral_group_identity():
    layer = _layer(group_id="constellations-line")

    assert layer.group_id == "constellations-line"


def test_scene_layer_freezes_ndarrays_retained_in_style():
    base = np.array([1, 99, 2, 99])
    source = base[::2]

    layer = _layer(style={"dash_pattern": source})

    pattern = layer.style["dash_pattern"]
    assert source.flags.writeable
    assert pattern.flags.c_contiguous
    assert not pattern.flags.writeable
    assert not np.shares_memory(pattern, source)
    base[0] = 42
    np.testing.assert_array_equal(pattern, [1, 2])


def test_scene_layer_snapshots_unknown_mutable_style_values():
    payload = bytearray(b"star")

    layer = _layer(style={"payload": payload})
    payload[:] = b"moon"

    assert layer.style["payload"] == b"star"


def test_scene_layer_rejects_unsupported_mutable_style_values():
    class MutablePayload:
        pass

    with pytest.raises(TypeError, match="MutablePayload"):
        _layer(style={"payload": MutablePayload()})


@pytest.mark.parametrize(
    "member",
    [
        CoordinateSpace.DATA,
        CommandType.SCATTER,
        SceneKind.SCATTER,
        InteractionPolicy.HOVER,
        CoordinateEncodingKind.RELATIVE_F32,
    ],
)
def test_public_string_enums_stringify_to_their_wire_value(member):
    assert str(member) == member.value


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"id": ""}, "non-empty"),
        ({"interaction": InteractionPolicy.NONE, "hover_fields": ("name",)}, "NONE"),
        ({"hover_fields": ("missing",)}, "data columns"),
    ],
)
def test_scene_layer_rejects_invalid_identity_and_hover_contract(overrides, message):
    with pytest.raises(ValueError, match=message):
        _layer(**overrides)


def test_scene_capabilities_rejects_non_positive_batch_size():
    with pytest.raises(ValueError, match="max_batch_rows"):
        SceneCapabilities(max_batch_rows=0)


def test_scene_package_recursively_freezes_all_retained_collections():
    layer = _layer()
    package = ScenePackage(
        layers=[layer],
        projection_info={"name": "mollweide", "parameters": {"central_longitude": 0}},
        style_info={"background": "#000"},
        viewport={"size": [1024, 768]},
        clips={"plot": {"points": [[0, 0], [1, 1]]}},
        palettes={"stars": ["#fff", "#000"]},
    )

    assert package.layers == (layer,)
    assert package.viewport["size"] == (1024, 768)
    assert package.clips["plot"]["points"] == ((0, 0), (1, 1))
    assert package.palettes["stars"] == ("#fff", "#000")
    with pytest.raises(TypeError):
        package.projection_info["name"] = "plate-carree"
    with pytest.raises(TypeError):
        package.clips["plot"]["points"] = ()


def test_scene_package_preserves_layer_order_and_rejects_duplicate_ids():
    foreground = _layer(id="foreground", zorder=20)
    background = _layer(id="background", zorder=1)

    package = ScenePackage(
        layers=[foreground, background],
        projection_info={},
        style_info={},
        viewport={},
        clips={},
        palettes={},
    )

    assert package.layers == (foreground, background)
    with pytest.raises(ValueError, match="duplicate layer id"):
        ScenePackage(
            layers=[foreground, foreground],
            projection_info={},
            style_info={},
            viewport={},
            clips={},
            palettes={},
        )
