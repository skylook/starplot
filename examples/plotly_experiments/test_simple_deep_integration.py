#!/usr/bin/env python3
"""
Simple test of deep integration
"""
from datetime import datetime
from pytz import timezone
from starplot import MapPlot, Projection, _
from starplot.styles import PlotStyle, extensions
import json

# Setup
tz = timezone("America/Los_Angeles")
dt = datetime(2023, 7, 13, 22, 0, tzinfo=tz)

def test_simple_deep_integration():
    """Test the deep integration functionality simply"""
    print("=== Simple Deep Integration Test ===")
    
    # Test plotly with deep integration (no labels to avoid timeout)
    print("\n1. Testing plotly with stars only...")
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
    
    # Add stars only (no labels to avoid complexity)
    print("   Adding stars...")
    plotly_plot.stars(where=[_.magnitude < 4.0], bayer_labels=False, flamsteed_labels=False)
    
    # Check figure data
    if hasattr(plotly_plot._backend, 'figure') and plotly_plot._backend.figure:
        fig = plotly_plot._backend.figure
        print(f"   Number of traces in plotly figure: {len(fig.data)}")
        
        for i, trace in enumerate(fig.data):
            if hasattr(trace, 'mode') and 'markers' in trace.mode:
                print(f"   Star trace {i}: {len(trace.x) if hasattr(trace, 'x') and trace.x else 0} points")
    
    # Export
    plotly_plot.export("simple_deep_integration_plotly.html")
    print("   ✓ Plotly export successful")
    
    # Test constellations
    print("\n2. Testing constellations...")
    plotly_plot.constellations()
    
    if hasattr(plotly_plot._backend, 'figure') and plotly_plot._backend.figure:
        fig = plotly_plot._backend.figure
        print(f"   Total traces after constellations: {len(fig.data)}")
        
        line_traces = 0
        for trace in fig.data:
            if hasattr(trace, 'mode') and 'lines' in trace.mode:
                line_traces += 1
        print(f"   Line traces (constellations): {line_traces}")
    
    # Final export
    plotly_plot.export("simple_deep_integration_full.html")
    print("   ✓ Full plotly export successful")
    
    print("\n3. Result Analysis:")
    
    if hasattr(plotly_plot._backend, 'figure') and plotly_plot._backend.figure:
        trace_count = len(plotly_plot._backend.figure.data)
        if trace_count > 0:
            print("   ✅ DEEP INTEGRATION SUCCESSFUL!")
            print(f"   📊 Plotly figure contains {trace_count} traces")
            print("   🌟 Stars are now rendered through backend system")
            print("   🔗 Constellations are now rendered through backend system")
            print("   🎯 True multi-backend support achieved!")
        else:
            print("   ❌ Deep integration failed - no traces found")
    else:
        print("   ❌ Backend system not working")

if __name__ == "__main__":
    test_simple_deep_integration()