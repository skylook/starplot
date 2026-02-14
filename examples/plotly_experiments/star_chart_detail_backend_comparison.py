"""
Modified version of star_chart_detail.py to compare matplotlib and plotly backends
"""
from datetime import datetime
from pytz import timezone
from starplot import MapPlot, Projection, Star, DSO, _
from starplot.styles import PlotStyle, extensions

# Common settings
tz = timezone("America/Los_Angeles")
dt = datetime(2023, 7, 13, 22, 0, tzinfo=tz)  # July 13, 2023 at 10pm PT

# Common style
style = PlotStyle().extend(extensions.BLUE_GOLD)

# Common plot settings
plot_settings = {
    "projection": Projection.ZENITH,
    "lat": 33.363484,
    "lon": -116.836394,
    "dt": dt,
    "style": style,
    "resolution": 3600,
    "autoscale": True,
}

def create_star_chart(backend_name):
    """Create a detailed star chart with the specified backend"""
    print(f"\nCreating detailed star chart with {backend_name} backend...")
    
    # Create the plot with specified backend
    p = MapPlot(
        **plot_settings,
        backend=backend_name
    )
    
    # Add celestial objects
    p.horizon()
    p.constellations()
    p.stars(where=[_.magnitude < 4.6], where_labels=[_.magnitude < 2.1])
    
    p.galaxies(where=[_.magnitude < 9], true_size=False, labels=None)
    p.open_clusters(where=[_.magnitude < 9], true_size=False, labels=None)
    
    p.constellation_borders()
    p.ecliptic()
    p.celestial_equator()
    p.milky_way()
    
    # Add special marker for Mel 111
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
    
    # Export with backend-specific filename
    if backend_name == "matplotlib":
        filename = "star_chart_detail_matplotlib.png"
        p.export(filename, transparent=True, padding=0.1)
    elif backend_name == "plotly":
        filename = "star_chart_detail_plotly.html"
        p.export(filename, transparent=True, padding=0.1)
    
    print(f"✓ {backend_name} chart exported as '{filename}'")
    return p, filename

def main():
    """Main function to create and compare charts"""
    print("Creating detailed star chart comparison...")
    print("=" * 50)
    
    # Create matplotlib version
    matplotlib_plot, matplotlib_file = create_star_chart("matplotlib")
    
    # Create plotly version  
    plotly_plot, plotly_file = create_star_chart("plotly")
    
    # Show comparison information
    print(f"\nComparison Results:")
    print(f"- Matplotlib: {matplotlib_file}")
    print(f"- Plotly: {plotly_file}")
    
    print(f"\nChart features:")
    print(f"- Horizon line")
    print(f"- Constellations and labels")
    print(f"- Stars (magnitude < 4.6)")
    print(f"- Bright star labels (magnitude < 2.1)")
    print(f"- Galaxies and open clusters (magnitude < 9)")
    print(f"- Constellation borders")
    print(f"- Ecliptic and celestial equator")
    print(f"- Milky Way")
    print(f"- Special marker for Mel 111")
    
    print(f"\nBackend comparison:")
    print(f"- Matplotlib: Static high-resolution PNG image")
    print(f"- Plotly: Interactive HTML visualization")
    print(f"- Both should show identical celestial object placement")
    
    # Show backend information
    print(f"\nBackend details:")
    print(f"- Matplotlib backend: {type(matplotlib_plot._backend)}")
    print(f"- Plotly backend: {type(plotly_plot._backend)}")
    
    print(f"\nComparison complete! 🌟")

if __name__ == "__main__":
    main()