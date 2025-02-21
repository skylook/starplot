from datetime import datetime
from pytz import timezone
from starplot import MapPlot, Projection, Star, _
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

# Set a smaller figure size (width, height in inches)
plt.figure(figsize=(10, 10))

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
p.horizon()
p.constellations()
p.stars(where=[_.magnitude < 4.6], where_labels=[_.magnitude < 2.4])
p.constellation_labels()

# 获取 mpld3 的 JSON 数据
fig_json = mpld3.fig_to_dict(p.fig)

# 保存数据到 JSON 文件
with open('star_chart_data.json', 'w') as f:
    json.dump(fig_json, f, cls=NumpyEncoder)

# 创建一个简单的 HTML 文件，通过 AJAX 加载 JSON 数据
html_template = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Star Chart</title>
    <script src="https://d3js.org/d3.v5.min.js"></script>
    <script src="https://mpld3.github.io/js/mpld3.v0.5.10.js"></script>
</head>
<body>
    <div id="figure"></div>
    <script>
        fetch('star_chart_data.json')
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
with open('star_chart_mpld3.html', 'w') as f:
    f.write(html_template)
