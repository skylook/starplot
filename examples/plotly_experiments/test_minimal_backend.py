#!/usr/bin/env python3
"""
Minimal backend test
"""
from datetime import datetime
from pytz import timezone
from starplot import MapPlot, Projection, _
from starplot.styles import PlotStyle, extensions

# Setup
tz = timezone("America/Los_Angeles")
dt = datetime(2023, 7, 13, 22, 0, tzinfo=tz)

def test_minimal_backend():
    """Minimal backend test"""
    print("=== Minimal Backend Test ===")
    
    try:
        # Test plotly backend creation
        print("\n1. Creating plotly plot...")
        plotly_plot = MapPlot(
            projection=Projection.ZENITH,
            lat=33.363484,
            lon=-116.836394,
            dt=dt,
            style=PlotStyle().extend(extensions.BLUE_GOLD),
            resolution=512,  # Lower resolution for speed
            autoscale=True,
            backend="plotly",
        )
        print("   ✓ Plot created")
        
        # Check backend
        print(f"   Backend: {type(plotly_plot._backend)}")
        print(f"   Has figure: {hasattr(plotly_plot._backend, 'figure')}")
        
        # Test basic export
        print("\n2. Testing basic export...")
        plotly_plot.export("minimal_test.html")
        print("   ✓ Export successful")
        
        # Test backend scatter directly
        print("\n3. Testing backend scatter directly...")
        import numpy as np
        test_x = np.array([10, 20, 30])
        test_y = np.array([10, 20, 30])
        test_sizes = np.array([5, 10, 15])
        
        plotly_plot._backend.scatter(test_x, test_y, sizes=test_sizes, colors='red')
        print("   ✓ Direct scatter successful")
        
        # Check traces
        if hasattr(plotly_plot._backend, 'figure'):
            traces = len(plotly_plot._backend.figure.data)
            print(f"   Traces created: {traces}")
        
        print("\n4. SUCCESS - Backend system working!")
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_minimal_backend()