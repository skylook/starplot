"""Tests for the typed recording contract: CoordinateSpace, ClipGeometry,
DrawingCommand.space, and DrawingCommand.clip_id."""

import pytest
from starplot.interactive.commands import CoordinateSpace, DrawingCommand
from starplot.interactive.recorder import DrawingRecorder


def test_recorder_marks_spatial_commands_as_final_data_space():
    recorder = DrawingRecorder()
    recorder.record_line(x=[1.0, 2.0], y=[3.0, 4.0], style_dict={},
                         gid="line", zorder=0, space=CoordinateSpace.DATA,
                         clip_id="plot")
    assert recorder.commands[0].space is CoordinateSpace.DATA
    assert recorder.commands[0].clip_id == "plot"


def test_command_rejects_unknown_coordinate_space():
    with pytest.raises(ValueError, match="Unknown coordinate space"):
        DrawingCommand(kind="line", space="ra_dec")
