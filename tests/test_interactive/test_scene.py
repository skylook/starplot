"""Contracts for the immutable, backend-neutral Scene boundary."""

from types import MappingProxyType

import numpy as np
import pytest

import starplot.interactive.scene as scene_module
from starplot.interactive.commands import CoordinateSpace
from starplot.interactive.scene import (
    ColumnarData,
    InteractionPolicy,
    SceneCapabilities,
    SceneKind,
    SceneLayer,
    ScenePackage,
    readonly_array,
)


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


def test_readonly_array_owns_storage_without_mutating_contiguous_input():
    source = np.array([1.0, 2.0], dtype=np.float32)

    result = readonly_array(source)

    assert source.flags.writeable
    assert result.dtype == source.dtype
    assert result.flags.owndata
    assert not np.shares_memory(result, source)
    source[0] = 99
    np.testing.assert_array_equal(result, [1.0, 2.0])


def test_readonly_array_detaches_from_non_contiguous_view_and_base():
    base = np.array([1.0, 99.0, 2.0, 99.0], dtype=np.float64)
    source = base[::2]

    result = readonly_array(source)

    assert source.flags.writeable
    assert result.flags.c_contiguous
    assert result.flags.owndata
    assert not np.shares_memory(result, source)
    base[0] = 42
    np.testing.assert_array_equal(result, [1.0, 2.0])


def test_columnar_data_is_contiguous_read_only_and_aligned():
    columns = ColumnarData.from_mapping({
        "x": [1.0, 2.0],
        "y": np.array([3.0, 4.0], dtype=np.float32)[::-1],
    })

    assert columns.row_count == 2
    assert columns["x"].flags.c_contiguous
    assert not columns["x"].flags.writeable
    assert isinstance(columns.columns, MappingProxyType)
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
    assert columns["x"].flags.owndata
    assert not columns["x"].flags.writeable


def test_columnar_data_exposes_no_owned_construction_bypass():
    assert not hasattr(scene_module, "_OWNED_COLUMNS_TOKEN")
    assert not hasattr(ColumnarData, "_from_owned_columns")


def test_columnar_data_from_mapping_snapshots_each_column_once(monkeypatch):
    original_array = scene_module.np.array
    allocations = []

    def array_spy(*args, **kwargs):
        result = original_array(*args, **kwargs)
        allocations.append(result)
        return result

    monkeypatch.setattr(scene_module.np, "array", array_spy)
    columns = ColumnarData.from_mapping({"x": [1, 2], "y": [3, 4]})
    monkeypatch.setattr(scene_module.np, "array", original_array)

    assert len(allocations) == 2
    assert columns["x"] is allocations[0]
    assert columns["y"] is allocations[1]
    assert all(column.flags.owndata for column in allocations)
    assert all(not column.flags.writeable for column in allocations)


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
