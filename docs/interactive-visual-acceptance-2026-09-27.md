# Interactive visual acceptance — 2026-09-27

## Summary

All 23 original/interactive example pairs have been generated and manually
inspected. The verdict is basic visual consistency with documented differences,
not pixel identity or support for arbitrary Matplotlib artist extensions.
Both backends are intentionally supported; reuse of native projection/layout
is compatible with the requirement for minimal example changes.

## Evidence and reproduction

The full clean-source batch used f14b406. Two affected examples were refreshed
after the narrow marker repair at 016446f; other pairs were not needlessly
regenerated and their older revision is explicitly retained below.
Local `comparison_outputs/EXAMPLE/` contains orig.png, the native-control
interactive.png, actual inline/external/provider Chromium screenshots, diff.md,
semantic crops, canonical transport checks and comparison-exports.json provenance.
Generated artifacts are Git-ignored; this report is the durable record.

```sh
PYTHONPATH=src:/private/tmp/starplot-readline-shim python -m tools.visual_parity.gen_comparison EXAMPLE --compact-crops
PYTHONPATH=src:/private/tmp/starplot-readline-shim python -m pytest tests/ -q
node --test web/tests/*.mjs
python -m ruff check src/ tests/ tools/
```

The temporary shim works around a reproduced host Anaconda readline segfault.
No shim is shipped. src remains first, avoiding the stale installed worktree.
Comparison seed42 is recorded. Explicit smaller browser viewports were compared
after normalizing dimensions. interactive.png is not a Plotly screenshot.

## Individual inspection matrix

Scores are qualitative whole-image judgments, not pixel-match percentages.
PASS means main plotted content is consistent, not that listed differences are
fixed. All rows below were actually viewed; capture success alone was not used.

| Example | Revision | Verdict / score | Observed remaining differences |
| --- | --- | --- | --- |
| galaxy_custom_marker | f14b406 | PASS / 92 | Text opacity/baseline, thin frame; original also crowds M81/M82 |
| horizon_double_cluster | f14b406 | PASS / 92 | Grid/bearing fonts and footer rules; transparent FOV repair confirmed |
| horizon_gradient | f14b406 | PASS / 94 | Font weight/color and antialiasing |
| horizon_sgr | f14b406 | PASS / 94 | Grid/footer fonts and rasterization |
| map_big | f14b406 | PASS / 96 | Subpixel stars and text baselines |
| map_big_dipper | f14b406 | PASS / 95 | Heavier labels; star extents corrected |
| map_canis_major | f14b406 | PASS / 92 | Frame dashes and tighter Wezen/2354 label gap |
| map_carina | f14b406 | PASS / 90 | Right-edge coordinate labels absent; small legend spur/white-hole artifacts |
| map_cas | f14b406 | PASS / 95 | Text and grid antialiasing |
| map_galaxy | f14b406 | PASS / 92 | Title bounding box and rasterization; Milk fill independently confirmed |
| map_milky_way_stars | f14b406 | PASS / 94 | Dense rasterization; PNG-only median filter excluded from both paths |
| map_orion | f14b406 | PASS / 92 | Dotted reference line becomes dashes; thin frame |
| map_orthographic | f14b406 | PASS / 94 | Reference dashes/text |
| map_sagittarius | f14b406 | PASS / 93 | Text opacity/baseline and dash density |
| map_virgo_cluster | f14b406 | PASS / 93 | Darker text and vertical title offset; overlaps also in original |
| optic_iss_transit | 016446f | PASS / 94 | Text baseline and outer-axis ticks; plus extents repaired |
| optic_m45 | f14b406 | PASS / 93 | Footer boxed border and row gap |
| optic_moon_saturn | f14b406 | PASS / 95 | Text and outer-axis ticks |
| optic_orion_nebula | f14b406 | PASS / 94 | Footer frame/spacing |
| optic_solar_eclipse | f14b406 | PASS / 95 | Outer-axis ticks |
| star_chart_basic | f14b406 | PASS / 94 | Thin ring outlines missing; typography |
| star_chart_detail | 016446f | PASS / 94 | Thin ring outlines and text; Mel111 circle restored |
| star_chart_french | f14b406 | PASS / 94 | Thin ring outlines/text/dashes; accents present |

## Blockers

No outstanding missing main geometry was observed in the 23 initial static
views after repairs. This is not exhaustive acceptance of zoom/pan/resize states,
arbitrary API combinations or downstream skytools workloads.

## Major Issues

Replacing all skytools charts efficiently remains workload-specific integration
work. Near-million-star data is real evidence, but cannot establish universal
latency or memory guarantees. Standard Figure exports do not include Scene DOM
corrections/fonts/responsive hooks; prefer Scene export_html for those features.

## Minor Issues

Carina coordinate/legend artifacts, typography/opacity, custom dash
approximation, footer borders and thin frames remain as listed. Dense WebGL
custom glyphs are approximations; bounded SVG Scene HTML preserves native paths.
Arbitrary PIL postprocessing is not reproduced in interactive HTML.

## Nits

Historical iteration notes remain linked for audit; they are not current status.

## What's Done Well

The harness checks canonical transport identity and rejects dirty/changing
tracked trees. Native paths, title coordinates, legends, bundled fonts, dotted
marker edges, overridden constellation styles and transparent polygons were
corrected. The final outline/plus regressions failed before repair and protect
half-opacity edges without weakening palette alpha semantics globally.

## Verification Evidence

At 016446f, full Python tests: 878 passed, no figure-count warning. Node tests:
81 passed (JavaScript unchanged by final Python repair). Ruff over src/tests/tools
and git diff checks passed. Both repaired examples passed all three transport
gates and their new screenshots were viewed. Full prior batch: zero failures.

Both export_html_modes.py and remote_provider_server.py were regenerated at
016446f. Five real outputs were loaded and viewed: inline, external, provider,
same-origin remote client and standard Figure. Zero page errors/failed requests;
55 Scene traces and three Figure traces at 1400x1200. Servers stopped afterward.
Provider independently builds a Scene, so randomized label positions differ;
this demo is functional evidence, not same-Scene pixel equality. Cross-origin
deployment was not exercised.

Dense actual example: 974302 stars, 16565744 Arrow bytes and 50 ScatterGL batches.
Three browser-mode screenshots are identical. Original/browser mean pixel diff
13.752, 49.48% changed pixels: dense subpixel rasterization differs substantially.
The 320.74-second comparison pipeline includes Python generation and multiple
exports/screenshots; it is not browser-only rendering time. Separate measured
timings are recorded in local dense-browser-timing.json and final-performance.json.

Actual dense inline navigation-to-rendered-flag measurements, with no concurrent
generation/test workload: 4133.40, 4129.64 and 4106.87 ms at 1400x703, zero page
errors. These are three new pages in one browser context (first-page and reused
context runs), not independent cold machines or network/server performance.

Clean c87b29f synthetic benchmark (100000 points, three repeats, no concurrent
test/generation load): external Arrow cold median 970.0 ms, warm median 968.5 ms,
warm p95 986.77 ms; Arrow payload 1336240 bytes; Scene compilation median 1.315 s;
isolated Python peak RSS 227.22 MiB. Small real-family browser diagnostics had
medians Map 538.0 ms, Horizon 523.7 ms, Zenith 355.9 ms and Optic 444.7 ms.
These family samples are coverage diagnostics, not representative full workloads.
No matching baseline or ordinary-chart comparison was supplied, so relative
improvement/regression gates were not enforced. The clean artifact is
comparison_outputs/final-performance-clean.json; the earlier dirty/overlapping
run final-performance.json must not replace it as final timing evidence.
