from datetime import datetime
from pytz import timezone
from starplot import MapPlot, Projection, Star, DSO, _
from starplot.styles import PlotStyle, extensions

print("📊 Generating FULL star chart detail with PLOTLY backend...")

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
    resolution=2048,  # 稍微降低分辨率
    autoscale=True,
    backend="plotly",  # 使用plotly后端
)

print("   Adding constellations...")
p.constellations()

print("   Adding stars (core functionality)...")
# 使用深度集成的核心功能 - stars 和 constellations
p.stars(
    where=[_.magnitude < 4.6], 
    bayer_labels=False,  # 简化标签避免超时
    flamsteed_labels=False,
    labels=None
)

print("   Adding deep sky objects...")
try:
    p.galaxies(where=[_.magnitude < 9], true_size=False, labels=None)
    p.open_clusters(where=[_.magnitude < 9], true_size=False, labels=None)
    print("   ✓ Deep sky objects added")
except Exception as e:
    print(f"   ⚠️ Deep sky objects skipped: {e}")

# 检查后端状态
if hasattr(p, '_backend') and hasattr(p._backend, 'figure'):
    traces = len(p._backend.figure.data)
    star_traces = sum(1 for trace in p._backend.figure.data 
                      if hasattr(trace, 'mode') and 'markers' in trace.mode)
    line_traces = sum(1 for trace in p._backend.figure.data 
                      if hasattr(trace, 'mode') and 'lines' in trace.mode)
    
    print(f"   📊 Generated {traces} traces ({star_traces} stars, {line_traces} lines)")

print("   Exporting HTML first...")
p.export("star_chart_detail_full_plotly.html")
print("   ✓ HTML exported")

print("   Attempting PNG export...")
try:
    p.export("star_chart_detail_full_plotly.png", format="png", width=3600, height=3600)
    print("✅ Full plotly PNG: star_chart_detail_full_plotly.png")
except Exception as e:
    print(f"❌ PNG export failed: {e}")

print("✅ Full plotly star chart processing complete")