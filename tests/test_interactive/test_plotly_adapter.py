"""Scene-to-Plotly adapter contracts and legacy semantic snapshots."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import numpy as np
import pytest
from matplotlib.colors import to_rgba

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
            metadata=[{"name": "A", "type": "star"}, {"name": "B", "type": "star"}],
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
                "direction": "vertical",
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


def _normalize_scalars(value):
    if isinstance(value, dict):
        return {key: _normalize_scalars(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_scalars(item) for item in value]
    if isinstance(value, float):
        if not np.isfinite(value):
            return None
        return round(value, 5)
    return value


def normalized_figure(figure):
    """Normalize generated identity and typed-array serialization only."""
    payload = json.loads(figure.to_json())
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
            if isinstance(marker.get("color"), list) and marker.get("colorscale"):
                marker["color"] = _css_colors(
                    marker["color"], marker.get("opacity", 1.0), marker["colorscale"]
                )
                marker["opacity"] = 1.0
                for key in ("colorscale", "cmin", "cmax", "showscale"):
                    marker.pop(key, None)
        # customdata is an adapter transport detail; hover text itself remains frozen.
        trace.pop("customdata", None)
        for key in ("x", "y", "text"):
            values = trace.get(key)
            if isinstance(values, list):
                while values and values[-1] is None:
                    values.pop()
    return _normalize_scalars(payload)


def _compile(command, *, width=500, height=500):
    return SceneCompiler().compile([command], PROJECTION, STYLE, width, height, False)


def test_legacy_primitive_snapshot_fixture_exists_and_covers_every_kind():
    payload = json.loads(GOLDEN_PATH.read_text())
    assert set(payload) == set(primitive_commands())


@pytest.mark.parametrize("name", primitive_commands())
def test_scene_adapter_matches_independently_captured_legacy_primitive_snapshot(name):
    from starplot.interactive.plotly_adapter import PlotlySceneAdapter

    expected = _normalize_scalars(json.loads(GOLDEN_PATH.read_text())[name])
    for trace in expected.get("data", []):
        for key in ("x", "y", "text"):
            values = trace.get(key)
            if isinstance(values, list):
                while values and values[-1] is None:
                    values.pop()
    figure = PlotlySceneAdapter().render(_compile(primitive_commands()[name]))

    assert normalized_figure(figure) == expected


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
