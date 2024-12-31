from datetime import datetime
from pytz import timezone
from starplot import MapPlot, Projection
from starplot.styles import PlotStyle, extensions


tz = timezone("America/Los_Angeles")
dt = datetime(2023, 7, 13, 22, 0, tzinfo=tz)  # July 13, 2023 at 10pm PT

p = MapPlot(
    projection=Projection.ZENITH,
    lat=33.363484,
    lon=-116.836394,
    dt=dt,
    # add a style to the plot
    style=PlotStyle().extend(
        extensions.BLUE_MEDIUM,
    ),
    resolution=4000,
    scale=0.9,
)
# Again, we plot the constellations first, because Starplot will use the constellation
# lines to determine where to place labels for stars (labels will look better if they're
# not crossing a constellation line)
p.constellations()
p.stars(mag=4.6)

# plot galaxies and open clusters with a limiting magnitude of 9
# and do NOT plot their true apparent size
p.galaxies(mag=9, true_size=False, labels=None)
p.open_clusters(mag=9, true_size=False, labels=None)

# plot constellation borders, the ecliptic, and celestial equator
p.constellation_borders()
p.ecliptic()
p.celestial_equator()

# plot the Milky Way
p.milky_way()

# plot a marker for the Coma Star Cluster (aka Melotte 111) and customize its style.
# Starplot also has functions for plotting circles, rectangles, polygons, and more.
# See the reference for MapPlot for details.
p.marker(
    ra=12.36,
    dec=25.85,
    style={
        "marker": {
            "size": 80,
            "symbol": "circle",
            "fill": "full",
            "color": "#ed7eed",
            "edge_color": "#e0c1e0",
            "alpha": 0.8,
        },
        "label": {
            "font_size": 25,
            "font_weight": "bold",
            "font_color": "#c83cc8",
            "font_alpha": 1,
        },
    },
    label="Mel 111",
)
p.horizon()

p.constellation_labels()  # Plot the constellation labels last for best placement

p.export("tutorial_03.png", transparent=True)
