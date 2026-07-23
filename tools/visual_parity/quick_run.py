#!/usr/bin/env python3
"""Quickly run a single example pair for step-by-step debugging.

Usage:
    python tools/visual_parity/quick_run.py horizon_sgr

This only runs the named original + interactive example and regenerates the
png/html files in comparison_outputs/. It does NOT re-download catalogs if they
are already cached.
"""

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "comparison_outputs"


def main(name: str):
    original = ROOT / 'examples' / f'{name}.py'
    interactive = ROOT / 'examples' / 'interactive' / f'{name}_interactive.py'
    if not original.exists():
        print(f'Original example not found: {original}')
        sys.exit(1)
    if not interactive.exists():
        print(f'Interactive example not found: {interactive}')
        sys.exit(1)

    # Remove stale outputs for this pair
    for suffix in ('.png', '.html', '_plotly.png'):
        for p in [
            OUTPUT / f'{name}{suffix}',
            OUTPUT / f'{name}_interactive{suffix}',
            OUTPUT / f'orig_{name}{suffix}',
            OUTPUT / f'int_{name}_interactive{suffix}',
        ]:
            if p.exists():
                p.unlink()

    print(f'Running original: {original.name}')
    result = subprocess.run(
        [sys.executable, str(original)],
        cwd=OUTPUT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        timeout=900,
    )
    if result.returncode != 0:
        print('FAIL')
        print(result.stderr)
        return
    print('OK')

    # Immediately rename the original output so the interactive run (which uses
    # the same filename via p.export) does NOT overwrite it.
    orig_png = OUTPUT / f'{name}.png'
    orig_dst = OUTPUT / f'orig_{name}.png'
    if orig_png.exists():
        orig_png.replace(orig_dst)

    # The interactive example calls export_html.  We monkey-patch it only for
    # verification so the example still produces an HTML export and an additional
    # static Plotly PNG snapshot without modifying library code.
    wrapper = f'''
import pathlib, runpy
import starplot.interactive.plots as _p

_orig = _p._InteractiveMixin.export_html

def _patched_export_html(self, filename, width=None, height=None, transparent=False, **kwargs):
    # Preserve the original export behaviour.
    _orig(self, filename, width=width, height=height, transparent=transparent, **kwargs)
    # Render the same figure to a PNG for visual comparison.
    fig = self.to_plotly(width=width, height=height, transparent=transparent)
    if width or height:
        fig.update_layout(width=width or fig.layout.width, height=height or fig.layout.height)
    png_path = pathlib.Path(filename).with_name(pathlib.Path(filename).stem + "_plotly.png")
    fig.write_image(str(png_path), width=width, height=height)

_p._InteractiveMixin.export_html = _patched_export_html

runpy.run_path({str(interactive)!r}, run_name="__main__")
'''
    print(f'Running interactive: {interactive.name}')
    result = subprocess.run(
        [sys.executable, '-c', wrapper],
        cwd=OUTPUT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        timeout=900,
    )
    if result.returncode != 0:
        print('FAIL')
        print(result.stderr)
        return
    print('OK')

    # Rename interactive outputs to comparison naming convention.
    # The original PNG was already renamed above (orig_{name}.png).
    # The interactive example produces {name}.png (matplotlib export from
    # the Interactive*Plot class) and {name}_plotly.png (Plotly snapshot).
    for src_name, dst_prefix in [
        (f'{name}.png', f'int_{name}_interactive'),
        (f'{name}_plotly.png', f'int_{name}_interactive_plotly'),
    ]:
        src = OUTPUT / src_name
        dst = OUTPUT / f'{dst_prefix}.png'
        if src.exists():
            src.replace(dst)

    print('Done. Run `python tools/visual_parity/diff_report.py` to see the diff for this pair.')


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: python quick_run.py <example_name>')
        print('Examples: horizon_sgr, map_orion, star_chart_basic')
        sys.exit(1)
    main(sys.argv[1])
