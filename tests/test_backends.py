import pytest
import holoviews as hv
from starplot.backends import get_backend, register_backend, PlotBackend
from starplot.backends.holoviews_backend import HoloViewsBackend
from starplot.styles import (
    MarkerStyle,
    LineStyle,
    PolygonStyle,
    LabelStyle,
    MarkerSymbolEnum,
    LineStyleEnum,
)
from starplot.projections import Projection

def test_backend_registration():
    # Test that HoloViews backend is registered
    backend_class = get_backend('holoviews')
    assert backend_class == HoloViewsBackend
    
    # Test invalid backend name
    with pytest.raises(ValueError):
        get_backend('invalid_backend')

def test_holoviews_backend_initialization():
    backend = HoloViewsBackend()
    backend.initialize(dpi=100, scale=1.0)
    assert backend.dpi == 100
    assert backend.scale == 1.0
    assert backend.backend == 'matplotlib'
    assert isinstance(backend.overlay, hv.Overlay)

def test_holoviews_style_conversion():
    backend = HoloViewsBackend()
    backend.initialize()
    
    # Test marker style conversion
    marker_style = MarkerStyle(
        symbol=MarkerSymbolEnum.CIRCLE,
        size=20,
        color="#ff0000",
        edge_color="#000000",
        edge_width=2,
        alpha=0.5,
    )
    hv_style = marker_style.holoviews_kwargs(scale=1.0)
    assert hv_style['marker'] == 'o'
    assert hv_style['size'] == 20
    assert hv_style['color'] == '#ff0000'
    assert hv_style['edge_color'] == '#000000'
    assert hv_style['edge_line_width'] == 2
    assert hv_style['alpha'] == 0.5
    
    # Test line style conversion
    line_style = LineStyle(
        color="#0000ff",
        width=2,
        style=LineStyleEnum.DASHED,
        alpha=0.8,
    )
    hv_style = line_style.holoviews_kwargs(scale=1.0)
    assert hv_style['color'] == '#0000ff'
    assert hv_style['line_width'] == 2
    assert hv_style['line_dash'] == '--'
    assert hv_style['alpha'] == 0.8

def test_holoviews_plotting():
    backend = HoloViewsBackend()
    backend.initialize()
    
    # Test marker plotting
    marker = backend.marker(0, 0, marker='o', size=10, color='red')
    assert isinstance(marker, hv.Scatter)
    
    # Test line plotting
    line = backend.plot([0, 1], [0, 1], color='blue', line_width=2)
    assert isinstance(line, hv.Curve)
    
    # Test text plotting
    text = backend.text(0, 0, "Test", color='black', text_font_size='12pt')
    assert isinstance(text, hv.Text)
    
    # Test polygon plotting
    polygon = backend.polygon([(0,0), (1,0), (1,1), (0,1)], fill_color='green')
    assert isinstance(polygon, hv.Polygons)

def test_holoviews_export(tmp_path):
    backend = HoloViewsBackend()
    backend.initialize()
    
    # Create a simple plot
    backend.marker(0, 0, marker='o', size=10, color='red')
    
    # Test PNG export
    png_file = tmp_path / "test.png"
    backend.export(str(png_file), format="png")
    assert png_file.exists()
    
    # Test SVG export
    svg_file = tmp_path / "test.svg"
    backend.export(str(svg_file), format="svg")
    assert svg_file.exists() 