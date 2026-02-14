"""
Debug export method specifically
"""
from datetime import datetime
from pytz import timezone
from starplot import MapPlot, Projection, _
from starplot.styles import PlotStyle, extensions
import os

# Setup
tz = timezone("America/Los_Angeles")
dt = datetime(2023, 7, 13, 22, 0, tzinfo=tz)

def test_export_method():
    """Test export method"""
    print("Testing export method...")
    
    # Create plot
    p = MapPlot(
        projection=Projection.ZENITH,
        lat=33.363484,
        lon=-116.836394,
        dt=dt,
        style=PlotStyle().extend(extensions.BLUE_GOLD),
        resolution=512,
        autoscale=True,
        backend="matplotlib",
    )
    
    # Add some content
    p.stars(where=[_.magnitude < 4.6])
    
    print(f"Backend: {p._backend_name}")
    print(f"Has backend: {hasattr(p, '_backend')}")
    print(f"Backend object: {p._backend}")
    print(f"Backend figure: {p._backend.figure}")
    
    # Test export with detailed error handling
    try:
        filename = "debug_export_method.png"
        print(f"Calling p.export('{filename}')")
        
        # Add some debugging to the export call
        result = p.export(filename)
        print(f"Export returned: {result}")
        
        if os.path.exists(filename):
            print(f"✓ Export successful: {filename}")
            print(f"  Size: {os.path.getsize(filename)} bytes")
        else:
            print(f"✗ Export failed - file not created")
            
    except Exception as e:
        print(f"✗ Export exception: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_export_method()