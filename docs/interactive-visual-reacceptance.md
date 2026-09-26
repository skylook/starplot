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
