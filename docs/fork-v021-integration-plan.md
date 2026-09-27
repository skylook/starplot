# Fork v0.21 synchronization and interactive integration assessment

Date: 2026-09-27. Repository: skylook/starplot, not the official upstream.

## Branch contract

- main and codex/release-readiness-docs retain the accepted Matplotlib + Plotly
  implementation at 1e50807. Main was fast-forwarded and pushed; the working
  branch was not rebased, rewritten or deleted.
- codex/upstream-v021-sync starts from official upstream c442894, including
  v0.21.0 and its latest fixes. This isolated branch does not yet contain the
  fork's interactive implementation. It is a synchronization/migration base,
  not a replacement for the accepted branch and not approved for merge to main.
- Worktree: /Users/skylook/.codex/worktrees/starplot-upstream-v021-sync/starplot.
- Only skylook/starplot receives pushes. No official repository/domain writes.

## Can our implementation be merged directly?

No. This is established by actual code, not only the upstream migration guide:

1. Current interactive recording_mixin.py reads ax.transData, fig dimensions,
   collections, native Matplotlib marker paths, artists and font extents.
2. Upstream BasePlot builds starplot.svg.canvas.Canvas, with no Matplotlib
   ax/fig/dpi. Canvas uses pyproj and SVG layout regions.
3. Upstream styles/elements.py, styles/types.py and styles/plot.py replace the
   old style contracts: stroke/fill/opacity/dash arrays, pixel marker sizes,
   different legend layout and several removed marker symbols.
4. Upstream replaces MkDocs navigation with zensical.toml and reorganizes docs.

The seven new upstream commits affect 303 files. A prior trial merge conflicted
in 14 paths and also auto-merged incompatible rendering/style files. Accepting
one side of those conflicts is not a compatibility solution.

## Reusable components and new integration boundary

Reuse is feasible, but requires a deliberate port rather than cherry-picking
the entire Matplotlib-dependent recording mixin:

| Component | Proposed treatment | Required verification |
| --- | --- | --- |
| Scene schema, numeric arrays, Arrow transport | Reuse after reviewing style/coordinate assumptions | Canonical hashes, validation, limits, immutable arrays |
| Provider, loader, browser security | Preserve contracts | Origin/redirect/CSP/XSS/detail endpoint tests |
| Plotly Scene adapter | Reuse selectively | Pixel-size units, y orientation, symbol paths, clipping and zorder |
| Native artist recorder | Replace with SVG Canvas recording bridge | DATA/PROJECTED/AXES/DISPLAY conversion without double projection |
| Native typography/legend corrections | Derive from SVG layout and font metrics | Legend/table/title offsets, font selection, resize idempotence |
| Examples and public API | Retain drawing calls where upstream still supports them | Explicit compatibility mapping for renamed/removed style fields |
| Documentation | Port guides into Zensical navigation | Build/link/API-reference checks; do not link deleted MkDocs paths |

Actual candidate hook points in svg/canvas.py are marker/markers (393/406),
line (511), polygon (691), text (749), title (771), legend (801), table (929),
and render/export (1309/1313). `_to_display` handles coordinate conversion;
`Layout` separates axes, frame, title, legend and table regions. These are
internal interfaces, so any bridge must be explicitly protected by tests.

Do not parse serialized SVG strings as the primary data transport. Preserve
numeric columnar data at Canvas inputs or structured elements; otherwise a
million-star field would incur per-element DOM/string costs and lose metadata.
Gradients, group inheritance, clipping and glyph units need dedicated fixtures.

## Staged implementation gates

1. Lock the clean v0.21 baseline/environment. No edits to current main/old branch.
2. Add failing Canvas-to-Scene contract tests for each supported primitive,
   including coordinate spaces, projected seam splitting, polygon holes,
   opacity and native SVG marker paths. Implement the minimal bridge.
3. Port one small Map example and validate inline/external/provider in an actual
   browser; keep native SVG as the new branch's visual reference.
4. Port Horizon, Zenith, Optic and Galaxy individually, including title/legend,
   gridlines, moon phases, FOVs and gradients. Only rebuild affected examples.
5. Cover all updated upstream examples. Old v0.20 screenshots cannot substitute
   for v0.21 visual acceptance: default styles, symbols and sizes changed.
6. Measure realistic dense fields and downstream skytools workloads. Separate
   data/build, Scene compilation, payload and browser completion times.
7. Update Zensical docs and migration mapping. Merge only after independent code
   review, tests and per-example visual acceptance; do not copy old PASS counts.

If Matplotlib support is required in a single v0.21 installation, that needs a
separate compatibility-backend design. The present branch split preserves old
Matplotlib + Plotly availability without claiming upstream v0.21 still supports it.

## Baseline verification

The host initially lacked pydantic-extra-types and pyqtree. Upstream-declared
dependencies were installed into /private/tmp/starplot-v021-sync-env using
system-site-packages; the global Anaconda environment and project manifests
were not modified. Installed additions: pydantic-extra-types, pyqtree, cairosvg,
fonttools, and their Cairo/CSS dependencies. This is not a fully pinned/released
v0.21 environment or a complete dependency-minimum audit.

```sh
cd /Users/skylook/.codex/worktrees/starplot-upstream-v021-sync/starplot
PYTHONPATH=src:/private/tmp/starplot-readline-shim \
STARPLOT_DATA_PATH=/Users/skylook/Develop/starplot/comparison_outputs/.data-cache \
/private/tmp/starplot-v021-sync-env/bin/python -m pytest tests/svg/ tests/plots/ -q
```

Result: 144 passed, 3 failed in tests/svg/test_fonts.py. Requested Inter and
Liberation Sans resolve to Arial on this macOS host; tests assume those font
families exist. No source code was changed to hide failures. Establish the
documented upstream font environment before calling this baseline accepted.
Full v0.21 tests and browser/interactive parity have not been run/passed.

Preserved current branch: full Python 878 passed; Node 81 passed in this turn.
The prior interactive/parity subset has 754 tests. User-owned untracked handoff
files remain untouched. Documentation deployment is not part of this branch
sync outcome; the upstream workflow targets official GCS buckets and must not
be triggered for a fork without an independently configured destination.
