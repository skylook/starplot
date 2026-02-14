"""
Test plotly content and create a simple PNG comparison
"""
from datetime import datetime
from pytz import timezone
from starplot import MapPlot, Projection, _
from starplot.styles import PlotStyle, extensions
import os

# Setup
tz = timezone("America/Los_Angeles")
dt = datetime(2023, 7, 13, 22, 0, tzinfo=tz)

def test_plotly_basic():
    """Test basic plotly functionality"""
    print("Testing basic plotly functionality...")
    
    # Create a simple plotly plot
    p = MapPlot(
        projection=Projection.ZENITH,
        lat=33.363484,
        lon=-116.836394,
        dt=dt,
        style=PlotStyle().extend(extensions.BLUE_GOLD),
        resolution=1024,
        autoscale=True,
        backend="plotly",
    )
    
    # Add minimal content
    p.stars(where=[_.magnitude < 3.0])  # Only very bright stars
    p.constellations()
    
    # Check if figure has data
    print(f"Backend: {p._backend_name}")
    print(f"Figure: {p._backend.figure}")
    print(f"Figure data: {len(p._backend.figure.data) if p._backend.figure else 'No figure'}")
    
    # Export as HTML
    p.export("test_plotly_simple.html")
    print("✓ HTML export attempted")
    
    # Check file size
    if os.path.exists("test_plotly_simple.html"):
        size = os.path.getsize("test_plotly_simple.html")
        print(f"✓ HTML file created: {size} bytes")
        
        # Check if file contains star data
        with open("test_plotly_simple.html", 'r') as f:
            content = f.read()
            if '"type":"scatter"' in content:
                print("✓ HTML contains scatter plot data")
            else:
                print("✗ HTML does not contain scatter plot data")
    else:
        print("✗ HTML file not created")

def test_matplotlib_baseline():
    """Test matplotlib baseline for comparison"""
    print("\nTesting matplotlib baseline...")
    
    # Create matplotlib version
    p = MapPlot(
        projection=Projection.ZENITH,
        lat=33.363484,
        lon=-116.836394,
        dt=dt,
        style=PlotStyle().extend(extensions.BLUE_GOLD),
        resolution=1024,
        autoscale=True,
        backend="matplotlib",
    )
    
    # Add same content
    p.stars(where=[_.magnitude < 3.0])  # Only very bright stars
    p.constellations()
    
    # Export as PNG
    p.export("test_matplotlib_simple.png")
    print("✓ PNG export attempted")
    
    # Check file size
    if os.path.exists("test_matplotlib_simple.png"):
        size = os.path.getsize("test_matplotlib_simple.png")
        print(f"✓ PNG file created: {size} bytes")
    else:
        print("✗ PNG file not created")

if __name__ == "__main__":
    test_plotly_basic()
    test_matplotlib_baseline()
    print("\nTest complete!")