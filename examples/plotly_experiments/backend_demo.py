"""
Demonstration of the new backend system
Shows how to create the same star chart with both matplotlib and plotly backends
"""
from datetime import datetime
from pytz import timezone
import starplot as sp

def create_star_chart(backend_name):
    """Create a star chart using the specified backend"""
    print(f"\nCreating star chart with {backend_name} backend...")
    
    # Set up time and location
    tz = timezone("America/Los_Angeles")
    dt = tz.localize(datetime(2024, 1, 1, 22, 0, 0))
    
    # Location: Palomar Observatory
    lat = 33.363484
    lon = -116.836394
    
    # Create the plot
    plot = sp.MapPlot(
        projection=sp.Projection.ZENITH,
        lat=lat,
        lon=lon,
        dt=dt,
        backend=backend_name,
        resolution=1024,
        style=sp.styles.PlotStyle().extend(
            sp.styles.extensions.BLUE_MEDIUM,
        ),
    )
    
    # Add celestial objects
    plot.stars(where=[sp._.magnitude < 4.6])
    plot.constellations()
    plot.constellation_labels()
    
    # Export the chart
    if backend_name == 'matplotlib':
        filename = 'star_chart_matplotlib.png'
        plot.export(filename)
        print(f"✓ {backend_name} chart exported as '{filename}'")
    elif backend_name == 'plotly':
        filename = 'star_chart_plotly.html'
        plot.export(filename)
        print(f"✓ {backend_name} chart exported as '{filename}'")
    
    return plot

def main():
    """Main demonstration function"""
    print("Starplot Backend System Demo")
    print("=" * 40)
    
    # Show available backends
    from starplot.backends import BackendFactory
    backends = BackendFactory.list_backends()
    print(f"Available backends: {', '.join(backends)}")
    
    # Create charts with both backends
    matplotlib_chart = create_star_chart('matplotlib')
    plotly_chart = create_star_chart('plotly')
    
    # Show backend information
    print(f"\nBackend Information:")
    print(f"- Matplotlib backend: {type(matplotlib_chart._backend)}")
    print(f"- Plotly backend: {type(plotly_chart._backend)}")
    
    print(f"\nComparison:")
    print(f"- Both charts show the same celestial objects")
    print(f"- Matplotlib: Static high-quality image (PNG)")
    print(f"- Plotly: Interactive web visualization (HTML)")
    
    print(f"\nFiles created:")
    print(f"- star_chart_matplotlib.png (static image)")
    print(f"- star_chart_plotly.html (interactive web page)")
    
    print(f"\nDemo complete! 🌟")

if __name__ == "__main__":
    main()