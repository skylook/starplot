"""
Example demonstrating the matplotlib and plotly backends
"""
from datetime import datetime
from pytz import timezone
import starplot as sp

# Create timezone
tz = timezone("America/Los_Angeles")
dt = tz.localize(datetime(2024, 1, 1, 22, 0, 0))

# Define location (Palomar Observatory)
lat = 33.363484
lon = -116.836394

# Create style
style = sp.styles.PlotStyle().extend(
    sp.styles.extensions.BLUE_MEDIUM,
)

print("Creating star charts with both backends...")

# Create matplotlib version
print("Creating matplotlib version...")
matplotlib_plot = sp.MapPlot(
    projection=sp.Projection.ZENITH,
    lat=lat,
    lon=lon,
    dt=dt,
    style=style,
    backend='matplotlib',
    resolution=2048,
)

# Add celestial objects
matplotlib_plot.stars(where=[sp._.magnitude < 4.6])
matplotlib_plot.constellations()
matplotlib_plot.constellation_labels()

# Export matplotlib version
matplotlib_plot.export("star_chart_matplotlib.png")
print("✓ Matplotlib chart exported as 'star_chart_matplotlib.png'")

# Create plotly version
print("Creating plotly version...")
plotly_plot = sp.MapPlot(
    projection=sp.Projection.ZENITH,
    lat=lat,
    lon=lon,
    dt=dt,
    style=style,
    backend='plotly',
    resolution=2048,
)

# Add celestial objects
plotly_plot.stars(where=[sp._.magnitude < 4.6])
plotly_plot.constellations()
plotly_plot.constellation_labels()

# Export plotly version
plotly_plot.export("star_chart_plotly.html")
print("✓ Plotly chart exported as 'star_chart_plotly.html'")

print("\nComparison complete!")
print("- Matplotlib version: star_chart_matplotlib.png")
print("- Plotly version: star_chart_plotly.html (interactive)")
print("\nBoth charts should show the same celestial objects but with different rendering:")
print("- Matplotlib: Static high-quality image")
print("- Plotly: Interactive web-based visualization")