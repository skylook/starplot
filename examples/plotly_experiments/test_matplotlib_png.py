#!/usr/bin/env python3
"""
Test matplotlib PNG generation
"""
from datetime import datetime
from pytz import timezone
from starplot import MapPlot, Projection, _
from starplot.styles import PlotStyle, extensions

tz = timezone("America/Los_Angeles")
dt = datetime(2023, 7, 13, 22, 0, tzinfo=tz)

print("🖼️ Testing Matplotlib PNG Generation...")

p = MapPlot(
    projection=Projection.ZENITH,
    lat=33.363484,
    lon=-116.836394,
    dt=dt,
    style=PlotStyle().extend(extensions.BLUE_GOLD),
    resolution=1024,
    autoscale=True,
    backend="matplotlib",
)

print("   Adding constellations...")
p.constellations()

print("   Adding bright stars...")
p.stars(where=[_.magnitude < 3.0], bayer_labels=False, flamsteed_labels=False, labels=None)

print("   Exporting PNG...")
p.export("test_matplotlib_backend.png", transparent=False, padding=0.1)
print("✅ Matplotlib PNG: test_matplotlib_backend.png")