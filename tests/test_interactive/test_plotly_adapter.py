"""Scene-to-Plotly adapter contracts and legacy semantic snapshots."""

from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import numpy as np
import pytest
from matplotlib.colors import to_rgba
from shapely.geometry import Point, Polygon

from starplot.interactive.commands import CoordinateSpace, DrawingCommand
from starplot.interactive.scene import (
    ColumnarData,
    CoordinateEncoding,
    CoordinateEncodingKind,
    SceneKind,
    SceneLayer,
    ScenePackage,
)
from starplot.interactive.scene_compiler import SceneCompiler


PROJECTION = {
    "x_min": -2.0,
    "x_max": 2.0,
    "y_min": -2.0,
    "y_max": 2.0,
    "plot_kind": "map",
    # Match the legacy renderer's fixed ten-pixel side margins at 500px.
    "axes_bbox": (0.02, 0.1, 0.96, 0.8),
    "axes_pixels": (500.0, 500.0),
    "clip_geometries": {},
}
STYLE = {
    "background_color": "#101820",
    "figure_background_color": "#010203",
    "show_legend": True,
    "resolution": 500,
    "dpi": 100,
    "source_axes_width": 500.0,
}
GOLDEN_PATH = (
    Path(__file__).parents[1] / "data/interactive/legacy_plotly_primitives.json"
)


def primitive_commands():
    return {
        "scatter": DrawingCommand(
            kind="scatter",
            data={
                "x": np.array([-1.0, 1.0]),
                "y": np.array([1.0, -1.0]),
                "sizes": np.array([9.0, 16.0]),
                "colors": np.array(["#ff0000", "#0000ff"]),
                "alphas": np.array([0.25, 0.75]),
            },
            style={"symbol": "circle", "edge_color": "none", "edge_width": 0},
            metadata=[
                {"name": "A", "type": "star", "object_id": "star-a"},
                {"name": "B", "type": "star", "object_id": "star-b"},
            ],
            gid="stars",
            clip_id=None,
        ),
        "line": DrawingCommand(
            kind="line",
            data={"x": [-1.0, 0.0, None, 0.5, 1.0], "y": [0.0, 1.0, None, -1.0, 0.0]},
            style={
                "color": "#abcdef",
                "width": 1.5,
                "line_style": "dashed",
                "alpha": 0.8,
            },
            gid="ecliptic-line",
            clip_id="plot",
        ),
        "line_collection": DrawingCommand(
            kind="line_collection",
            data={"lines": [[(-1.0, 0.0), (0.0, 1.0)], [(0.0, -1.0), (1.0, 0.0)]]},
            style={"color": "#778899", "width": 1.0, "alpha": 0.6},
            metadata=[{"name": "A"}, {"name": "B"}],
            gid="constellations-line",
            clip_id=None,
        ),
        "polygon": DrawingCommand(
            kind="polygon",
            data={"points": [(-1.0, -1.0), (1.0, -1.0), (0.0, 1.0)]},
            style={
                "fill_color": "#223344",
                "edge_color": "#ffffff",
                "edge_width": 0.5,
                "alpha": 0.7,
            },
            gid="milky-way",
            clip_id=None,
        ),
        "text": DrawingCommand(
            kind="text",
            data={
                "text": "Orion\nMajor",
                "x": 0.5,
                "y": 0.75,
                "offset_points": (7.2, -3.6),
            },
            style={
                "font_size": 12,
                "font_color": "#ffffff",
                "font_name": "Inter",
                "ha": "left",
                "va": "bottom",
                "rotation": 15,
            },
            gid="label",
            space=CoordinateSpace.AXES,
            clip_id=None,
        ),
        "gradient": DrawingCommand(
            kind="gradient",
            data={
                "direction": "linear",
                "color_stops": [(0.0, "#000022"), (1.0, "#000000")],
            },
            gid="gradient",
            clip_id=None,
        ),
        "info_table": DrawingCommand(
            kind="info_table",
            data={
                "columns": ["Field", "Value"],
                "values": ["Type", "Galaxy"],
                "widths": [0.4, 0.6],
            },
            style={
                "font_size": 12,
                "font_color": "#ffffff",
                "background_color": "#111111",
            },
            gid="info-table",
            space=CoordinateSpace.PAPER,
            clip_id=None,
        ),
    }


def _decoded(value):
    if isinstance(value, dict) and "bdata" in value:
        dtype = np.dtype(value["dtype"])
        decoded = np.frombuffer(base64.b64decode(value["bdata"]), dtype=dtype)
        shape = value.get("shape")
        if shape:
            if isinstance(shape, str):
                shape = tuple(int(part.strip()) for part in shape.split(","))
            decoded = decoded.reshape(tuple(shape))
        return decoded.tolist()
    return value


def _css_colors(colors, opacity, colorscale):
    palette = [colorscale[index][1] for index in range(0, len(colorscale), 2)]
    opacity_values = opacity if isinstance(opacity, list) else [opacity] * len(colors)
    result = []
    for color_index, alpha in zip(colors, opacity_values):
        red, green, blue, base_alpha = to_rgba(palette[int(color_index)])
        css_alpha = f"{base_alpha * float(alpha):.8f}".rstrip("0").rstrip(".") or "0"
        result.append(
            f"rgba({round(red * 255)},{round(green * 255)},{round(blue * 255)},{css_alpha})"
        )
    return result


def normalized_payload(payload):
    """Remove generated identity and normalize Plotly array serialization only."""
    payload = deepcopy(payload)
    for trace in payload.get("data", []):
        trace.pop("uid", None)
        for key in ("x", "y", "z", "customdata", "text"):
            if key in trace:
                trace[key] = _decoded(trace[key])
        marker = trace.get("marker")
        if marker:
            for key in ("size", "opacity", "color"):
                if key in marker:
                    marker[key] = _decoded(marker[key])
        x_values = trace.get("x")
        y_values = trace.get("y")
        if isinstance(x_values, list) and isinstance(y_values, list):
            for index, (x_value, y_value) in enumerate(zip(x_values, y_values)):
                x_separator = x_value is None or (
                    isinstance(x_value, float) and not np.isfinite(x_value)
                )
                y_separator = y_value is None or (
                    isinstance(y_value, float) and not np.isfinite(y_value)
                )
                if x_separator and y_separator:
                    x_values[index] = None
                    y_values[index] = None
                    text = trace.get("text")
                    if isinstance(text, list) and index < len(text):
                        text_value = text[index]
                        if text_value is None or (
                            isinstance(text_value, float)
                            and not np.isfinite(text_value)
                        ):
                            text[index] = None
            while (
                x_values and y_values and x_values[-1] is None and y_values[-1] is None
            ):
                x_values.pop()
                y_values.pop()
                text = trace.get("text")
                if isinstance(text, list) and text and text[-1] is None:
                    text.pop()
    return payload


def normalized_figure(figure):
    return normalized_payload(json.loads(figure.to_json()))


def legacy_visual_view(payload):
    """Compare legacy visual/hover output while naming new nonvisual payload."""
    payload = deepcopy(payload)
    for trace in payload.get("data", []):
        marker = trace.get("marker")
        if (
            marker
            and isinstance(marker.get("color"), list)
            and marker.get("colorscale")
        ):
            marker["color"] = _css_colors(
                marker["color"], marker.get("opacity", 1.0), marker["colorscale"]
            )
            marker["opacity"] = 1.0
            for key in ("colorscale", "cmin", "cmax", "showscale"):
                marker.pop(key, None)
        # Scene customdata is asserted exactly before excluding this new,
        # nonvisual field from the legacy visual/hover snapshot.
        trace.pop("customdata", None)
    return payload


_FLOAT32_MACHINE_EPSILON = float(np.finfo(np.float32).eps)


def _coordinate_tolerance(scene, name, path):
    axis = name[0]
    pixels = float(scene.viewport[f"reference_{'width' if axis == 'x' else 'height'}"])
    if path and path[0] == "data":
        encoding = scene.layers[0].coordinate_encoding.get(axis)
        bounds = scene.viewport["data_bounds"]
        span = (
            abs(float(encoding.scale))
            if encoding is not None
            else abs(float(bounds[f"{axis}_max"]) - float(bounds[f"{axis}_min"]))
        )
        supported_zoom = float(scene.style_info.get("supported_zoom", 1.0))
        return span / pixels / supported_zoom * 0.05
    return 0.05 / pixels


def _float32_tolerance(value):
    return _FLOAT32_MACHINE_EPSILON * max(1.0, abs(float(value)))


def assert_semantic_equal(actual, expected, scene, path=(), allowed_diffs=None):
    allowed_diffs = allowed_diffs or {}
    if path in allowed_diffs:
        old_value, new_value = allowed_diffs[path]
        assert expected == old_value
        assert actual == new_value
        return
    if isinstance(expected, dict):
        assert isinstance(actual, dict)
        assert set(actual) == set(expected), path
        for key in expected:
            assert_semantic_equal(
                actual[key], expected[key], scene, path + (key,), allowed_diffs
            )
        return
    if isinstance(expected, list):
        assert isinstance(actual, list)
        assert len(actual) == len(expected), path
        coordinate = path[-1] if path and path[-1] in {"x", "y"} else None
        for index, expected_value in enumerate(expected):
            actual_value = actual[index]
            if coordinate and actual_value is not None and expected_value is not None:
                assert actual_value == pytest.approx(
                    expected_value,
                    abs=_coordinate_tolerance(scene, coordinate, path),
                )
            elif (
                len(path) >= 2
                and path[-2:] in (("marker", "size"), ("marker", "opacity"))
                and actual_value is not None
                and expected_value is not None
            ):
                tolerance = _float32_tolerance(expected_value)
                assert actual_value == pytest.approx(expected_value, abs=tolerance)
            else:
                assert_semantic_equal(
                    actual_value,
                    expected_value,
                    scene,
                    path + (index,),
                    allowed_diffs,
                )
        return
    coordinate = (
        path[-1] if path and path[-1] in {"x", "y", "x0", "x1", "y0", "y1"} else None
    )
    if (
        coordinate
        and isinstance(actual, (int, float))
        and isinstance(expected, (int, float))
    ):
        assert actual == pytest.approx(
            expected,
            abs=_coordinate_tolerance(scene, coordinate, path),
        )
        return
    if (
        path
        and path[-1] in {"xshift", "yshift"}
        and isinstance(actual, (int, float))
        and isinstance(expected, (int, float))
    ):
        assert actual == pytest.approx(expected, abs=0.05)
        return
    assert actual == expected, path


def _compile(command, *, width=500, height=500):
    return SceneCompiler().compile([command], PROJECTION, STYLE, width, height, False)


def test_scene_adapter_escapes_all_html_metacharacters_in_text_sinks():
    from starplot.interactive.plotly_adapter import PlotlySceneAdapter

    malicious = '<a title="double" data-note=\'single\'>& link</a>'
    expected = (
        "&lt;a title=&quot;double&quot; data-note=&#x27;single&#x27;&gt;"
        "&amp; link&lt;/a&gt;"
    )

    scatter = primitive_commands()["scatter"]
    scatter.metadata[0]["name"] = malicious
    scatter.style["legend_label"] = malicious
    scatter_figure = PlotlySceneAdapter().render(_compile(scatter))
    assert scatter_figure.data[0].name == expected
    assert expected in scatter_figure.data[0].text[0]

    text = primitive_commands()["text"]
    text.data["text"] = malicious
    text_figure = PlotlySceneAdapter().render(_compile(text))
    assert text_figure.layout.annotations[0].text == expected

    info_table = primitive_commands()["info_table"]
    info_table.data["columns"] = [malicious]
    info_table.data["values"] = [malicious]
    info_table.data["widths"] = [1.0]
    table_figure = PlotlySceneAdapter().render(_compile(info_table))
    assert table_figure.layout.annotations[0].text == f"<b>{expected}</b>"
    assert table_figure.layout.annotations[1].text == expected


def test_scene_adapter_escapes_unknown_group_id_before_using_it_as_legend_name():
    from starplot.interactive.plotly_adapter import PlotlySceneAdapter

    command = primitive_commands()["scatter"]
    command.gid = '<img title="double" note=\'single\' src=x>'
    figure = PlotlySceneAdapter().render(_compile(command))

    assert figure.data[0].name == (
        "&lt;Img Title=&quot;Double&quot; Note=&#x27;Single&#x27; Src=X&gt;"
    )
    assert "<" not in figure.data[0].name


def test_legacy_primitive_snapshot_fixture_exists_and_covers_every_kind():
    payload = json.loads(GOLDEN_PATH.read_text())
    assert set(payload) == set(primitive_commands())


@pytest.mark.parametrize("name", primitive_commands())
def test_scene_adapter_matches_independently_captured_legacy_primitive_snapshot(name):
    from starplot.interactive.plotly_adapter import PlotlySceneAdapter

    scene = _compile(primitive_commands()[name])
    figure = PlotlySceneAdapter().render(scene)
    actual = normalized_figure(figure)
    expected = normalized_payload(json.loads(GOLDEN_PATH.read_text())[name])

    if name == "scatter":
        customdata = actual["data"][0]["customdata"]
        fields = scene.layers[0].hover_fields
        expected_customdata = np.column_stack(
            [scene.layers[0].data[field] for field in fields]
        ).tolist()
        assert fields == ("name", "type", "object_id")
        assert customdata == expected_customdata

    assert_semantic_equal(
        legacy_visual_view(actual),
        legacy_visual_view(expected),
        scene,
    )


def test_scatter_trace_keeps_plotly6_typed_arrays():
    from starplot.interactive.plotly_adapter import PlotlySceneAdapter

    count = 1000
    command = DrawingCommand(
        kind="scatter",
        data={
            "x": np.linspace(0, 1, count),
            "y": np.linspace(1, 0, count),
            "sizes": np.ones(count),
            "colors": np.full(count, "#ffffff"),
            "alphas": np.ones(count),
        },
        gid="stars",
        clip_id=None,
    )
    encoded = json.loads(PlotlySceneAdapter().render(_compile(command)).to_json())[
        "data"
    ][0]

    assert encoded["x"]["dtype"] == "f4"
    assert "bdata" in encoded["x"]
    assert encoded["marker"]["size"]["dtype"] == "f4"
    assert encoded["marker"]["opacity"]["dtype"] == "f4"


def test_adapter_never_builds_per_point_css_colors():
    from starplot.interactive.plotly_adapter import PlotlySceneAdapter

    count = 10_000
    command = DrawingCommand(
        kind="scatter",
        data={
            "x": np.linspace(0, 1, count),
            "y": np.linspace(1, 0, count),
            "sizes": np.ones(count),
            "colors": np.resize(np.array(["#ffffff", "#000000"]), count),
            "alphas": np.ones(count),
        },
        gid="stars",
        clip_id=None,
    )
    figure = PlotlySceneAdapter().render(_compile(command))
    colors = figure.data[0].marker.color

    assert isinstance(colors, np.ndarray)
    assert colors.dtype.kind == "u"


def test_discrete_palette_contract_for_zero_single_and_multiple_colors():
    from starplot.interactive.plotly_adapter import (
        PlotlySceneAdapter,
        _discrete_colorscale,
    )

    assert _discrete_colorscale(()) == [
        [0.0, "rgba(0,0,0,0)"],
        [1.0, "rgba(0,0,0,0)"],
    ]
    assert _discrete_colorscale(("#ff0000",)) == [
        [0.0, "#ff0000"],
        [1.0, "#ff0000"],
    ]
    assert _discrete_colorscale(("#0000ff", "#ff0000")) == [
        [0.0, "#0000ff"],
        [0.5, "#0000ff"],
        [0.5, "#ff0000"],
        [1.0, "#ff0000"],
    ]

    single = primitive_commands()["scatter"]
    single.data["colors"] = np.array(["#ff000080", "#ff000080"])
    single.data["alphas"] = np.array([0.25, 0.75])
    single_trace = PlotlySceneAdapter().render(_compile(single)).data[0]
    assert list(single_trace.marker.color) == [0, 0]
    np.testing.assert_allclose(
        single_trace.marker.opacity,
        np.asarray([0.25, 0.75], dtype=np.float32) * np.float32(128 / 255),
        rtol=_FLOAT32_MACHINE_EPSILON,
        atol=_FLOAT32_MACHINE_EPSILON,
    )
    assert list(single_trace.marker.colorscale) == [
        (0.0, "#ff0000"),
        (1.0, "#ff0000"),
    ]
    assert single_trace.marker.cmin == -0.5
    assert single_trace.marker.cmax == 0.5
    assert single_trace.marker.showscale is False

    multi_trace = (
        PlotlySceneAdapter().render(_compile(primitive_commands()["scatter"])).data[0]
    )
    assert list(multi_trace.marker.color) == [1, 0]
    np.testing.assert_allclose(
        multi_trace.marker.opacity,
        np.asarray([0.25, 0.75], dtype=np.float32),
        rtol=_FLOAT32_MACHINE_EPSILON,
        atol=_FLOAT32_MACHINE_EPSILON,
    )
    assert list(multi_trace.marker.colorscale) == [
        (0.0, "#0000ff"),
        (0.5, "#0000ff"),
        (0.5, "#ff0000"),
        (1.0, "#ff0000"),
    ]
    assert multi_trace.marker.cmin == -0.5
    assert multi_trace.marker.cmax == 1.5
    assert multi_trace.marker.showscale is False


def test_svg_scatter_applies_plotly_minimum_without_changing_scene_values():
    from starplot.interactive.plotly_adapter import PlotlySceneAdapter

    command = DrawingCommand(
        kind="scatter",
        data={
            "x": [0.0],
            "y": [0.0],
            "sizes": [0.02],
            "colors": ["#ffffff"],
            "alphas": [0.5],
        },
        style={"edge_color": "#ffffff", "edge_width": 2.0},
        gid="marker",
        clip_id=None,
    )
    scene = _compile(command)

    trace = PlotlySceneAdapter().render(scene).data[0]

    assert scene.layers[0].data["size"][0] < 1.0
    assert trace.type == "scatter"
    assert trace.marker.size[0] == 1.5
    assert trace.marker.opacity[0] == pytest.approx(0.5)
    assert trace.marker.line.width > 0


def test_plotly_marker_calibration_is_applied_only_after_scene_compilation():
    from starplot.interactive.plotly_adapter import PlotlySceneAdapter
    from starplot.interactive.style_converter import calibrate_marker_size

    command = DrawingCommand(
        kind="scatter",
        data={
            "x": [0.0],
            "y": [0.0],
            "sizes": [9.0],
            "colors": ["#ffffff"],
            "alphas": [1.0],
        },
        gid="stars",
        clip_id=None,
    )
    scene = _compile(command)
    neutral_size = calibrate_marker_size(
        9.0,
        width=scene.viewport["target_axes_width"],
        dpi=STYLE["dpi"],
        source_axes_width=STYLE["source_axes_width"],
        min_size=0.0,
    )

    trace = PlotlySceneAdapter().render(scene).data[0]

    assert scene.layers[0].data["size"][0] == pytest.approx(neutral_size)
    assert trace.marker.size[0] == pytest.approx(neutral_size * 1.0)


def test_ellipse_marker_has_larger_extent_than_circle():
    """The ellipse marker's major axis is larger than its bbox width, so its
    calibrated Plotly diameter must exceed a circle's for the same matplotlib s.
    The Python plotly.py backend still receives the circle fallback because
    plotly.py (as of 5.24.1) does not accept arbitrary SVG path marker strings;
    the browser JS adapter supplies the actual rotated ellipse path.
    """
    from starplot.interactive.style_converter import (
        MARKER_SYMBOL_MAP,
        _marker_extent_factor,
    )

    extent = _marker_extent_factor("ellipse")
    assert extent == pytest.approx(2.0 / 1.948776650870625)
    assert extent > _marker_extent_factor("circle")
    # Python adapter keeps the safe circle approximation until plotly.py supports
    # custom SVG marker paths.
    assert MARKER_SYMBOL_MAP["ellipse"] == "circle"

    circle = DrawingCommand(
        kind="scatter",
        data={"x": [0.0], "y": [0.0], "sizes": [9.0], "colors": ["#ffffff"], "alphas": [1.0]},
        style={"symbol": "circle"},
        gid="dso",
        clip_id=None,
    )
    ellipse = replace(circle, style={"symbol": "ellipse"})
    circle_scene = _compile(circle)
    ellipse_scene = _compile(ellipse)
    assert ellipse_scene.layers[0].data["size"][0] == pytest.approx(
        circle_scene.layers[0].data["size"][0] * extent
    )


def test_relative_identity_coordinates_stay_float32_typed_arrays():
    from starplot.interactive.plotly_adapter import PlotlySceneAdapter

    encoding = CoordinateEncoding(CoordinateEncodingKind.RELATIVE_F32)
    layer = SceneLayer(
        id="identity",
        kind=SceneKind.LINE,
        group_id="line",
        zorder=0,
        load_priority=0,
        space=CoordinateSpace.DATA,
        clip_id="plot",
        style={"color": "#fff"},
        data=ColumnarData.from_mapping(
            {
                "path_id": np.array([0, 0], dtype=np.uint32),
                "vertex_index": np.array([0, 1], dtype=np.uint32),
                "x": np.array([0, 1], dtype=np.float32),
                "y": np.array([1, 0], dtype=np.float32),
            }
        ),
        coordinate_encoding={"x": encoding, "y": encoding},
    )
    scene = ScenePackage(
        (layer,),
        {},
        STYLE,
        {"reference_width": 500, "reference_height": 500, "data_bounds": {}},
        {},
        {},
    )
    encoded = json.loads(PlotlySceneAdapter().render(scene).to_json())["data"][0]

    assert encoded["x"]["dtype"] == "f4"
    assert encoded["y"]["dtype"] == "f4"


def test_nonidentity_relative_coordinates_decode_to_absolute_float64():
    from starplot.interactive.plotly_adapter import PlotlySceneAdapter

    encoding = CoordinateEncoding(
        CoordinateEncodingKind.RELATIVE_F32, origin=10.0, scale=2.0
    )
    layer = SceneLayer(
        id="relative",
        kind=SceneKind.LINE,
        group_id="line",
        zorder=0,
        load_priority=0,
        space=CoordinateSpace.DATA,
        clip_id="plot",
        style={"color": "#fff"},
        data=ColumnarData.from_mapping(
            {
                "path_id": np.array([0, 0], dtype=np.uint32),
                "vertex_index": np.array([0, 1], dtype=np.uint32),
                "x": np.array([0, 1], dtype=np.float32),
                "y": np.array([1, 0], dtype=np.float32),
            }
        ),
        coordinate_encoding={"x": encoding, "y": encoding},
    )
    scene = ScenePackage(
        (layer,),
        {},
        STYLE,
        {"reference_width": 500, "reference_height": 500, "data_bounds": {}},
        {},
        {},
    )
    figure = PlotlySceneAdapter().render(scene)
    encoded = json.loads(figure.to_json())["data"][0]

    assert encoded["x"]["dtype"] == "f8"
    assert list(figure.data[0].x) == pytest.approx([10.0, 12.0])


def test_zero_row_layer_emits_no_plotly_object():
    from starplot.interactive.plotly_adapter import PlotlySceneAdapter

    command = DrawingCommand(
        kind="text",
        data={"x": 20.0, "y": 20.0, "text": "outside"},
        clip_id="plot",
    )
    projection = {
        **PROJECTION,
        "clip_geometries": {
            "plot": __import__(
                "starplot.interactive.commands", fromlist=["ClipGeometry"]
            ).ClipGeometry("rect", ((-1, -1), (1, 1)))
        },
    }
    scene = SceneCompiler().compile([command], projection, STYLE, 500, 500, False)

    figure = PlotlySceneAdapter().render(scene)

    assert not figure.data
    assert not figure.layout.annotations


def test_paths_insert_nan_only_between_distinct_path_ids():
    from starplot.interactive.plotly_adapter import PlotlySceneAdapter

    command = primitive_commands()["line"]
    figure = PlotlySceneAdapter().render(_compile(command))
    values = np.asarray(figure.data[0].x)

    assert np.isnan(values[2])
    assert values.tolist()[:2] == [-1.0, 0.0]
    assert values.tolist()[3:] == [0.5, 1.0]


def test_adapter_rejects_unknown_gradient_direction_fail_closed():
    from starplot.interactive.plotly_adapter import PlotlySceneAdapter

    scene = _compile(primitive_commands()["gradient"])
    invalid_layer = replace(
        scene.layers[0],
        style={**dict(scene.layers[0].style), "direction": "diagonal"},
    )
    invalid_scene = replace(scene, layers=(invalid_layer,))

    with pytest.raises(RuntimeError) as error:
        PlotlySceneAdapter().render(invalid_scene)

    assert isinstance(error.value.__cause__, ValueError)
    assert "unsupported gradient direction" in str(error.value.__cause__)


def _split_finite_paths(x, y):
    paths = []
    current = []
    for x_value, y_value in zip(x, y):
        if not np.isfinite(x_value) or not np.isfinite(y_value):
            if current:
                paths.append(current)
                current = []
        else:
            current.append((float(x_value), float(y_value)))
    if current:
        paths.append(current)
    return paths


def _polygon_with_hole(*, zorder):
    return DrawingCommand(
        kind="polygon",
        data={
            "polygons": [
                [
                    [(0, 0), (4, 0), (4, 4), (0, 4)],
                    [(1, 1), (1, 3), (3, 3), (3, 1)],
                ]
            ]
        },
        style={
            "fill_color": "#223344",
            "edge_color": "#ffffff",
            "edge_width": 1,
        },
        zorder=zorder,
        gid="hole",
        clip_id=None,
    )


def test_data_polygon_hole_is_tessellated_on_trace_plane_with_stable_zorder():
    from starplot.interactive.plotly_adapter import PlotlySceneAdapter

    polygon = _polygon_with_hole(zorder=2)
    foreground = DrawingCommand(
        kind="line",
        data={"x": [0, 4], "y": [2, 2]},
        style={"color": "#ff0000", "width": 1},
        zorder=10,
        gid="foreground",
        clip_id="plot",
    )
    scene = SceneCompiler().compile(
        [foreground, polygon], PROJECTION, STYLE, 500, 500, False
    )

    figure = PlotlySceneAdapter().render(scene)

    assert not figure.layout.shapes
    fill, outline, foreground_trace = figure.data
    assert fill.type == "scatter"
    assert outline.type == "scatter"
    assert fill.fill == "toself"
    assert fill.line.width == 0
    assert fill.zorder == 2
    assert outline.zorder == 2
    assert foreground_trace.zorder == 10
    triangles = [Polygon(path) for path in _split_finite_paths(fill.x, fill.y)]
    assert sum(triangle.area for triangle in triangles) == pytest.approx(12.0)
    assert not any(triangle.covers(Point(2, 2)) for triangle in triangles)


@pytest.mark.parametrize("hole_zorder", [1, 5, 12])
def test_polygon_holes_and_scattergl_candidates_share_one_ordered_trace_plane(
    hole_zorder,
):
    from starplot.interactive.plotly_adapter import PlotlySceneAdapter

    scatter = DrawingCommand(
        kind="scatter",
        data={
            "x": [0.5, 3.5],
            "y": [0.5, 3.5],
            "sizes": [4.0, 4.0],
            "colors": ["#ff0000", "#ff0000"],
            "alphas": [1.0, 1.0],
        },
        zorder=2,
        gid="stars",
        clip_id=None,
    )
    lines = DrawingCommand(
        kind="line_collection",
        data={"lines": [[(0, 2), (4, 2)]]},
        style={"color": "#00ff00", "width": 1},
        zorder=8,
        gid="gl-lines",
        clip_id=None,
    )
    adapter = PlotlySceneAdapter()
    assert adapter.render(_compile(scatter)).data[0].type == "scattergl"
    assert adapter.render(_compile(lines)).data[0].type == "scattergl"

    scene = SceneCompiler().compile(
        [lines, _polygon_with_hole(zorder=hole_zorder), scatter],
        PROJECTION, STYLE, 500, 500, False,
    )
    figure = adapter.render(scene)

    assert {trace.type for trace in figure.data} == {"scatter"}
    star_trace = next(trace for trace in figure.data if trace.legendgroup == "stars")
    line_trace = next(trace for trace in figure.data if trace.legendgroup == "gl-lines")
    hole_traces = [trace for trace in figure.data if trace.legendgroup == "hole"]
    assert star_trace.zorder == 2
    assert line_trace.zorder == 8
    assert {trace.zorder for trace in hole_traces} == {hole_zorder}
    if hole_zorder < 2:
        assert hole_traces[0].zorder < star_trace.zorder < line_trace.zorder
    elif hole_zorder < 8:
        assert star_trace.zorder < hole_traces[0].zorder < line_trace.zorder
    else:
        assert star_trace.zorder < line_trace.zorder < hole_traces[0].zorder


def test_independent_single_ring_polygons_do_not_disable_scattergl():
    from starplot.interactive.plotly_adapter import PlotlySceneAdapter

    polygons = DrawingCommand(
        kind="polygon",
        data={"polygons": [
            [[(0, 0), (1, 0), (0, 1)]],
            [[(2, 2), (3, 2), (2, 3)]],
        ]},
        style={"fill_color": "#223344"},
        zorder=1,
        gid="polygons",
        clip_id=None,
    )
    stars = DrawingCommand(
        kind="scatter",
        data={
            "x": [0.5], "y": [0.5], "sizes": [4.0],
            "colors": ["#ffffff"], "alphas": [1.0],
        },
        zorder=2,
        gid="stars",
        clip_id=None,
    )
    scene = SceneCompiler().compile(
        [polygons, stars], PROJECTION, STYLE, 500, 500, False
    )

    figure = PlotlySceneAdapter().render(scene)

    star_trace = next(trace for trace in figure.data if trace.legendgroup == "stars")
    assert star_trace.type == "scattergl"


def test_public_adapter_is_stateless_across_parallel_and_sequential_renders():
    from starplot.interactive.plotly_adapter import PlotlySceneAdapter

    adapter = PlotlySceneAdapter()
    first_scene = _compile(primitive_commands()["line"])
    second_command = primitive_commands()["line"]
    second_command.style["color"] = "#123456"
    second_command.gid = "other-line"
    second_scene = _compile(second_command)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(adapter.render, first_scene)
        second_future = pool.submit(adapter.render, second_scene)
        first = first_future.result()
        second = second_future.result()
    third = adapter.render(first_scene)

    assert first.data[0].line.color == "#abcdef"
    assert second.data[0].line.color == "#123456"
    assert third.data[0].line.color == "#abcdef"
    assert vars(adapter) == {}
