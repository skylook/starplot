"""Basic zenith chart - interactive version (corresponds to star_chart_basic.py)"""
from datetime import datetime
from zoneinfo import ZoneInfo

from starplot.interactive import InteractiveZenithPlot
from starplot import Observer, _
from starplot.styles import PlotStyle, extensions

tz = ZoneInfo("America/Los_Angeles")
dt = datetime(2023, 7, 13, 22, 0, tzinfo=tz)

observer = Observer(dt=dt, lat=33.363484, lon=-116.836394)

p = InteractiveZenithPlot(
    observer=observer,
    style=PlotStyle().extend(extensions.BLUE_MEDIUM),
    resolution=3600,
    autoscale=True,
)
p.horizon()
p.constellations()
p.stars(where=[_.magnitude < 4.6], where_labels=[_.magnitude < 2.4])
p.constellation_labels()

# Static export (same as original)
p.export("star_chart_basic.png", transparent=True, padding=0.1)
# Interactive HTML export
p.export_html("star_chart_basic.html")
