"""Moon and Saturn through binoculars - interactive version (corresponds to optic_moon_saturn.py)"""
from datetime import datetime
from zoneinfo import ZoneInfo

from starplot.interactive import InteractiveOpticPlot
from starplot import Moon, Binoculars, Observer, _
from starplot.styles import PlotStyle, extensions

dt = datetime(2024, 8, 20, 21, 0, 0, tzinfo=ZoneInfo("US/Pacific"))

observer = Observer(
    dt=dt,
    lat=33.070833,  # Julian, CA
    lon=-116.585556,
)

m = Moon.get(observer)

op = InteractiveOpticPlot(
    ra=m.ra,
    dec=m.dec,
    observer=observer,
    optic=Binoculars(magnification=15, fov=65),
    style=PlotStyle().extend(extensions.GRAYSCALE_DARK, extensions.OPTIC),
    resolution=2000,
    autoscale=True,
)
op.moon(
    true_size=True,
    show_phase=True,
)
op.planets(
    true_size=True,
    style__marker__color="#ffe785",
    style__label__offset_x=6,
    style__label__offset_y=-6,
)
op.stars(where=[_.magnitude < 12])

op.export("optic_moon_saturn.png", padding=0.1, transparent=True)
op.export_html("optic_moon_saturn.html", width=1000, height=1000, transparent=True)
