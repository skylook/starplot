"""Orthographic full-sky map - interactive version (corresponds to map_orthographic.py)
Includes constellation lines, borders, DSOs, ecliptic, celestial equator, milky way"""
from datetime import datetime
from pytz import timezone

from starplot.interactive import InteractiveMapPlot
from starplot import Orthographic, Observer, _
from starplot.styles import PlotStyle, extensions

style = PlotStyle().extend(extensions.BLUE_MEDIUM, extensions.MAP)
tz = timezone("America/Los_Angeles")
dt = datetime(2024, 10, 19, 21, 00, tzinfo=tz)

observer = Observer(dt=dt, lat=32.97, lon=-117.038611)
p = InteractiveMapPlot(
    projection=Orthographic(center_ra=observer.lst, center_dec=observer.lat),
    observer=observer, style=style, resolution=2800, scale=0.86,
)
p.gridlines(labels=False)
p.constellations()
p.constellation_borders()
p.stars(where=[_.magnitude < 7], where_labels=[False])
p.open_clusters(where=[_.magnitude < 12], where_labels=[False], where_true_size=[False])
p.galaxies(where=[_.magnitude < 12], where_labels=[False], where_true_size=[False])
p.nebula(where=[_.magnitude < 12], where_labels=[False], where_true_size=[False])
p.ecliptic()
p.celestial_equator()
p.milky_way()

p.export("map_orthographic.png", padding=0.3, transparent=True)
p.export_html("map_orthographic.html", width=1000, height=1000)
