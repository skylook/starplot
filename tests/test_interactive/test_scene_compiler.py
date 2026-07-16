"""Vectorized compilation contracts for high-volume scatter layers."""

from dataclasses import FrozenInstanceError

import numpy as np
import pytest
import shapely.geometry

import starplot.interactive.scene_compiler as compiler_module
from starplot.interactive.scene import ClipGeometry, ColumnarData
from starplot.interactive.scene_compiler import (
    PaletteEncoding,
    encode_palette,
    filter_columns,
    scatter_clip_mask,
)


def test_rectangle_clip_mask_is_boundary_inclusive_and_finite():
    clip = ClipGeometry(kind="rect", points=((0, 0), (1, 1)))

    mask = scatter_clip_mask(
        np.array([-1, 0, 0.5, 1, 2, np.nan], dtype=np.float32),
        np.array([0.5, 0, 0.5, 1, 0.5, 0.5], dtype=np.float32),
        clip,
    )

    assert mask.dtype == np.bool_
    assert mask.tolist() == [False, True, True, True, False, False]


def test_polygon_clip_uses_contains_xy_without_point_objects(monkeypatch):
    clip = ClipGeometry(
        kind="polygon",
        points=((0, 0), (2, 0), (2, 2), (0, 2)),
    )
    calls = []
    real_contains_xy = compiler_module.shapely.contains_xy

    def forbidden_point(*args, **kwargs):
        raise AssertionError("per-point Point allocation")

    def contains_xy_spy(geometry, x, y):
        calls.append((geometry, x, y))
        return real_contains_xy(geometry, x, y)

    monkeypatch.setattr(shapely.geometry, "Point", forbidden_point)
    monkeypatch.setattr(compiler_module.shapely, "contains_xy", contains_xy_spy)

    mask = scatter_clip_mask(
        np.array([1.0, 3.0, np.nan], dtype=np.float32),
        np.array([1.0, 1.0, 1.0], dtype=np.float32),
        clip,
    )

    assert len(calls) == 1
    assert calls[0][1].shape == (3,)
    assert mask.dtype == np.bool_
    assert mask.tolist() == [True, False, False]


@pytest.mark.parametrize(
    ("x", "y", "message"),
    [
        (np.zeros((1, 2)), np.zeros(2), "one-dimensional"),
        (np.zeros(2), np.zeros(3), "same length"),
    ],
)
def test_scatter_clip_mask_rejects_misaligned_inputs(x, y, message):
    clip = ClipGeometry(kind="rect", points=((0, 0), (1, 1)))

    with pytest.raises(ValueError, match=message):
        scatter_clip_mask(x, y, clip)


def test_filter_columns_retains_each_boolean_selection_without_second_copy(
    monkeypatch,
):
    data = ColumnarData.from_mapping(
        {
            "x": np.array([1, 2, 3], dtype=np.float32),
            "name": np.array(["a", "b", "c"]),
        }
    )
    captured = []
    real_seal = compiler_module._seal_owned_array

    def seal_spy(array):
        captured.append(array)
        return real_seal(array)

    def forbidden_from_mapping(cls, values):
        raise AssertionError("selected columns must not be copied again")

    monkeypatch.setattr(compiler_module, "_seal_owned_array", seal_spy)
    monkeypatch.setattr(
        ColumnarData,
        "from_mapping",
        classmethod(forbidden_from_mapping),
    )

    filtered = filter_columns(data, np.array([True, False, True]))

    assert filtered.row_count == 2
    assert len(captured) == 2
    assert filtered["x"] is captured[0]
    assert filtered["name"] is captured[1]
    np.testing.assert_array_equal(filtered["x"], [1, 3])
    np.testing.assert_array_equal(filtered["name"], ["a", "c"])
    assert all(column.flags.owndata for column in captured)
    assert all(column.flags.c_contiguous for column in captured)
    assert all(column.flags.aligned for column in captured)
    assert all(not column.flags.writeable for column in captured)


@pytest.mark.parametrize(
    ("data", "mask", "error", "message"),
    [
        ({"x": [1]}, np.array([True]), TypeError, "ColumnarData"),
        (
            ColumnarData.from_mapping({"x": [1, 2]}),
            np.array([1, 0]),
            TypeError,
            "boolean",
        ),
        (
            ColumnarData.from_mapping({"x": [1, 2]}),
            np.array([[True, False]]),
            ValueError,
            "one-dimensional",
        ),
        (
            ColumnarData.from_mapping({"x": [1, 2]}),
            np.array([True]),
            ValueError,
            "row count",
        ),
    ],
)
def test_filter_columns_rejects_unvalidated_inputs(data, mask, error, message):
    with pytest.raises(error, match=message):
        filter_columns(data, mask)


def test_palette_encoding_converts_unique_colors_only_and_separates_alpha(
    monkeypatch,
):
    colors = np.array(["#ffffff80", "#ffffff80", "#ff0000"])
    opacity = np.array([0.2, 0.5, 1.0], dtype=np.float32)
    calls = []
    real_to_rgba = compiler_module.to_rgba

    def to_rgba_spy(color):
        calls.append(color)
        return real_to_rgba(color)

    monkeypatch.setattr(compiler_module, "to_rgba", to_rgba_spy)

    encoded = encode_palette(colors, opacity)

    assert calls == ["#ff0000", "#ffffff80"]
    assert encoded.palette == ("#ff0000", "#ffffff")
    assert encoded.color_index.dtype == np.uint8
    assert encoded.color_index.tolist() == [1, 1, 0]
    assert encoded.opacity.dtype == np.float32
    assert encoded.opacity.tolist() == pytest.approx(
        [0.2 * (128 / 255), 0.5 * (128 / 255), 1.0]
    )


@pytest.mark.parametrize("opacity", [0.25, np.array(0.25, dtype=np.float32)])
def test_palette_encoding_broadcasts_scalar_opacity(opacity):
    encoded = encode_palette(np.array(["red", "blue"]), opacity)

    assert encoded.opacity.tolist() == pytest.approx([0.25, 0.25])


def test_palette_encoding_uses_uint16_above_256_colors():
    colors = np.array([f"#{value:06x}" for value in range(257)])

    encoded = encode_palette(colors, 1.0)

    assert len(encoded.palette) == 257
    assert encoded.color_index.dtype == np.uint16


def test_palette_encoding_rejects_more_than_uint16_can_address(monkeypatch):
    colors = np.array([f"#{value:06x}" for value in range(65_537)])

    def forbidden_to_rgba(color):
        raise AssertionError("limit must be checked before color conversion")

    monkeypatch.setattr(compiler_module, "to_rgba", forbidden_to_rgba)

    with pytest.raises(ValueError, match="65,536"):
        encode_palette(colors, 1.0)


@pytest.mark.parametrize(
    ("opacity", "message"),
    [
        (np.array([0.5]), "same length"),
        (np.array([0.5, np.nan]), "finite"),
        (np.ones((1, 2)), "scalar or one-dimensional"),
    ],
)
def test_palette_encoding_rejects_invalid_opacity(opacity, message):
    with pytest.raises(ValueError, match=message):
        encode_palette(np.array(["red", "blue"]), opacity)


def test_palette_encoding_arrays_are_independent_contiguous_read_only_aligned():
    colors = np.array(["red", "blue"])
    opacity = np.array([0.25, 0.75], dtype=np.float32)

    encoded = encode_palette(colors, opacity)
    colors[0] = "blue"
    opacity[0] = 1.0

    assert encoded.palette == ("#0000ff", "#ff0000")
    assert encoded.opacity.tolist() == pytest.approx([0.25, 0.75])
    for array in (encoded.color_index, encoded.opacity):
        assert array.flags.owndata
        assert array.flags.c_contiguous
        assert array.flags.aligned
        assert not array.flags.writeable
        with pytest.raises(ValueError):
            array[0] = 0

    with pytest.raises(FrozenInstanceError):
        encoded.palette = ()


def test_palette_encoding_constructor_snapshots_arrays():
    color_index = np.array([0, 1], dtype=np.uint8)
    opacity = np.array([0.2, 0.8], dtype=np.float32)

    encoded = PaletteEncoding(("#000000", "#ffffff"), color_index, opacity)
    color_index[0] = 1
    opacity[0] = 1.0

    assert encoded.color_index.tolist() == [0, 1]
    assert encoded.opacity.tolist() == pytest.approx([0.2, 0.8])


def test_palette_encoding_constructor_rejects_index_before_narrowing():
    with pytest.raises(ValueError, match="outside the palette"):
        PaletteEncoding(
            ("#000000", "#ffffff"),
            np.array([256], dtype=np.int64),
            np.array([1.0], dtype=np.float32),
        )
