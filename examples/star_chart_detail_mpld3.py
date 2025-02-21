from datetime import datetime
from pytz import timezone
from starplot import MapPlot, Projection, Star, DSO, _
from starplot.styles import PlotStyle, extensions
import mpld3
import matplotlib.pyplot as plt
import json
import os
import numpy as np

class NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        return super().default(obj)

tz = timezone("America/Los_Angeles")
dt = datetime(2023, 7, 13, 22, 0, tzinfo=tz)  # July 13, 2023 at 10pm PT

# Set a reasonable figure size
plt.figure(figsize=(10, 10))

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
)
p.horizon()
p.constellations()
p.stars(where=[_.magnitude < 4.6], where_labels=[_.magnitude < 2.1])

p.galaxies(where=[_.magnitude < 9], true_size=False, labels=None)
p.open_clusters(where=[_.magnitude < 9], true_size=False, labels=None)

p.constellation_borders()
p.ecliptic()
p.celestial_equator()
p.milky_way()

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
p.constellation_labels()

# 保存为PNG格式
p.export("star_chart_detail.png", transparent=True, padding=0.1)

# 获取 mpld3 的 JSON 数据
fig_json = mpld3.fig_to_dict(p.fig)

# 保存数据到 JSON 文件
with open('star_chart_detail_data.json', 'w') as f:
    json.dump(fig_json, f, cls=NumpyEncoder)

# 创建一个简单的 HTML 文件，通过 AJAX 加载 JSON 数据
html_template = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Detailed Star Chart</title>
    <script src="https://d3js.org/d3.v5.min.js"></script>
    <script src="https://mpld3.github.io/js/mpld3.v0.5.10.js"></script>
    <style>
        body {
            margin: 0;
            padding: 20px;
            background: #1a1a1a;
            color: #ffffff;
            font-family: Arial, sans-serif;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
        }
        h1 {
            text-align: center;
            color: #ffd700;
        }
        .chart-container {
            background: rgba(0, 0, 0, 0.5);
            padding: 20px;
            border-radius: 10px;
            margin-top: 20px;
        }
        #figure {
            width: 100%;
            height: 100%;
        }
        .description {
            margin-top: 20px;
            text-align: center;
            font-style: italic;
            color: #cccccc;
        }
        .comparison {
            margin-top: 30px;
            text-align: center;
        }
        .comparison a {
            color: #ffd700;
            text-decoration: none;
        }
        .comparison a:hover {
            text-decoration: underline;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Interactive Detailed Star Chart</h1>
        <div class="chart-container">
            <div id="figure"></div>
        </div>
        <div class="description">
            Interactive star chart showing celestial objects and constellations
        </div>
        <div class="comparison">
            <a href="star_chart_detail.png" target="_blank">View Static PNG Version</a>
        </div>
    </div>
    <script>
        fetch('star_chart_detail_data.json')
            .then(response => response.json())
            .then(data => {
                mpld3.draw_figure('figure', data);
            })
            .catch(error => console.error('Error loading the chart data:', error));
    </script>
</body>
</html>
"""

# 保存 HTML 文件
with open('star_chart_detail_mpld3.html', 'w') as f:
    f.write(html_template)
