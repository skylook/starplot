# Upstream synchronization assessment — 2026-09-27

Status: blocked on backend compatibility and deployment destination/credentials;
no main merge or production documentation deployment was performed.

## Verified revisions

- Local accepted branch: codex/release-readiness-docs, 17582fc.
- Fork origin/main: 6126d13.
- Official steveberardi/starplot main fetched from GitHub: c442894.
- Common ancestor: ad7a510.
- HEAD...official main: 147 local-only / 7 upstream-only commits.
- origin/main...HEAD: 0 main-only / 19 branch-only commits.

Seven new upstream commits include e22aaf8 (v0.21.0), Dutch translations,
data/documentation URL changes and Cartopy pin work. Despite the small commit
count, the upstream diff affects 303 files, with 17716 insertions and 9519 deletions.

## Why this is not a routine conflict resolution

Actual upstream src/starplot/plots/base.py imports starplot.svg.canvas.Canvas
and no longer exposes the native Matplotlib figure/axes lifecycle. Styles now
come from styles/elements.py, styles/plot.py and new constants/types modules.
The upstream migration guide documents removed ax/fig/dpi, renamed style fields,
removed marker symbols and changed export semantics. The code independently
confirms that rendering now uses the SVG canvas rather than Matplotlib.

Current src/starplot/interactive/recording_mixin.py directly uses ax.transData,
fig.draw_without_rendering, artist collections, native marker paths and native
font/layout extents. Merging upstream without porting those dependencies would
invalidate the previously tested Plotly implementation and visual evidence.

A trial `git merge --no-commit --no-ff` produced conflicts in Makefile, README,
changelog/index/reference docs, CLI, BasePlot, ZenithPlot, arrow/star plotters and
CLI/data tests; upstream deletes mkdocs.yml and supplies zensical.toml. Keeping
our old conflicted files alone would not solve the incompatible auto-merged files.
The trial was safely aborted, restoring 17582fc and preserving all user-owned
untracked handoff files. No upstream changes were discarded from upstream history.

## Required product decision

The prior requirement explicitly retains Matplotlib and Plotly. Official v0.21
instead removes Matplotlib. Fully incorporating v0.21 while retaining that
requirement entails a compatibility backend/three-backend migration, not merely
resolving textual conflicts. Alternatively, keep the tested v0.20-based dual
backend as the fork's supported release, merging it to fork main, and develop
v0.21 migration separately. Neither choice should be silently substituted for
the other or reported as full official-upstream synchronization.

## Deployment boundary

The checked-in docs workflow is manual and publishes to gs://starplot.dev and
gs://archives.starplot.dev using GCP_CREDENTIALS. It does not automatically
publish a fork's documentation after a push. With the current GitHub token:

- `gh secret list`: HTTP 403, Resource not accessible by personal access token.
- `gh api repos/skylook/starplot/pages`: HTTP 404.
- Repository permission response reports admin/push access; this does not prove
  token access to Actions secrets or GCP authorization.

No deployment job was started: the workflow targets the official production
domain, and we have not verified credentials or permission to overwrite it.
Choose/authorize the fork's documentation destination (for example a fork Pages
site) and provide the appropriate deployment configuration, or explicitly verify
the existing official GCS authorization. A local successful docs build must not
be presented as a deployed website.
