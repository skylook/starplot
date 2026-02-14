"""
Detailed debugging of star chart creation
"""
from datetime import datetime
from pytz import timezone
from starplot import MapPlot, Projection, _
from starplot.styles import PlotStyle, extensions
import os

# Setup
tz = timezone("America/Los_Angeles")
dt = datetime(2023, 7, 13, 22, 0, tzinfo=tz)

def test_step_by_step():
    """Test step by step"""
    print("Step-by-step star chart creation...")
    
    try:
        # Step 1: Create plot
        print("Step 1: Creating plot...")
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
        print("✓ Plot created successfully")
        
        # Step 2: Add stars
        print("Step 2: Adding stars...")
        p.stars(where=[_.magnitude < 4.6])
        print("✓ Stars added successfully")
        
        # Step 3: Add constellations
        print("Step 3: Adding constellations...")
        p.constellations()
        print("✓ Constellations added successfully")
        
        # Step 4: Add labels
        print("Step 4: Adding constellation labels...")
        p.constellation_labels()
        print("✓ Labels added successfully")
        
        # Step 5: Export
        print("Step 5: Exporting...")
        filename = "debug_step_by_step.png"
        print(f"About to export to: {filename}")
        print(f"Backend figure: {p._backend.figure}")
        
        # Try direct export first
        print("Trying direct matplotlib export...")
        p.fig.savefig(filename)
        
        if os.path.exists(filename):
            print(f"✓ Direct export successful: {filename}")
            print(f"  Size: {os.path.getsize(filename)} bytes")
        else:
            print(f"✗ Direct export failed")
            
        # Try backend export
        print("Trying backend export...")
        filename2 = "debug_backend_export.png"
        p._backend.export(filename2)
        
        if os.path.exists(filename2):
            print(f"✓ Backend export successful: {filename2}")
            print(f"  Size: {os.path.getsize(filename2)} bytes")
        else:
            print(f"✗ Backend export failed")
            
        # Try plot export method
        print("Trying plot export method...")
        filename3 = "debug_plot_export.png"
        p.export(filename3)
        
        if os.path.exists(filename3):
            print(f"✓ Plot export successful: {filename3}")
            print(f"  Size: {os.path.getsize(filename3)} bytes")
        else:
            print(f"✗ Plot export failed")
        
    except Exception as e:
        print(f"✗ Error at step: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_step_by_step()