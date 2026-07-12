"""Unit tests for PlotlyRenderer."""

import pytest

try:
    import plotly.graph_objects as go
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False

pytestmark = pytest.mark.skipif(not PLOTLY_AVAILABLE, reason="plotly not installed")

from starplot.interactive.commands import DrawingCommand
from starplot.interactive.plotly_renderer import PlotlyRenderer


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

    assert list(fig.data[0].marker.color) == [
        "rgba(255,255,255,0.25)",
        "rgba(0,0,0,0.75)",
    ]
    assert fig.data[0].marker.opacity == 1.0


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
    assert None in fig.data[0].x
    assert fig.data[0].mode == "lines"


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
    assert ann.font.family == "Inter, Arial, sans-serif"


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

    # Plot width inside the 10px left/right margins is 720px. At 100 DPI,
    # 12 points on a 1000px source axes therefore maps to 12 Plotly pixels.
    assert fig.layout.annotations[0].font.size == pytest.approx(12.0)


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


def test_renderer_gradient_no_traces_without_proj_info():
    """Gradient without projected axis bounds should not add traces."""
    cmd = DrawingCommand(
        kind="gradient",
        data={"direction": "vertical", "color_stops": [(0.0, "#000"), (1.0, "#001")]},
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
        data={"direction": "vertical", "color_stops": [(0.0, "#000"), (1.0, "#001")]},
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


# ------------------------------------------------------------------
# Task 4: Clipping tests
# ------------------------------------------------------------------

import math
import numpy as np
from starplot.interactive.commands import ClipGeometry, CoordinateSpace


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
