"""Tests for the typed recording contract: CoordinateSpace, ClipGeometry,
DrawingCommand.space, and DrawingCommand.clip_id."""

import math
from datetime import datetime
from zoneinfo import ZoneInfo

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


# ------------------------------------------------------------------
# Plot factory helpers for four-family tests
# ------------------------------------------------------------------

def make_map_plot():
    from starplot.interactive import InteractiveMapPlot
    from starplot import Miller
    return InteractiveMapPlot(
        projection=Miller(), ra_min=60, ra_max=120,
        dec_min=-10, dec_max=30, resolution=512,
    )


def make_horizon_plot():
    from starplot.interactive import InteractiveHorizonPlot
    return InteractiveHorizonPlot(
        altitude=(0, 60), azimuth=(325, 440), resolution=512,
    )


def make_zenith_plot():
    from starplot.interactive import InteractiveZenithPlot
    from starplot import Observer
    from starplot.styles import PlotStyle, extensions
    tz = ZoneInfo("America/Los_Angeles")
    dt = datetime(2023, 7, 13, 22, 0, tzinfo=tz)
    observer = Observer(dt=dt, lat=33.363484, lon=-116.836394)
    return InteractiveZenithPlot(
        observer=observer,
        style=PlotStyle().extend(extensions.BLUE_MEDIUM),
        resolution=512, autoscale=True,
    )


def make_optic_plot():
    from starplot.interactive import InteractiveOpticPlot
    from starplot import Observer
    from starplot.models import Refractor
    from starplot.styles import PlotStyle, extensions
    dt = datetime(2023, 12, 16, 21, 0, 0, tzinfo=ZoneInfo("US/Pacific"))
    observer = Observer(dt=dt, lat=33.363484, lon=-116.836394)
    return InteractiveOpticPlot(
        ra=90.0, dec=10.0, observer=observer,
        optic=Refractor(focal_length=430, eyepiece_focal_length=11, eyepiece_fov=82),
        style=PlotStyle().extend(extensions.GRAYSCALE_DARK, extensions.OPTIC),
        resolution=512, autoscale=True,
    )


@pytest.mark.parametrize("plot_factory, expected_kind", [
    (make_map_plot, "rect"),
    (make_horizon_plot, "rect"),
    (make_zenith_plot, "polygon"),
    (make_optic_plot, "polygon"),
])
def test_plot_metadata_has_final_clip_and_axes_geometry(plot_factory, expected_kind):
    plot = plot_factory()
    plot._record_plot_info()
    info = plot._recorder.projection_info
    assert info["plot_kind"] in {"map", "horizon", "zenith", "optic"}
    assert info["axes_pixels"][0] > 0 and info["axes_pixels"][1] > 0
    clip = info["clip_geometries"]["plot"]
    assert clip.kind == expected_kind
    assert len(clip.points) >= (4 if expected_kind == "rect" else 64)
    assert all(math.isfinite(v) for point in clip.points for v in point)


# ------------------------------------------------------------------
# Task 3: Final-artist geometry parity
# ------------------------------------------------------------------

@pytest.mark.parametrize("plot_factory", [
    make_map_plot, make_horizon_plot, make_zenith_plot, make_optic_plot,
])
def test_recorded_marker_matches_matplotlib_artist_data_coordinate(plot_factory):
    plot = plot_factory()
    plot.marker(ra=90.0, dec=10.0, label="probe",
                skip_bounds_check=True, style__marker__symbol="circle")
    command = next(c for c in plot._recorder.commands if c.gid == "marker")
    # Extract the artist's final DATA coordinates by transforming its
    # offsets through the collection transform and inverse transData.
    coll = plot.ax.collections[-1]
    raw_offsets = coll.get_offsets()
    display = coll.get_transform().transform(raw_offsets)
    data_coords = plot.ax.transData.inverted().transform(display)
    expected = data_coords[0]
    assert command.space.value == "data"
    assert command.data["x"] == pytest.approx([expected[0]])
    assert command.data["y"] == pytest.approx([expected[1]])


def test_renderer_contains_no_coordinate_transform_calls():
    from pathlib import Path
    source = Path("src/starplot/interactive/plotly_renderer.py").read_text()
    assert "transform_point(" not in source
    assert "_prepare_coords(" not in source
