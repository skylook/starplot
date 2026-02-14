"""Unit tests for DrawingRecorder."""

import pytest
from starplot.interactive.recorder import DrawingRecorder
from starplot.interactive.commands import DrawingCommand


def test_recorder_initial_state():
    rec = DrawingRecorder()
    assert rec.commands == []
    assert rec.projection_info == {}
    assert rec.style_info == {}


def test_recorder_records_scatter():
    rec = DrawingRecorder()
    rec.record_scatter(
        x=[1, 2, 3], y=[4, 5, 6],
        sizes=[10, 20, 30],
        colors=["#ffffff", "#aaaaaa", "#000000"],
        alphas=[1.0, 0.8, 0.6],
        metadata=[{"name": "Sirius"}],
        gid="stars",
        zorder=1,
    )
    assert len(rec.commands) == 1
    cmd = rec.commands[0]
    assert cmd.kind == "scatter"
    assert cmd.gid == "stars"
    assert cmd.zorder == 1
    assert cmd.data["x"] == [1, 2, 3]
    assert cmd.data["sizes"] == [10, 20, 30]


def test_recorder_records_scatter_with_single_color():
    """record_scatter should broadcast a single string color to a list."""
    rec = DrawingRecorder()
    rec.record_scatter(
        x=[1, 2], y=[3, 4],
        sizes=[10, 20],
        colors="#ffffff",  # single color
        alphas=1.0,  # single alpha
        metadata=[],
        gid="stars",
        zorder=0,
    )
    cmd = rec.commands[0]
    assert isinstance(cmd.data["colors"], list)
    assert len(cmd.data["colors"]) == 2


def test_recorder_records_line():
    rec = DrawingRecorder()
    rec.record_line(
        x=[0.0, 1.0, 2.0], y=[0.0, 0.5, 1.0],
        style_dict={"color": "#ff0000", "width": 2},
        gid="ecliptic-line",
        zorder=5,
    )
    assert len(rec.commands) == 1
    cmd = rec.commands[0]
    assert cmd.kind == "line"
    assert cmd.style["color"] == "#ff0000"
    assert cmd.gid == "ecliptic-line"


def test_recorder_records_polygon():
    rec = DrawingRecorder()
    pts = [(0.0, 0.0), (1.0, 0.0), (0.5, 1.0)]
    rec.record_polygon(
        points=pts,
        style_dict={"fill_color": "#223344", "alpha": 0.5},
        gid="milky-way",
        zorder=2,
    )
    assert len(rec.commands) == 1
    cmd = rec.commands[0]
    assert cmd.kind == "polygon"
    assert cmd.data["points"] == pts
    assert cmd.style["alpha"] == 0.5


def test_recorder_records_text():
    rec = DrawingRecorder()
    rec.record_text(
        text="Sirius",
        x=10.5, y=-5.0,
        style_dict={"font_size": 12, "font_color": "#ffffff"},
        gid="stars-label",
        zorder=10,
    )
    assert len(rec.commands) == 1
    cmd = rec.commands[0]
    assert cmd.kind == "text"
    assert cmd.data["text"] == "Sirius"
    assert cmd.data["x"] == 10.5


def test_recorder_records_line_collection():
    rec = DrawingRecorder()
    lines = [[(0, 0), (1, 1)], [(2, 2), (3, 3)]]
    metadata = [{"name": "Orion"}, {"name": "Orion"}]
    rec.record_line_collection(
        lines=lines,
        style_dict={"color": "#cccccc", "width": 1},
        gid="constellations-line",
        zorder=3,
        metadata=metadata,
    )
    cmd = rec.commands[0]
    assert cmd.kind == "line_collection"
    assert len(cmd.data["lines"]) == 2
    assert len(cmd.metadata) == 2


def test_recorder_records_gradient():
    rec = DrawingRecorder()
    rec.record_gradient(
        direction="vertical",
        color_stops=[(0.0, "#000000"), (1.0, "#000080")],
    )
    cmd = rec.commands[0]
    assert cmd.kind == "gradient"
    assert cmd.data["direction"] == "vertical"


def test_recorder_clear():
    rec = DrawingRecorder()
    rec.record_line(x=[1], y=[2], style_dict={}, gid="line", zorder=0)
    rec.record_text(text="A", x=1, y=2, style_dict={}, gid="text", zorder=0)
    assert len(rec.commands) == 2
    rec.clear()
    assert len(rec.commands) == 0


def test_recorder_multiple_commands():
    rec = DrawingRecorder()
    rec.record_scatter(x=[1], y=[2], sizes=[10], colors=["#fff"], alphas=[1.0],
                       metadata=[], gid="stars", zorder=1)
    rec.record_line(x=[0, 1], y=[0, 0], style_dict={}, gid="equator", zorder=2)
    rec.record_text(text="A", x=1, y=1, style_dict={}, gid="label", zorder=3)
    assert len(rec.commands) == 3
    assert [c.kind for c in rec.commands] == ["scatter", "line", "text"]
