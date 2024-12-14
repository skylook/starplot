from datetime import datetime
from pytz import timezone
from starplot import MapPlot, Projection, Star
from starplot.styles import PlotStyle, extensions

tz = timezone("America/Los_Angeles")
dt = datetime(2023, 7, 13, 22, 0, tzinfo=tz)  # July 13, 2023 at 10pm PT

p = MapPlot(
    projection=Projection.ZENITH,
    lat=33.363484,
    lon=-116.836394,
    dt=dt,
    style=PlotStyle().extend(
        extensions.BLUE_MEDIUM,
    ),
    resolution=3600,
    autoscale=True,
)
p.constellations()
p.stars(mag=4.4, where_labels=[Star.magnitude < 2.4])
p.horizon()

p.export("star_chart_basic.png", transparent=True, padding=0.1)
