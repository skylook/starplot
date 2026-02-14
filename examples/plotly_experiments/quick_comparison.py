#!/usr/bin/env python3
"""
Quick star chart comparison - essential features only
"""
from datetime import datetime
from pytz import timezone
from starplot import MapPlot, Projection, _
from starplot.styles import PlotStyle, extensions

print("🚀 Quick comparison - essential features only")

tz = timezone("America/Los_Angeles")
dt = datetime(2023, 7, 13, 22, 0, tzinfo=tz)

# Matplotlib version
print("\n🖼️  Matplotlib (essential)...")
p1 = MapPlot(
    projection=Projection.ZENITH,
    lat=33.363484,
    lon=-116.836394,
    dt=dt,
    style=PlotStyle().extend(extensions.BLUE_GOLD),
    resolution=1024,
    autoscale=True,
    backend="matplotlib",
)

p1.constellations()
p1.stars(where=[_.magnitude < 3.0], labels=None)
p1.export("quick_matplotlib.png")
print("✅ Matplotlib done")

# Plotly version  
print("\n📊 Plotly (essential)...")
p2 = MapPlot(
    projection=Projection.ZENITH,
    lat=33.363484,
    lon=-116.836394,
    dt=dt,
    style=PlotStyle().extend(extensions.BLUE_GOLD),
    resolution=1024,
    autoscale=True,
    backend="plotly",
)

p2.constellations()
p2.stars(where=[_.magnitude < 3.0], labels=None)

# Check backend integration
if hasattr(p2, '_backend') and hasattr(p2._backend, 'figure'):
    traces = len(p2._backend.figure.data)
    print(f"📊 Plotly traces: {traces}")

p2.export("quick_plotly.html")

try:
    p2.export("quick_plotly.png", format="png")
    print("✅ Plotly PNG: quick_plotly.png")
    success = True
except Exception as e:
    print(f"❌ PNG failed: {e}")
    success = False

print(f"\n🎯 Result: {'Both backends working!' if success else 'Partial success'}")