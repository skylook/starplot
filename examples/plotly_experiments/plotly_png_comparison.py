#!/usr/bin/env python3
"""
Generate PNG comparisons for plotly backend
"""
from datetime import datetime
from pytz import timezone
from starplot import MapPlot, Projection, _
from starplot.styles import PlotStyle, extensions
import numpy as np
import os

# Setup
tz = timezone("America/Los_Angeles")
dt = datetime(2023, 7, 13, 22, 0, tzinfo=tz)

def create_png_comparison():
    """Create PNG comparison between matplotlib and plotly backends"""
    print("Creating PNG comparison...")
    
    # Create matplotlib plot
    print("\n1. Creating matplotlib plot...")
    matplotlib_plot = MapPlot(
        projection=Projection.ZENITH,
        lat=33.363484,
        lon=-116.836394,
        dt=dt,
        style=PlotStyle().extend(extensions.BLUE_GOLD),
        resolution=1024,
        autoscale=True,
        backend="matplotlib",
    )
    
    # Add stars using existing method
    matplotlib_plot.stars(where=[_.magnitude < 3.0])
    
    # Export matplotlib version
    matplotlib_plot.export("star_chart_matplotlib.png")
    print("✓ Matplotlib version exported")
    
    # Create plotly plot
    print("\n2. Creating plotly plot...")
    plotly_plot = MapPlot(
        projection=Projection.ZENITH,
        lat=33.363484,
        lon=-116.836394,
        dt=dt,
        style=PlotStyle().extend(extensions.BLUE_GOLD),
        resolution=1024,
        autoscale=True,
        backend="plotly",
    )
    
    # Add stars using existing method (will still use matplotlib internally)
    plotly_plot.stars(where=[_.magnitude < 3.0])
    
    # Export plotly version as PNG
    try:
        plotly_plot.export("star_chart_plotly.png", format="png")
        print("✓ Plotly PNG version exported")
    except Exception as e:
        print(f"❌ Plotly PNG export failed: {e}")
        # Try HTML export as fallback
        plotly_plot.export("star_chart_plotly.html")
        print("✓ Plotly HTML version exported as fallback")
    
    # Test direct backend PNG export
    print("\n3. Testing direct backend PNG export...")
    
    # Test plotly backend directly with PNG
    plotly_backend = plotly_plot._backend
    plotly_backend.create_figure(800, 600)
    
    # Add some test data
    test_x = np.array([100, 200, 300, 400, 500])
    test_y = np.array([100, 200, 300, 400, 500])
    test_sizes = np.array([20, 30, 40, 50, 60])
    
    plotly_backend.scatter(test_x, test_y, sizes=test_sizes, colors='blue')
    
    try:
        plotly_backend.export("backend_direct_plotly.png", format="png")
        print("✓ Direct plotly backend PNG test exported")
    except Exception as e:
        print(f"❌ Direct plotly PNG export failed: {e}")
        plotly_backend.export("backend_direct_plotly.html")
        print("✓ Direct plotly HTML test exported as fallback")
    
    # Check file sizes
    print("\n4. File comparison:")
    files = [
        "star_chart_matplotlib.png",
        "star_chart_plotly.png", 
        "star_chart_plotly.html",
        "backend_direct_plotly.png",
        "backend_direct_plotly.html"
    ]
    
    for filename in files:
        if os.path.exists(filename):
            size = os.path.getsize(filename)
            print(f"  {filename}: {size} bytes")
        else:
            print(f"  {filename}: NOT FOUND")
    
    print("\n5. Analysis:")
    print("Testing plotly PNG export capabilities...")
    
    if os.path.exists("star_chart_plotly.png"):
        print("✅ Plotly PNG export works - files can be directly compared")
    else:
        print("⚠️  Plotly PNG export issue - using HTML as primary format")
        print("Note: The existing starplot methods still use matplotlib internally")
        print("This is the fundamental limitation we identified earlier")

if __name__ == "__main__":
    create_png_comparison()