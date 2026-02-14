"""Unit tests for DrawingCommand dataclass."""

import pytest
from starplot.interactive.commands import DrawingCommand


def test_drawing_command_creation():
    cmd = DrawingCommand(
        kind="scatter",
        data={"x": [1, 2], "y": [3, 4]},
        style={"color": "#ffffff"},
        metadata=[],
        zorder=0,
        gid="stars",
    )
    assert cmd.kind == "scatter"
    assert len(cmd.data["x"]) == 2
    assert cmd.gid == "stars"
    assert cmd.zorder == 0


def test_drawing_command_defaults():
    cmd = DrawingCommand(kind="line")
    assert cmd.data == {}
    assert cmd.style == {}
    assert cmd.metadata == []
    assert cmd.zorder == 0
    assert cmd.gid == ""


def test_drawing_command_kinds():
    for kind in ("scatter", "line", "polygon", "text", "line_collection", "gradient"):
        cmd = DrawingCommand(kind=kind)
        assert cmd.kind == kind


def test_drawing_command_metadata():
    meta = [{"name": "Sirius", "magnitude": -1.46, "type": "star"}]
    cmd = DrawingCommand(kind="scatter", metadata=meta)
    assert len(cmd.metadata) == 1
    assert cmd.metadata[0]["name"] == "Sirius"


def test_drawing_command_zorder():
    cmd = DrawingCommand(kind="polygon", zorder=42)
    assert cmd.zorder == 42


def test_drawing_command_polygon():
    cmd = DrawingCommand(
        kind="polygon",
        data={"points": [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]},
        style={"fill_color": "#112244", "alpha": 0.7},
    )
    assert len(cmd.data["points"]) == 4
    assert cmd.style["alpha"] == 0.7


def test_drawing_command_text():
    cmd = DrawingCommand(
        kind="text",
        data={"text": "Orion", "x": 5.5, "y": 10.0},
        style={"font_size": 14, "font_color": "#ffffff"},
        gid="constellation-label",
    )
    assert cmd.data["text"] == "Orion"
    assert cmd.style["font_size"] == 14


def test_drawing_command_line_collection():
    cmd = DrawingCommand(
        kind="line_collection",
        data={"lines": [[(0, 0), (1, 1)], [(2, 2), (3, 3)]]},
        metadata=[{"name": "Orion"}, {"name": "Orion"}],
    )
    assert len(cmd.data["lines"]) == 2
    assert len(cmd.metadata) == 2
