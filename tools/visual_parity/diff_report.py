#!/usr/bin/env python3
"""Generate a pixel diff report for comparison_outputs.

Usage:
    python tools/visual_parity/diff_report.py
"""
from PIL import Image
import numpy as np
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2] / "comparison_outputs"

def compare(a, b):
    # Composite both images onto a white background so transparent pixels
    # (alpha=0) are compared consistently.  The resulting alpha is 255 everywhere,
    # so only RGB differences matter (transparent areas become white in both).
    def composite_white(img):
        rgba = img.convert('RGBA')
        bg = Image.new('RGBA', rgba.size, (255, 255, 255, 255))
        return Image.alpha_composite(bg, rgba)

    aa = np.array(composite_white(a)).astype(np.float32)
    bb = np.array(composite_white(b)).astype(np.float32)
    diff = np.abs(aa - bb)
    total = diff.size
    nz = np.count_nonzero(diff)
    return {
        'size': a.size,
        'max': float(diff.max()),
        'mean': float(diff.mean()),
        'nonzero_percent': nz / total * 100,
    }

orig_files = sorted(ROOT.glob('orig_*.png'))
rows = []

for orig_path in orig_files:
    name = orig_path.stem.replace('orig_', '')
    int_path = ROOT / f'int_{name}_interactive.png'
    plotly_path = ROOT / f'int_{name}_interactive_plotly.png'

    row = {'name': name}

    if int_path.exists():
        orig = Image.open(orig_path)
        int_img = Image.open(int_path)
        if orig.size == int_img.size:
            row['orig_vs_int'] = compare(orig, int_img)
        else:
            row['orig_vs_int'] = {'size': orig.size, 'note': 'size mismatch'}

    if plotly_path.exists():
        orig = Image.open(orig_path)
        int_img = Image.open(int_path) if int_path.exists() else None
        plotly = Image.open(plotly_path)
        orig_r = orig.resize(plotly.size, Image.Resampling.LANCZOS)
        if int_img is not None:
            int_r = int_img.resize(plotly.size, Image.Resampling.LANCZOS)
            row['int_vs_plotly'] = compare(int_r, plotly)
        else:
            row['int_vs_plotly'] = {'note': 'no int png'}
        row['orig_vs_plotly'] = compare(orig_r, plotly)
    else:
        row['plotly'] = 'missing'

    rows.append(row)

lines = []
lines.append('# Pixel diff report for comparison_outputs\n')
lines.append('This report compares the original matplotlib PNG (`orig_*.png`),')
lines.append('the matplotlib export from `Interactive*Plot` (`int_*_interactive.png`),')
lines.append('and the static Plotly snapshot (`int_*_interactive_plotly.png`).\n')
lines.append('## Legend')
lines.append('- `nonzero%`: percentage of all RGBA values that differ by at least 1/255')
lines.append('- `max`: largest per-channel difference (0-255)')
lines.append('- `mean`: average per-channel difference')
lines.append('- Plotly snapshots are compared after resizing the original matplotlib image to the Plotly PNG size.\n')

lines.append('| Example | orig vs int (matplotlib) | int vs plotly | orig vs plotly |')
lines.append('|---------|----------------------------|---------------|----------------|')

def fmt(d):
    if isinstance(d, dict):
        if 'note' in d:
            return d['note']
        return f"max={d['max']:.0f} mean={d['mean']:.2f} nz={d['nonzero_percent']:.2f}%"
    return str(d)

for row in rows:
    name = row['name']
    o_i = fmt(row.get('orig_vs_int', 'missing'))
    i_p = fmt(row.get('int_vs_plotly', 'missing'))
    o_p = fmt(row.get('orig_vs_plotly', 'missing'))
    lines.append(f'| {name} | {o_i} | {i_p} | {o_p} |')

lines.append('\n')
lines.append('## Notes')
lines.append('- `orig vs int` should be very close; any non-zero difference is usually due to DuckDB/catalog row ordering and star overdraw, not a RecordingMixin bug.')
lines.append('- `orig vs plotly` will be larger because Plotly PNGs are lower resolution and may have white paper/margin backgrounds, while many `orig` examples use `transparent=True`.')
lines.append('- `int vs plotly` is the most useful comparison for Plotly parity; values above 30-40% are typically dominated by resolution, margins, and background, not content.')

out = ROOT / 'diff_report.md'
out.write_text('\n'.join(lines))
print(f'Wrote {out}')
