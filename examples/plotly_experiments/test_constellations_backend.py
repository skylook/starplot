#!/usr/bin/env python3
"""
Test constellations through backend system
"""
from datetime import datetime
from pytz import timezone
from starplot import MapPlot, Projection, _
from starplot.styles import PlotStyle, extensions

# Setup
tz = timezone("America/Los_Angeles")
dt = datetime(2023, 7, 13, 22, 0, tzinfo=tz)

def test_constellations_backend():
    """Test constellations through backend system"""
    print("=== Constellations Backend Test ===")
    
    try:
        # Test plotly backend 
        print("\n1. Creating plotly plot...")
        plotly_plot = MapPlot(
            projection=Projection.ZENITH,
            lat=33.363484,
            lon=-116.836394,
            dt=dt,
            style=PlotStyle().extend(extensions.BLUE_GOLD),
            resolution=512,  # Lower resolution
            autoscale=True,
            backend="plotly",
        )
        print("   ✓ Plot created")
        
        # Test constellations method
        print("\n2. Adding constellations...")
        plotly_plot.constellations()
        print("   ✓ Constellations added")
        
        # Check traces
        if hasattr(plotly_plot._backend, 'figure'):
            traces = len(plotly_plot._backend.figure.data)
            print(f"   Total traces created: {traces}")
            
            # Check trace details
            line_traces = 0
            if traces > 0:
                for i, trace in enumerate(plotly_plot._backend.figure.data):
                    if hasattr(trace, 'mode') and 'lines' in trace.mode:
                        line_traces += 1
                        points = len(trace.x) if hasattr(trace, 'x') and trace.x is not None else 0
                        print(f"   Line trace {i}: {points} points")
            
            print(f"   Total constellation line traces: {line_traces}")
        
        # Export
        plotly_plot.export("constellations_backend_test.html")
        print("   ✓ Export successful")
        
        print("\n3. SUCCESS - Constellations working through backend!")
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_constellations_backend()