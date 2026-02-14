"""
Simple comparison of matplotlib vs plotly backends
"""
from datetime import datetime
from pytz import timezone
from starplot import MapPlot, Projection, _
from starplot.styles import PlotStyle, extensions
import os

# Setup
tz = timezone("America/Los_Angeles")
dt = datetime(2023, 7, 13, 22, 0, tzinfo=tz)

def create_star_chart(backend_name, suffix):
    """Create a star chart with the specified backend"""
    print(f"\nCreating star chart with {backend_name} backend...")
    
    p = MapPlot(
        projection=Projection.ZENITH,
        lat=33.363484,
        lon=-116.836394,
        dt=dt,
        style=PlotStyle().extend(extensions.BLUE_GOLD),
        resolution=1024,
        autoscale=True,
        backend=backend_name,
    )
    
    # Add celestial objects
    p.stars(where=[_.magnitude < 4.6], where_labels=[_.magnitude < 2.1])
    p.constellations()
    p.constellation_labels()
    p.horizon()
    
    # Export based on backend
    if backend_name == "matplotlib":
        filename = f"star_chart_{suffix}.png"
        p.export(filename, transparent=True, padding=0.1)
    elif backend_name == "plotly":
        filename = f"star_chart_{suffix}.html"
        p.export(filename)
    
    print(f"✓ Export attempted: {filename}")
    
    # Check if file exists
    if os.path.exists(filename):
        print(f"✓ File created: {filename}")
        print(f"  Size: {os.path.getsize(filename)} bytes")
        return filename
    else:
        print(f"✗ File not found: {filename}")
        return None

def main():
    """Main function"""
    print("Star Chart Backend Comparison")
    print("=" * 40)
    
    # Create matplotlib version
    matplotlib_file = create_star_chart("matplotlib", "matplotlib")
    
    # Create plotly version
    plotly_file = create_star_chart("plotly", "plotly")
    
    # Summary
    print(f"\nSummary:")
    if matplotlib_file:
        print(f"✓ Matplotlib: {matplotlib_file}")
    else:
        print(f"✗ Matplotlib: Failed to create")
        
    if plotly_file:
        print(f"✓ Plotly: {plotly_file}")
    else:
        print(f"✗ Plotly: Failed to create")
    
    print(f"\nComparison complete!")

if __name__ == "__main__":
    main()