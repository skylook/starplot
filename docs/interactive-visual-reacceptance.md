# Interactive visual reacceptance

Status: in progress, not global acceptance. The user requires both supported
backends and minimal changes to examples, not removal of Matplotlib. Reusing
Matplotlib projection/layout is not itself an unmet requirement.

## Acceptance method

Compare each unchanged original example against its interactive version at the
same resolution. Inspect full images and semantic crops, including positions,
labels, symbols, title, legend, boundaries and clipping. Browser screenshots
must cover inline, external Arrow and provider exports. Byte parity and passing
tests do not substitute for visual acceptance. Record revision and fingerprint
from each `comparison-exports.json`. Old screenshots remain historical evidence.

Reproduction (one example at a time):

```sh
PYTHONPATH=src:/private/tmp/starplot-readline-shim python -m tools.visual_parity.gen_comparison map_galaxy
```

The extra PYTHONPATH component is a host-only Anaconda readline crash workaround;
`src` remains first. Comparison RNG seed42 is recorded in provenance; production
label-layout defaults are unchanged.

## Initial inspection at c27c9f3

| Example | Evidence | Verdict and next action |
| --- | --- | --- |
| map_galaxy | comparison_outputs/map_galaxy/{orig,inline,external,provider}.png | Needs changes: reference-label slopes reversed, bold font too heavy, horizontal legend title beside entries. Re-render after fixes. |
| map_carina | comparison_outputs/map_carina/{orig,interactive,inline,external,provider}.png | Not accepted: legend spacing/symbol differences. Apparent constellation-label displacement is independent RNG, not Plotly coordinate mapping: seeded paired actual runs produced identical Matplotlib label coordinates. Regenerate seeded evidence. |
| map_virgo_cluster | comparison_outputs/map_virgo_cluster/{orig,inline,external,provider}.png | Needs changes: ellipse symbol slope reversed, title too heavy. Dense overlapping labels also occur in original; do not silently alter example's collision policy to hide them. |

## Repairs under verification

- Convert Matplotlib counterclockwise text rotation to Plotly clockwise angles in
  both adapters, leaving Scene rotation canonical.
- Preserve recorded font family and express bold as weight, not Arial Black.
- Place legend title above entries, including horizontal legends.
- Correct browser ellipse SVG rotation and preserve resize idempotence.
- Use seed42 for both comparison subprocesses and record it in provenance.
- Restore original Milky Way stars alpha, edge color and single-layer semantics;
  an AST regression test protects the example's drawing calls.

Remaining issues require screenshot confirmation, including font availability
(Matplotlib registers bundled Inter; HTML does not yet embed it), legend spacing,
custom symbol styling, and the dense example's published PNG-only median filter.
No claim of universal visual equivalence is made.

## Recheck at e04c6ef

Galaxy and Carina were regenerated individually at clean revision
`e04c6eff84dfa20dda8bc7bff54622b9028b6548`, with seed42. Both runs completed;
each has three actual browser screenshots and passing canonical transport gates.
Galaxy's original and interactive Matplotlib controls are pixel identical.
Manual full-image and Galaxy crop inspection confirms corrected reference-label
rotation and improved title weight. Carina's constellation labels now align
with its seeded original. Neither is unconditional visual acceptance: ordinary
legend glyph sizes/padding and font fallback remain visibly different.

Root causes for the remaining legend differences: Matplotlib builds independent
fixed-size legend handles (`plots/base.py`), while Plotly inherits plotted trace
marker sizes. Recorder currently captures the legend's top-right position but
not handle dimensions or frame padding. Browser `_applyLegendSymbolScale`
currently only corrects magnitude legends. Preserve independent handle sizes;
do not stretch the entire legend or use the first plotted star's size.

Bundled Inter regular/bold fonts can be supplied without dependencies, but
unconditionally embedding TTF adds about 1.1 MB per HTML. Prefer reusable font
assets for directory exports and self-contained fonts only for inline exports;
retain the existing font license and wait for fonts before screenshot capture.
This design is not implemented yet.

Full 23-script normalized AST audit found and corrected two additional drifts:
Big Dipper colors and Orthographic's pytz direct `tzinfo` assignment. The latter
produced UTC04:53 instead of the original ZoneInfo UTC04:00, changing projection
center. Regression tests now protect original inputs. Remaining drawing calls
match originals after backend/factory/export normalization. This audit is not
a substitute for screenshot inspection.

Verification: interactive/parity suite 728 passed before the two additional AST
tests, final harness suite31 passed, Node76 passed, Ruff and diff-check passed.

## Complete queue

23 paired examples (all require final-revision inspection):

galaxy_custom_marker, horizon_double_cluster, horizon_gradient, horizon_sgr,
map_big, map_big_dipper, map_canis_major, map_carina, map_cas, map_galaxy,
map_milky_way_stars, map_orion, map_orthographic, map_sagittarius,
map_virgo_cluster, optic_iss_transit, optic_m45, optic_moon_saturn,
optic_orion_nebula, optic_solar_eclipse, star_chart_basic, star_chart_detail,
star_chart_french.

Also inspect `export_html_modes.py` and `remote_provider_server.py` as functional
mode demos; they have no corresponding original Matplotlib pair.

Next: commit verified repairs for clean provenance, regenerate Galaxy and Carina
individually, inspect results, then proceed through the queue. Do not launch all
high-resolution renders concurrently or mark generated screenshots as accepted.
