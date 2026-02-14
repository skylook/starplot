"""M45 telescope view - interactive version (corresponds to optic_m45.py)"""
from datetime import datetime
from zoneinfo import ZoneInfo

from starplot.interactive import InteractiveOpticPlot
from starplot import DSO, Observer, _
from starplot.callables import color_by_bv
from starplot.models import Refractor
from starplot.styles import PlotStyle, extensions

dt = datetime(2023, 12, 16, 21, 0, 0, tzinfo=ZoneInfo("US/Pacific"))
style = PlotStyle().extend(extensions.GRAYSCALE_DARK, extensions.OPTIC)
observer = Observer(dt=dt, lat=33.363484, lon=-116.836394)

m45 = DSO.get(m="45")
p = InteractiveOpticPlot(
    ra=m45.ra, dec=m45.dec,
    observer=observer,
    optic=Refractor(focal_length=430, eyepiece_focal_length=11, eyepiece_fov=82),
    style=style, resolution=4096, autoscale=True,
)
p.stars(where=[_.magnitude < 12], color_fn=color_by_bv)
p.info()

p.export("optic_m45.png", padding=0.1, transparent=True)
p.export_html("optic_m45.html", width=1000, height=1000)
