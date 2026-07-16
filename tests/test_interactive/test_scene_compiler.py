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


@pytest.mark.parametrize(
    "points",
    [
        ((0, 0), (0, 1)),
        ((0, 0), (1, 0)),
        ((0, 0), (0, 0)),
    ],
)
def test_rectangle_clip_rejects_zero_width_or_height(points):
    clip = ClipGeometry(kind="rect", points=points)

    with pytest.raises(ValueError, match="positive width and height"):
        scatter_clip_mask(np.array([0.0]), np.array([0.0]), clip)


@pytest.mark.parametrize(
    "points",
    [
        ((0, 0), (1, 1), (2, 2)),
        ((0, 0), (1, 0), (0, 0)),
        ((0, 0), (2, 2), (0, 2), (2, 0)),
    ],
)
def test_polygon_clip_rejects_degenerate_or_invalid_geometry(
    points, monkeypatch
):
    clip = ClipGeometry(kind="polygon", points=points)

    def forbidden_contains_xy(*args, **kwargs):
        raise AssertionError("invalid polygon must fail before contains_xy")

    monkeypatch.setattr(
        compiler_module.shapely,
        "contains_xy",
        forbidden_contains_xy,
    )

    with pytest.raises(ValueError, match="non-empty, valid, positive-area"):
        scatter_clip_mask(np.array([0.0]), np.array([0.0]), clip)


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


@pytest.mark.parametrize(
    "opacity",
    [
        np.nextafter(np.float32(0.0), np.float32(-1.0)),
        np.nextafter(np.float32(1.0), np.float32(2.0)),
    ],
)
def test_encode_palette_rejects_opacity_outside_unit_interval(opacity):
    with pytest.raises(ValueError, match="between 0 and 1"):
        encode_palette(np.array(["red"]), opacity)


def test_encode_palette_accepts_opacity_boundaries_and_color_alpha_product():
    encoded = encode_palette(
        np.array(["#ff000000", "#ffffff80", "#0000ff"]),
        np.array([0.0, 1.0, 1.0], dtype=np.float32),
    )

    assert encoded.opacity.tolist() == pytest.approx([0.0, 128 / 255, 1.0])
    assert np.all((encoded.opacity >= 0.0) & (encoded.opacity <= 1.0))


def test_encode_palette_accepts_homogeneous_string_specs_only():
    encoded = encode_palette(["red", np.str_("blue"), "red"], 1.0)

    assert encoded.palette == ("#0000ff", "#ff0000")
    assert encoded.color_index.tolist() == [1, 0, 1]


def test_encode_palette_rejects_plain_mixed_list_with_stable_message():
    with pytest.raises(
        ValueError,
        match=r"^colors must be a one-dimensional string array$",
    ):
        encode_palette(["red", (1.0, 0.0, 0.0)], 1.0)


@pytest.mark.parametrize(
    "opacity",
    [np.array([], dtype=np.float32), 1.0],
)
def test_encode_palette_normalizes_empty_python_sequence(opacity):
    encoded = encode_palette([], opacity)

    assert encoded.palette == ()
    assert encoded.color_index.dtype == np.uint8
    assert encoded.color_index.size == 0
    assert encoded.opacity.dtype == np.float32
    assert encoded.opacity.size == 0


@pytest.mark.parametrize(
    "colors",
    [
        np.array(["red", (1.0, 0.0, 0.0)], dtype=object),
        np.array([object(), object()], dtype=object),
        np.array([1.0, 0.0], dtype=np.float32),
    ],
)
def test_encode_palette_rejects_unsupported_color_forms_clearly(colors):
    with pytest.raises(ValueError, match="one-dimensional string"):
        encode_palette(colors, 1.0)


def test_encode_palette_wraps_invalid_matplotlib_string(monkeypatch):
    real_to_rgba = compiler_module.to_rgba
    calls = []

    def to_rgba_spy(color):
        calls.append(color)
        return real_to_rgba(color)

    monkeypatch.setattr(compiler_module, "to_rgba", to_rgba_spy)

    with pytest.raises(ValueError, match="Invalid Matplotlib color spec.*bad-color"):
        encode_palette(np.array(["red", "bad-color", "red"]), 1.0)

    assert calls == ["bad-color"]


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


@pytest.mark.parametrize(
    "color_index",
    [
        np.array([0.5], dtype=np.float64),
        np.array([np.nan], dtype=np.float64),
        np.array([np.inf], dtype=np.float64),
        np.array([-1], dtype=np.int64),
        np.array([2], dtype=np.int64),
        np.array([True], dtype=np.bool_),
        np.array([0], dtype=object),
        [0],
    ],
)
def test_palette_encoding_constructor_rejects_non_integer_or_invalid_indices(
    color_index,
):
    with pytest.raises(ValueError, match="one-dimensional integer ndarray|outside"):
        PaletteEncoding(
            ("#000000", "#ffffff"),
            color_index,
            np.array([1.0], dtype=np.float32),
        )


@pytest.mark.parametrize(
    ("palette_size", "index", "expected_dtype"),
    [
        (256, 255, np.uint8),
        (257, 256, np.uint16),
        (65_536, 65_535, np.uint16),
    ],
)
def test_palette_encoding_constructor_preserves_index_boundaries(
    palette_size, index, expected_dtype
):
    encoded = PaletteEncoding(
        ("#000000",) * palette_size,
        np.array([index], dtype=np.int64),
        np.array([1.0], dtype=np.float32),
    )

    assert encoded.color_index.dtype == expected_dtype
    assert encoded.color_index.tolist() == [index]


def test_palette_encoding_constructor_allows_empty_palette_for_empty_indices():
    encoded = PaletteEncoding(
        (),
        np.array([], dtype=np.int64),
        np.array([], dtype=np.float32),
    )

    assert encoded.color_index.dtype == np.uint8
    assert encoded.color_index.size == 0


@pytest.mark.parametrize(
    "opacity",
    [
        np.array([-np.finfo(np.float32).eps], dtype=np.float32),
        np.array([1.0 + np.finfo(np.float32).eps], dtype=np.float32),
    ],
)
def test_palette_encoding_constructor_rejects_opacity_outside_unit_interval(
    opacity,
):
    with pytest.raises(ValueError, match="between 0 and 1"):
        PaletteEncoding(
            ("#000000",),
            np.array([0], dtype=np.int64),
            opacity,
        )


def test_palette_encoding_constructor_accepts_opacity_boundaries():
    encoded = PaletteEncoding(
        ("#000000", "#ffffff"),
        np.array([0, 1], dtype=np.int64),
        np.array([0.0, 1.0], dtype=np.float32),
    )

    assert encoded.opacity.tolist() == [0.0, 1.0]
