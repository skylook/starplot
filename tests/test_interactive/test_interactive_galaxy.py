"""GalaxyPlot's Galactic projection must survive interactive export."""

import pytest


def test_interactive_galaxy_is_exported():
    import starplot.interactive as interactive

    assert hasattr(interactive, "InteractiveGalaxyPlot")


@pytest.fixture
def plot():
    import starplot.interactive as interactive

    if not hasattr(interactive, "InteractiveGalaxyPlot"):
        pytest.skip("InteractiveGalaxyPlot not implemented yet")
    return interactive.InteractiveGalaxyPlot(resolution=512)


def test_galaxy_plot_exposes_interactive_api(plot):
    from starplot.plots.galaxy import GalaxyPlot

    assert isinstance(plot, GalaxyPlot)
    assert callable(plot.to_plotly)
    assert callable(plot.export_html)


def test_radec_coordinates_use_galactic_projection(plot):
    ra, dec = 80.0, -20.0
    lon, lat = plot._prepare_coords(ra, dec)
    expected = plot._proj.transform_point(lon, lat, plot._crs)

    assert plot._to_final_data(ra, dec, "radec") == pytest.approx(expected)


def test_galaxy_gridlines_are_recorded(plot):
    plot.gridlines()

    commands = [command for command in plot._recorder.commands if command.gid == "gridlines"]
    assert commands
    assert any(command.kind == "line_collection" for command in commands)


def test_galaxy_ecliptic_preserves_num_labels_option(plot):
    plot.ecliptic(num_labels=2)


def test_galactic_equator_records_rendered_labels(plot):
    plot.galactic_equator(num_labels=2)

    labels = [command for command in plot._recorder.commands
              if command.gid == "galactic-equator-label"]
    rendered = [artist for artist in plot.ax.texts
                if artist.get_text() == "GALACTIC EQUATOR"
                and artist.get_transform() == plot.ax.transAxes]
    assert len(labels) == len(rendered) > 0


def test_galaxy_legend_geometry_is_preserved_for_both_adapters(plot):
    plot.marker(ra=266.4, dec=-29.0, legend_label="Center")
    plot.legend()

    scene = plot._compile_scene()
    geometry = scene.viewport.get("legend_position")
    assert geometry is not None
    assert geometry["xanchor"] == "right"
    assert geometry["yanchor"] == "top"

    legend = plot.to_plotly().layout.legend
    assert legend.orientation == geometry["orientation"]
    assert legend.xanchor == "right"
    assert legend.yanchor == "top"
    assert legend.x == pytest.approx(geometry["x"])
    assert legend.y == pytest.approx(geometry["y"])
    assert 0 < legend.x < 1.1
    assert -0.1 < legend.y < 1.1


def test_galaxy_scene_and_plotly_export(plot, tmp_path):
    plot.text("Galactic center", ra=266.4, dec=-29.0)

    scene = plot._compile_scene()
    assert scene.projection_info["plot_kind"] == "galaxy"
    assert any(annotation.text == "Galactic center" for annotation in plot.to_plotly().layout.annotations)

    result = plot.export_html(tmp_path / "galaxy.html")
    assert result.html_path.exists()
