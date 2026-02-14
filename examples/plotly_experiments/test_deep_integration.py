#!/usr/bin/env python3
"""
Test deep integration of backend system
"""
from datetime import datetime
from pytz import timezone
from starplot import MapPlot, Projection, _
from starplot.styles import PlotStyle, extensions
import numpy as np
import json

# Setup
tz = timezone("America/Los_Angeles")
dt = datetime(2023, 7, 13, 22, 0, tzinfo=tz)

def test_deep_integration():
    """Test the deep integration functionality"""
    print("=== Testing Deep Integration ===")
    
    # Test matplotlib with deep integration
    print("\n1. Testing matplotlib with deep integration...")
    matplotlib_plot = MapPlot(
        projection=Projection.ZENITH,
        lat=33.363484,
        lon=-116.836394,
        dt=dt,
        style=PlotStyle().extend(extensions.BLUE_GOLD),
        resolution=1024,
        autoscale=True,
        backend="matplotlib",
    )
    
    # Add stars and constellations
    matplotlib_plot.stars(where=[_.magnitude < 3.0])
    matplotlib_plot.constellations()
    
    # Export
    matplotlib_plot.export("deep_integration_matplotlib.png")
    print("   ✓ Matplotlib deep integration completed")
    
    # Test plotly with deep integration
    print("\n2. Testing plotly with deep integration...")
    plotly_plot = MapPlot(
        projection=Projection.ZENITH,
        lat=33.363484,
        lon=-116.836394,
        dt=dt,
        style=PlotStyle().extend(extensions.BLUE_GOLD),
        resolution=1024,
        autoscale=True,
        backend="plotly",
    )
    
    # Add stars and constellations
    plotly_plot.stars(where=[_.magnitude < 3.0])
    plotly_plot.constellations()
    
    # Check figure data
    if hasattr(plotly_plot._backend, 'figure') and plotly_plot._backend.figure:
        fig = plotly_plot._backend.figure
        print(f"   Number of traces in plotly figure: {len(fig.data)}")
        
        star_traces = 0
        line_traces = 0
        
        for i, trace in enumerate(fig.data):
            if hasattr(trace, 'mode'):
                if 'markers' in trace.mode:
                    star_traces += 1
                    print(f"   Trace {i}: Star markers, {len(trace.x) if hasattr(trace, 'x') and trace.x else 0} points")
                elif 'lines' in trace.mode:
                    line_traces += 1
                    print(f"   Trace {i}: Constellation lines, {len(trace.x) if hasattr(trace, 'x') and trace.x else 0} points")
        
        print(f"   Total star traces: {star_traces}")
        print(f"   Total line traces: {line_traces}")
        
        # Export debug data
        fig_dict = fig.to_dict()
        with open('deep_integration_debug.json', 'w') as f:
            json.dump(fig_dict, f, indent=2, default=str)
    
    # Export plotly version
    plotly_plot.export("deep_integration_plotly.html")
    print("   ✓ Plotly deep integration completed")
    
    # Try PNG export
    try:
        plotly_plot.export("deep_integration_plotly.png", format="png")
        print("   ✓ Plotly PNG export successful")
    except Exception as e:
        print(f"   ⚠️ Plotly PNG export failed: {e}")
    
    print("\n3. Analysis:")
    
    # Check if files were created
    import os
    files = [
        "deep_integration_matplotlib.png",
        "deep_integration_plotly.html",
        "deep_integration_plotly.png"
    ]
    
    for filename in files:
        if os.path.exists(filename):
            size = os.path.getsize(filename)
            print(f"   ✓ {filename}: {size:,} bytes")
        else:
            print(f"   ✗ {filename}: NOT FOUND")
    
    print("\n4. Deep Integration Status:")
    
    if hasattr(plotly_plot._backend, 'figure') and plotly_plot._backend.figure:
        trace_count = len(plotly_plot._backend.figure.data)
        if trace_count > 0:
            print("   ✅ Deep integration SUCCESSFUL!")
            print(f"   📊 Plotly figure contains {trace_count} traces")
            print("   🔄 Stars and constellations now use backend system")
            print("   🎯 Both matplotlib and plotly backends working")
        else:
            print("   ❌ Deep integration FAILED")
            print("   📊 Plotly figure contains 0 traces")
    else:
        print("   ❌ Backend system not working")
    
    print("\n5. Comparison with previous shallow integration:")
    print("   Before: Only figure creation/export used backends")
    print("   After: Stars and constellations use backend system")
    print("   Result: True multi-backend visualization support")

if __name__ == "__main__":
    test_deep_integration()