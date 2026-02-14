#!/usr/bin/env python
"""Analyze star sizes in matplotlib vs plotly"""
from datetime import datetime
from zoneinfo import ZoneInfo
from starplot.interactive import InteractiveZenithPlot
from starplot import Observer, _
from starplot.styles import PlotStyle, extensions
from starplot.interactive.style_converter import calibrate_marker_size
import math

tz = ZoneInfo('America/Los_Angeles')
dt = datetime(2023, 7, 13, 22, 0, tzinfo=tz)
observer = Observer(dt=dt, lat=33.363484, lon=-116.836394)

p = InteractiveZenithPlot(
    observer=observer,
    style=PlotStyle().extend(extensions.BLUE_MEDIUM),
    resolution=3600,
    autoscale=True,
)
p.stars(where=[_.magnitude < 4.6], where_labels=[_.magnitude < 2.4])

# Get star sizes
cmds = p._recorder.commands
star_cmds = [c for c in cmds if c.kind == 'scatter' and isinstance(c.metadata, dict) and c.metadata.get('type') == 'star']

if star_cmds:
    mpl_sizes = star_cmds[0].data['sizes']
    print(f"Matplotlib star sizes (points²):")
    print(f"  Count: {len(mpl_sizes)}")
    print(f"  Range: {min(mpl_sizes):.2f} - {max(mpl_sizes):.2f}")
    print(f"  Mean: {sum(mpl_sizes)/len(mpl_sizes):.2f}")
    
    # Show distribution
    bins = [0, 50, 100, 200, 500, 1000, 2000, 5000]
    for i in range(len(bins)-1):
        count = sum(1 for s in mpl_sizes if bins[i] <= s < bins[i+1])
        print(f"  {bins[i]:4d}-{bins[i+1]:4d}: {count:3d} stars")
    
    print(f"\nPlotly conversion (resolution={p.resolution}):")
    print(f"  Formula: diameter = 2 × sqrt(s/π) × 1.389 × (1000/{p.resolution})")
    
    # Test conversions
    test_sizes = [min(mpl_sizes), 100, 500, 1000, max(mpl_sizes)]
    for s in test_sizes:
        plotly_size = calibrate_marker_size(s, resolution=p.resolution)
        # Calculate what matplotlib would show (approximate)
        mpl_radius_px = math.sqrt(s / math.pi) * 1.389  # at DPI=100
        print(f"  mpl_size={s:6.1f} -> mpl_radius≈{mpl_radius_px:.2f}px -> plotly_diameter={plotly_size:.2f}px")
    
    print(f"\nCurrent formula may be too large. Let's check what factor would match:")
    # For a typical star (size=500), what should the plotly size be?
    typical_mpl = 500
    typical_mpl_radius = math.sqrt(typical_mpl / math.pi) * 1.389
    print(f"  Typical star (mpl_size=500):")
    print(f"    matplotlib radius ≈ {typical_mpl_radius:.2f}px")
    print(f"    Current plotly diameter = {calibrate_marker_size(typical_mpl, resolution=3600):.2f}px")
    print(f"    Suggested plotly diameter = {typical_mpl_radius * 2:.2f}px (if 1:1 scale)")
    
    # Calculate correction factor
    current = calibrate_marker_size(typical_mpl, resolution=3600)
    suggested = typical_mpl_radius * 2
    factor = suggested / current
    print(f"    Correction factor needed: {factor:.3f}")
