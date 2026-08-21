# Interactive Scene / Arrow Parity Ledger

> Final Scene/Arrow browser review: **ACCEPTED, 2026-08-16** at revision
> `67d13d637cd90286e2e8b5c3a41e3a131225ae8b`. This run includes the dense
> finite-palette ScatterGL batching and responsive marker-edge paths.

This ledger supersedes the earlier direct-Python-Plotly/Kaleido review. Every
row below was regenerated from one `ScenePackage`, exported as inline Arrow,
external Arrow and remote `SceneProvider` data, then rendered in a real Chrome
browser. The exact artifacts live in the corresponding example directory.

## Evidence contract applied to every example

- `orig.png`: original Matplotlib example; `interactive.png`: Interactive
  Matplotlib export regression control.
- `inline.html`/`inline.png`, `external.html`/`external.png`, and
  `provider.html`/`provider.png`: actual browser output, not Kaleido output.
- `transport.md`: canonical manifest bytes, every raw Arrow layer byte stream,
  decoded Arrow columns/dtypes, and provider HTTP headers/body are equal.
- `browser-render.json`: all three transports preserve the same rendered trace
  count and canonical Scene layer order.
- `diff.md`: diagnostic only; differing browser/Matplotlib dimensions and
  rasterizers make raw pixels unsuitable as the acceptance criterion.

Final evidence: **22/22** folders contain all required artifacts, **22/22**
transport reports pass, and **22/22** browser reports have equal inline /
external / provider trace counts. Every report records `tracked_dirty=false`
and source fingerprint
`sha256:fa0f6855dcfcec3b23617cbafdbab0951097d81062556de6e6899cfa66953045`.
`map_milky_way_stars` renders as 51 bounded finite-palette ScatterGL traces in
every transport, with identical canonical Arrow data and restored dense-field
marker-edge coverage.

## Pair review matrix

| Example | Verdict | Visual review result |
|---|---|---|
| `horizon_double_cluster` | PASS | Latitude grid, horizon footer, double-cluster markers, red dashed optic FOV, arrow and constellation geometry align. |
| `horizon_gradient` | PASS | Gradient direction, Milky Way band, Messier markers, labels and horizon layout are present. |
| `horizon_sgr` | PASS | Crop, grid, dense stars, constellation paths and labels align. |
| `galaxy_custom_marker` | PASS | Custom marker geometry, galaxy/DSO symbols, labels and recorded final paths are present. |
| `map_big` | PASS | Full-sky geometry, Milky Way, DSO categories, grid and constellation paths align; no 0°/360° bridge. |
| `map_big_dipper` | PASS | Local map star/DSO placement, labels and constellation geometry align. |
| `map_canis_major` | PASS | Labels, stars and boundary/grid layers align. |
| `map_carina` | PASS | Southern field, object categories, labels and legend-related geometry align. |
| `map_cas` | PASS | Cassiopeia objects, grid and label placement align. |
| `map_milky_way_stars` | PASS | Full high-density sky and Galactic band remain visible through 51 bounded ScatterGL traces; no layer or transport loss. |
| `map_orion` | PASS | Orion field, Milky Way and DSO/star placement align. |
| `map_orthographic` | PASS | Circular projection/crop, object placement and map boundary align. |
| `map_sagittarius` | PASS | Dense map content, grid and constellation paths align. |
| `map_virgo_cluster` | PASS | High-trace cluster field loads/rendered in all transports without loss. |
| `optic_iss_transit` | PASS | Optic boundary, transit path and labels align. |
| `optic_m45` | PASS | Cluster field, stars, optic clipping and recorded five-column footer align. |
| `optic_moon_saturn` | PASS | Relative Moon/Saturn positions and optic field align. |
| `optic_orion_nebula` | PASS | Nebula field, stars, labels, clip and recorded five-column footer align. |
| `optic_solar_eclipse` | PASS | Sun/Moon overlap and optic geometry align. |
| `star_chart_basic` | PASS | Zenith ring, cardinal labels, stars and clipping align. |
| `star_chart_detail` | PASS | DSO layers, Milky Way polygons, constellation paths and cardinal ring align. |
| `star_chart_french` | PASS | French text, dense all-sky geometry, dashed references and cardinal ring align. |

## Shared mechanisms verified

- The recorder captures final Matplotlib geometry and coalesces only adjacent,
  semantically identical scatter commands during Scene finalization. This
  avoids per-object quadratic copying while reducing Arrow files and Plotly
  traces.
- CSS RGBA colors, final-artist polygon normalization, discontinuous paths,
  clip geometry, coordinate spaces and Matplotlib custom dash strings have
  one shared Scene representation.
- Browser rendering uses one final `Plotly.react`, two animation frames before
  reporting completion, and a bounded SVG z-order plane when a safe mixed
  SVG/WebGL chart would otherwise hide lower SVG geometry behind a canvas.
- Large pure-point charts retain WebGL; mixed moderate charts preserve final
  Scene ordering by re-ranking the SVG plane above the gradient canvas.
- Sparse star-group WebGL traces retain the established subpixel calibration;
  row-count-driven dense traces preserve recorded marker edges and rescale
  those edges from immutable baselines after actual-axis correction and resize.

## Accepted non-blocking rasterizer differences

- Browser output uses the Scene reference viewport (commonly 1000–1400 px),
  while Matplotlib comparison PNGs are high resolution. Thus labels and some
  Messier/DSO symbols can look modestly smaller after side-by-side viewing.
- Font metrics, antialiasing, gradient interpolation and SVG marker fill
  appearance differ slightly between browser Plotly and Matplotlib. No review
  found a coordinate, projection, missing-layer, seam-crossing or clipping
  defect attributable to these differences.
