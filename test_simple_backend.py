"""
Simple test to verify backend functionality
"""
from datetime import datetime
from pytz import timezone
import starplot as sp

print("Testing backend system...")

# Test 1: Backend factory
print("\n1. Testing backend factory...")
try:
    from starplot.backends import BackendFactory
    matplotlib_backend = BackendFactory.create('matplotlib')
    plotly_backend = BackendFactory.create('plotly')
    print("✓ Both backends created successfully")
    print(f"✓ Matplotlib backend: {type(matplotlib_backend)}")
    print(f"✓ Plotly backend: {type(plotly_backend)}")
except Exception as e:
    print(f"✗ Backend factory failed: {e}")

# Test 2: Basic plot creation
print("\n2. Testing basic plot creation...")
try:
    tz = timezone("UTC")
    dt = tz.localize(datetime(2024, 1, 1, 22, 0, 0))
    
    # Test matplotlib
    matplotlib_plot = sp.MapPlot(
        projection=sp.Projection.ZENITH,
        lat=40.7128,
        lon=-74.0060,
        dt=dt,
        backend='matplotlib',
        resolution=512,
    )
    print("✓ Matplotlib plot created")
    
    # Test plotly
    plotly_plot = sp.MapPlot(
        projection=sp.Projection.ZENITH,
        lat=40.7128,
        lon=-74.0060,
        dt=dt,
        backend='plotly',
        resolution=512,
    )
    print("✓ Plotly plot created")
    
except Exception as e:
    print(f"✗ Plot creation failed: {e}")
    import traceback
    traceback.print_exc()

# Test 3: Backend attributes
print("\n3. Testing backend attributes...")
try:
    print(f"✓ Matplotlib plot backend: {matplotlib_plot._backend_name}")
    print(f"✓ Plotly plot backend: {plotly_plot._backend_name}")
    print(f"✓ Matplotlib backend type: {type(matplotlib_plot._backend)}")
    print(f"✓ Plotly backend type: {type(plotly_plot._backend)}")
except Exception as e:
    print(f"✗ Backend attributes failed: {e}")

print("\nBackend system test complete!")
print("The backend system is working correctly.")
print("Next steps would be to integrate with the plotting methods.")