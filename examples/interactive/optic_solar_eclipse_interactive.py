"""Solar eclipse view - interactive version (corresponds to optic_solar_eclipse.py)"""
from datetime import datetime
from zoneinfo import ZoneInfo

from starplot.interactive import InteractiveOpticPlot
from starplot import Moon, Binoculars, Observer
from starplot.styles import PlotStyle, extensions

# time of partial eclipse. total eclipse started at 15:13:46
dt = datetime(2024, 4, 8, 14, 45, 0, tzinfo=ZoneInfo("US/Eastern"))


observer = Observer(
    dt=dt,
    lat=41.482222,  # Cleveland, Ohio
    lon=-81.669722,
)

m = Moon.get(dt=observer.dt, lat=observer.lat, lon=observer.lon)

op = InteractiveOpticPlot(
    ra=m.ra,
    dec=m.dec,
    observer=observer,
    optic=Binoculars(magnification=30, fov=65),
    style=PlotStyle().extend(
        extensions.GRAYSCALE_DARK,
        extensions.OPTIC,
        extensions.GRADIENT_DAYLIGHT,
    ),
    resolution=2000,
)
op.moon(
    true_size=True,
    show_phase=True,
    label=None,
)
op.sun(
    true_size=True,
    style__marker__color="#ffd22e",
    label=None,
)

op.export("optic_solar_eclipse.png", padding=0.1, transparent=True)
op.export_html("optic_solar_eclipse.html", width=1000, height=1000)
