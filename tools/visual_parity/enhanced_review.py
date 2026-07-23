#!/usr/bin/env python3
"""Generate an enhanced review page with full-image + zoomed-crop comparisons.

Crops are taken from the same normalized regions of `orig.png` and `inline.png`,
with `inline.png` resized to `orig.png` dimensions using Lanczos resampling so
that stars/labels/clusters align for side-by-side and diff inspection.

The ``--semantic`` mode also extracts crops around bright stars, dense clusters,
and high-gradient line/edge regions so important chart features are reviewed
locally.
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
from http.server import HTTPServer, SimpleHTTPRequestHandler
import threading
import webbrowser

import numpy as np
from PIL import Image, ImageChops

try:
    from scipy import ndimage as _ndimage
except ImportError:  # pragma: no cover - semantic crops are optional
    _ndimage = None

ROOT = pathlib.Path(__file__).resolve().parents[2] / "comparison_outputs"
CROP_DIR = ROOT / "_crops"
HTML_PATH = ROOT / "_enhanced_review.html"
PORT = 8766

# (name, normalized box as (x0, y0, x1, y1), description)
CROP_BOXES = [
    ("center", (0.30, 0.30, 0.70, 0.70), "center region"),
    ("top-left", (0.00, 0.70, 0.30, 1.00), "top-left"),
    ("top-right", (0.70, 0.70, 1.00, 1.00), "top-right"),
    ("bottom-left", (0.00, 0.00, 0.30, 0.30), "bottom-left"),
    ("bottom-right", (0.70, 0.00, 1.00, 0.30), "bottom-right"),
    ("middle-left", (0.00, 0.35, 0.25, 0.65), "middle-left"),
    ("middle-right", (0.75, 0.35, 1.00, 0.65), "middle-right"),
    ("upper-center", (0.35, 0.75, 0.65, 1.00), "upper-center"),
]


def crop_box(width: int, height: int, box: tuple[float, float, float, float]) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = box
    return (
        int(round(x0 * width)),
        int(round(y0 * height)),
        int(round(x1 * width)),
        int(round(y1 * height)),
    )


def _composite_on_black(img: Image.Image) -> Image.Image:
    """Composite an RGBA image onto a black background so transparent
    regions compare consistently with browser screenshots."""
    if img.mode == "RGBA":
        black = Image.new("RGB", img.size, (0, 0, 0))
        black.paste(img, mask=img.getchannel("A"))
        return black
    return img.convert("RGB")


def diff_stats(orig: Image.Image, inline: Image.Image) -> dict[str, float]:
    """Return diff metrics when both images are the same size."""
    orig_g = _composite_on_black(orig).convert("L")
    inline_g = _composite_on_black(inline).convert("L")
    diff = ImageChops.difference(orig_g, inline_g)
    arr = np.asarray(diff, dtype=np.float32)
    mae = float(arr.mean())
    rmse = float(math.sqrt((arr * arr).mean()))
    nonzero = float(np.count_nonzero(arr > 5)) / arr.size * 100.0
    max_diff = float(arr.max())
    return {
        "mae": round(mae, 2),
        "rmse": round(rmse, 2),
        "nonzero_gt5": round(nonzero, 2),
        "max_diff": round(max_diff, 2),
    }


def _semantic_crop_boxes(
    img: Image.Image,
    count: int = 8,
) -> list[tuple[str, tuple[float, float, float, float], str]]:
    """Detect semantic regions (bright stars, clusters, lines/edges) and return crop boxes.

    Falls back to geometric boxes when scipy is unavailable or no salient features
    are found.
    """
    if _ndimage is None:
        return CROP_BOXES[:count]

    gray = np.asarray(_composite_on_black(img).convert("L"), dtype=np.float32)
    height, width = gray.shape
    min_dim = min(width, height)
    crop_px = max(300, min_dim // 4)
    half_x = crop_px / (2 * width)
    half_y = crop_px / (2 * height)

    def to_box(cy: int, cx: int) -> tuple[float, float, float, float]:
        x = cx / width
        y = cy / height
        return (
            max(0.0, x - half_x),
            max(0.0, y - half_y),
            min(1.0, x + half_x),
            min(1.0, y + half_y),
        )

    def pick(
        coords: np.ndarray,
        scores: np.ndarray,
        label: str,
        existing: list[tuple[int, int]],
        min_distance: float,
    ) -> list[tuple[str, tuple[float, float, float, float], str]]:
        chosen = []
        order = np.argsort(scores)[::-1]
        for index in order:
            cy, cx = coords[index]
            if any(
                math.hypot(cx - ex, cy - ey) < min_distance for ey, ex in existing
            ):
                continue
            existing.append((cy, cx))
            name = f"{label.replace('/', '-')}-{len(chosen) + 1}"
            chosen.append((name, to_box(cy, cx), label))
            if len(chosen) >= count:
                break
        return chosen

    # 1. Bright stars: local maxima above a high intensity threshold.
    bright_max = _ndimage.maximum_filter(gray, size=15, mode="constant")
    bright_threshold = max(np.percentile(gray, 95), gray.mean() + 1.5 * gray.std())
    bright_mask = (gray == bright_max) & (gray > bright_threshold)
    bright_coords = np.argwhere(bright_mask)
    bright_scores = gray[bright_mask]

    # 2. Dense clusters: large connected components above the mean.
    binary = gray > (gray.mean() + 0.5 * gray.std())
    labeled, num_labels = _ndimage.label(binary)
    if num_labels:
        areas = _ndimage.sum(binary, labeled, index=range(1, num_labels + 1))
        centers = _ndimage.center_of_mass(gray, labeled, index=range(1, num_labels + 1))
        valid = areas > 100
        centers = np.asarray(centers)[valid]
        cluster_points = centers[:, :2].astype(int)
        cluster_scores = areas[valid].astype(np.float32)
    else:
        cluster_points = np.empty((0, 2), dtype=int)
        cluster_scores = np.empty(0, dtype=np.float32)

    # 3. Lines / arrows / edges: high Sobel-gradient local maxima.
    grad_x = _ndimage.sobel(gray, axis=1)
    grad_y = _ndimage.sobel(gray, axis=0)
    gradient = np.hypot(grad_x, grad_y)
    edge_max = _ndimage.maximum_filter(gradient, size=15, mode="constant")
    edge_threshold = max(np.percentile(gradient, 95), gradient.mean() + 2 * gradient.std())
    edge_mask = (gradient == edge_max) & (gradient > edge_threshold)
    edge_coords = np.argwhere(edge_mask)
    edge_scores = gradient[edge_mask]

    min_distance = min_dim * 0.15
    existing: list[tuple[int, int]] = []
    results: list[tuple[str, tuple[float, float, float, float], str]] = []

    sources = (
        ("bright-star", bright_coords, bright_scores),
        ("cluster", cluster_points, cluster_scores),
        ("lines/arrows", edge_coords, edge_scores),
    )
    per_source = max(1, count // len(sources))
    for source, coords, scores in sources:
        if len(coords) == 0:
            continue
        results.extend(pick(coords, scores, source, existing, min_distance)[:per_source])

    # If semantic detection produced too few crops, pad with the geometric boxes.
    if len(results) < count:
        results.extend(CROP_BOXES[: max(0, count - len(results))])

    return results[:count]


def build(semantic: bool = False):
    CROP_DIR.mkdir(exist_ok=True)
    # Clean old crops
    for p in CROP_DIR.iterdir():
        if p.is_file():
            p.unlink()

    rows = []
    for d in sorted(ROOT.iterdir()):
        if not d.is_dir():
            continue
        orig_path = d / "orig.png"
        inline_path = d / "inline.png"
        if not orig_path.exists() or not inline_path.exists():
            continue

        orig = Image.open(orig_path).convert("RGBA")
        inline_raw = Image.open(inline_path).convert("RGBA")
        # Resize inline to orig size so crops correspond to the same sky area.
        inline = inline_raw.resize(orig.size, Image.Resampling.LANCZOS)

        full_stats = diff_stats(orig, inline)
        crop_entries = []
        crop_boxes = _semantic_crop_boxes(orig) if semantic else CROP_BOXES
        for crop_name, box, desc in crop_boxes:
            crop_orig = orig.crop(crop_box(*orig.size, box))
            crop_inline = inline.crop(crop_box(*inline.size, box))
            stats = diff_stats(crop_orig, crop_inline)

            # Save side-by-side crop
            combined = Image.new("RGBA", (crop_orig.width * 2, crop_orig.height))
            combined.paste(crop_orig, (0, 0))
            combined.paste(crop_inline, (crop_orig.width, 0))
            combined_path = CROP_DIR / f"{d.name}_{crop_name}.png"
            combined.save(combined_path)

            # Save diff visualization (scaled)
            diff_img = ImageChops.difference(crop_orig.convert("L"), crop_inline.convert("L"))
            diff_vis = diff_img.point(lambda v: min(255, v * 4))
            diff_path = CROP_DIR / f"{d.name}_{crop_name}_diff.png"
            diff_vis.save(diff_path)

            crop_entries.append({
                "name": crop_name,
                "desc": desc,
                "combined": str(combined_path.relative_to(ROOT)),
                "diff": str(diff_path.relative_to(ROOT)),
                "stats": stats,
            })

        rows.append({
            "name": d.name,
            "orig": str(orig_path.relative_to(ROOT)),
            "inline": str(inline_path.relative_to(ROOT)),
            "full_stats": full_stats,
            "crops": crop_entries,
        })

    rows.sort(key=lambda r: r["name"])

    # Compute aggregate ranking by full nonzero diff
    rows.sort(key=lambda r: r["full_stats"]["nonzero_gt5"], reverse=True)

    html = generate_html(rows)
    HTML_PATH.write_text(html, encoding="utf-8")
    return rows


def generate_html(rows: list[dict]) -> str:
    rows_json = json.dumps(rows)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Starplot Enhanced Parity Review</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #12121f; color: #e0e0e0; padding: 20px;
  }}
  h1 {{ font-size: 22px; margin-bottom: 12px; color: #8be9fd; }}
  .summary {{
    position: sticky; top: 0; background: #12121f; z-index: 100;
    padding: 12px 0; border-bottom: 1px solid #333; margin-bottom: 16px;
  }}
  table {{ width: 100%; border-collapse: collapse; margin-bottom: 30px; }}
  th, td {{ text-align: left; padding: 8px; border-bottom: 1px solid #2a2a3e; font-size: 13px; }}
  th {{ color: #888; position: sticky; top: 70px; background: #12121f; }}
  tr:hover {{ background: #1e1e34; }}
  .ex-header {{
    margin: 24px 0 8px; font-size: 18px; color: #bd93f9; border-bottom: 2px solid #333;
    padding-bottom: 6px;
  }}
  .stats {{ color: #888; font-size: 12px; margin-left: 12px; }}
  .img-row {{ display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 16px; }}
  .img-row img {{ max-width: 100%; border: 1px solid #333; border-radius: 4px; }}
  .crop-card {{
    width: 340px; background: #1a1a2e; border: 1px solid #2a2a3e; border-radius: 6px;
    padding: 8px; margin: 4px;
  }}
  .crop-title {{ font-size: 12px; color: #8be9fd; margin-bottom: 4px; }}
  .crop-stats {{ font-size: 11px; color: #888; margin-bottom: 4px; }}
  .crop-card img {{ width: 100%; display: block; margin-bottom: 4px; }}
  .diff-red {{ color: #ff5555; }}
  .diff-green {{ color: #50fa7b; }}
</style>
</head>
<body>
<h1>Starplot Enhanced Parity Review (orig vs inline)</h1>
<div class="summary">
  <p>Inline.png is resized to orig.png dimensions before cropping/diff so regions align.</p>
  <p>Click any table row to jump to that example.</p>
</div>
<table id="summary-table">
  <thead>
    <tr>
      <th>Example</th>
      <th>Orig size</th>
      <th>Inline size</th>
      <th>MAE</th>
      <th>RMSE</th>
      <th>Nonzero %</th>
      <th>Max diff</th>
    </tr>
  </thead>
  <tbody id="summary-body"></tbody>
</table>
<div id="examples"></div>
<script>
const rows = {rows_json};
const summaryBody = document.getElementById('summary-body');
const examplesDiv = document.getElementById('examples');

function statClass(v) {{
  if (v > 20) return 'diff-red';
  if (v > 5) return 'diff-red';
  if (v > 1) return 'diff-green';
  return '';
}}

rows.forEach(row => {{
  const tr = document.createElement('tr');
  tr.style.cursor = 'pointer';
  tr.onclick = () => document.getElementById('ex-' + row.name).scrollIntoView({{behavior:'smooth'}});
  tr.innerHTML = `
    <td>${{row.name}}</td>
    <td>${{row.orig_size || ''}}</td>
    <td>${{row.inline_size || ''}}</td>
    <td>${{row.full_stats.mae}}</td>
    <td>${{row.full_stats.rmse}}</td>
    <td class="${{statClass(row.full_stats.nonzero_gt5)}}">${{row.full_stats.nonzero_gt5}}%</td>
    <td>${{row.full_stats.max_diff}}</td>
  `;
  summaryBody.appendChild(tr);

  const section = document.createElement('section');
  section.id = 'ex-' + row.name;
  section.innerHTML = `
    <div class="ex-header">
      ${{row.name}}
      <span class="stats">full: MAE=${{row.full_stats.mae}} RMSE=${{row.full_stats.rmse}} nonzero=${{row.full_stats.nonzero_gt5}}% max=${{row.full_stats.max_diff}}</span>
    </div>
    <div class="img-row">
      <img src="${{row.orig}}" style="max-width:48%; max-height:400px" title="orig">
      <img src="${{row.inline}}" style="max-width:48%; max-height:400px" title="inline">
    </div>
    <div class="img-row">
      ${{row.crops.map(c => `
        <div class="crop-card">
          <div class="crop-title">${{c.name}} — ${{c.desc}}</div>
          <div class="crop-stats">
            MAE=${{c.stats.mae}} RMSE=${{c.stats.rmse}}
            <span class="${{statClass(c.stats.nonzero_gt5)}}">nonzero=${{c.stats.nonzero_gt5}}%</span>
            max=${{c.stats.max_diff}}
          </div>
          <img src="${{c.combined}}" title="${{c.name}}: left=orig, right=inline (resized)">
          <img src="${{c.diff}}" title="${{c.name}}: diff * 4">
        </div>
      `).join('')}}
    </div>
  `;
  examplesDiv.appendChild(section);
}});
</script>
</body>
</html>"""


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

    def log_message(self, *args):
        pass


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Enhanced visual parity review for starplot")
    parser.add_argument(
        "--semantic",
        action="store_true",
        help="crop semantic regions (bright stars, clusters, lines/edges) instead of geometric boxes",
    )
    args = parser.parse_args(argv)

    rows = build(semantic=args.semantic)
    print(f"Generated review page with {len(rows)} examples: {HTML_PATH}")
    url = f"http://localhost:{PORT}/_enhanced_review.html"
    print(f"Starting server at {url}")
    print("Press Ctrl+C to stop.")
    server = HTTPServer(("127.0.0.1", PORT), Handler)
    threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
