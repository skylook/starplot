from datetime import datetime
from pytz import timezone
from starplot import MapPlot, Projection, Star, DSO, _
from starplot.styles import PlotStyle, extensions

print("📊 Creating SIMPLIFIED plotly star chart (core features only)...")

tz = timezone("America/Los_Angeles")
dt = datetime(2023, 7, 13, 22, 0, tzinfo=tz)

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

print("   Adding bright stars...")
p.stars(
    where=[_.magnitude < 3.5],  # Bright stars only
    bayer_labels=False,
    flamsteed_labels=False,
    labels=None
)

print("   Exporting HTML...")
p.export("star_chart_core_plotly_simplified.html")

print("   Checking traces...")
if hasattr(p, '_backend') and hasattr(p._backend, 'figure'):
    traces = len(p._backend.figure.data)
    star_traces = sum(1 for trace in p._backend.figure.data 
                      if hasattr(trace, 'mode') and 'markers' in trace.mode)
    line_traces = sum(1 for trace in p._backend.figure.data 
                      if hasattr(trace, 'mode') and 'lines' in trace.mode)
    
    print(f"📊 Generated {traces} traces ({star_traces} stars, {line_traces} lines)")

print("   Attempting PNG export...")
try:
    p.export("star_chart_core_plotly_simplified.png", format="png")
    print("✅ Plotly PNG created successfully!")
except Exception as e:
    print(f"❌ PNG export failed: {e}")

print("✅ Simplified plotly version complete")