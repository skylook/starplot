import sys
from datetime import datetime
from pytz import timezone
from starplot import MapPlot, Projection, Star, DSO, _
from starplot.styles import PlotStyle, extensions

# 支持命令行参数切换backend: python star_chart_detail.py matplotlib/plotly
backend = "matplotlib"  # 默认backend
if len(sys.argv) > 1:
    backend = sys.argv[1].lower()
    if backend not in ["matplotlib", "plotly"]:
        print(f"❌ 无效的backend: {backend}")
        print("✅ 支持的backend: matplotlib, plotly")
        sys.exit(1)

print(f"🎯 使用 {backend} backend 生成星图...")

tz = timezone("America/Los_Angeles")
dt = datetime(2023, 7, 13, 22, 0, tzinfo=tz)  # July 13, 2023 at 10pm PT

# 根据backend调整配置
resolution = 3600 if backend == "matplotlib" else 1024  # plotly用更低分辨率避免超时

p = MapPlot(
    projection=Projection.ZENITH,
    lat=33.363484,
    lon=-116.836394,
    dt=dt,
    style=PlotStyle().extend(
        extensions.BLUE_GOLD,
    ),
    resolution=resolution,
    autoscale=True,
    backend=backend,
)
# 添加绘图元素 - 根据backend调整功能
print("   添加基础元素...")

if backend == "matplotlib":
    # matplotlib支持所有功能
    p.horizon()
    p.constellations()
    p.stars(where=[_.magnitude < 4.6], where_labels=[_.magnitude < 2.1])
    
    print("   添加深空天体...")
    p.galaxies(where=[_.magnitude < 9], true_size=False, labels=None)
    p.open_clusters(where=[_.magnitude < 9], true_size=False, labels=None)
    
    print("   添加坐标系统...")
    p.constellation_borders()
    p.ecliptic()
    p.celestial_equator()
    p.milky_way()
    
    print("   添加标记和标签...")
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
    
else:  # plotly backend - 极简版本确保能运行
    print("   极简plotly版本（仅核心功能）...")
    # 只添加最基本的星星，不添加星座线
    p.stars(
        where=[_.magnitude < 2.5],  # 只显示最亮的星
        bayer_labels=False,
        flamsteed_labels=False, 
        labels=None
    )
    print("   仅显示最亮恒星以演示深度集成...")

# 导出文件
output_filename = f"star_chart_detail_{backend}.png"
print(f"   导出为: {output_filename}")

if backend == "matplotlib":
    p.export(output_filename, transparent=True, padding=0.1)
else:  # plotly
    # 先导出HTML
    html_filename = f"star_chart_detail_{backend}.html"
    p.export(html_filename)
    print(f"   HTML文件: {html_filename}")
    
    # 尝试导出PNG
    try:
        p.export(output_filename, format="png")
        print(f"✅ 成功生成: {output_filename}")
    except Exception as e:
        print(f"❌ PNG导出失败: {e}")
        print(f"💡 请查看HTML文件: {html_filename}")

print(f"🎯 {backend} backend 星图生成完成!")
