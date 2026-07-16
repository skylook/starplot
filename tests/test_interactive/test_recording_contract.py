"""Tests for the typed recording contract: CoordinateSpace, ClipGeometry,
DrawingCommand.space, and DrawingCommand.clip_id."""

import math
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from starplot.interactive.commands import CommandType, CoordinateSpace, DrawingCommand
from starplot.interactive.recorder import DrawingRecorder


def test_matplotlib_color_serialization_preserves_transparent_edges():
    from starplot.interactive.recording_mixin import _rgba_to_hex

    assert _rgba_to_hex((0.0, 0.0, 0.0, 0.0)) == "rgba(0,0,0,0)"
    assert _rgba_to_hex((1.0, 0.0, 0.0, 0.5)) == "rgba(255,0,0,0.5)"


def test_artist_offset_extraction_uses_collection_offset_transform():
    """Scatter offsets live in the offset transform, not marker-path transform."""
    import matplotlib.pyplot as plt
    from types import SimpleNamespace
    from starplot.interactive.recording_mixin import RecordingMixin

    fig, ax = plt.subplots()
    collection = ax.scatter([12.0], [34.0], transform=ax.transData)
    expected = ax.transData.inverted().transform(
        collection.get_offset_transform().transform(collection.get_offsets())
    )[0]

    xs, ys = RecordingMixin._artist_offsets_to_final_data(
        SimpleNamespace(ax=ax), collection
    )

    assert xs == pytest.approx([expected[0]])
    assert ys == pytest.approx([expected[1]])
    plt.close(fig)


def test_transformed_path_segments_preserves_matplotlib_moveto_boundaries():
    """Independent rendered subpaths must never become a Plotly bridge."""
    import matplotlib.pyplot as plt
    from matplotlib.path import Path
    from starplot.interactive.recording_mixin import _transformed_path_segments

    fig, ax = plt.subplots()
    vertices = [(0, 0), (1, 0), (10, 0), (11, 0)]
    codes = [Path.MOVETO, Path.LINETO, Path.MOVETO, Path.LINETO]

    segments = _transformed_path_segments(ax, ax.transData, vertices, codes)

    assert len(segments) == 2
    assert segments[0] == pytest.approx([(0, 0), (1, 0)])
    assert segments[1] == pytest.approx([(10, 0), (11, 0)])
    plt.close(fig)


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


@pytest.mark.parametrize("kind", list(CommandType))
def test_command_normalizes_every_supported_kind_to_string_compatible_enum(kind):
    command = DrawingCommand(kind=kind.value)

    assert command.kind is kind
    assert command.kind == kind.value


def test_command_rejects_unknown_primitive_kind():
    with pytest.raises(ValueError, match="Unknown command type"):
        DrawingCommand(kind="heatmap")


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


def make_mollweide_plot():
    from starplot.interactive import InteractiveMapPlot
    from starplot import Mollweide
    return InteractiveMapPlot(projection=Mollweide(), resolution=512)


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


def test_map_clip_uses_final_curved_projection_boundary():
    plot = make_mollweide_plot()
    plot._record_plot_info()

    clip = plot._recorder.projection_info["clip_geometries"]["plot"]

    assert clip.kind == "polygon"
    assert len(clip.points) > 20
    assert max(x for x, _ in clip.points) == pytest.approx(plot.ax.get_xlim()[1])
    assert min(y for _, y in clip.points) == pytest.approx(plot.ax.get_ylim()[0])


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


# ------------------------------------------------------------------
# Task 5: Final label placement and style
# ------------------------------------------------------------------

def test_text_command_preserves_offset_and_rotation():
    plot = make_horizon_plot()
    plot._text(380.0, 30.0, "Probe", xytext=(12, -8), rotation=15, gid="probe")
    command = next(c for c in plot._recorder.commands if c.gid == "probe")
    assert command.data["offset_points"] == (12.0, -8.0)
    assert command.style["rotation"] == 15.0
    assert command.space.value == "data"


def test_horizon_gridlines_record_the_final_gridliner_segments():
    """The interactive grid must use Cartopy's rendered -180° azimuth geometry."""
    plot = make_horizon_plot()
    plot.gridlines(
        alt_locations=[30, 40, 50],
        az_locations=[330, 345, 0, 15, 30, 45, 60, 75],
    )
    plot.fig.canvas.draw()
    gridliner = next(artist for artist in plot.ax.artists
                     if type(artist).__name__ == "Gridliner")
    collection = gridliner.xline_artists[0]
    source_segment = collection.get_segments()[0]
    display = collection.get_transform().transform(source_segment)
    expected = plot.ax.transData.inverted().transform(display)

    command = next(c for c in plot._recorder.commands if c.gid == "gridlines")
    assert command.data["lines"][0] == pytest.approx(expected.tolist())


def test_constellation_borders_keeps_base_default_catalog():
    """Omitting catalog must retain the base plotter's default catalog."""
    plot = make_map_plot()
    plot.constellation_borders()
    assert any(c.gid == "constellations-border" for c in plot._recorder.commands)


def test_reference_lines_record_final_matplotlib_dash_and_width():
    plot = make_zenith_plot()

    lines_before = len(plot.ax.lines)
    plot.ecliptic()
    ecliptic_artist = plot.ax.lines[lines_before]
    ecliptic_command = next(
        c for c in plot._recorder.commands if c.gid == "ecliptic-line"
    )

    lines_before = len(plot.ax.lines)
    plot.celestial_equator()
    equator_artist = plot.ax.lines[lines_before]
    equator_command = next(
        c for c in plot._recorder.commands if c.gid == "celestial-equator-line"
    )

    assert ecliptic_command.style["line_style"] == ecliptic_artist.get_linestyle()
    assert ecliptic_command.style["width"] == pytest.approx(
        ecliptic_artist.get_linewidth()
    )
    assert equator_command.style["line_style"] == equator_artist.get_linestyle()
    assert equator_command.style["width"] == pytest.approx(
        equator_artist.get_linewidth()
    )


def test_title_records_final_artist_style_and_tight_bbox_gutter():
    plot = make_map_plot()
    plot.title("Probe")
    command = next(c for c in plot._recorder.commands if c.gid == "title")

    assert command.style["font_size"] == pytest.approx(plot.ax.title.get_fontsize())
    assert command.style["axes_domain_top"] < 1.0
    assert command.style["axes_domain_top"] < command.data["y"] <= 1.0


def test_zenith_horizon_uses_axes_circle_and_fixed_cardinal_positions():
    """ZenithPlot must not fall through to its MapPlot superclass branch."""
    plot = make_zenith_plot()
    plot.horizon()

    circle = next(c for c in plot._recorder.commands if c.gid == "horizon-circle")
    labels = [c for c in plot._recorder.commands if c.gid == "horizon-label"]
    xlim = plot.ax.get_xlim()
    ylim = plot.ax.get_ylim()
    expected_positions = [
        (xlim[0] + (xlim[1] - xlim[0]) * 0.5,
         ylim[0] + (ylim[1] - ylim[0]) * 0.95),
        (xlim[0] + (xlim[1] - xlim[0]) * 0.045,
         ylim[0] + (ylim[1] - ylim[0]) * 0.5),
        (xlim[0] + (xlim[1] - xlim[0]) * 0.5,
         ylim[0] + (ylim[1] - ylim[0]) * 0.045),
        (xlim[0] + (xlim[1] - xlim[0]) * 0.954,
         ylim[0] + (ylim[1] - ylim[0]) * 0.5),
    ]

    assert len(circle.data["x"]) == 100
    assert circle.clip_id is None
    assert circle.style["width"] == pytest.approx(
        plot.ax.patches[-1].get_linewidth()
    )
    assert [c.data["text"] for c in labels] == ["N", "E", "S", "W"]
    assert [c.style["font_size"] for c in labels] == pytest.approx(
        [artist.get_fontsize() for artist in plot.ax.texts[-4:]]
    )
    assert [(c.data["x"], c.data["y"]) for c in labels] == pytest.approx(
        expected_positions
    )


# ------------------------------------------------------------------
# Task 6: Magnitude scale and info recording
# ------------------------------------------------------------------

def test_magnitude_scale_and_zenith_info_are_recorded():
    plot = make_zenith_plot()
    plot.star_magnitude_scale()
    plot.info()
    assert any(c.gid == "star-magnitude-scale" for c in plot._recorder.commands)
    assert any(c.gid == "zenith-info" for c in plot._recorder.commands)
    assert plot._interactive_magnitude_scale["labels"] == [
        str(value) for value in range(-1, 9)
    ]
    assert len(plot._interactive_magnitude_scale["sizes"]) == 10
