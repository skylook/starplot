#!/usr/bin/env python3
"""
Core star chart comparison - stars and constellations only
Based on star_chart_detail.py but simplified for backend comparison
"""
from datetime import datetime
from pytz import timezone
from starplot import MapPlot, Projection, Star, DSO, _
from starplot.styles import PlotStyle, extensions
import os

tz = timezone("America/Los_Angeles")
dt = datetime(2023, 7, 13, 22, 0, tzinfo=tz)  # July 13, 2023 at 10pm PT

def create_comparison_charts():
    """Create charts with both backends focusing on core functionality"""
    print("=" * 60)
    print("🎯 STAR CHART DETAIL COMPARISON")
    print("=" * 60)
    
    # Common parameters from star_chart_detail.py
    common_params = {
        'projection': Projection.ZENITH,
        'lat': 33.363484,
        'lon': -116.836394,
        'dt': dt,
        'style': PlotStyle().extend(extensions.BLUE_GOLD),
        'resolution': 2048,  # Reasonable resolution
        'autoscale': True,
    }
    
    # 1. Matplotlib version (full functionality)
    print("\n🖼️  MATPLOTLIB VERSION")
    print("-" * 40)
    
    p1 = MapPlot(backend="matplotlib", **common_params)
    
    print("   Adding constellations...")
    p1.constellations()
    
    print("   Adding stars (same as original)...")
    p1.stars(where=[_.magnitude < 4.6], where_labels=[_.magnitude < 2.1])
    
    print("   Exporting matplotlib PNG...")
    p1.export("star_chart_comparison_matplotlib.png", transparent=True, padding=0.1)
    print("   ✅ Matplotlib chart complete")
    
    # 2. Plotly version (core functionality)
    print("\n📊 PLOTLY VERSION")
    print("-" * 40)
    
    p2 = MapPlot(backend="plotly", **common_params)
    
    print("   Adding constellations...")
    p2.constellations()
    
    print("   Adding stars (simplified for stability)...")
    p2.stars(
        where=[_.magnitude < 4.6],  # Same magnitude filter
        bayer_labels=False,         # Skip labels for stability
        flamsteed_labels=False,
        labels=None
    )
    
    # Check backend data
    if hasattr(p2, '_backend') and hasattr(p2._backend, 'figure'):
        traces = len(p2._backend.figure.data)
        star_traces = sum(1 for trace in p2._backend.figure.data 
                          if hasattr(trace, 'mode') and 'markers' in trace.mode)
        line_traces = sum(1 for trace in p2._backend.figure.data 
                          if hasattr(trace, 'mode') and 'lines' in trace.mode)
        
        print(f"   📊 Plotly traces: {traces} total ({star_traces} stars, {line_traces} lines)")
    
    print("   Exporting plotly files...")
    p2.export("star_chart_comparison_plotly.html")
    
    try:
        p2.export("star_chart_comparison_plotly.png", format="png")
        print("   ✅ Plotly PNG successful")
        plotly_png_success = True
    except Exception as e:
        print(f"   ❌ Plotly PNG failed: {e}")
        plotly_png_success = False
    
    return plotly_png_success

def analyze_results(plotly_png_success):
    """Analyze the generated files"""
    print("\n" + "=" * 60)
    print("📁 FILE ANALYSIS")
    print("=" * 60)
    
    files = [
        ("star_chart_comparison_matplotlib.png", "Matplotlib PNG"),
        ("star_chart_comparison_plotly.png", "Plotly PNG"),
        ("star_chart_comparison_plotly.html", "Plotly HTML")
    ]
    
    for filename, description in files:
        if os.path.exists(filename):
            size = os.path.getsize(filename)
            print(f"✅ {description}: {size:,} bytes")
        else:
            print(f"❌ {description}: Not found")
    
    # Comparison summary
    print("\n🎯 BACKEND COMPARISON SUMMARY")
    print("=" * 60)
    
    matplotlib_exists = os.path.exists("star_chart_comparison_matplotlib.png")
    plotly_exists = plotly_png_success and os.path.exists("star_chart_comparison_plotly.png")
    
    if matplotlib_exists and plotly_exists:
        print("✅ SUCCESS: Both backends generated PNG files!")
        print("📊 Ready for visual comparison!")
        print("\n🔍 Key achievements:")
        print("   • Same star_chart_detail.py parameters")
        print("   • Both use deep integration (backend.scatter/plot_lines)")
        print("   • Matplotlib: Full traditional astronomical visualization")
        print("   • Plotly: Core astronomical data with modern styling")
        return True
    elif matplotlib_exists:
        print("⚠️  PARTIAL: Matplotlib working, Plotly PNG failed")
        print("📊 Matplotlib chart available for review")
        print("📊 Plotly HTML available as interactive alternative")
        return False
    else:
        print("❌ FAILED: Charts not generated properly")
        return False

if __name__ == "__main__":
    plotly_success = create_comparison_charts()
    analyze_results(plotly_success)