"""
Manual test of matplotlib export
"""
from datetime import datetime
from pytz import timezone
from starplot import MapPlot, Projection, _
from starplot.styles import PlotStyle, extensions
import os

# Setup
tz = timezone("America/Los_Angeles")
dt = datetime(2023, 7, 13, 22, 0, tzinfo=tz)

print("Testing manual matplotlib export...")

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

print(f"Backend: {p._backend_name}")
print(f"Backend figure: {p._backend.figure}")
print(f"Plot fig: {p.fig}")

# Try direct matplotlib export
try:
    filename = "manual_matplotlib_test.png"
    p.fig.savefig(filename)
    print(f"✓ Direct matplotlib export attempted: {filename}")
    
    if os.path.exists(filename):
        print(f"✓ File created: {filename}")
        print(f"  Size: {os.path.getsize(filename)} bytes")
    else:
        print(f"✗ File not found: {filename}")
        
except Exception as e:
    print(f"✗ Direct matplotlib export failed: {e}")

# Try backend export
try:
    filename2 = "backend_matplotlib_test.png"
    p._backend.export(filename2)
    print(f"✓ Backend export attempted: {filename2}")
    
    if os.path.exists(filename2):
        print(f"✓ File created: {filename2}")
        print(f"  Size: {os.path.getsize(filename2)} bytes")
    else:
        print(f"✗ File not found: {filename2}")
        
except Exception as e:
    print(f"✗ Backend export failed: {e}")
    import traceback
    traceback.print_exc()

print("Manual test complete!")