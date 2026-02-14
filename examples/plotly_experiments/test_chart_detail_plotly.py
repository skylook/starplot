#!/usr/bin/env python3
"""
Star chart detail with plotly backend
"""
from datetime import datetime
from pytz import timezone
from starplot import MapPlot, Projection, Star, DSO, _
from starplot.styles import PlotStyle, extensions

tz = timezone("America/Los_Angeles")
dt = datetime(2023, 7, 13, 22, 0, tzinfo=tz)  # July 13, 2023 at 10pm PT

print("📊 Creating detailed star chart with PLOTLY backend...")

p = MapPlot(
    projection=Projection.ZENITH,
    lat=33.363484,
    lon=-116.836394,
    dt=dt,
    style=PlotStyle().extend(
        extensions.BLUE_GOLD,
    ),
    resolution=2048,  # Lower resolution for faster processing
    autoscale=True,
    backend="plotly",  # 使用plotly后端
)

print("   Adding constellations...")
p.constellations()

print("   Adding stars (without labels to avoid timeout)...")
# 简化星星处理，避免标签超时
p.stars(where=[_.magnitude < 4.0], bayer_labels=False, flamsteed_labels=False, labels=None)

print("   Trying to export HTML first...")
p.export("star_chart_detail_plotly_test.html")
print("✅ Plotly HTML export complete")

print("   Attempting PNG export...")
try:
    p.export("star_chart_detail_plotly_test.png", format="png")
    print("✅ Plotly PNG export successful: star_chart_detail_plotly_test.png")
except Exception as e:
    print(f"❌ Plotly PNG export failed: {e}")
    print("💡 Using HTML as alternative visualization")

# 检查后端数据
if hasattr(p, '_backend') and hasattr(p._backend, 'figure'):
    traces = len(p._backend.figure.data)
    print(f"📊 Plotly figure contains {traces} traces")
    
    star_traces = sum(1 for trace in p._backend.figure.data 
                      if hasattr(trace, 'mode') and 'markers' in trace.mode)
    line_traces = sum(1 for trace in p._backend.figure.data 
                      if hasattr(trace, 'mode') and 'lines' in trace.mode)
    
    print(f"   🌟 Star traces: {star_traces}")
    print(f"   🔗 Line traces: {line_traces}")

print("✅ Plotly star chart processing complete")