#!/usr/bin/env python3
"""Generate a pixel diff report for per-example comparison_outputs.

Usage:
    python tools/visual_parity/diff_report.py

Scans ``comparison_outputs/<example>/`` for the PNGs produced by
``gen_comparison.py`` and writes ``comparison_outputs/diff_report.md``.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
from PIL import Image

if __package__:
    from . import crops
else:
    import crops

ROOT = Path(__file__).resolve().parents[2] / "comparison_outputs"
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def compare(a: Image.Image, b: Image.Image) -> dict:
    """Return per-channel diff stats after compositing both images onto white.

    ``a`` is resized to ``b``'s dimensions if they differ, so renderings with
    different pixel sizes can still be compared.
    """
    if a.size != b.size:
        a = a.resize(b.size, Image.Resampling.LANCZOS)
    a_array = np.asarray(crops.composite_on_color(a, (255, 255, 255)), dtype=np.float32)
    b_array = np.asarray(crops.composite_on_color(b, (255, 255, 255)), dtype=np.float32)
    delta = np.abs(a_array - b_array)
    total = delta.size
    nz = np.count_nonzero(delta)
    return {
        "size": b.size,
        "max": float(delta.max()),
        "mean": float(delta.mean()),
        "nonzero_percent": nz / total * 100,
    }


def _fmt(d: dict | None) -> str:
    if d is None:
        return "missing"
    if "note" in d:
        return d["note"]
    return f"max={d['max']:.0f} mean={d['mean']:.2f} nz={d['nonzero_percent']:.2f}%"


def main() -> None:
    rows = []
    for folder in sorted(ROOT.iterdir()):
        if not folder.is_dir() or not _SAFE_NAME_RE.fullmatch(folder.name):
            continue
        orig = folder / "orig.png"
        interactive = folder / "interactive.png"
        plotly = folder / "plotly.png"
        inline = folder / "inline.png"
        external = folder / "external.png"
        provider = folder / "provider.png"
        if not orig.exists():
            continue

        row = {"name": folder.name}

        with Image.open(orig) as orig_img:
            if interactive.exists():
                with Image.open(interactive) as interactive_img:
                    row["orig vs interactive"] = compare(orig_img, interactive_img)
            if plotly.exists():
                with Image.open(plotly) as plotly_img:
                    row["orig vs plotly"] = compare(orig_img, plotly_img)
                    if interactive.exists():
                        with Image.open(interactive) as interactive_img:
                            row["interactive vs plotly"] = compare(interactive_img, plotly_img)
            if inline.exists():
                with Image.open(inline) as inline_img:
                    row["orig vs inline"] = compare(orig_img, inline_img)
            if external.exists():
                with Image.open(external) as external_img:
                    row["orig vs external"] = compare(orig_img, external_img)
            if provider.exists():
                with Image.open(provider) as provider_img:
                    row["orig vs provider"] = compare(orig_img, provider_img)

        rows.append(row)

    if not rows:
        print(f"No comparison folders found under {ROOT}")
        return

    columns = [
        "orig vs interactive",
        "orig vs plotly",
        "orig vs inline",
        "orig vs external",
        "orig vs provider",
        "interactive vs plotly",
    ]
    header = "| Example | " + " | ".join(columns) + " |"
    separator = "|---|---|---|---|---|---|---|"

    lines = [
        "# Pixel diff report for comparison_outputs\n",
        "This report compares the original matplotlib PNG with the outputs produced by ``gen_comparison.py``.\n",
        "## Legend",
        "- `nz`: percentage of all pixel values that differ by at least 1/255",
        "- `max`: largest per-channel difference (0-255)",
        "- `mean`: average per-channel difference\n",
        header,
        separator,
    ]
    for row in rows:
        cells = [row["name"]] + [_fmt(row.get(column)) for column in columns]
        lines.append("| " + " | ".join(cells) + " |")

    lines.append("\n")
    lines.append("## Notes")
    lines.append("- `orig vs interactive` compares the original matplotlib render with the static matplotlib export from `Interactive*Plot`.")
    lines.append("- `orig vs plotly` compares the original to the static Plotly snapshot generated via kaleido.")
    lines.append("- `orig vs inline/external/provider` compares the original to each browser-rendered transport.")
    lines.append("- Differences above 30-40% are usually dominated by resolution, margins, and background, not content.")

    out = ROOT / "diff_report.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
