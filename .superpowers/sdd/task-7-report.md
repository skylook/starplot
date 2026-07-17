# Task 7 implementation report

Status: DONE_WITH_CONCERNS

## Implemented

- Added a plain-browser `StarplotScene` runtime with inline, static, and API
  `SceneSource` implementations sharing one Arrow IPC Stream validation path.
- Added the browser Plotly adapter for all Scene 1.0 kinds with stable
  `(zorder, layer.id)` trace slots and one `Plotly.restyle` per loaded layer.
- Kept high-volume numeric columns as typed arrays and combined complete layer
  batches only once immediately before rendering.
- Ported Python adapter policy for small SVG versus stars/large ScatterGL,
  marker calibration, gradient resolution/sampling, radial center/radius,
  Mollweide ICRS-to-Galactic rotation, and distinct DATA/AXES/PAPER references.
- Validated exact Task 6 field order, required/allowed columns, Arrow types,
  NumPy dtype metadata, nullability, schema metadata, length, SHA-256, Stream
  prefix/EOS, and row count.
- Vendored the official Apache Arrow JS 21.1.0 ES2015 browser artifact with a
  reproducible checksum script and Apache-2.0 notice.
- Included browser assets and notices in Flit wheel/sdist package data.

## Verification

- `cd web && npm test`: 17 passed.
- `/opt/anaconda3/envs/starplot/bin/python tools/sync_arrow_js_asset.py --check`:
  Arrow JS 21.1.0 checksum and byte identity passed.
- `/opt/anaconda3/envs/starplot/bin/python -m build --wheel --no-isolation
  --outdir /private/tmp/starplot-task7-dist`: built
  `starplot-0.19.5-py2.py3-none-any.whl`.
- Wheel inspection confirmed loader, adapter, Arrow vendor asset, and
  `THIRD_PARTY_NOTICES.md`.
- `git diff --check`: passed.

## Concerns / deferred contracts

- Polygon holes fail closed in the browser adapter instead of being silently
  filled. Correct hole rendering needs a later multi-trace/shape policy while
  preserving stable layer ordering.
- Full manifest self-hash and origin/size security gates remain Task 12 scope;
  Task 7 validates the declared hash syntax and every layer's exact bytes.
- The normal isolated wheel build attempted to download its fresh build
  environment and was blocked by sandbox proxy/network policy. The identical
  installed Flit backend succeeded with `--no-isolation` and the resulting
  wheel contents were inspected.

## Review remediation (2026-07-17)

Status: DONE

### Exact fixes

- Replaced browser text traces and overlay-axis/pixel-to-coordinate emulation
  with Python-authority Plotly annotations (`xref`/`yref`, anchors, pixel
  shifts, angle, font, weight, and opacity). Text keeps one invisible Scatter
  trace slot and one layer restyle; annotations are accumulated separately.
- Replaced the incompatible Plotly Table trace with the Python footer layout:
  normalized domains, bottom margin, background rectangle, separators, and
  header/value annotations. The footer also keeps one invisible Scatter slot.
- Ported strict Scene 1.0 required/extra field, version, extension, capability,
  layer/encoding/interaction, unique ID, style/palette reference, and canonical
  self-hash checks. Self-hashing consumes exact canonical manifest JSON so
  Python float lexemes are not reconstructed from lossy parsed JS numbers.
- Replaced suffix-only stream acceptance with Arrow `MessageReader` framing and
  body-length consumption, then requires the source to be empty after EOS.
- Matched Python Arrow metadata bytes exactly, including canonical encoding
  JSON and float representations; matched dictionary Utf8/index policy and
  retained Utf8-or-dictionary support for string/object extensions.
- Resolved relative and root-relative source bases against the document base,
  then resolved each layer URI against the actual resolved manifest URL.
- Computed radial default center/radius before applying explicit overrides.
- Rendered polygon holes as deterministic Plotly path shapes with
  `fillrule: "evenodd"` while preserving the reserved trace slot.
- Added abort gates between fetch, digest, decode, schema, batch, table, adapter,
  restyle, and layer stages. Optional layer failures remain hidden and loading
  continues; required failures hide all loaded slots and purge annotations and
  shapes before rethrowing.
- Disabled hover/customdata materialization above 100,000 declared rows.
- Made missing or non-finite gradient viewport bounds skip closed through a
  valid hidden Heatmap slot rather than inventing `[0, 1]` bounds.
- Vendored exact upstream Arrow 21.1.0 `LICENSE.txt` and `NOTICE.txt`, pinned
  both checksums, synchronized byte identity, and included them in wheel/sdist.

### Verification

- `cd web && npm test`: 23 passed.
- Python-produced manifest/Arrow fixture loaded through the plain browser
  runtime, including relative-f32 metadata, dictionary text, and nullable Utf8.
- Browser text/footer/hole outputs passed real Plotly Python 6.5.2 schema
  construction and `to_plotly_json()` validation.
- Focused pytest itself exits 139 in both local conda environments before test
  collection; both new Python integration functions were therefore executed
  directly with the same interpreter and passed. Existing Python authority
  modules were exercised while producing the cross-runtime fixture.
- `tools/sync_arrow_js_asset.py --check`: JS, LICENSE, and NOTICE hashes and
  upstream byte identity passed.
- `python -m build --wheel --sdist --no-isolation`: passed; inspection confirmed
  both archives contain loader, adapter, Arrow JS, LICENSE, and NOTICE.
- `git diff --check`: passed.

### Remaining concerns

- The environment-level pytest collection segfault remains outside Task 7; it
  reproduces on unchanged focused tests as well as the new test. No Task 7 test
  assertion failed, and direct execution of the new Python integration gates
  passed.
