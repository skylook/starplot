#!/usr/bin/env python3
"""
Core star chart with plotly backend - simplified
"""
from datetime import datetime
from pytz import timezone
from starplot import MapPlot, Projection, Star, DSO, _
from starplot.styles import PlotStyle, extensions

tz = timezone("America/Los_Angeles")
dt = datetime(2023, 7, 13, 22, 0, tzinfo=tz)

print("📊 Creating CORE star chart with PLOTLY backend...")

p = MapPlot(
    projection=Projection.ZENITH,
    lat=33.363484,
    lon=-116.836394,
    dt=dt,
    style=PlotStyle().extend(extensions.BLUE_GOLD),
    resolution=1024,  # Lower resolution
    autoscale=True,
    backend="plotly",
)

print("   Adding constellations...")
p.constellations()

print("   Adding bright stars only...")
p.stars(
    where=[_.magnitude < 3.0],  # Only bright stars
    bayer_labels=False, 
    flamsteed_labels=False, 
    labels=None
)

print("   Exporting HTML...")
p.export("star_chart_core_plotly.html")

print("   Attempting PNG...")
try:
    p.export("star_chart_core_plotly.png", format="png")
    print("✅ PNG export successful")
except Exception as e:
    print(f"❌ PNG failed: {e}")

# Check traces
if hasattr(p, '_backend') and hasattr(p._backend, 'figure'):
    traces = len(p._backend.figure.data)
    star_traces = sum(1 for trace in p._backend.figure.data 
                      if hasattr(trace, 'mode') and 'markers' in trace.mode)
    line_traces = sum(1 for trace in p._backend.figure.data 
                      if hasattr(trace, 'mode') and 'lines' in trace.mode)
    
    print(f"📊 Total traces: {traces}")
    print(f"   🌟 Star traces: {star_traces}")
    print(f"   🔗 Line traces: {line_traces}")

print("✅ Core plotly chart complete")