from datetime import datetime
from pytz import timezone
from starplot import MapPlot, Projection, Star, DSO, _
from starplot.styles import PlotStyle, extensions

print("🖼️  Creating SIMPLIFIED matplotlib star chart (to match plotly capabilities)...")

tz = timezone("America/Los_Angeles")
dt = datetime(2023, 7, 13, 22, 0, tzinfo=tz)

p = MapPlot(
    projection=Projection.ZENITH,
    lat=33.363484,
    lon=-116.836394,
    dt=dt,
    style=PlotStyle().extend(extensions.BLUE_GOLD),
    resolution=1024,  # Same as plotly test
    autoscale=True,
    backend="matplotlib",
)

print("   Adding constellations...")
p.constellations()

print("   Adding bright stars...")
p.stars(
    where=[_.magnitude < 3.5],  # Same filter as plotly
    bayer_labels=False,
    flamsteed_labels=False,
    labels=None
)

print("   Exporting PNG...")
p.export("star_chart_core_matplotlib_simple.png", transparent=True, padding=0.1)
print("✅ Simplified matplotlib version: star_chart_core_matplotlib_simple.png")