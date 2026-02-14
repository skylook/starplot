"""
Test basic export functionality with both backends
"""
from datetime import datetime
from pytz import timezone
from starplot import MapPlot, Projection, _
from starplot.styles import PlotStyle, extensions

# Setup
tz = timezone("America/Los_Angeles")
dt = datetime(2023, 7, 13, 22, 0, tzinfo=tz)

def test_matplotlib_export():
    """Test matplotlib export"""
    print("Testing matplotlib export...")
    
    import os
    
    try:
        p = MapPlot(
            projection=Projection.ZENITH,
            lat=33.363484,
            lon=-116.836394,
            dt=dt,
            style=PlotStyle().extend(extensions.BLUE_GOLD),
            resolution=1024,  # Lower resolution for faster testing
            autoscale=True,
            backend="matplotlib",
        )
        
        # Add some basic objects
        p.stars(where=[_.magnitude < 4.0])
        p.constellations()
        
        # Export
        filename = "test_matplotlib_export.png"
        print(f"About to export to: {filename}")
        print(f"Current working directory: {os.getcwd()}")
        print(f"Backend figure: {p._backend.figure}")
        
        p.export(filename, transparent=True, padding=0.1)
        print(f"✓ Matplotlib export attempted: {filename}")
        
        # Check if file exists
        if os.path.exists(filename):
            print(f"✓ File created: {filename}")
            print(f"  Size: {os.path.getsize(filename)} bytes")
        else:
            print(f"✗ File not found: {filename}")
            
    except Exception as e:
        print(f"✗ Matplotlib export failed: {e}")
        import traceback
        traceback.print_exc()

def test_plotly_export():
    """Test plotly export"""
    print("\nTesting plotly export...")
    
    import os
    
    try:
        p = MapPlot(
            projection=Projection.ZENITH,
            lat=33.363484,
            lon=-116.836394,
            dt=dt,
            style=PlotStyle().extend(extensions.BLUE_GOLD),
            resolution=1024,
            autoscale=True,
            backend="plotly",
        )
        
        # Add some basic objects
        p.stars(where=[_.magnitude < 4.0])
        p.constellations()
        
        # Export
        filename = "test_plotly_export.html"
        p.export(filename)
        print(f"✓ Plotly export attempted: {filename}")
        
        # Check if file exists
        if os.path.exists(filename):
            print(f"✓ File created: {filename}")
            print(f"  Size: {os.path.getsize(filename)} bytes")
        else:
            print(f"✗ File not found: {filename}")
            
    except Exception as e:
        print(f"✗ Plotly export failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_matplotlib_export()
    test_plotly_export()
    
    print("\nTest complete!")