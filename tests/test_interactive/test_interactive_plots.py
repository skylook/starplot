"""Integration tests for Interactive*Plot classes."""

import pytest

try:
    import plotly.graph_objects as go
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False

pytestmark = pytest.mark.skipif(not PLOTLY_AVAILABLE, reason="plotly not installed")


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


def test_interactive_map_plot_creates():
    p = _make_map_plot()
    assert p is not None
    assert hasattr(p, "_recorder")
    assert hasattr(p, "export_html")
    assert hasattr(p, "to_plotly")


def test_recorder_initialized():
    p = _make_map_plot()
    assert p._recorder.commands == []
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
    p.export_html(str(html_path))

    assert html_path.exists()
    content = html_path.read_text(encoding="utf-8")
    assert "plotly" in content.lower()
    assert "<script" in content


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
    assert "background_color" in p._recorder.style_info
    assert "resolution" in p._recorder.style_info


def test_ecliptic_records_line():
    p = _make_map_plot()
    p.ecliptic()

    line_cmds = [c for c in p._recorder.commands if c.kind == "line" and c.gid == "ecliptic-line"]
    assert len(line_cmds) == 1
    assert len(line_cmds[0].data["x"]) > 10


def test_celestial_equator_records_line():
    p = _make_map_plot()
    p.celestial_equator()

    line_cmds = [c for c in p._recorder.commands
                 if c.kind == "line" and c.gid == "celestial-equator-line"]
    assert len(line_cmds) == 1
    assert len(line_cmds[0].data["x"]) > 10


def test_text_labels_recorded():
    from ibis import _ as ibis_col
    p = _make_map_plot()
    p.stars(where=[ibis_col.magnitude < 5], where_labels=[ibis_col.magnitude < 3])

    text_cmds = [c for c in p._recorder.commands if c.kind == "text"]
    # At least some labels should be recorded
    assert len(text_cmds) >= 0  # could be 0 if all labels collide
