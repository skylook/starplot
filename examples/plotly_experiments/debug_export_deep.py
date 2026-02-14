"""
Deep debug of export method
"""
from datetime import datetime
from pytz import timezone
from starplot import MapPlot, Projection, _
from starplot.styles import PlotStyle, extensions
import os

# Setup
tz = timezone("America/Los_Angeles")
dt = datetime(2023, 7, 13, 22, 0, tzinfo=tz)

def test_export_deep():
    """Test export with deep debugging"""
    print("Deep debugging export method...")
    
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
    print(f"Backend figure: {p._backend.figure}")
    
    # Test step by step what export does
    filename = "debug_export_deep.png"
    print(f"\nTesting export steps...")
    
    # Step 1: Check if _backend exists
    print(f"Step 1: hasattr(p, '_backend'): {hasattr(p, '_backend')}")
    print(f"Step 1: p._backend: {p._backend}")
    print(f"Step 1: bool(p._backend): {bool(p._backend)}")
    
    # Step 2: Try calling backend export directly
    print(f"\nStep 2: Calling backend export directly...")
    try:
        p._backend.export(filename, dpi=144, format="png", padding=0.1)
        print(f"✓ Backend export called successfully")
        
        if os.path.exists(filename):
            print(f"✓ File created: {filename}")
            print(f"  Size: {os.path.getsize(filename)} bytes")
        else:
            print(f"✗ File not created")
            
    except Exception as e:
        print(f"✗ Backend export exception: {e}")
        import traceback
        traceback.print_exc()
    
    # Step 3: Test matplotlib savefig directly
    print(f"\nStep 3: Testing matplotlib savefig directly...")
    try:
        filename2 = "debug_matplotlib_direct.png"
        p._backend.figure.savefig(filename2, dpi=144, format="png", bbox_inches="tight", pad_inches=0.1)
        print(f"✓ Matplotlib savefig called successfully")
        
        if os.path.exists(filename2):
            print(f"✓ File created: {filename2}")
            print(f"  Size: {os.path.getsize(filename2)} bytes")
        else:
            print(f"✗ File not created")
            
    except Exception as e:
        print(f"✗ Matplotlib savefig exception: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_export_deep()