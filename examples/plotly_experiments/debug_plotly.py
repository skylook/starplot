#!/usr/bin/env python3
"""
Debug plotly backend data
"""
from datetime import datetime
from pytz import timezone
from starplot import MapPlot, Projection, _
from starplot.styles import PlotStyle, extensions
import json

# Setup
tz = timezone("America/Los_Angeles")
dt = datetime(2023, 7, 13, 22, 0, tzinfo=tz)

def debug_plotly_data():
    """Debug what data plotly is receiving"""
    print("=== Debugging Plotly Backend ===")
    
    # Create plotly plot
    print("\n1. Creating plotly plot...")
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
    
    print(f"   Backend: {plotly_plot._backend}")
    print(f"   Figure created: {hasattr(plotly_plot._backend, 'figure')}")
    
    # Add stars 
    print("\n2. Adding stars...")
    plotly_plot.stars(where=[_.magnitude < 3.0])
    
    # Check what's in the figure
    if hasattr(plotly_plot._backend, 'figure') and plotly_plot._backend.figure:
        fig = plotly_plot._backend.figure
        print(f"   Number of traces: {len(fig.data)}")
        
        for i, trace in enumerate(fig.data):
            print(f"   Trace {i}: {trace.type}, {len(trace.x) if hasattr(trace, 'x') and trace.x else 0} points")
        
        # Export data structure to understand what's happening
        fig_dict = fig.to_dict()
        with open('plotly_debug_data.json', 'w') as f:
            json.dump(fig_dict, f, indent=2, default=str)
        print("   Debug data exported to plotly_debug_data.json")
    else:
        print("   No figure found!")
    
    # Export the plot
    plotly_plot.export("debug_plotly.html")
    print("   HTML exported")
    
    print("\n3. Analysis:")
    print("This debug helps us understand why the plotly HTML shows no stars.")
    print("The issue is likely that the existing starplot methods don't")
    print("integrate with the backend system for data transfer.")

if __name__ == "__main__":
    debug_plotly_data()