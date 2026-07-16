"""Vectorized compilation contracts for high-volume scatter layers."""

from dataclasses import FrozenInstanceError

import numpy as np
import pytest
import shapely.geometry

import starplot.interactive.scene_compiler as compiler_module
from starplot.interactive.commands import (
    ClipGeometry as RecordedClipGeometry,
    CoordinateSpace,
    DrawingCommand,
)
from starplot.interactive.scene import (
    ClipGeometry,
    ColumnarData,
    CoordinateEncodingKind,
    InteractionPolicy,
    SceneKind,
    ScenePackage,
)
from starplot.interactive.scene_compiler import (
    PaletteEncoding,
    SceneCompiler,
    choose_coordinate_encoding,
    encode_palette,
    filter_columns,
    scatter_clip_mask,
)
from starplot.interactive.style_converter import calibrate_marker_size


PROJECTION = {
    "x_min": 0.0,
    "x_max": 10.0,
    "y_min": -5.0,
    "y_max": 5.0,
    "clip_geometries": {
        "plot": RecordedClipGeometry("rect", ((0.0, -5.0), (10.0, 5.0))),
        "none": RecordedClipGeometry("none"),
    },
}
STYLE = {
    "background_color": "#101820",
    "figure_background_color": "#010203",
    "resolution": 4096,
    "dpi": 100,
    "supported_zoom": 4,
}


def _primitive_commands():
    return [
        DrawingCommand(
            kind="scatter",
            data={
                "x": np.array([1.0, 2.0]),
                "y": np.array([3.0, 4.0]),
                "sizes": np.array([4.0, 9.0]),
                "colors": np.array(["red", "blue"]),
                "alphas": np.array([1.0, 0.5]),
            },
            metadata=[
                {"name": "A", "object_id": "star-a", "unsafe": [1]},
                {"name": "B", "object_id": "star-b", "unsafe": [2]},
            ],
            zorder=20,
        ),
        DrawingCommand(
            kind="line",
            data={"x": [0.0, 1.0], "y": [0.0, 1.0]},
            zorder=30,
        ),
        DrawingCommand(
            kind="line_collection",
            data={"lines": [[(0.0, 0.0), (1.0, 1.0)]]},
            zorder=31,
        ),
        DrawingCommand(
            kind="polygon",
            data={"points": [(0.0, 0.0), (2.0, 0.0), (1.0, 2.0)]},
            zorder=0,
        ),
        DrawingCommand(
            kind="text",
            data={"x": 0.5, "y": 0.75, "text": "Orion", "offset_points": (2, -3)},
            style={"rotation": 15.0},
            zorder=10,
            space=CoordinateSpace.AXES,
            clip_id=None,
        ),
        DrawingCommand(
            kind="gradient",
            data={"direction": "vertical", "color_stops": [(0, "#000"), (1, "#fff")]},
            zorder=-100,
        ),
        DrawingCommand(
            kind="info_table",
            data={"columns": ["A", "B"], "values": ["1", "2"], "widths": [0.4, 0.6]},
            zorder=11,
            space=CoordinateSpace.PAPER,
            clip_id=None,
        ),
    ]


def _configured_compiler():
    return SceneCompiler(
        projection_info=PROJECTION,
        style_info=STYLE,
        width=1200,
        height=800,
        transparent=False,
    )


@pytest.mark.parametrize(
    ("command_index", "expected_kind", "expected_columns"),
    [
        (
            0,
            SceneKind.SCATTER,
            {"x", "y", "size", "color_index", "opacity", "name", "object_id"},
        ),
        (1, SceneKind.LINE, {"path_id", "vertex_index", "x", "y"}),
        (2, SceneKind.LINE_COLLECTION, {"path_id", "vertex_index", "x", "y"}),
        (3, SceneKind.POLYGON, {"polygon_id", "ring_id", "vertex_index", "x", "y"}),
        (
            4,
            SceneKind.TEXT,
            {"x", "y", "text", "rotation", "x_offset", "y_offset", "style_id"},
        ),
        (5, SceneKind.GRADIENT, set()),
        (6, SceneKind.INFO_TABLE, {"column", "value", "width"}),
    ],
)
def test_compiler_covers_every_recorded_primitive(
    command_index, expected_kind, expected_columns
):
    command = _primitive_commands()[command_index]

    scene = SceneCompiler().compile([command], PROJECTION, STYLE, 1200, 800, False)

    assert len(scene.layers) == 1
    layer = scene.layers[0]
    assert layer.kind is expected_kind
    assert layer.id == f"layer-0000-{expected_kind.value}"
    assert layer.zorder == command.zorder
    assert layer.space is command.space
    assert layer.clip_id == command.clip_id
    assert layer.required is True
    assert set(layer.data.columns) == expected_columns
    assert {len(column) for column in layer.data.columns.values()} <= {
        layer.data.row_count
    }
    for column in layer.data.columns.values():
        assert column.flags.aligned
        assert column.flags.c_contiguous
        assert not column.flags.writeable


def test_primitive_schemas_use_protocol_dtypes():
    layers = [
        _configured_compiler().compile_command(command, index)
        for index, command in enumerate(_primitive_commands())
    ]

    assert layers[0].data["size"].dtype == np.float32
    assert layers[0].data["color_index"].dtype == np.uint8
    assert layers[0].data["opacity"].dtype == np.float32
    for layer in layers[1:4]:
        assert layer.data["vertex_index"].dtype == np.uint32
    assert layers[1].data["path_id"].dtype == np.uint32
    assert layers[2].data["path_id"].dtype == np.uint32
    assert layers[3].data["polygon_id"].dtype == np.uint32
    assert layers[3].data["ring_id"].dtype == np.uint32
    assert layers[4].data["rotation"].dtype == np.float32
    assert layers[4].data["x_offset"].dtype == np.float32
    assert layers[4].data["y_offset"].dtype == np.float32
    assert layers[4].data["style_id"].dtype == np.uint16
    assert layers[6].data["width"].dtype == np.float32


def test_unconfigured_compile_command_rejects_context_dependent_scatter():
    command = _primitive_commands()[0]

    with pytest.raises(ValueError, match=r"constructor context|compile\(\)"):
        SceneCompiler().compile_command(command, 7)


def test_configured_standalone_scatter_is_self_contained_and_matches_full_compile():
    command = _primitive_commands()[0]
    compiler = _configured_compiler()

    standalone = compiler.compile_command(command, 0)
    scene = compiler.compile([command], PROJECTION, STYLE, 1200, 800, False)
    packaged = scene.layers[0]

    assert standalone.id == "layer-0000-scatter"
    assert standalone.style["palette_id"] == "palette-0000"
    assert "palette" not in standalone.style
    assert standalone.palette == ("#0000ff", "#ff0000")
    assert scene.palettes == {"palette-0000": ("#0000ff", "#ff0000")}
    assert packaged.palette is scene.palettes["palette-0000"]
    assert packaged.palette == standalone.palette
    assert packaged.coordinate_encoding == standalone.coordinate_encoding
    for name in packaged.data.columns:
        np.testing.assert_array_equal(packaged.data[name], standalone.data[name])


def test_scene_package_rejects_palette_asset_that_disagrees_with_layer():
    layer = _configured_compiler().compile_command(_primitive_commands()[0], 0)

    with pytest.raises(ValueError, match="palette asset must match"):
        ScenePackage(
            layers=(layer,),
            projection_info={},
            style_info={},
            viewport={},
            clips={},
            palettes={"palette-0000": ("#badbad",)},
        )


def test_constructor_context_must_be_complete_when_any_value_is_supplied():
    with pytest.raises(ValueError, match="complete constructor context"):
        SceneCompiler(width=1200)


@pytest.mark.parametrize(
    "command",
    [
        DrawingCommand(kind="line", data={"x": [0, 1], "y": [0, 1]}),
        DrawingCommand(kind="polygon", data={"points": [(0, 0), (1, 0), (0, 1)]}),
        DrawingCommand(kind="text", data={"x": 0, "y": 0, "text": "x"}),
        DrawingCommand(kind="line_collection", data={"lines": [[(0, 0), (1, 1)]]}),
        DrawingCommand(kind="gradient", data={"direction": "vertical", "color_stops": []}),
    ],
)
def test_unconfigured_compile_command_rejects_any_clip_reference(command):
    with pytest.raises(ValueError, match=r"clip reference.*constructor context|compile\(\)"):
        SceneCompiler().compile_command(command, 0)


def test_unconfigured_line_without_clip_uses_absolute_f64():
    command = DrawingCommand(
        kind="line",
        data={"x": [0, 1], "y": [0, 1]},
        clip_id=None,
    )

    layer = SceneCompiler().compile_command(command, 0)

    assert layer.coordinate_encoding["x"].kind is CoordinateEncodingKind.ABSOLUTE_F64
    assert layer.coordinate_encoding["y"].kind is CoordinateEncodingKind.ABSOLUTE_F64


def test_target_axes_width_controls_marker_calibration_and_viewport_contract():
    projection = {
        **PROJECTION,
        "axes_bbox": (0.2, 0.1, 0.6, 0.8),
    }
    style = {
        **STYLE,
        "source_axes_width": 1200.0,
    }
    command = DrawingCommand(
        kind="scatter",
        data={
            "x": np.array([1.0]),
            "y": np.array([1.0]),
            "sizes": np.array([9.0]),
            "colors": np.array(["red"]),
            "alphas": np.array([1.0]),
        },
    )

    scene = SceneCompiler().compile([command], projection, style, 1000, 500, False)

    expected = calibrate_marker_size(
        9.0,
        width=600.0,
        dpi=100.0,
        source_axes_width=1200.0,
    ) * 1.15
    assert scene.viewport["target_axes_width"] == pytest.approx(600.0)
    assert scene.layers[0].data["size"].tolist() == pytest.approx([expected])


@pytest.mark.parametrize("width_fraction", [0.0, -0.1, 1.01, np.nan, np.inf])
def test_context_rejects_invalid_axes_bbox_width_fraction(width_fraction):
    projection = {**PROJECTION, "axes_bbox": (0.0, 0.0, width_fraction, 1.0)}

    with pytest.raises(ValueError, match="axes_bbox.*width fraction"):
        SceneCompiler().compile([], projection, STYLE, 1000, 500, False)


def test_discontinuous_and_longitude_wrap_lines_keep_permanent_path_boundaries():
    command = DrawingCommand(
        kind="line",
        data={
            "x": [359.0, 360.0, None, 0.0, 1.0, np.nan, 2.0, 3.0, 4.0, 5.0],
            "y": [0.0, 1.0, None, 2.0, 3.0, 4.0, 4.0, 5.0, 6.0, 7.0],
            "breaks": [False, False, False, False, False, False, False, False, True, False],
        },
        clip_id=None,
    )

    layer = SceneCompiler().compile_command(command, 0)

    assert layer.coordinate_encoding["x"].kind is CoordinateEncodingKind.ABSOLUTE_F64
    assert layer.coordinate_encoding["y"].kind is CoordinateEncodingKind.ABSOLUTE_F64
    assert layer.data["path_id"].tolist() == [0, 0, 1, 1, 2, 2, 3, 3]
    assert layer.data["vertex_index"].tolist() == [0, 1, 0, 1, 0, 1, 0, 1]
    decoded_x = layer.coordinate_encoding["x"].decode(layer.data["x"])
    assert decoded_x.tolist() == pytest.approx(
        [359.0, 360.0, 0.0, 1.0, 2.0, 3.0, 4.0, 5.0]
    )


def test_line_collection_clip_assigns_each_result_piece_a_distinct_path():
    concave = RecordedClipGeometry(
        "polygon",
        ((0, 0), (4, 0), (4, 4), (3, 4), (3, 1), (1, 1), (1, 4), (0, 4)),
    )
    projection = {**PROJECTION, "clip_geometries": {"plot": concave}}
    command = DrawingCommand(
        kind="line_collection",
        data={"lines": [[(-1.0, 2.0), (5.0, 2.0)], [(0.5, 0.5), (3.5, 0.5)]]},
    )

    layer = (
        SceneCompiler().compile([command], projection, STYLE, 400, 400, False).layers[0]
    )

    assert layer.data["path_id"].tolist() == [0, 0, 1, 1, 2, 2]
    assert layer.data["vertex_index"].tolist() == [0, 1, 0, 1, 0, 1]


def test_polygon_preserves_multiple_polygon_and_ring_ids_through_schema():
    command = DrawingCommand(
        kind="polygon",
        data={
            "polygons": [
                [
                    [(0, 0), (4, 0), (4, 4), (0, 4)],
                    [(1, 1), (1, 2), (2, 2), (2, 1)],
                ],
                [[(6, 0), (8, 0), (7, 2)]],
            ]
        },
        clip_id=None,
    )

    layer = SceneCompiler().compile_command(command, 0)

    assert layer.data["polygon_id"].tolist() == [0] * 8 + [1] * 3
    assert layer.data["ring_id"].tolist() == [0] * 4 + [1] * 4 + [0] * 3
    assert layer.data["vertex_index"].tolist() == [0, 1, 2, 3, 0, 1, 2, 3, 0, 1, 2]


def test_recorder_rings_are_independent_polygons_not_implicit_holes():
    command = DrawingCommand(
        kind="polygon",
        data={
            "points": [(0, 0), (2, 0), (1, 2)],
            "rings": [
                [(0, 0), (2, 0), (1, 2)],
                [(5, 0), (7, 0), (6, 2)],
            ],
        },
        clip_id=None,
    )

    layer = SceneCompiler().compile_command(command, 0)

    assert layer.data["polygon_id"].tolist() == [0, 0, 0, 1, 1, 1]
    assert layer.data["ring_id"].tolist() == [0, 0, 0, 0, 0, 0]


def test_explicit_polygons_preserve_exterior_and_hole_ring_ids():
    command = DrawingCommand(
        kind="polygon",
        data={
            "polygons": [
                [
                    [(0, 0), (4, 0), (4, 4), (0, 4)],
                    [(1, 1), (1, 2), (2, 2), (2, 1)],
                ]
            ]
        },
        clip_id=None,
    )

    layer = SceneCompiler().compile_command(command, 0)

    assert layer.data["polygon_id"].tolist() == [0] * 8
    assert layer.data["ring_id"].tolist() == [0] * 4 + [1] * 4


def test_polygon_clip_can_split_one_input_into_distinct_polygon_ids():
    concave = RecordedClipGeometry(
        "polygon",
        ((0, 0), (4, 0), (4, 4), (3, 4), (3, 1), (1, 1), (1, 4), (0, 4)),
    )
    projection = {**PROJECTION, "clip_geometries": {"plot": concave}}
    command = DrawingCommand(
        kind="polygon",
        data={"points": [(-1, 2), (5, 2), (5, 3), (-1, 3)]},
    )

    layer = (
        SceneCompiler().compile([command], projection, STYLE, 400, 400, False).layers[0]
    )

    assert set(layer.data["polygon_id"].tolist()) == {0, 1}
    assert layer.data["ring_id"].tolist() == [0] * layer.data.row_count


def test_independent_recorder_rings_remain_independent_after_clip():
    command = DrawingCommand(
        kind="polygon",
        data={
            "rings": [
                [(-1, 0), (2, 0), (2, 2), (-1, 2)],
                [(8, 0), (11, 0), (11, 2), (8, 2)],
            ]
        },
    )

    layer = SceneCompiler().compile(
        [command], PROJECTION, STYLE, 400, 400, False
    ).layers[0]

    assert set(layer.data["polygon_id"].tolist()) == {0, 1}
    assert set(layer.data["ring_id"].tolist()) == {0}


def test_polygon_clipping_rejects_invalid_input_instead_of_retaining_it():
    command = DrawingCommand(
        kind="polygon",
        data={"points": [(0, 0), (4, 4), (0, 4), (4, 0)]},
    )

    with pytest.raises(ValueError, match="non-empty, valid, positive-area"):
        SceneCompiler().compile([command], PROJECTION, STYLE, 400, 400, False)


def test_data_scatter_is_clipped_with_every_aligned_metadata_column():
    command = DrawingCommand(
        kind="scatter",
        data={
            "x": np.array([-1.0, 1.0, 11.0]),
            "y": np.array([0.0, 1.0, 0.0]),
            "sizes": np.array([1.0, 4.0, 9.0]),
            "colors": np.array(["red", "green", "blue"]),
            "alphas": np.array([0.1, 0.5, 0.9]),
        },
        metadata=[{"name": "left"}, {"name": "inside"}, {"name": "right"}],
    )

    layer = (
        SceneCompiler()
        .compile([command], PROJECTION, STYLE, 1000, 500, False)
        .layers[0]
    )

    assert layer.data.row_count == 1
    assert layer.data["x"].tolist() == pytest.approx([0.0])
    assert layer.coordinate_encoding["x"].decode(
        layer.data["x"]
    ).tolist() == pytest.approx([1.0])
    assert layer.data["name"].tolist() == ["inside"]
    assert layer.interaction is InteractionPolicy.HOVER


def test_non_data_and_unknown_clips_do_not_trigger_scene_geometry_clipping():
    axes_command = DrawingCommand(
        kind="line",
        data={"x": [-1.0, 11.0], "y": [0.0, 0.0]},
        space=CoordinateSpace.AXES,
        clip_id="plot",
    )
    unknown_command = DrawingCommand(
        kind="line",
        data={"x": [-1.0, 11.0], "y": [0.0, 0.0]},
        clip_id="unknown",
    )

    scene = SceneCompiler().compile(
        [axes_command, unknown_command], PROJECTION, STYLE, 100, 100, False
    )

    assert [layer.data.row_count for layer in scene.layers] == [2, 2]


def test_none_recording_clip_is_ignored_at_scene_boundary():
    command = DrawingCommand(
        kind="line",
        data={"x": [0, 1], "y": [0, 1]},
        clip_id="none",
    )

    scene = SceneCompiler().compile([command], PROJECTION, STYLE, 100, 100, False)

    assert "none" not in scene.clips
    assert scene.layers[0].clip_id is None


def test_scatter_interaction_columnizes_only_safe_declared_metadata():
    command = _primitive_commands()[0]

    layer = _configured_compiler().compile_command(command, 0)

    assert layer.interaction is InteractionPolicy.HOVER_AND_DETAIL
    assert layer.hover_fields == ("name", "object_id")
    assert "unsafe" not in layer.data.columns


def test_high_volume_scatter_omits_metadata_and_loads_last():
    rows = 100_000
    command = DrawingCommand(
        kind="scatter",
        data={
            "x": np.arange(rows, dtype=np.float64),
            "y": np.arange(rows, dtype=np.float64),
            "sizes": np.ones(rows),
            "colors": np.full(rows, "white"),
            "alphas": np.ones(rows),
        },
        metadata=[{"name": "faint", "object_id": "x"}] * rows,
        clip_id=None,
    )

    layer = _configured_compiler().compile_command(command, 0)

    assert layer.load_priority == 100
    assert layer.interaction is InteractionPolicy.NONE
    assert layer.hover_fields == ()
    assert set(layer.data.columns) == {"x", "y", "size", "color_index", "opacity"}


def test_metadata_columns_use_stable_protocol_dtypes_and_missing_sentinels():
    command = _primitive_commands()[0]
    command.metadata = [
        {"name": "A", "magnitude": 1.25, "type": "star", "object_id": None},
        {"name": None, "type": "star", "object_id": "star-b"},
    ]

    layer = _configured_compiler().compile_command(command, 0)

    assert layer.data["name"].dtype.kind == "U"
    assert layer.data["name"].tolist() == ["A", ""]
    assert layer.data["type"].dtype.kind == "U"
    assert layer.data["object_id"].dtype.kind == "U"
    assert layer.data["object_id"].tolist() == ["", "star-b"]
    assert layer.data["magnitude"].dtype == np.float32
    assert layer.data["magnitude"][0] == pytest.approx(1.25)
    assert np.isnan(layer.data["magnitude"][1])
    assert all(not layer.data[name].flags.writeable for name in layer.hover_fields)


def test_mixed_or_complex_metadata_fields_are_not_retained():
    command = _primitive_commands()[0]
    command.metadata = [
        {"name": "A", "magnitude": 1.0, "type": "star"},
        {"name": 42, "magnitude": 1 + 2j, "type": ["star"]},
    ]

    layer = _configured_compiler().compile_command(command, 0)

    assert not {"name", "magnitude", "type"}.intersection(layer.data.columns)
    assert layer.interaction is InteractionPolicy.NONE


def test_line_collection_clip_repeats_source_metadata_for_every_piece_vertex():
    concave = RecordedClipGeometry(
        "polygon",
        ((0, 0), (4, 0), (4, 4), (3, 4), (3, 1), (1, 1), (1, 4), (0, 4)),
    )
    projection = {**PROJECTION, "clip_geometries": {"plot": concave}}
    command = DrawingCommand(
        kind="line_collection",
        data={
            "lines": [
                [(-1.0, 2.0), (5.0, 2.0)],
                [(0.5, 0.5), (3.5, 0.5)],
            ]
        },
        metadata=[
            {"name": "split", "object_id": "source-0", "magnitude": 1.5},
            {"name": "base", "object_id": "source-1", "magnitude": None},
        ],
    )

    layer = SceneCompiler().compile(
        [command], projection, STYLE, 400, 400, False
    ).layers[0]

    assert layer.data["path_id"].tolist() == [0, 0, 1, 1, 2, 2]
    assert layer.data["name"].tolist() == ["split"] * 4 + ["base"] * 2
    assert layer.data["object_id"].tolist() == ["source-0"] * 4 + ["source-1"] * 2
    assert layer.data["magnitude"].dtype == np.float32
    assert layer.data["magnitude"][:4].tolist() == pytest.approx([1.5] * 4)
    assert np.isnan(layer.data["magnitude"][-2:]).all()
    assert layer.interaction is InteractionPolicy.HOVER_AND_DETAIL


def test_line_collection_without_metadata_is_noninteractive():
    command = DrawingCommand(
        kind="line_collection",
        data={"lines": [[(0, 0), (1, 1)]]},
        clip_id=None,
    )

    layer = SceneCompiler().compile_command(command, 0)

    assert layer.interaction is InteractionPolicy.NONE
    assert layer.hover_fields == ()


def test_load_priority_is_semantic_and_layers_sort_by_zorder_then_input_index():
    commands = _primitive_commands()
    commands[0].zorder = 50
    commands[1].zorder = 5
    commands[2].zorder = 5

    scene = SceneCompiler().compile(commands, PROJECTION, STYLE, 1200, 800, False)

    assert [(layer.kind, layer.load_priority) for layer in scene.layers] == [
        (SceneKind.GRADIENT, 0),
        (SceneKind.POLYGON, 0),
        (SceneKind.LINE, 30),
        (SceneKind.LINE_COLLECTION, 30),
        (SceneKind.TEXT, 10),
        (SceneKind.INFO_TABLE, 10),
        (SceneKind.SCATTER, 20),
    ]
    assert scene.layers[2].id == "layer-0001-line"
    assert scene.layers[3].id == "layer-0002-line_collection"


def test_compile_builds_frozen_viewport_clips_and_context_mappings():
    projection = dict(PROJECTION)
    style = dict(STYLE)

    scene = SceneCompiler().compile([], projection, style, 1200, 800, True)
    projection["x_min"] = 99
    style["background_color"] = "changed"

    assert scene.viewport == {
        "reference_width": 1200,
        "reference_height": 800,
        "data_bounds": {"x_min": 0.0, "x_max": 10.0, "y_min": -5.0, "y_max": 5.0},
        "paper_background": "#010203",
        "axes_background": "#101820",
        "transparent": True,
        "target_axes_width": 1200.0,
    }
    assert scene.projection_info["x_min"] == 0.0
    assert scene.style_info["background_color"] == "#101820"
    assert isinstance(scene.clips["plot"], ClipGeometry)
    with pytest.raises(TypeError):
        scene.viewport["reference_width"] = 1


@pytest.mark.parametrize(("width", "height"), [(0, 1), (1, 0), (-1, 1), (1, -1)])
def test_compile_requires_positive_reference_dimensions(width, height):
    with pytest.raises(ValueError, match="width and height"):
        SceneCompiler().compile([], PROJECTION, STYLE, width, height, False)


def test_gradient_is_declarative_and_has_no_rows():
    layer = _configured_compiler().compile_command(_primitive_commands()[5], 0)

    assert layer.data.row_count == 0
    assert layer.style["direction"] == "vertical"
    assert layer.style["color_stops"] == ((0, "#000"), (1, "#fff"))


@pytest.mark.parametrize(
    ("clip", "point", "expected_rows"),
    [
        (RecordedClipGeometry("rect", ((0, 0), (2, 2))), (1, 1), 1),
        (RecordedClipGeometry("rect", ((0, 0), (2, 2))), (3, 1), 0),
        (RecordedClipGeometry("rect", ((0, 0), (2, 2))), (0, 1), 1),
        (
            RecordedClipGeometry("polygon", ((0, 0), (2, 0), (2, 2), (0, 2))),
            (1, 1),
            1,
        ),
        (
            RecordedClipGeometry("polygon", ((0, 0), (2, 0), (2, 2), (0, 2))),
            (3, 1),
            0,
        ),
        (
            RecordedClipGeometry("polygon", ((0, 0), (2, 0), (2, 2), (0, 2))),
            (0, 1),
            0,
        ),
    ],
)
def test_data_text_known_clip_uses_scatter_boundary_policy(
    clip, point, expected_rows
):
    projection = {**PROJECTION, "clip_geometries": {"plot": clip}}
    command = DrawingCommand(
        kind="text",
        data={"x": point[0], "y": point[1], "text": "probe"},
    )

    layer = SceneCompiler().compile(
        [command], projection, STYLE, 200, 200, False
    ).layers[0]

    assert layer.id == "layer-0000-text"
    assert layer.data.row_count == expected_rows
    assert all(len(column) == expected_rows for column in layer.data.columns.values())


@pytest.mark.parametrize(
    ("space", "clip_id"),
    [
        (CoordinateSpace.AXES, "plot"),
        (CoordinateSpace.PAPER, "plot"),
        (CoordinateSpace.DATA, "unknown"),
    ],
)
def test_non_data_or_unknown_clip_does_not_filter_text(space, clip_id):
    command = DrawingCommand(
        kind="text",
        data={"x": 100, "y": 100, "text": "probe"},
        space=space,
        clip_id=clip_id,
    )

    layer = _configured_compiler().compile_command(command, 0)

    assert layer.data.row_count == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("columns", "scalar"),
        ("columns", [["A"]]),
        ("values", "scalar"),
        ("values", [["1"]]),
        ("widths", 1.0),
        ("widths", [[1.0]]),
    ],
)
def test_info_table_requires_each_input_to_be_one_dimensional(field, value):
    data = {"columns": ["A"], "values": ["1"], "widths": [1.0]}
    data[field] = value
    command = DrawingCommand(kind="info_table", data=data, clip_id=None)

    with pytest.raises(ValueError, match=rf"info_table {field} must be one-dimensional"):
        SceneCompiler().compile_command(command, 0)


@pytest.mark.parametrize("width", [np.nan, np.inf, -0.01])
def test_info_table_widths_must_be_finite_and_nonnegative(width):
    command = DrawingCommand(
        kind="info_table",
        data={"columns": ["A"], "values": ["1"], "widths": [width]},
        clip_id=None,
    )

    with pytest.raises(ValueError, match="finite and non-negative"):
        SceneCompiler().compile_command(command, 0)


def test_info_table_allows_zero_width():
    command = DrawingCommand(
        kind="info_table",
        data={"columns": ["A"], "values": ["1"], "widths": [0.0]},
        clip_id=None,
    )

    layer = SceneCompiler().compile_command(command, 0)

    assert layer.data["width"].tolist() == [0.0]


def test_coordinate_encoding_round_trips_and_preserves_nan_breaks():
    values = np.array([1.0e12, np.nan, 1.0e12 + 0.25], dtype=np.float64)
    encoding = choose_coordinate_encoding(values, pixel_span=1000, supported_zoom=10)

    encoded = encoding.encode(values)
    decoded = encoding.decode(encoded)

    assert encoding.kind is CoordinateEncodingKind.RELATIVE_F32
    assert encoded.dtype == np.float32
    assert encoded.flags.c_contiguous and not encoded.flags.writeable
    assert np.isnan(encoded[1]) and np.isnan(decoded[1])
    np.testing.assert_allclose(
        decoded[[0, 2]], values[[0, 2]], rtol=0, atol=encoding.scale * 1e-7
    )


def test_protocol_exposes_no_absolute_float32_coordinate_encoding():
    assert {kind.value for kind in CoordinateEncodingKind} == {
        "absolute-f64",
        "relative-f32",
    }


def test_precision_falls_back_to_absolute_f64_when_zoom_exceeds_error_budget():
    values = np.array([0.0, 1.0 / 3.0, 1.0], dtype=np.float64)

    encoding = choose_coordinate_encoding(
        values, pixel_span=2000, supported_zoom=1_000_000
    )
    encoded = encoding.encode(values)

    assert encoding.kind is CoordinateEncodingKind.ABSOLUTE_F64
    assert encoded.dtype == np.float64
    assert encoding.max_error_pixels == 0.0


def test_precision_policy_has_deterministic_constant_and_no_finite_behavior():
    constant = choose_coordinate_encoding([42.0, 42.0, np.nan], 100, 1)
    no_finite = choose_coordinate_encoding([np.nan, np.inf], 100, 1)

    assert constant.kind is CoordinateEncodingKind.RELATIVE_F32
    assert constant.origin == 42.0
    assert constant.scale == 1.0
    assert constant.max_error_pixels == 0.0
    assert no_finite.kind is CoordinateEncodingKind.ABSOLUTE_F64
    assert no_finite.max_error_pixels == 0.0


@pytest.mark.parametrize(
    "values",
    [
        np.array([-180.0, -45.25, 0.0, 179.999]),
        np.array([1.0e-12, 1.0001e-12, 1.0002e-12]),
    ],
)
def test_ordinary_map_and_tiny_optical_fields_use_bounded_relative_f32(values):
    encoding = choose_coordinate_encoding(values, 1600, 32)

    assert encoding.kind is CoordinateEncodingKind.RELATIVE_F32
    assert encoding.max_error_pixels <= 0.05


@pytest.mark.parametrize(
    ("values", "pixel_span", "supported_zoom", "max_error", "message"),
    [
        ([[1.0]], 100, 1, 0.05, "one-dimensional"),
        (["x"], 100, 1, 0.05, "numeric"),
        ([1.0], 0, 1, 0.05, "pixel_span"),
        ([1.0], 100, 0.5, 0.05, "supported_zoom"),
        ([1.0], 100, 1, 0, "max_pixel_error"),
    ],
)
def test_precision_policy_rejects_invalid_inputs(
    values, pixel_span, supported_zoom, max_error, message
):
    with pytest.raises(ValueError, match=message):
        choose_coordinate_encoding(values, pixel_span, supported_zoom, max_error)


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
def test_polygon_clip_rejects_degenerate_or_invalid_geometry(points, monkeypatch):
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
    "opacity",
    [
        -0.1,
        1.1,
        float("nan"),
        float("inf"),
        np.array(float("nan")),
    ],
)
def test_encode_empty_palette_validates_scalar_opacity_before_broadcast(opacity):
    with pytest.raises(ValueError, match="finite|between 0 and 1"):
        encode_palette([], opacity)


@pytest.mark.parametrize("opacity", [0.0, 1.0, np.array(0.0), np.array(1.0)])
def test_encode_empty_palette_accepts_scalar_opacity_boundaries(opacity):
    encoded = encode_palette([], opacity)

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
