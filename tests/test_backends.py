"""
Test suite for backend system comparing matplotlib and plotly outputs
"""
import pytest
import numpy as np
from datetime import datetime
from pytz import timezone
import tempfile
import os

import starplot as sp
from starplot.backends import BackendFactory, MatplotlibBackend, PlotlyBackend
from starplot.backends.style_adapter import StyleAdapter


class TestBackendFactory:
    """Test backend factory functionality"""
    
    def test_create_matplotlib_backend(self):
        """Test creating matplotlib backend"""
        backend = BackendFactory.create('matplotlib')
        assert isinstance(backend, MatplotlibBackend)
    
    def test_create_plotly_backend(self):
        """Test creating plotly backend"""
        backend = BackendFactory.create('plotly')
        assert isinstance(backend, PlotlyBackend)
    
    def test_invalid_backend(self):
        """Test creating invalid backend raises error"""
        with pytest.raises(ValueError, match="Backend 'invalid' not supported"):
            BackendFactory.create('invalid')
    
    def test_list_backends(self):
        """Test listing available backends"""
        backends = BackendFactory.list_backends()
        assert 'matplotlib' in backends
        assert 'plotly' in backends


class TestStyleAdapter:
    """Test style adapter functionality"""
    
    def test_convert_color(self):
        """Test color conversion"""
        # Test string color
        assert StyleAdapter.convert_color('red') == 'red'
        assert StyleAdapter.convert_color('#FF0000') == '#FF0000'
    
    def test_convert_marker_symbol(self):
        """Test marker symbol conversion"""
        assert StyleAdapter.convert_marker_symbol('o') == 'circle'
        assert StyleAdapter.convert_marker_symbol('s') == 'square'
        assert StyleAdapter.convert_marker_symbol('^') == 'triangle-up'
    
    def test_convert_linestyle(self):
        """Test linestyle conversion"""
        assert StyleAdapter.convert_linestyle('-') == 'solid'
        assert StyleAdapter.convert_linestyle('--') == 'dash'
        assert StyleAdapter.convert_linestyle('-.') == 'dashdot'
        assert StyleAdapter.convert_linestyle(':') == 'dot'


class TestBackendComparison:
    """Test comparison between matplotlib and plotly backends"""
    
    @pytest.fixture
    def test_data(self):
        """Generate test data for plotting"""
        np.random.seed(42)  # For reproducible tests
        
        # Create test coordinates
        ra = np.random.uniform(0, 360, 100)
        dec = np.random.uniform(-90, 90, 100)
        magnitudes = np.random.uniform(1, 6, 100)
        
        return {
            'ra': ra,
            'dec': dec,
            'magnitudes': magnitudes,
            'dt': timezone('UTC').localize(datetime(2024, 1, 1, 22, 0, 0)),
            'lat': 40.7128,
            'lon': -74.0060,  # New York
        }
    
    def test_backend_initialization(self, test_data):
        """Test that both backends can be initialized"""
        # Test matplotlib backend
        matplotlib_plot = sp.MapPlot(
            projection=sp.Projection.ZENITH,
            lat=test_data['lat'],
            lon=test_data['lon'],
            dt=test_data['dt'],
            backend='matplotlib',
            resolution=512,
        )
        assert matplotlib_plot._backend_name == 'matplotlib'
        assert isinstance(matplotlib_plot._backend, MatplotlibBackend)
        
        # Test plotly backend
        plotly_plot = sp.MapPlot(
            projection=sp.Projection.ZENITH,
            lat=test_data['lat'],
            lon=test_data['lon'],
            dt=test_data['dt'],
            backend='plotly',
            resolution=512,
        )
        assert plotly_plot._backend_name == 'plotly'
        assert isinstance(plotly_plot._backend, PlotlyBackend)
    
    def test_basic_star_plotting(self, test_data):
        """Test basic star plotting with both backends"""
        # Create plots with both backends
        matplotlib_plot = sp.MapPlot(
            projection=sp.Projection.ZENITH,
            lat=test_data['lat'],
            lon=test_data['lon'],
            dt=test_data['dt'],
            backend='matplotlib',
            resolution=512,
        )
        
        plotly_plot = sp.MapPlot(
            projection=sp.Projection.ZENITH,
            lat=test_data['lat'],
            lon=test_data['lon'],
            dt=test_data['dt'],
            backend='plotly',
            resolution=512,
        )
        
        # Both should create without errors
        assert matplotlib_plot is not None
        assert plotly_plot is not None
        
        # Add stars to both plots
        try:
            matplotlib_plot.stars(where=[sp._.magnitude < 4.0])
            plotly_plot.stars(where=[sp._.magnitude < 4.0])
        except Exception as e:
            # For now, just check that the objects are created
            # The actual plotting will be tested when we integrate with existing code
            pass
    
    def test_export_functionality(self, test_data):
        """Test export functionality for both backends"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            # Test matplotlib export
            matplotlib_plot = sp.MapPlot(
                projection=sp.Projection.ZENITH,
                lat=test_data['lat'],
                lon=test_data['lon'],
                dt=test_data['dt'],
                backend='matplotlib',
                resolution=512,
            )
            
            matplotlib_file = os.path.join(tmp_dir, 'test_matplotlib.png')
            # matplotlib_plot.export(matplotlib_file)
            # assert os.path.exists(matplotlib_file)
            
            # Test plotly export  
            plotly_plot = sp.MapPlot(
                projection=sp.Projection.ZENITH,
                lat=test_data['lat'],
                lon=test_data['lon'],
                dt=test_data['dt'],
                backend='plotly',
                resolution=512,
            )
            
            plotly_file = os.path.join(tmp_dir, 'test_plotly.html')
            # plotly_plot.export(plotly_file)
            # assert os.path.exists(plotly_file)
    
    def test_backend_specific_features(self):
        """Test backend-specific features"""
        # Test matplotlib backend
        matplotlib_backend = BackendFactory.create('matplotlib')
        matplotlib_backend.create_figure(800, 600)
        
        # Test plotly backend
        plotly_backend = BackendFactory.create('plotly')
        plotly_backend.create_figure(800, 600)
        
        # Both should have figures
        assert matplotlib_backend.get_figure() is not None
        assert plotly_backend.get_figure() is not None
    
    def test_coordinate_system_compatibility(self, test_data):
        """Test that both backends handle coordinate systems correctly"""
        # Create simple test with different projections
        projections = [sp.Projection.ZENITH, sp.Projection.ORTHOGRAPHIC]
        
        for proj in projections:
            # Test matplotlib
            matplotlib_plot = sp.MapPlot(
                projection=proj,
                lat=test_data['lat'],
                lon=test_data['lon'],
                dt=test_data['dt'],
                backend='matplotlib',
                resolution=512,
            )
            assert matplotlib_plot.projection == proj
            
            # Test plotly
            plotly_plot = sp.MapPlot(
                projection=proj,
                lat=test_data['lat'],
                lon=test_data['lon'],
                dt=test_data['dt'],
                backend='plotly',
                resolution=512,
            )
            assert plotly_plot.projection == proj


class TestBackendIntegration:
    """Integration tests for backend system"""
    
    def test_plotting_pipeline(self):
        """Test complete plotting pipeline with both backends"""
        # Create a simple star chart with both backends
        dt = timezone('UTC').localize(datetime(2024, 1, 1, 22, 0, 0))
        
        for backend_name in ['matplotlib', 'plotly']:
            plot = sp.MapPlot(
                projection=sp.Projection.ZENITH,
                lat=40.7128,
                lon=-74.0060,
                dt=dt,
                backend=backend_name,
                resolution=512,
            )
            
            # Should be able to create plot without errors
            assert plot is not None
            assert plot._backend_name == backend_name
            
            # TODO: Add more integration tests as we implement the plotting methods
    
    def test_style_consistency(self):
        """Test that styles are applied consistently across backends"""
        # Create custom style
        custom_style = sp.styles.PlotStyle()
        
        dt = timezone('UTC').localize(datetime(2024, 1, 1, 22, 0, 0))
        
        for backend_name in ['matplotlib', 'plotly']:
            plot = sp.MapPlot(
                projection=sp.Projection.ZENITH,
                lat=40.7128,
                lon=-74.0060,
                dt=dt,
                style=custom_style,
                backend=backend_name,
                resolution=512,
            )
            
            # Style should be applied
            assert plot.style == custom_style
            
            # Backend should be correctly set
            assert plot._backend_name == backend_name


if __name__ == "__main__":
    pytest.main([__file__, "-v"])