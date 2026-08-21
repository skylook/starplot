#!/usr/bin/env python3
"""Generate an enhanced review page with full-image + zoomed-crop comparisons.

Crops are taken from the same normalized regions of `orig.png` and `inline.png`,
with `inline.png` resized to `orig.png` dimensions using Lanczos resampling so
that stars/labels/clusters align for side-by-side and diff inspection.

By default, crops are selected from semantically important regions: bright stars,
dense clusters, and high-gradient line/edge areas.  Use ``--geometric`` to fall
back to fixed geometric boxes instead.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
from http.server import HTTPServer
import threading
import webbrowser

if __package__:
    from .server import SafeStaticHandler
else:
    from server import SafeStaticHandler

if __package__:
    from . import crops
else:
    import crops

ROOT = pathlib.Path(__file__).resolve().parents[2] / "comparison_outputs"
CROP_DIR = ROOT / "_crops"
HTML_PATH = ROOT / "_enhanced_review.html"
PORT = 8766
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def build(semantic: bool = True):
    CROP_DIR.mkdir(parents=True, exist_ok=True)

    rows = []
    for d in sorted(ROOT.iterdir()):
        if not d.is_dir() or not _SAFE_NAME_RE.fullmatch(d.name):
            continue
        # Remove only the crops previously generated for this example.
        # `crops.build_pair_review` slugifies the pair name with the same rule
        # below, so the cleanup glob must use the slug, not the raw directory
        # name, or hyphenated example names will be missed.
        slug = re.sub(r"[^\w]+", "_", d.name).strip("_")
        prefix = f"{slug}_"
        crop_name_re = re.compile(r"^[A-Za-z0-9\-]+(_diff)?\.png$")
        for p in CROP_DIR.glob(f"{slug}_*.png"):
            if not p.is_file() or not p.name.startswith(prefix):
                continue
            rest = p.name[len(prefix):]
            if crop_name_re.fullmatch(rest):
                p.unlink()
        orig_path = d / "orig.png"
        inline_path = d / "inline.png"
        if not orig_path.exists() or not inline_path.exists():
            continue

        review = crops.build_pair_review(
            orig_path,
            inline_path,
            CROP_DIR,
            d.name,
            root_dir=ROOT,
            semantic=semantic,
            reference="left",
        )

        rows.append({
            "name": d.name,
            "orig": str(orig_path.relative_to(ROOT)),
            "inline": str(inline_path.relative_to(ROOT)),
            "orig_size": f"{review['left_size'][0]}x{review['left_size'][1]}",
            "inline_size": f"{review['right_size'][0]}x{review['right_size'][1]}",
            "full_stats": review["full_stats"],
            "crops": review["crops"],
        })

    rows.sort(key=lambda r: r["name"])

    # Compute aggregate ranking by full nonzero diff
    rows.sort(key=lambda r: r["full_stats"]["nonzero_gt5"], reverse=True)

    html = generate_html(rows)
    HTML_PATH.write_text(html, encoding="utf-8")
    return rows


def _json_for_script(value: object) -> str:
    """Serialize JSON for safe insertion inside a <script> / template literal."""
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    text = re.sub(r"</", lambda m: "<\\/", text, flags=re.IGNORECASE)
    return (
        text
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("`", "\\u0060")
        .replace("${", "\\u0024{")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def generate_html(rows: list[dict]) -> str:
    rows_json = _json_for_script(rows)
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


class Handler(SafeStaticHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, *args):
        pass


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Enhanced visual parity review for starplot")
    parser.add_argument(
        "--geometric",
        action="store_true",
        help="use fixed geometric crop boxes instead of semantic region detection",
    )
    args = parser.parse_args(argv)

    rows = build(semantic=not args.geometric)
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
