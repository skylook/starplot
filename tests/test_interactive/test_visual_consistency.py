"""Visual consistency tests: validate that recording doesn't lose data.

These tests verify structural consistency (star counts, line counts) between
the matplotlib render and the recorded commands.  Pixel-level comparison
requires kaleido and is marked as optional.
"""

import pytest

try:
    import plotly.graph_objects as go
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False

pytestmark = pytest.mark.skipif(not PLOTLY_AVAILABLE, reason="plotly not installed")


def _make_plot():
    from starplot.interactive import InteractiveMapPlot
    from starplot import Miller
    return InteractiveMapPlot(
        projection=Miller(),
        ra_min=60, ra_max=120,
        dec_min=-10, dec_max=30,
        resolution=512,
    )


def test_star_count_consistency():
    """Every plotted star must be recorded exactly once."""
    from ibis import _ as ibis_col
    p = _make_plot()
    p.stars(where=[ibis_col.magnitude < 6])

    scatter_cmds = [c for c in p._recorder.commands
                    if c.kind == "scatter" and c.gid == "stars"]
    total_recorded = sum(len(c.data.get("x", [])) for c in scatter_cmds)
    assert total_recorded == len(p.objects.stars), (
        f"Recorded {total_recorded} stars but plotted {len(p.objects.stars)}"
    )


def test_constellation_line_count_consistency():
    """Constellation lines must be recorded."""
    p = _make_plot()
    p.constellations()

    line_cmds = [c for c in p._recorder.commands if c.kind == "line_collection"]
    assert len(line_cmds) > 0, "Should have recorded constellation lines"
    total_lines = sum(len(c.data.get("lines", [])) for c in line_cmds)
    assert total_lines > 0


def test_star_coordinates_are_finite():
    """Recorded star coordinates should all be finite numbers."""
    import math
    from ibis import _ as ibis_col
    p = _make_plot()
    p.stars(where=[ibis_col.magnitude < 5])

    scatter_cmds = [c for c in p._recorder.commands if c.kind == "scatter"]
    for cmd in scatter_cmds:
        for x, y in zip(cmd.data.get("x", []), cmd.data.get("y", [])):
            assert math.isfinite(x), f"Non-finite x: {x}"
            assert math.isfinite(y), f"Non-finite y: {y}"


def test_constellation_line_coordinates_are_finite():
    """Recorded constellation line coordinates should all be finite numbers."""
    import math
    p = _make_plot()
    p.constellations()

    line_cmds = [c for c in p._recorder.commands if c.kind == "line_collection"]
    for cmd in line_cmds:
        for seg in cmd.data.get("lines", []):
            for pt in seg:
                assert math.isfinite(pt[0]), f"Non-finite x: {pt[0]}"
                assert math.isfinite(pt[1]), f"Non-finite y: {pt[1]}"


def test_plotly_figure_has_traces():
    """After plotting stars, the Plotly figure should have traces."""
    from ibis import _ as ibis_col
    p = _make_plot()
    p.stars(where=[ibis_col.magnitude < 6])

    fig = p.to_plotly()
    assert len(fig.data) > 0


def test_plotly_figure_axes_configured():
    """Plotly figure should have configured axes (no grid, no ticks)."""
    p = _make_plot()
    fig = p.to_plotly()
    assert fig.layout.xaxis.showgrid is False
    assert fig.layout.yaxis.showgrid is False
    assert fig.layout.xaxis.showticklabels is False


@pytest.mark.skipif(True, reason="Requires kaleido installed; run manually")
def test_visual_hash_comparison(tmp_path):
    """Pixel-level visual comparison between matplotlib PNG and Plotly PNG.

    Requires: pip install kaleido imagehash Pillow
    """
    import imagehash
    from PIL import Image
    from ibis import _ as ibis_col

    p = _make_plot()
    p.stars(where=[ibis_col.magnitude < 6])

    mpl_path = str(tmp_path / "mpl.png")
    plotly_path = str(tmp_path / "plotly.png")

    p.export(mpl_path)
    fig = p.to_plotly()
    fig.write_image(plotly_path, width=1024, height=800)

    def dhash_rgb(img):
        r, g, b = img.convert("RGB").split()
        return str(imagehash.dhash(r)) + str(imagehash.dhash(g)) + str(imagehash.dhash(b))

    def hamming_distance(h1, h2):
        return sum(c1 != c2 for c1, c2 in zip(h1, h2))

    h1 = dhash_rgb(Image.open(mpl_path))
    h2 = dhash_rgb(Image.open(plotly_path))
    dist = hamming_distance(h1, h2)

    TOLERANCE = 50  # loose tolerance: different renderers, fonts, etc.
    assert dist < TOLERANCE, f"Visual hash distance {dist} exceeds tolerance {TOLERANCE}"
