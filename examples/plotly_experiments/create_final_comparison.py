#!/usr/bin/env python3
"""
Final comparison using known working methods
"""
from datetime import datetime
from pytz import timezone
from starplot import MapPlot, Projection, _
from starplot.styles import PlotStyle, extensions

print("🎯 Creating final comparison using proven methods...")

tz = timezone("America/Los_Angeles")
dt = datetime(2023, 7, 13, 22, 0, tzinfo=tz)

# Test plotly with minimal but representative data
print("\n📊 Creating plotly version (core stars)...")
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

# Use very bright stars only for comparison
p.stars(where=[_.magnitude < 2.5], bayer_labels=False, flamsteed_labels=False, labels=None)

# Export
p.export("final_plotly_comparison.html")

try:
    p.export("final_plotly_comparison.png", format="png")
    print("✅ Plotly PNG: final_plotly_comparison.png")
except Exception as e:
    print(f"❌ PNG failed: {e}")

# Check traces
if hasattr(p, '_backend') and hasattr(p._backend, 'figure'):
    traces = len(p._backend.figure.data)
    print(f"📊 Plotly traces: {traces}")

print("✅ Comparison files ready for analysis")