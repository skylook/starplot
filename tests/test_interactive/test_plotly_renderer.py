"""Unit tests for PlotlyRenderer."""

import math

import numpy as np
import pytest

try:
    import plotly.graph_objects as go
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False

pytestmark = pytest.mark.skipif(not PLOTLY_AVAILABLE, reason="plotly not installed")

from starplot.interactive.commands import (  # noqa: E402
    ClipGeometry,
    CoordinateSpace,
    DrawingCommand,
)
from starplot.interactive.plotly_renderer import PlotlyRenderer  # noqa: E402


PROJ_INFO = {"ra_min": 0, "ra_max": 360, "dec_min": -90, "dec_max": 90}
STYLE_INFO = {"background_color": "#0a0a1a", "figure_background_color": "#000000", "show_legend": True}


def make_renderer():
    return PlotlyRenderer(PROJ_INFO, STYLE_INFO)


def test_renderer_creates_figure():
    renderer = make_renderer()
    fig = renderer.render([])
    assert fig is not None
    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 0


def test_renderer_layout_background():
    renderer = make_renderer()
    fig = renderer.render([])
    assert fig.layout.plot_bgcolor == "#0a0a1a"
    assert fig.layout.paper_bgcolor == "#000000"


def test_renderer_uses_requested_output_dimensions():
    """Marker scaling and the exported figure must use the same dimensions."""
    fig = PlotlyRenderer(PROJ_INFO, STYLE_INFO, width=1400, height=900).render([])

    assert fig.layout.width == 1400
    assert fig.layout.height == 900


def test_renderer_defaults_to_recorded_figure_dimensions_over_axes_dimensions():
    renderer = PlotlyRenderer(
        {
            **PROJ_INFO,
            "axes_bbox": (0.1, 0.1, 0.8, 0.8),
            "axes_pixels": (800.0, 640.0),
            "figure_pixels": (1000.0, 800.0),
        },
        STYLE_INFO,
    )

    assert renderer._reference_dimensions() == (1000.0, 800.0)


def test_renderer_leaves_dimensions_responsive_when_none_are_requested():
    """to_plotly() without dimensions must keep Plotly's responsive default."""
    fig = make_renderer().render([])

    assert fig.layout.width is None
    assert fig.layout.height is None


def test_renderer_scatter_trace():
    cmd = DrawingCommand(
        kind="scatter",
        data={
            "x": [1.0, 2.0, 3.0],
            "y": [4.0, 5.0, 6.0],
            "sizes": [10, 20, 30],
            "colors": ["#ffffff", "#aaaaaa", "#555555"],
            "alphas": [1.0, 1.0, 1.0],
        },
        metadata=[
            {"name": "Sirius", "magnitude": -1.46, "ra": 101.3, "dec": -16.7, "type": "star"}
        ] * 3,
        zorder=0,
        gid="stars",
    )
    renderer = make_renderer()
    fig = renderer.render([cmd])
    assert len(fig.data) == 1
    assert fig.data[0].type == "scattergl"
    assert list(fig.data[0].x) == [1.0, 2.0, 3.0]
    assert fig.data[0].name == "Stars"


def test_renderer_scatter_preserves_per_point_alpha():
    """A star alpha function must remain per-star after Plotly rendering."""
    cmd = DrawingCommand(
        kind="scatter",
        data={
            "x": [1.0, 2.0],
            "y": [3.0, 4.0],
            "sizes": [10, 10],
            "colors": ["#ffffff", "#000000"],
            "alphas": [0.25, 0.75],
        },
        metadata=[{}, {}],
        zorder=0,
        gid="stars",
    )

    fig = make_renderer().render([cmd])

    assert fig.data[0].marker.color.dtype == np.uint8
    assert list(fig.data[0].marker.opacity) == pytest.approx([0.25, 0.75])
    assert fig.data[0].marker.colorscale


def test_renderer_line_collection():
    cmd = DrawingCommand(
        kind="line_collection",
        data={"lines": [[(0, 0), (1, 1)], [(2, 2), (3, 3)]]},
        style={"color": "#aaaaaa", "width": 1, "alpha": 1.0},
        metadata=[{"name": "Orion"}, {"name": "Orion"}],
        zorder=1,
        gid="constellations-line",
    )
    renderer = make_renderer()
    fig = renderer.render([cmd])
    assert len(fig.data) == 1
    # 2 segments × 2 points + 2 None separators = 6 entries
    assert np.isnan(fig.data[0].x).any()
    assert fig.data[0].mode == "lines"


def test_renderer_single_line_uses_svg_layer_for_annotation_stacking():
    cmd = DrawingCommand(
        kind="line",
        data={"x": [0.0, 1.0], "y": [0.0, 1.0]},
        style={"color": "#ffffff", "width": 2, "alpha": 1.0},
        zorder=1,
        gid="horizon-circle",
        clip_id="plot",
    )

    fig = make_renderer().render([cmd])

    assert fig.data[0].type == "scatter"


def test_renderer_unclipped_line_uses_shape_below_annotations():
    line = DrawingCommand(
        kind="line",
        data={"x": [0.0, 1.0], "y": [0.0, 1.0]},
        style={"color": "#ffffff", "width": 2, "alpha": 1.0},
        zorder=1,
        gid="decoration",
        clip_id=None,
    )
    label = DrawingCommand(
        kind="text",
        data={"text": "N", "x": 0.5, "y": 0.5},
        style={"font_color": "#ffffff"},
        zorder=2,
        gid="label",
        space=CoordinateSpace.DATA,
        clip_id=None,
    )

    fig = make_renderer().render([line, label])

    assert len(fig.data) == 0
    assert len(fig.layout.shapes) == 1
    assert fig.layout.shapes[0].layer == "above"
    assert len(fig.layout.annotations) == 1


def test_renderer_polygon():
    cmd = DrawingCommand(
        kind="polygon",
        data={"points": [(0.0, 0.0), (1.0, 0.0), (0.5, 1.0)]},
        style={"fill_color": "#223344", "edge_color": None, "edge_width": 0, "alpha": 0.7},
        zorder=0,
        gid="milky-way",
    )
    renderer = make_renderer()
    fig = renderer.render([cmd])
    assert len(fig.data) == 1
    assert fig.data[0].fill == "toself"


def test_renderer_polygon_no_fill():
    cmd = DrawingCommand(
        kind="polygon",
        data={"points": [(0.0, 0.0), (1.0, 0.0), (0.5, 1.0)]},
        style={"fill_color": None, "edge_color": "#ffffff", "edge_width": 1, "alpha": 1.0},
        zorder=0,
        gid="dso-outline",
    )
    renderer = make_renderer()
    fig = renderer.render([cmd])
    assert fig.data[0].fill is None


def test_renderer_reserves_paper_space_for_horizon_footer():
    """Negative Matplotlib axes coordinates must remain visible in Plotly."""
    footer = DrawingCommand(
        kind="polygon",
        data={"points": [(0.0, -0.04), (1.0, -0.04), (1.0, -0.11), (0.0, -0.11)]},
        style={"fill_color": "#111111", "edge_color": "#111111", "xref": "paper", "yref": "paper"},
        zorder=0,
        gid="horizon-bottom",
    )
    label = DrawingCommand(
        kind="text",
        data={"text": "SOUTH", "x": 0.5, "y": -0.08},
        style={"xref": "paper", "yref": "paper"},
        zorder=1,
        gid="horizon-label",
    )

    fig = make_renderer().render([footer, label])

    assert fig.layout.yaxis.domain[0] == pytest.approx(0.11)
    assert "-0." not in fig.layout.shapes[0].path
    assert fig.layout.annotations[0].y == pytest.approx(0.03)


def test_renderer_reserves_map_gutters_for_final_gridliner_labels():
    """Gridliner labels outside Matplotlib axes must survive in Plotly paper."""
    projection = {**PROJ_INFO, "plot_kind": "map"}
    bottom = DrawingCommand(
        kind="text", data={"text": "4h", "x": 0.9, "y": -0.02},
        style={"font_color": "#000000", "ha": "center", "va": "top"},
        zorder=1, gid="gridlines-label", space=CoordinateSpace.PAPER,
    )
    right = DrawingCommand(
        kind="text", data={"text": "20°", "x": 1.02, "y": 0.8},
        style={"font_color": "#000000", "ha": "left", "va": "center"},
        zorder=1, gid="gridlines-label", space=CoordinateSpace.PAPER,
    )

    fig = PlotlyRenderer(projection, STYLE_INFO).render([bottom, right])

    assert fig.layout.xaxis.domain[1] < 1
    assert fig.layout.yaxis.domain[0] > 0
    assert 0 < fig.layout.annotations[0].y < 1
    assert 0 < fig.layout.annotations[1].x < 1


def test_renderer_text_annotation():
    cmd = DrawingCommand(
        kind="text",
        data={"text": "Sirius", "x": 10.5, "y": -5.0},
        style={
            "font_size": 12,
            "font_color": "#ffffff",
            "font_name": "Inter",
            "va": "bottom",
            "ha": "left",
        },
        zorder=10,
        gid="stars-label",
    )
    renderer = make_renderer()
    fig = renderer.render([cmd])
    assert len(fig.layout.annotations) == 1
    ann = fig.layout.annotations[0]
    assert ann.text == "Sirius"
    assert ann.x == 10.5
    assert ann.xanchor == "left"
    assert ann.font.family == "Inter, Arial, sans-serif"


def test_renderer_text_preserves_matplotlib_multiline_labels():
    cmd = DrawingCommand(
        kind="text",
        data={"text": "CANIS\nMAJOR", "x": 1.0, "y": 2.0},
        style={"font_color": "#ffffff", "font_weight": "normal"},
        zorder=1,
        gid="constellations-label-name",
        space=CoordinateSpace.DATA,
    )

    fig = make_renderer().render([cmd])

    assert fig.layout.annotations[0].text == "CANIS<br>MAJOR"


def test_renderer_text_escapes_html_in_user_labels():
    cmd = DrawingCommand(
        kind="text",
        data={"text": "<b>A&B</b>", "x": 1.0, "y": 2.0},
        style={"font_color": "#ffffff", "font_weight": "normal"},
        zorder=1,
        gid="constellations-label-name",
        space=CoordinateSpace.DATA,
    )

    fig = make_renderer().render([cmd])

    assert fig.layout.annotations[0].text == "&lt;b&gt;A&amp;B&lt;/b&gt;"


def test_renderer_scales_text_from_matplotlib_points():
    """Text uses recorded Matplotlib DPI, plot scale, and axes dimensions."""
    style_info = {
        **STYLE_INFO,
        "dpi": 100,
        "plot_scale": 1.0,
        "source_axes_width": 1000.0,
    }
    cmd = DrawingCommand(
        kind="text",
        data={"text": "Sirius", "x": 10.5, "y": -5.0},
        style={"font_size": 12, "font_color": "#ffffff"},
        zorder=10,
        gid="stars-label",
    )

    fig = PlotlyRenderer(PROJ_INFO, style_info, width=740, height=500).render([cmd])

    # 12 points at 100 DPI is 12 * 100/72 ~= 16.7 pixels, scaled by the
    # target/source axes width ratio (740/1000) so text stays visually
    # proportional to the output dimensions.
    assert fig.layout.annotations[0].font.size == pytest.approx(12.33, abs=0.01)


def test_renderer_line():
    cmd = DrawingCommand(
        kind="line",
        data={"x": [0.0, 90.0, 180.0, 270.0, 360.0], "y": [0.0] * 5},
        style={"color": "#ffff00", "width": 1.5, "line_style": "dashed", "alpha": 0.8},
        zorder=3,
        gid="ecliptic-line",
    )
    renderer = make_renderer()
    fig = renderer.render([cmd])
    assert len(fig.data) == 1
    assert fig.data[0].line.color == "#ffff00"
    assert fig.data[0].line.dash == "dash"
    assert fig.data[0].name == "Ecliptic"


def test_renderer_zorder_sorting():
    """Commands should be rendered in zorder order."""
    cmd_high = DrawingCommand(kind="line", data={"x": [0], "y": [0]},
                               style={"color": "#ff0000", "width": 1, "alpha": 1.0},
                               zorder=10, gid="high")
    cmd_low = DrawingCommand(kind="line", data={"x": [0], "y": [0]},
                              style={"color": "#0000ff", "width": 1, "alpha": 1.0},
                              zorder=1, gid="low")
    renderer = make_renderer()
    fig = renderer.render([cmd_high, cmd_low])
    # Low zorder should be rendered first (index 0)
    assert fig.data[0].name == "Low"
    assert fig.data[1].name == "High"


def test_renderer_legend_dedup():
    """Each gid should appear at most once in the legend."""
    cmds = [
        DrawingCommand(kind="scatter",
                       data={"x": [i], "y": [i], "sizes": [10], "colors": ["#fff"], "alphas": [1.0]},
                       metadata=[{}], zorder=0, gid="stars")
        for i in range(3)
    ]
    renderer = make_renderer()
    fig = renderer.render(cmds)
    legend_entries = [t.name for t in fig.data if t.showlegend]
    assert legend_entries.count("Stars") == 1


def test_renderer_uses_explicit_matplotlib_legend_and_magnitude_scale():
    style_info = {
        **STYLE_INFO,
        "legend_labels": ["Star", "Nebula"],
        "legend_title": "Legend",
        "legend_background_color": "#f1f6fe",
        "legend_font_color": "#000000",
        "legend_title_font_size": 14,
        "magnitude_scale": {
            "title": "Star Magnitude",
            "labels": ["0", "1"],
            "sizes": [12.0, 8.0],
            "color": "#000000",
            "edge_color": "#000000",
        },
    }
    commands = [
        DrawingCommand(
            kind="scatter",
            data={"x": [1], "y": [1], "sizes": [10], "colors": ["#fff"], "alphas": [1.0]},
            style={"legend_label": "Star"}, metadata=[{}], gid="stars",
        ),
        DrawingCommand(
            kind="scatter",
            data={"x": [2], "y": [2], "sizes": [10], "colors": ["#afa"], "alphas": [1.0]},
            style={"legend_label": "Nebula"}, metadata=[{}], gid="dso_nebula",
        ),
        DrawingCommand(
            kind="line_collection", data={"lines": [[(0, 0), (1, 1)]]},
            style={"color": "#777"}, gid="gridlines",
        ),
    ]

    fig = PlotlyRenderer(PROJ_INFO, style_info).render(commands)
    legend_entries = [trace.name for trace in fig.data if trace.showlegend]

    assert legend_entries == ["Star", "Nebula", "0", "1"]
    assert fig.layout.legend.bgcolor == "#f1f6fe"
    assert fig.layout.legend.font.color == "#000000"
    assert fig.layout.legend.title.text == "Legend"
    assert fig.data[-2].legendgrouptitle.text == "Star Magnitude"
    assert fig.data[-2].legendgrouptitle.font.color == "#000000"
    assert fig.data[-2].legendgrouptitle.font.size == fig.layout.legend.title.font.size


def test_renderer_gradient_no_traces_without_proj_info():
    """Gradient without projected axis bounds should not add traces."""
    cmd = DrawingCommand(
        kind="gradient",
        data={"direction": "linear", "color_stops": [(0.0, "#000"), (1.0, "#001")]},
        zorder=-1,
    )
    renderer = make_renderer()
    fig = renderer.render([cmd])
    assert len(fig.data) == 0


def test_renderer_gradient_renders_heatmap_with_proj_info():
    """Gradient with projected axis bounds should render a heatmap trace."""
    proj_info = {
        "ra_min": 0, "ra_max": 360, "dec_min": -90, "dec_max": 90,
        "x_min": 0.0, "x_max": 100.0, "y_min": -50.0, "y_max": 50.0,
    }
    cmd = DrawingCommand(
        kind="gradient",
        data={"direction": "linear", "color_stops": [(0.0, "#000"), (1.0, "#001")]},
        zorder=-1,
    )
    renderer = PlotlyRenderer(proj_info, STYLE_INFO)
    fig = renderer.render([cmd])
    assert len(fig.data) == 1
    assert fig.data[0].type == "heatmap"


def test_renderer_hover_star_text():
    cmd = DrawingCommand(
        kind="scatter",
        data={"x": [1.0], "y": [2.0], "sizes": [15], "colors": ["#fff"], "alphas": [1.0]},
        metadata=[{
            "name": "Sirius", "magnitude": -1.46, "bayer": "α CMa",
            "constellation": "Canis Major", "ra": 101.3, "dec": -16.7, "type": "star"
        }],
        zorder=0, gid="stars",
    )
    renderer = make_renderer()
    fig = renderer.render([cmd])
    hover_text = fig.data[0].text[0]
    assert "Sirius" in hover_text
    assert "Magnitude" in hover_text
    assert "RA" in hover_text


def test_renderer_hover_text_escapes_html_metacharacters():
    cmd = DrawingCommand(
        kind="scatter",
        data={"x": [1.0], "y": [2.0], "sizes": [15], "colors": ["#fff"], "alphas": [1.0]},
        metadata=[{
            "name": "<b>Evil</b>", "magnitude": 1.0, "bayer": "&test",
            "constellation": "A&B", "ra": 0.0, "dec": 0.0, "type": "star"
        }],
        zorder=0, gid="stars",
    )
    renderer = make_renderer()
    fig = renderer.render([cmd])
    hover_text = fig.data[0].text[0]
    assert "<b>Evil</b>" not in hover_text
    assert "&lt;b&gt;Evil&lt;/b&gt;" in hover_text
    assert "&amp;test" in hover_text
    assert "A&amp;B" in hover_text


def test_renderer_disables_hover_payload_for_high_volume_trace(monkeypatch):
    import starplot.interactive.plotly_adapter as adapter_module

    monkeypatch.setattr(adapter_module, "_MAX_INTERACTIVE_HOVER_POINTS", 1)
    cmd = DrawingCommand(
        kind="scatter",
        data={
            "x": [1.0, 2.0],
            "y": [3.0, 4.0],
            "sizes": [4.0, 4.0],
            "colors": ["#fff", "#fff"],
            "alphas": [1.0, 1.0],
        },
        metadata=[{"name": "A", "type": "star"}, {"name": "B", "type": "star"}],
        gid="stars",
    )

    fig = make_renderer().render([cmd])

    assert fig.data[0].hoverinfo == "skip"
    assert fig.data[0].text is None


def test_renderer_scattergl_preserves_subpixel_area():
    cmd = DrawingCommand(
        kind="scatter",
        data={
            "x": [1.0, 2.0],
            "y": [3.0, 4.0],
            "sizes": [0.02, 0.02],
            "colors": ["#ffffff", "#ffffff"],
            "alphas": 0.5,
        },
        style={"edge_color": "#ffffff", "edge_width": 2.0},
        gid="stars",
    )

    fig = make_renderer().render([cmd])

    assert list(fig.data[0].marker.size) == [1.0, 1.0]
    assert fig.data[0].marker.line.color == "#ffffff"
    assert fig.data[0].marker.line.width > 0
    assert all(float(opacity) < 0.5 for opacity in fig.data[0].marker.opacity)


def test_marker_size_calibration_can_retain_subpixel_diameter():
    from starplot.interactive.style_converter import (
        calibrate_marker_size,
        calibrate_marker_sizes_array,
    )

    assert calibrate_marker_size(0.02, min_size=0.0) < 1.0
    assert calibrate_marker_size(0.02) == 1.5
    assert calibrate_marker_size(0.0, min_size=0.0) == 0.0

    mpl_sizes = np.array([0.0, 0.02, 1.0, 50.0], dtype=np.float32)
    calibrated = calibrate_marker_sizes_array(
        mpl_sizes,
        dpi=100.0,
        target_width=500.0,
        source_axes_width=400.0,
        kaleido_scale=1.15,
    )
    expected = np.array(
        [
            calibrate_marker_size(
                size,
                dpi=100.0,
                width=500.0,
                source_axes_width=400.0,
            )
            * 1.15
            for size in mpl_sizes
        ],
        dtype=np.float32,
    )

    assert calibrated.dtype == np.float32
    assert calibrated.flags.c_contiguous
    assert calibrated.flags.aligned
    assert not calibrated.flags.writeable
    np.testing.assert_allclose(calibrated, expected, rtol=2e-6)


def test_marker_size_calibration_matches_matplotlib_circle_extent():
    """Matplotlib's default circle path has a diameter of sqrt(s) points."""
    from starplot.interactive.style_converter import calibrate_marker_size

    assert calibrate_marker_size(
        3800.0,
        dpi=100.0,
        width=4800.0,
        source_axes_width=4800.0,
        min_size=0.0,
    ) == pytest.approx(math.sqrt(3800.0) * 100.0 / 72.0)
    assert calibrate_marker_size(
        3800.0, dpi=100.0, width=4800.0, source_axes_width=4800.0,
        min_size=0.0, symbol="star_8",
    ) == pytest.approx(math.sqrt(3800.0) * 100.0 / 144.0)
    for symbol in ("point", "star_4"):
        assert calibrate_marker_size(
            3800.0, dpi=100.0, width=4800.0, source_axes_width=4800.0,
            min_size=0.0, symbol=symbol,
        ) == pytest.approx(math.sqrt(3800.0) * 100.0 / 144.0)



@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"dpi": 0.0}, "dpi"),
        ({"dpi": float("nan")}, "dpi"),
        ({"target_width": 0.0}, "target_width"),
        ({"target_width": "wide"}, "target_width"),
        ({"source_axes_width": -1.0}, "source_axes_width"),
    ],
)
def test_marker_size_array_rejects_invalid_calibration_dimensions(
    kwargs, message
):
    from starplot.interactive.style_converter import calibrate_marker_sizes_array

    values = {
        "dpi": 100.0,
        "target_width": 500.0,
        "source_axes_width": 400.0,
    }
    values.update(kwargs)

    with pytest.raises(ValueError, match=message):
        calibrate_marker_sizes_array(np.array([1.0], dtype=np.float32), **values)


def test_tiny_per_point_alpha_stays_numeric_for_plotly6():
    cmd = DrawingCommand(
        kind="scatter",
        data={
            "x": [1.0],
            "y": [2.0],
            "sizes": [1.0],
            "colors": ["#ffffff"],
            "alphas": [0.0000836198],
        },
        gid="stars",
    )

    figure = make_renderer().render([cmd])

    assert figure.data[0].marker.opacity[0] == pytest.approx(1.9228892e-05)
    assert figure.data[0].marker.color.dtype == np.uint8


def test_renderer_marker_uses_legend_label():
    cmd = DrawingCommand(
        kind="scatter",
        data={"x": [10.0], "y": [20.0], "sizes": [50], "colors": ["#ff0000"], "alphas": [1.0]},
        style={"legend_label": "Target", "symbol": "circle", "edge_width": 1},
        metadata=[{}],
        zorder=0, gid="marker",
    )
    renderer = make_renderer()
    fig = renderer.render([cmd])
    assert fig.data[0].name == "Target"
    assert fig.data[0].showlegend is True


def test_renderer_text_with_paper_ref():
    cmd = DrawingCommand(
        kind="text",
        data={"text": "Title", "x": 0.5, "y": 0.98},
        style={"font_size": 24, "font_color": "#ffffff", "xref": "paper", "yref": "paper"},
        zorder=10, gid="title",
    )
    renderer = make_renderer()
    fig = renderer.render([cmd])
    ann = fig.layout.annotations[0]
    assert ann.xref == "paper"
    assert ann.yref == "paper"


def test_renderer_reserves_matplotlib_title_gutter():
    cmd = DrawingCommand(
        kind="text",
        data={"text": "Virgo Cluster", "x": 0.5, "y": 0.95},
        style={
            "font_size": 64,
            "font_color": "#ffffff",
            "axes_domain_top": 0.86,
        },
        zorder=10,
        gid="title",
        space=CoordinateSpace.PAPER,
    )

    fig = make_renderer().render([cmd])

    assert fig.layout.yaxis.domain[1] == pytest.approx(0.86)
    assert fig.layout.annotations[0].y == pytest.approx(0.95)


def test_renderer_uses_coordinate_space_for_axes_annotation():
    """AXES-space source text must track the Plotly axes domain, not paper."""
    cmd = DrawingCommand(
        kind="text",
        data={"text": "axes label", "x": 0.05, "y": 0.05},
        style={"xref": "paper", "yref": "paper"},
        zorder=1,
        gid="axes-label",
        space=CoordinateSpace.AXES,
    )

    fig = make_renderer().render([cmd])

    assert fig.layout.annotations[0].xref == "x domain"
    assert fig.layout.annotations[0].yref == "y domain"


# ------------------------------------------------------------------
# Task 4: Clipping tests
# ------------------------------------------------------------------

def _unit_circle_clip():
    """Build a 64-vertex unit-circle ClipGeometry centered at origin."""
    theta = np.linspace(0, 2 * math.pi, 65)[:-1]
    points = tuple((math.cos(t), math.sin(t)) for t in theta)
    return ClipGeometry(kind="polygon", points=points)


def renderer_with_circle_clip():
    """Renderer with a unit-circle clip polygon and matching axis range."""
    clip = _unit_circle_clip()
    proj = {
        "x_min": -1.5, "x_max": 1.5, "y_min": -1.5, "y_max": 1.5,
        "clip_geometries": {"plot": clip},
        "plot_kind": "optic",
    }
    style = {"background_color": "#000", "figure_background_color": "#000",
             "resolution": 512, "dpi": 100, "plot_scale": 1.0,
             "source_axes_width": 500.0}
    return PlotlyRenderer(proj, style, width=500, height=500)


def test_renderer_paints_background_inside_recorded_clip_only():
    renderer = renderer_with_circle_clip()
    figure = renderer.render([])

    assert figure.layout.plot_bgcolor == "rgba(0,0,0,0)"
    assert len(figure.layout.shapes) == 1
    background = figure.layout.shapes[0]
    assert background.fillcolor == "#000"
    assert background.layer == "below"


def scatter_command(x, y):
    return DrawingCommand(
        kind="scatter",
        data={"x": list(x), "y": list(y), "sizes": [10] * len(x),
              "colors": ["#fff"] * len(x), "alphas": [1.0] * len(x)},
        style={"symbol": "circle"},
        gid="test-scatter",
        zorder=0,
        space=CoordinateSpace.DATA,
        clip_id="plot",
    )


def line_command(x, y):
    return DrawingCommand(
        kind="line",
        data={"x": list(x), "y": list(y)},
        style={"color": "#fff", "width": 1},
        gid="test-line",
        zorder=0,
        space=CoordinateSpace.DATA,
        clip_id="plot",
    )


def test_scatter_points_outside_clip_are_not_rendered():
    renderer = renderer_with_circle_clip()
    figure = renderer.render([scatter_command(x=[0.0, 1.5], y=[0.0, 0.0])])
    # The point at (1.5, 0) is outside the unit circle and must be removed
    assert list(figure.data[0].x) == [0.0]
    assert list(figure.data[0].y) == [0.0]


def test_line_crossing_circle_is_trimmed_to_boundary():
    renderer = renderer_with_circle_clip()
    figure = renderer.render([line_command(x=[-2.0, 2.0], y=[0.0, 0.0])])
    # The line from (-2,0) to (2,0) clipped to the unit circle should
    # have endpoints at approximately (-1, 0) and (1, 0)
    xs = list(figure.data[0].x)
    ys = list(figure.data[0].y)
    # Filter out None separators
    xs = [v for v in xs if v is not None]
    ys = [v for v in ys if v is not None]
    assert len(xs) >= 2
    assert xs[0] == pytest.approx(-1.0, abs=0.05)
    assert xs[-1] == pytest.approx(1.0, abs=0.05)


# ------------------------------------------------------------------
# Task 5: Label placement tests
# ------------------------------------------------------------------

def text_command(offset_points=(0.0, 0.0), rotation=0.0):
    return DrawingCommand(
        kind="text",
        data={"text": "Probe", "x": 0.0, "y": 0.0,
              "offset_points": offset_points},
        style={"font_size": 12, "font_color": "#ffffff",
               "rotation": rotation, "ha": "center", "va": "center"},
        gid="test-text",
        zorder=0,
        space=CoordinateSpace.DATA,
    )


def renderer_with_known_axes_pixels():
    """Renderer with known axes pixel dimensions for offset conversion."""
    proj = {
        "x_min": -1.5, "x_max": 1.5, "y_min": -1.5, "y_max": 1.5,
        "axes_pixels": (500.0, 500.0),
        "axes_bbox": (0.1, 0.1, 0.8, 0.8),
        "clip_geometries": {},
        "plot_kind": "map",
    }
    style = {"background_color": "#000", "figure_background_color": "#000",
             "resolution": 512, "dpi": 100, "plot_scale": 1.0,
             "source_axes_width": 500.0}
    return PlotlyRenderer(proj, style, width=500, height=500)


def test_renderer_converts_offset_points_to_pixels():
    renderer = renderer_with_known_axes_pixels()
    figure = renderer.render([text_command(offset_points=(7.2, -3.6))])
    annotation = figure.layout.annotations[0]
    # 7.2 points at 100 dpi → 7.2 / 72 * 100 = 10 pixels, scaled by the
    # target/source axes width ratio (400/500 = 0.8) because offsets are
    # recorded relative to the source figure and must stay proportional.
    assert annotation.xshift == pytest.approx(8.0, abs=0.5)
    assert annotation.yshift == pytest.approx(-4.0, abs=0.5)


# ------------------------------------------------------------------
# Task 6: Layout, gradients, transparency
# ------------------------------------------------------------------

def test_transparent_export_clears_paper_but_preserves_axes_background():
    """Match Matplotlib: transparent paper, explicit opaque axes facecolor."""
    from starplot.interactive import InteractiveMapPlot
    from starplot import Miller
    plot = InteractiveMapPlot(
        projection=Miller(), ra_min=60, ra_max=120,
        dec_min=-10, dec_max=30, resolution=256,
    )
    fig = plot.to_plotly(transparent=True)
    assert fig.layout.paper_bgcolor == "rgba(0,0,0,0)"
    assert fig.layout.plot_bgcolor == "rgba(0,0,0,0)"
    background = fig.layout.shapes[0]
    assert background.fillcolor != "rgba(0,0,0,0)"
    assert background.layer == "below"


def radial_gradient_command():
    return DrawingCommand(
        kind="gradient",
        data={
            "direction": "radial",
            "color_stops": [[0.0, "#000022"], [0.5, "#000011"], [1.0, "#000000"]],
            "center": (0.0, 0.0),
            "radius": 1.0,
        },
        style={},
        gid="gradient",
        zorder=-2000,
        space=CoordinateSpace.DATA,
        clip_id="plot",
    )


def test_radial_gradient_uses_source_radius_squared_and_reversal():
    """Radial gradient values should be radius^2 with reversed colors."""
    renderer = renderer_with_circle_clip()
    figure = renderer.render([radial_gradient_command()])
    heatmap = next(trace for trace in figure.data if trace.type == "heatmap")
    z = np.array(heatmap.z)
    # The data remains radius^2; reversal is encoded in the colorscale,
    # matching Matplotlib's reversed LinearSegmentedColormap.
    center = z.shape[0] // 2, z.shape[1] // 2
    assert z[center] == pytest.approx(0.0, abs=0.05)
    assert np.isnan(z[0][0])
    assert heatmap.colorscale[0][1] == "#000000"
    assert heatmap.colorscale[-1][1] == "#000022"


def _heatmap_value_at(heatmap, x, y):
    x_index = int(np.argmin(np.abs(np.asarray(heatmap.x) - x)))
    y_index = int(np.argmin(np.abs(np.asarray(heatmap.y) - y)))
    return np.asarray(heatmap.z)[y_index, x_index]


def test_radial_gradient_without_clip_is_transparent_outside_radius():
    renderer = PlotlyRenderer(
        {
            "x_min": -1.5,
            "x_max": 1.5,
            "y_min": -1.5,
            "y_max": 1.5,
            "clip_geometries": {},
        },
        STYLE_INFO,
        width=500,
        height=500,
    )
    command = radial_gradient_command()
    command.clip_id = None

    heatmap = renderer.render([command]).data[0]

    assert np.isfinite(_heatmap_value_at(heatmap, 0, 0))
    assert np.isnan(_heatmap_value_at(heatmap, 1.4, 1.4))


@pytest.mark.parametrize(
    ("clip", "inside", "outside"),
    [
        (
            ClipGeometry("rect", ((-1.0, -0.5), (1.0, 0.5))),
            (0.0, 0.0),
            (0.0, 0.75),
        ),
        (
            ClipGeometry("polygon", ((-1.0, -1.0), (1.0, -1.0), (0.0, 1.0))),
            (0.0, 0.0),
            (0.9, 0.9),
        ),
    ],
)
def test_radial_gradient_masks_actual_scene_clip_geometry(clip, inside, outside):
    projection = {
        "x_min": -1.5,
        "x_max": 1.5,
        "y_min": -1.5,
        "y_max": 1.5,
        "clip_geometries": {"plot": clip},
    }

    heatmap = PlotlyRenderer(
        projection, STYLE_INFO, width=500, height=500
    ).render([radial_gradient_command()]).data[0]

    assert np.isfinite(_heatmap_value_at(heatmap, *inside))
    assert np.isnan(_heatmap_value_at(heatmap, *outside))


@pytest.mark.parametrize("direction", ["linear", "mollweide"])
def test_nonradial_gradient_masks_actual_scene_clip_geometry(direction):
    clip = ClipGeometry(
        "polygon",
        ((-1.0, -1.0), (1.0, -1.0), (0.0, 1.0)),
    )
    projection = {
        "x_min": -1.5,
        "x_max": 1.5,
        "y_min": -1.5,
        "y_max": 1.5,
        "clip_geometries": {"plot": clip},
    }
    command = DrawingCommand(
        kind="gradient",
        data={
            "direction": direction,
            "color_stops": [(0.0, "#000022"), (1.0, "#000000")],
        },
        clip_id="plot",
    )

    heatmap = PlotlyRenderer(
        projection, STYLE_INFO, width=500, height=500
    ).render([command]).data[0]

    assert np.isfinite(_heatmap_value_at(heatmap, 0.0, 0.0))
    assert np.isnan(_heatmap_value_at(heatmap, 0.9, 0.9))
    if direction == "mollweide":
        middle_row = np.asarray(heatmap.z)[len(heatmap.y) // 2]
        finite = middle_row[np.isfinite(middle_row)]
        assert np.ptp(finite) > 0.01
