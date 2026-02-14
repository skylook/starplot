#!/usr/bin/env python3
"""
Test stars through backend system
"""
from datetime import datetime
from pytz import timezone
from starplot import MapPlot, Projection, _
from starplot.styles import PlotStyle, extensions

# Setup
tz = timezone("America/Los_Angeles")
dt = datetime(2023, 7, 13, 22, 0, tzinfo=tz)

def test_stars_backend():
    """Test stars through backend system"""
    print("=== Stars Backend Test ===")
    
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
        
        # Test stars method with very limited stars and no labels
        print("\n2. Adding stars (limited, no labels)...")
        # Use a very restrictive filter to limit stars
        plotly_plot.stars(
            where=[_.magnitude < 2.0],  # Very bright stars only
            bayer_labels=False,
            flamsteed_labels=False,
            labels=None  # No labels
        )
        print("   ✓ Stars added")
        
        # Check traces
        if hasattr(plotly_plot._backend, 'figure'):
            traces = len(plotly_plot._backend.figure.data)
            print(f"   Star traces created: {traces}")
            
            # Check trace details
            if traces > 0:
                for i, trace in enumerate(plotly_plot._backend.figure.data):
                    if hasattr(trace, 'mode') and 'markers' in trace.mode:
                        points = len(trace.x) if hasattr(trace, 'x') and trace.x is not None else 0
                        print(f"   Trace {i}: {points} star points")
        
        # Export
        plotly_plot.export("stars_backend_test.html")
        print("   ✓ Export successful")
        
        print("\n3. SUCCESS - Stars working through backend!")
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_stars_backend()