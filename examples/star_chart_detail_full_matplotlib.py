from datetime import datetime
from pytz import timezone
from starplot import MapPlot, Projection, Star, DSO, _
from starplot.styles import PlotStyle, extensions

print("🖼️  Generating FULL star chart detail with MATPLOTLIB backend...")

tz = timezone("America/Los_Angeles")
dt = datetime(2023, 7, 13, 22, 0, tzinfo=tz)  # July 13, 2023 at 10pm PT

p = MapPlot(
    projection=Projection.ZENITH,
    lat=33.363484,
    lon=-116.836394,
    dt=dt,
    style=PlotStyle().extend(
        extensions.BLUE_GOLD,
    ),
    resolution=3600,
    autoscale=True,
    backend="matplotlib",  # 使用matplotlib后端
)

print("   Adding horizon...")
p.horizon()

print("   Adding constellations...")
p.constellations()

print("   Adding stars...")
p.stars(where=[_.magnitude < 4.6], where_labels=[_.magnitude < 2.1])

print("   Adding deep sky objects...")
p.galaxies(where=[_.magnitude < 9], true_size=False, labels=None)
p.open_clusters(where=[_.magnitude < 9], true_size=False, labels=None)

print("   Adding coordinate systems...")
p.constellation_borders()
p.ecliptic()
p.celestial_equator()
p.milky_way()

print("   Adding marker...")
p.marker(
    ra=12.36 * 15,
    dec=25.85,
    style={
        "marker": {
            "size": 60,
            "symbol": "circle",
            "fill": "none",
            "color": None,
            "edge_color": "hsl(44, 70%, 73%)",
            "edge_width": 2,
            "line_style": [1, [2, 3]],
            "alpha": 1,
            "zorder": 100,
        },
        "label": {
            "zorder": 200,
            "font_size": 22,
            "font_weight": "bold",
            "font_color": "hsl(44, 70%, 64%)",
            "font_alpha": 1,
            "offset_x": "auto",
            "offset_y": "auto",
            "anchor_point": "top right",
        },
    },
    label="Mel 111",
)

print("   Adding constellation labels...")
p.constellation_labels()

print("   Exporting PNG...")
p.export("star_chart_detail_full_matplotlib.png", transparent=True, padding=0.1)
print("✅ Full matplotlib star chart: star_chart_detail_full_matplotlib.png")