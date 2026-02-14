"""
Debug export functionality
"""
from datetime import datetime
from pytz import timezone
from starplot import MapPlot, Projection
from starplot.styles import PlotStyle, extensions

# Setup
tz = timezone("America/Los_Angeles")
dt = datetime(2023, 7, 13, 22, 0, tzinfo=tz)

print("Debugging export functionality...")

# Create plot
p = MapPlot(
    projection=Projection.ZENITH,
    lat=33.363484,
    lon=-116.836394,
    dt=dt,
    style=PlotStyle().extend(extensions.BLUE_GOLD),
    resolution=512,
    autoscale=True,
    backend="matplotlib",
)

print(f"Backend: {p._backend_name}")
print(f"Backend type: {type(p._backend)}")
print(f"Backend figure: {p._backend.figure}")
print(f"Has fig attribute: {hasattr(p, 'fig')}")

if hasattr(p, 'fig'):
    print(f"Plot fig: {p.fig}")
else:
    print("No fig attribute found")

# Try to get matplotlib figure
try:
    import matplotlib.pyplot as plt
    current_fig = plt.gcf()
    print(f"Current matplotlib figure: {current_fig}")
except Exception as e:
    print(f"Error getting matplotlib figure: {e}")

# Check if we can access the figure through the backend
try:
    backend_fig = p._backend.get_figure()
    print(f"Backend figure via get_figure(): {backend_fig}")
except Exception as e:
    print(f"Error getting backend figure: {e}")

print("\nDebug complete!")