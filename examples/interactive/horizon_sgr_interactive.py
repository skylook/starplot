"""Sagittarius horizon chart - interactive version (corresponds to horizon_sgr.py)"""
from datetime import datetime
from zoneinfo import ZoneInfo

from starplot.interactive import InteractiveHorizonPlot
from starplot import Observer, _
from starplot.styles import PlotStyle, extensions

style = PlotStyle().extend(extensions.BLUE_MEDIUM, extensions.MAP)
dt = datetime(2024, 8, 30, 21, 0, 0, 0, tzinfo=ZoneInfo("US/Pacific"))
observer = Observer(dt=dt, lat=36.606111, lon=-118.079444)

p = InteractiveHorizonPlot(
    altitude=(0, 60), azimuth=(135, 225),
    observer=observer, style=style, resolution=4000, scale=0.9,
)
p.constellations()
p.milky_way()
p.stars(where=[_.magnitude < 5], where_labels=[_.magnitude < 2])
p.messier(where=[_.magnitude < 11], where_true_size=[False])
p.constellation_labels()
p.horizon(labels={180: "SOUTH"})
p.gridlines()

p.export("horizon_sgr.png", padding=0.5)
p.export_html("horizon_sgr.html", width=1400, height=700)
