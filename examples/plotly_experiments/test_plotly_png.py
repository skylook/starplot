#!/usr/bin/env python3
"""
Test plotly PNG generation
"""
from datetime import datetime
from pytz import timezone
from starplot import MapPlot, Projection, _
from starplot.styles import PlotStyle, extensions

tz = timezone("America/Los_Angeles")
dt = datetime(2023, 7, 13, 22, 0, tzinfo=tz)

print("📊 Testing Plotly PNG Generation...")

p = MapPlot(
    projection=Projection.ZENITH,
    lat=33.363484,
    lon=-116.836394,
    dt=dt,
    style=PlotStyle().extend(extensions.BLUE_GOLD),
    resolution=512,  # Lower resolution for faster processing
    autoscale=True,
    backend="plotly",
)

print("   Adding bright stars only...")
p.stars(where=[_.magnitude < 2.0], bayer_labels=False, flamsteed_labels=False, labels=None)

print("   Checking backend data...")
if hasattr(p, '_backend') and hasattr(p._backend, 'figure'):
    traces = len(p._backend.figure.data)
    print(f"   📊 Created {traces} traces")

print("   Exporting HTML...")
p.export("test_plotly_backend.html")
print("   ✅ HTML exported")

print("   Attempting PNG...")
try:
    p.export("test_plotly_backend.png", format="png")
    print("   ✅ PNG exported: test_plotly_backend.png")
except Exception as e:
    print(f"   ❌ PNG failed: {e}")

print("✅ Plotly test complete")