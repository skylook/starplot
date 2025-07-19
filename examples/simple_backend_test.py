"""
Simple test to verify backend functionality works
"""
from datetime import datetime
from pytz import timezone
import starplot as sp

print("Testing backend functionality...")

# Test basic backend creation
tz = timezone("UTC")
dt = tz.localize(datetime(2024, 1, 1, 22, 0, 0))

# Create matplotlib plot
print("\n1. Creating matplotlib plot...")
matplotlib_plot = sp.MapPlot(
    projection=sp.Projection.ZENITH,
    lat=40.7128,
    lon=-74.0060,
    dt=dt,
    backend='matplotlib',
    resolution=512,
)

print(f"✓ Matplotlib plot created with backend: {matplotlib_plot._backend_name}")
print(f"✓ Backend type: {type(matplotlib_plot._backend)}")

# Create plotly plot
print("\n2. Creating plotly plot...")
plotly_plot = sp.MapPlot(
    projection=sp.Projection.ZENITH,
    lat=40.7128,
    lon=-74.0060,
    dt=dt,
    backend='plotly',
    resolution=512,
)

print(f"✓ Plotly plot created with backend: {plotly_plot._backend_name}")
print(f"✓ Backend type: {type(plotly_plot._backend)}")

# Test backend objects
print("\n3. Testing backend objects...")
print(f"✓ Matplotlib backend figure: {matplotlib_plot._backend.get_figure()}")
print(f"✓ Plotly backend figure: {plotly_plot._backend.get_figure()}")

# Test simple export with specific paths
print("\n4. Testing export...")
try:
    # Test matplotlib export - use absolute path
    matplotlib_plot.export("/Users/skylook/Develop/starplot/examples/test_matplotlib.png")
    print("✓ Matplotlib export attempt completed")
except Exception as e:
    print(f"✗ Matplotlib export failed: {e}")

try:
    # Test plotly export - use absolute path
    plotly_plot.export("/Users/skylook/Develop/starplot/examples/test_plotly.html")
    print("✓ Plotly export attempt completed")
except Exception as e:
    print(f"✗ Plotly export failed: {e}")

print("\nTest complete!")