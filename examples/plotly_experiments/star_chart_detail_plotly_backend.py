from datetime import datetime
from pytz import timezone
from starplot import MapPlot, Projection, Star, DSO, _
from starplot.styles import PlotStyle, extensions

print("📊 Generating star chart with PLOTLY backend...")

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
    resolution=2048,  # 稍微降低分辨率加快处理
    autoscale=True,
    backend="plotly",  # 使用plotly后端
)

print("   Adding constellations...")
p.constellations()

print("   Adding stars (simplified)...")
# 简化星星以避免标签超时，只显示主要星星
p.stars(
    where=[_.magnitude < 4.6], 
    bayer_labels=False,  # 关闭标签避免超时
    flamsteed_labels=False,
    labels=None
)

print("   Adding deep sky objects...")
p.galaxies(where=[_.magnitude < 9], true_size=False, labels=None)
p.open_clusters(where=[_.magnitude < 9], true_size=False, labels=None)

print("   Exporting HTML first...")
p.export("star_chart_detail_plotly.html")
print("✅ Plotly HTML saved")

print("   Attempting PNG export...")
try:
    p.export("star_chart_detail_plotly.png", format="png")
    print("✅ Plotly PNG saved: star_chart_detail_plotly.png")
except Exception as e:
    print(f"❌ PNG export failed: {e}")
    print("💡 Check kaleido installation: pip install kaleido")

# 检查生成的数据
if hasattr(p, '_backend') and hasattr(p._backend, 'figure'):
    traces = len(p._backend.figure.data)
    star_traces = sum(1 for trace in p._backend.figure.data 
                      if hasattr(trace, 'mode') and 'markers' in trace.mode)
    line_traces = sum(1 for trace in p._backend.figure.data 
                      if hasattr(trace, 'mode') and 'lines' in trace.mode)
    
    print(f"📊 Plotly traces: {traces} total, {star_traces} stars, {line_traces} lines")
    
    if star_traces > 0 and line_traces > 0:
        print("✅ Deep integration verified: Stars and constellations through backend")
    else:
        print("⚠️  Deep integration incomplete")

print("✅ Plotly version processing complete")