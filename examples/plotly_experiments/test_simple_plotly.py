#!/usr/bin/env python3
"""
Simple plotly test
"""
from datetime import datetime
from pytz import timezone
from starplot import MapPlot, Projection, _
from starplot.styles import PlotStyle, extensions

tz = timezone("America/Los_Angeles")
dt = datetime(2023, 7, 13, 22, 0, tzinfo=tz)

print("📊 Simple plotly test...")

p = MapPlot(
    projection=Projection.ZENITH,
    lat=33.363484,
    lon=-116.836394,
    dt=dt,
    style=PlotStyle().extend(extensions.BLUE_GOLD),
    resolution=512,
    autoscale=True,
    backend="plotly",
)

print("   Adding just the brightest stars...")
p.stars(where=[_.magnitude < 1.0], bayer_labels=False, flamsteed_labels=False, labels=None)

print("   Exporting HTML...")
p.export("simple_plotly_test.html")

print("   Checking traces...")
if hasattr(p, '_backend') and hasattr(p._backend, 'figure'):
    traces = len(p._backend.figure.data)
    print(f"   Created {traces} traces")

print("✅ Simple plotly test complete")