"""Integration tests for Interactive*Plot classes."""

import pytest
import starplot.interactive.plots as interactive_plots

try:
    import plotly.graph_objects as go
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False

pytestmark = pytest.mark.skipif(not PLOTLY_AVAILABLE, reason="plotly not installed")


@pytest.fixture(autouse=True)
def _chdir(tmp_path, monkeypatch):
    """Run each test in ``tmp_path`` so relative export paths resolve there."""
    monkeypatch.chdir(tmp_path)


def _make_map_plot(**kwargs):
    from starplot.interactive import InteractiveMapPlot
    from starplot import Miller
    defaults = dict(
        projection=Miller(),
        ra_min=60, ra_max=120,
        dec_min=-10, dec_max=30,
        resolution=512,
    )
    defaults.update(kwargs)
    return InteractiveMapPlot(**defaults)


def test_interactive_map_plot_imports():
    from starplot.interactive import (
        InteractiveMapPlot, InteractiveZenithPlot,
        InteractiveHorizonPlot, InteractiveOpticPlot,
    )
    assert InteractiveMapPlot is not None
    assert InteractiveZenithPlot is not None
    assert InteractiveHorizonPlot is not None
    assert InteractiveOpticPlot is not None


def test_interactive_map_plot_creates():
    p = _make_map_plot()
    assert p is not None
    assert hasattr(p, "_recorder")
    assert hasattr(p, "export_html")
    assert hasattr(p, "to_plotly")


def test_recorder_initialized():
    p = _make_map_plot()
    assert p._recorder.commands == []
    p._record_plot_info()
    assert p._recorder.projection_info != {}
    assert "ra_min" in p._recorder.projection_info


def test_stars_records_scatter():
    from ibis import _ as ibis_col
    p = _make_map_plot()
    p.stars(where=[ibis_col.magnitude < 5])

    scatter_cmds = [c for c in p._recorder.commands if c.kind == "scatter"]
    assert len(scatter_cmds) >= 1


def test_stars_metadata():
    from ibis import _ as ibis_col
    p = _make_map_plot()
    p.stars(where=[ibis_col.magnitude < 5])

    scatter_cmds = [c for c in p._recorder.commands if c.kind == "scatter"]
    if scatter_cmds:
        meta = scatter_cmds[0].metadata
        assert len(meta) > 0
        assert meta[0].get("type") == "star"
        assert "magnitude" in meta[0]


def test_constellations_records_line_collection():
    p = _make_map_plot()
    p.constellations()

    line_cmds = [c for c in p._recorder.commands if c.kind == "line_collection"]
    assert len(line_cmds) >= 1
    total_lines = sum(len(c.data.get("lines", [])) for c in line_cmds)
    assert total_lines > 0


def test_line_accepts_public_nested_style_override():
    """RecordingMixin must preserve MapPlot.line's optional style contract."""
    from shapely import LineString

    p = _make_map_plot()
    p.line(
        geometry=LineString([(70, 0), (80, 10)]),
        style__line=p.style.constellation_borders,
    )

    line_commands = [
        command for command in p._recorder.commands
        if command.kind == "line_collection"
    ]
    assert len(line_commands) == 1
    assert line_commands[0].style["line_style"] == "--"


def test_to_plotly_returns_figure():
    from ibis import _ as ibis_col
    p = _make_map_plot()
    p.stars(where=[ibis_col.magnitude < 5])

    fig = p.to_plotly()
    assert isinstance(fig, go.Figure)
    assert len(fig.data) > 0


def test_export_html_creates_file(tmp_path):
    from ibis import _ as ibis_col
    p = _make_map_plot()
    p.stars(where=[ibis_col.magnitude < 4])

    html_path = tmp_path / "test.html"
    p.export_html("test.html")

    assert html_path.exists()
    content = html_path.read_text(encoding="utf-8")
    assert "plotly" in content.lower()
    assert "<script" in content


def test_export_html_maps_legacy_inline_library_request(tmp_path):
    p = _make_map_plot()
    html_path = tmp_path / "legacy.html"
    with pytest.warns(DeprecationWarning, match="single-file"):
        result = p.export_html("legacy.html", include_plotlyjs=True)
    assert result.bundle_path is None
    assert 'id="starplot-manifest"' in html_path.read_text(encoding="utf-8")


def test_export_html_maps_legacy_cdn_library_request(monkeypatch):
    p = _make_map_plot()
    captured = {}
    monkeypatch.setattr(p, "_compile_scene", lambda **kwargs: object())
    monkeypatch.setattr(
        interactive_plots,
        "export_scene_html",
        lambda scene, filename, **kwargs: captured.update(kwargs),
    )
    with pytest.warns(DeprecationWarning, match="include_plotlyjs"):
        p.export_html("legacy.html", include_plotlyjs="cdn")
    assert captured["library_mode"] == "cdn"
    assert captured["data_mode"] == "external"


def test_export_html_rejects_legacy_false_without_no_library_mode(monkeypatch):
    p = _make_map_plot()
    monkeypatch.setattr(p, "_compile_scene", lambda **kwargs: object())
    monkeypatch.setattr(
        interactive_plots,
        "export_scene_html",
        lambda scene, filename, **kwargs: None,
    )

    with pytest.raises(ValueError, match="no-library mode"):
        p.export_html("legacy.html", include_plotlyjs=False)


def test_export_html_maps_legacy_directory_library_request(monkeypatch):
    p = _make_map_plot()
    captured = {}
    monkeypatch.setattr(p, "_compile_scene", lambda **kwargs: object())
    monkeypatch.setattr(
        interactive_plots,
        "export_scene_html",
        lambda scene, filename, **kwargs: captured.update(kwargs),
    )
    with pytest.warns(DeprecationWarning, match="include_plotlyjs"):
        p.export_html("legacy.html", include_plotlyjs="directory")
    assert captured["library_mode"] == "directory"
    assert captured["data_mode"] == "external"


def test_export_html_maps_legacy_inline_string_to_single_file(monkeypatch):
    p = _make_map_plot()
    captured = {}
    monkeypatch.setattr(p, "_compile_scene", lambda **kwargs: object())
    monkeypatch.setattr(
        interactive_plots,
        "export_scene_html",
        lambda scene, filename, **kwargs: captured.update(kwargs),
    )
    with pytest.warns(DeprecationWarning, match="include_plotlyjs"):
        p.export_html("legacy.html", include_plotlyjs="inline")
    assert captured["library_mode"] == "inline"
    assert captured["data_mode"] == "inline"


def test_export_html_rejects_unsupported_legacy_library_request():
    p = _make_map_plot()
    with pytest.raises(ValueError, match="include_plotlyjs"):
        p.export_html("legacy.html", include_plotlyjs="/custom/plotly.js")


def test_export_html_rejects_conflicting_library_options():
    p = _make_map_plot()
    with pytest.raises(ValueError, match="conflicts"):
        p.export_html(
            "legacy.html", include_plotlyjs="cdn", library_mode="directory"
        )


def test_matplotlib_output_unchanged():
    """RecordingMixin must not change the matplotlib rendering output."""
    from starplot import MapPlot, Miller
    from starplot.interactive import InteractiveMapPlot
    from ibis import _ as ibis_col

    kwargs = dict(projection=Miller(), ra_min=60, ra_max=120,
                  dec_min=-10, dec_max=30, resolution=512)

    p1 = MapPlot(**kwargs)
    p1.stars(where=[ibis_col.magnitude < 5])

    p2 = InteractiveMapPlot(**kwargs)
    p2.stars(where=[ibis_col.magnitude < 5])

    # Same number of stars plotted
    assert len(p1.objects.stars) == len(p2.objects.stars)
    # Same HIP IDs
    assert set(s.hip for s in p1.objects.stars) == set(s.hip for s in p2.objects.stars)


def test_stars_count_matches_recorded():
    """Number of recorded star points must match number of plotted stars."""
    from ibis import _ as ibis_col
    p = _make_map_plot()
    p.stars(where=[ibis_col.magnitude < 6])

    scatter_cmds = [c for c in p._recorder.commands if c.kind == "scatter" and c.gid == "stars"]
    total_recorded = sum(len(c.data.get("x", [])) for c in scatter_cmds)
    assert total_recorded == len(p.objects.stars)


def test_style_info_recorded():
    p = _make_map_plot()
    p._record_plot_info()
    assert "background_color" in p._recorder.style_info
    assert "resolution" in p._recorder.style_info


def test_ecliptic_records_line():
    p = _make_map_plot()
    p.ecliptic()

    line_cmds = [c for c in p._recorder.commands if c.gid == "ecliptic-line"]
    assert len(line_cmds) == 1
    # line_collection commands store segments under "lines"
    segments = line_cmds[0].data["lines"]
    assert len(segments) >= 1
    assert len(segments[0]) > 10


def test_celestial_equator_records_line():
    p = _make_map_plot()
    p.celestial_equator()

    line_cmds = [c for c in p._recorder.commands
                 if c.gid == "celestial-equator-line"]
    assert len(line_cmds) == 1
    segments = line_cmds[0].data["lines"]
    assert len(segments) >= 1
    assert len(segments[0]) > 10


def test_text_labels_recorded():
    from ibis import _ as ibis_col
    p = _make_map_plot()
    p.stars(where=[ibis_col.magnitude < 5], where_labels=[ibis_col.magnitude < 3])

    text_cmds = [c for c in p._recorder.commands if c.kind == "text"]
    # Labels that survive collision detection should be recorded with text content
    for cmd in text_cmds:
        assert cmd.data.get("text", "") != "", "Recorded text label must have non-empty text"
        assert "x" in cmd.data and "y" in cmd.data, "Text label must have coordinates"


def test_marker_records_scatter():
    p = _make_map_plot()
    p.marker(
        ra=90,
        dec=10,
        style={"marker": {"symbol": "circle", "size": 20, "color": "#ff0000"}},
    )

    scatter_cmds = [c for c in p._recorder.commands if c.kind == "scatter" and c.gid == "marker"]
    assert len(scatter_cmds) == 1
    assert len(scatter_cmds[0].data["x"]) == 1
    assert scatter_cmds[0].style.get("legend_label") is None


def test_marker_records_legend_label():
    p = _make_map_plot()
    p.marker(
        ra=90,
        dec=10,
        style={"marker": {"symbol": "circle", "size": 20, "color": "#ff0000"}},
        legend_label="Target",
    )

    scatter_cmds = [c for c in p._recorder.commands if c.kind == "scatter" and c.gid == "marker"]
    assert len(scatter_cmds) == 1
    assert scatter_cmds[0].style.get("legend_label") == "Target"


def test_gridlines_records_line_collection():
    p = _make_map_plot()
    p.gridlines()

    line_cmds = [c for c in p._recorder.commands if c.kind == "line_collection" and c.gid == "gridlines"]
    assert len(line_cmds) >= 1
    assert len(line_cmds[0].data["lines"]) > 0


def test_title_records_text():
    p = _make_map_plot()
    p.title("Test Title")

    text_cmds = [c for c in p._recorder.commands if c.kind == "text" and c.gid == "title"]
    assert len(text_cmds) == 1
    assert text_cmds[0].data["text"] == "Test Title"
    assert text_cmds[0].style.get("xref") == "paper"
    assert text_cmds[0].style.get("yref") == "paper"


def test_legend_records_style_info():
    p = _make_map_plot()
    p.marker(ra=90, dec=10, style={"marker": {"symbol": "circle", "size": 20, "color": "#ff0000"}}, legend_label="Target")
    p.legend(title="My Legend")

    assert p._recorder.style_info.get("show_legend") is True
    assert p._recorder.style_info.get("legend_title") == "My Legend"


def test_constellation_borders_records_line_collection():
    p = _make_map_plot()
    p.constellation_borders()

    line_cmds = [c for c in p._recorder.commands if c.kind == "line_collection" and c.gid == "constellations-border"]
    assert len(line_cmds) >= 1
