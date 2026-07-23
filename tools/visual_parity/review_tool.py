#!/usr/bin/env python3
"""Launch a local review tool for visually comparing orig vs plotly outputs.

Usage:
    python tools/visual_parity/review_tool.py

Opens a browser table: one row per example, orig.png | inline.png side by
side, a text input for review notes, and a save button that downloads a
Markdown ledger of your feedback.
"""

from __future__ import annotations

import json
import pathlib
import textwrap
from http.server import HTTPServer, SimpleHTTPRequestHandler
import threading
import webbrowser

ROOT = pathlib.Path(__file__).resolve().parents[2] / "comparison_outputs"
PORT = 8765


def discover_examples() -> list[dict]:
    """Scan comparison_outputs for example folders with orig.png and inline.png."""
    examples = []
    for d in sorted(ROOT.iterdir()):
        if not d.is_dir():
            continue
        orig = d / "orig.png"
        inline = d / "inline.png"
        if not orig.exists() or not inline.exists():
            continue
        diff_md = ""
        diff_file = d / "diff.md"
        if diff_file.exists():
            diff_md = diff_file.read_text()
        examples.append({
            "name": d.name,
            "orig": f"{d.name}/orig.png",
            "inline": f"{d.name}/inline.png",
            "diff": diff_md,
        })
    return examples


def build_html(examples: list[dict]) -> str:
    examples_json = json.dumps(examples)
    return textwrap.dedent(f"""\
    <!DOCTYPE html>
    <html lang="en">
    <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Starplot Interactive Parity Review</title>
    <style>
      * {{ box-sizing: border-box; margin: 0; padding: 0; }}
      body {{
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        background: #1a1a2e; color: #e0e0e0; padding: 20px;
      }}
      h1 {{ font-size: 22px; margin-bottom: 16px; color: #8be9fd; }}
      .toolbar {{
        position: sticky; top: 0; z-index: 100;
        background: #1a1a2e; padding: 12px 0; border-bottom: 1px solid #333;
        display: flex; gap: 12px; align-items: center; flex-wrap: wrap;
      }}
      .toolbar button {{
        padding: 8px 20px; font-size: 14px; border: none; border-radius: 6px;
        cursor: pointer; font-weight: 600;
      }}
      #saveBtn {{ background: #50fa7b; color: #1a1a2e; }}
      #saveBtn:hover {{ background: #40e36b; }}
      #exportJsonBtn {{ background: #8be9fd; color: #1a1a2e; }}
      #exportJsonBtn:hover {{ background: #7bd6ee; }}
      .stats {{ font-size: 13px; color: #888; }}
      table {{ width: 100%; border-collapse: collapse; margin-top: 16px; }}
      th {{
        text-align: left; padding: 10px 12px; font-size: 13px; color: #888;
        border-bottom: 2px solid #333; position: sticky; top: 60px;
        background: #1a1a2e; z-index: 50;
      }}
      td {{
        padding: 10px 12px; border-bottom: 1px solid #2a2a3e;
        vertical-align: top; font-size: 13px;
      }}
      tr:hover {{ background: #1e1e34; }}
      .ex-name {{ font-weight: 600; color: #bd93f9; white-space: nowrap; }}
      .img-cell {{ cursor: zoom-in; }}
      .img-cell img {{
        max-width: 320px; max-height: 240px; object-fit: contain;
        border: 1px solid #333; border-radius: 4px; display: block;
      }}
      .img-cell:hover img {{ border-color: #8be9fd; }}
      .diff-info {{ font-size: 11px; color: #666; margin-top: 4px; }}
      textarea {{
        width: 100%; min-height: 80px; padding: 8px; font-size: 13px;
        border: 1px solid #333; border-radius: 4px; background: #12122a;
        color: #e0e0e0; font-family: inherit; resize: vertical;
      }}
      textarea:focus {{ outline: none; border-color: #8be9fd; }}
      .status-badge {{
        display: inline-block; padding: 2px 8px; border-radius: 10px;
        font-size: 11px; font-weight: 600; margin-left: 6px;
      }}
      .status-pending {{ background: #444; color: #aaa; }}
      .status-reviewed {{ background: #2d4a2d; color: #50fa7b; }}
      /* Modal overlay for image zoom */
      #overlay {{
        display: none; position: fixed; top: 0; left: 0; width: 100%;
        height: 100%; background: rgba(0,0,0,0.92); z-index: 9999;
        justify-content: center; align-items: center; cursor: zoom-out;
      }}
      #overlay img {{ max-width: 95vw; max-height: 95vh; object-fit: contain; }}
      #overlay .label {{
        position: absolute; bottom: 20px; left: 50%; transform: translateX(-50%);
        font-size: 14px; color: #8be9fd; background: rgba(0,0,0,0.7);
        padding: 6px 16px; border-radius: 6px;
      }}
    </style>
    </head>
    <body>
    <h1>Starplot Interactive Parity Review</h1>
    <div class="toolbar">
      <button id="saveBtn" onclick="saveMarkdown()">Save Review (MD)</button>
      <button id="exportJsonBtn" onclick="saveJson()">Export (JSON)</button>
      <span class="stats" id="stats"></span>
    </div>
    <table>
      <thead>
        <tr>
          <th style="width:180px">Example</th>
          <th style="width:360px">Original (Matplotlib)</th>
          <th style="width:360px">Interactive (Plotly)</th>
          <th>Review Notes</th>
        </tr>
      </thead>
      <tbody id="tbody"></tbody>
    </table>
    <div id="overlay" onclick="closeOverlay()">
      <img id="overlayImg" src="">
      <div class="label" id="overlayLabel"></div>
    </div>
    <script>
    const examples = {examples_json};

    const tbody = document.getElementById('tbody');
    const stats = document.getElementById('stats');

    function parseDiff(text) {{
      const m = text.match(/interactive vs inline.*?nonzero=([0-9.]+)%/);
      return m ? parseFloat(m[1]) : null;
    }}

    examples.forEach((ex, i) => {{
      const tr = document.createElement('tr');
      tr.id = 'row-' + i;
      const diffPct = parseDiff(ex.diff);
      const diffStr = diffPct !== null ? diffPct.toFixed(1) + '%' : 'n/a';

      tr.innerHTML = `
        <td class="ex-name">
          ${{ex.name}}
          <span class="status-badge status-pending" id="badge-${{i}}">pending</span>
          <div class="diff-info">diff: ${{diffStr}}</div>
        </td>
        <td class="img-cell" onclick="zoom('${{ex.orig}}', '${{ex.name}} — Original (Matplotlib)')">
          <img src="${{ex.orig}}" loading="lazy" alt="orig">
        </td>
        <td class="img-cell" onclick="zoom('${{ex.inline}}', '${{ex.name}} — Interactive (Plotly)')">
          <img src="${{ex.inline}}" loading="lazy" alt="plotly">
        </td>
        <td>
          <textarea
            id="notes-${{i}}"
            placeholder="输入 review 意见... (留空 = 基本一致)"
            oninput="markReviewed(${{i}})"
          ></textarea>
        </td>
      `;
      tbody.appendChild(tr);
    }});

    function markReviewed(i) {{
      const badge = document.getElementById('badge-' + i);
      const ta = document.getElementById('notes-' + i);
      if (ta.value.trim()) {{
        badge.textContent = 'reviewed';
        badge.className = 'status-badge status-reviewed';
      }} else {{
        badge.textContent = 'pending';
        badge.className = 'status-badge status-pending';
      }}
      updateStats();
    }}

    function updateStats() {{
      let reviewed = 0;
      examples.forEach((_, i) => {{
        const ta = document.getElementById('notes-' + i);
        if (ta && ta.value.trim()) reviewed++;
      }});
      stats.textContent = `${{reviewed}} / ${{examples.length}} reviewed`;
    }}
    updateStats();

    function zoom(src, label) {{
      const overlay = document.getElementById('overlay');
      const img = document.getElementById('overlayImg');
      const lbl = document.getElementById('overlayLabel');
      img.src = src;
      lbl.textContent = label;
      overlay.style.display = 'flex';
    }}

    function closeOverlay() {{
      document.getElementById('overlay').style.display = 'none';
    }}

    document.addEventListener('keydown', (e) => {{
      if (e.key === 'Escape') closeOverlay();
    }});

    function collectReviews() {{
      return examples.map((ex, i) => {{
        const ta = document.getElementById('notes-' + i);
        const notes = ta ? ta.value.trim() : '';
        return {{
          name: ex.name,
          notes: notes,
          status: notes ? 'reviewed' : 'pass',
        }};
      }});
    }}

    function download(filename, content, mime) {{
      const blob = new Blob([content], {{ type: mime }});
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
    }}

    function saveMarkdown() {{
      const reviews = collectReviews();
      const now = new Date().toISOString().slice(0, 19).replace('T', ' ');
      let md = `# Interactive Plotly Parity — Visual Review\\n\\n`;
      md += `Review date: ${{now}}\\n\\n`;
      md += `| Example | Status | Review Notes |\\n`;
      md += `|---------|--------|-------------|\\n`;
      reviews.forEach(r => {{
        const notes = r.notes || '(基本一致 — no issues noted)';
        md += `| ${{r.name}} | ${{r.status}} | ${{notes.replace(/\\|/g, '\\\\|')}} |\\n`;
      }});
      md += `\\n---\\n\\n`;
      const reviewed = reviews.filter(r => r.notes);
      const passed = reviews.filter(r => !r.notes);
      md += `## Summary\\n\\n`;
      md += `- Total examples: ${{reviews.length}}\\n`;
      md += `- Pass (no notes): ${{passed.length}}\\n`;
      md += `- Reviewed (with notes): ${{reviewed.length}}\\n`;
      download('parity-review.md', md, 'text/markdown');
    }}

    function saveJson() {{
      const reviews = collectReviews();
      const data = JSON.stringify(reviews, null, 2);
      download('parity-review.json', data, 'application/json');
    }}
    </script>
    </body>
    </html>
    """)


class ReviewHandler(SimpleHTTPRequestHandler):
    """Serve files from comparison_outputs with CORS headers."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

    def log_message(self, *args):
        pass  # suppress request logging


def main():
    examples = discover_examples()
    if not examples:
        print("No examples found. Run gen_comparison.py first.")
        return

    html = build_html(examples)
    html_path = ROOT / "_review.html"
    html_path.write_text(html, encoding="utf-8")

    url = f"http://localhost:{PORT}/_review.html"
    print(f"Found {len(examples)} examples.")
    print(f"Starting review server at {url}")
    print("Press Ctrl+C to stop.")

    server = HTTPServer(("127.0.0.1", PORT), ReviewHandler)
    # Open browser after a short delay
    threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        html_path.unlink(missing_ok=True)
        server.shutdown()


if __name__ == "__main__":
    main()
