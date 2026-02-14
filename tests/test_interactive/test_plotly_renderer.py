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
STYLE_INFO = {"background_color": "#0a0a1a", "figure_background_color": "#000000"}


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


def test_renderer_text_annotation():
    cmd = DrawingCommand(
        kind="text",
        data={"text": "Sirius", "x": 10.5, "y": -5.0},
        style={"font_size": 12, "font_color": "#ffffff", "va": "bottom", "ha": "left"},
        zorder=10,
        gid="stars-label",
    )
    renderer = make_renderer()
    fig = renderer.render([cmd])
    assert len(fig.layout.annotations) == 1
    ann = fig.layout.annotations[0]
    assert ann.text == "Sirius"
    assert ann.x == 10.5


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


def test_renderer_gradient_skipped():
    """Gradient commands should not add traces (V1: uses solid background)."""
    cmd = DrawingCommand(
        kind="gradient",
        data={"direction": "vertical", "color_stops": [(0.0, "#000"), (1.0, "#001")]},
        zorder=-1,
    )
    renderer = make_renderer()
    fig = renderer.render([cmd])
    assert len(fig.data) == 0


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
