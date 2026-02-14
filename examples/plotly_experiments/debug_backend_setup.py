#!/usr/bin/env python3
"""
Debug backend setup
"""
from datetime import datetime
from pytz import timezone
from starplot import MapPlot, Projection, _
from starplot.styles import PlotStyle, extensions

# Setup
tz = timezone("America/Los_Angeles")
dt = datetime(2023, 7, 13, 22, 0, tzinfo=tz)

def debug_backend_setup():
    """Debug backend setup and attributes"""
    print("=== Debugging Backend Setup ===")
    
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
    
    print(f"   Plot created successfully")
    print(f"   Has _backend: {hasattr(matplotlib_plot, '_backend')}")
    print(f"   Has _backend_name: {hasattr(matplotlib_plot, '_backend_name')}")
    print(f"   Has fig: {hasattr(matplotlib_plot, 'fig')}")
    print(f"   Has ax: {hasattr(matplotlib_plot, 'ax')}")
    
    if hasattr(matplotlib_plot, '_backend'):
        print(f"   Backend type: {type(matplotlib_plot._backend)}")
        print(f"   Backend has ax: {hasattr(matplotlib_plot._backend, 'ax')}")
        if hasattr(matplotlib_plot._backend, 'ax'):
            print(f"   Backend ax value: {matplotlib_plot._backend.ax}")
    
    if hasattr(matplotlib_plot, '_backend_name'):
        print(f"   Backend name: {matplotlib_plot._backend_name}")
    
    # Try to access the ax attribute directly
    try:
        ax = matplotlib_plot.ax
        print(f"   Direct ax access successful: {type(ax)}")
    except Exception as e:
        print(f"   Direct ax access failed: {e}")
    
    # Try to access the fig attribute
    try:
        fig = matplotlib_plot.fig
        print(f"   Direct fig access successful: {type(fig)}")
    except Exception as e:
        print(f"   Direct fig access failed: {e}")
    
    print("\n2. Analysis:")
    print("   Investigating where matplotlib figure and axes are created...")

if __name__ == "__main__":
    debug_backend_setup()