#!/usr/bin/env python3
# ruff: noqa: SLF001
"""Run one interactive example and export the requested Scene transport modes.

This is an internal harness used by ``gen_comparison.py``.  It temporarily
replaces ``_InteractiveMixin.export_html`` with a dispatcher; the dispatcher
calls the original ``export_html`` implementation once per selected transport
(mode and library are overridden by the harness) and writes the metadata
``gen_comparison.py`` needs.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import runpy
import sys
import unittest.mock as mock
import warnings
from pathlib import Path

try:
    import starplot.interactive.plots as plots
    from starplot.interactive.plotly_renderer import PlotlyRenderer
    from starplot.interactive.web_export import ExportResult
except ImportError as exc:
    raise SystemExit(
        "Could not import starplot interactive modules. "
        "Ensure the repo 'src/' directory is on PYTHONPATH and the "
        "'interactive' extra (plotly, kaleido) is installed."
    ) from exc

# Captured before the harness temporarily patches the mixin at runtime.
_ORIG_EXPORT_HTML = plots._InteractiveMixin.export_html


def _selected_transports() -> tuple[str, ...]:
    """Return the transports requested by the comparison harness."""
    raw = os.environ.get("STARPLOT_COMPARISON_TRANSPORTS")
    if raw is None:
        # Default to all transports when the provider manifest URL is supplied;
        # otherwise skip the provider transport.
        default = "inline,external"
        if "STARPLOT_COMPARISON_PROVIDER_MANIFEST_URL" in os.environ:
            default = "inline,external,provider"
        raw = default
    parts = tuple(part.strip() for part in raw.split(",") if part.strip())
    allowed = {"inline", "external", "provider"}
    invalid = set(parts) - allowed
    if invalid:
        raise ValueError(f"invalid comparison transports: {sorted(invalid)}")
    return parts


def _comparison_export(
    self,
    filename,
    width=None,
    height=None,
    transparent=False,
    **kwargs,
):
    """Export the example's Scene through the requested transports and record metadata.

    The example's single call to ``export_html`` is redirected so the comparison
    harness can export the same compiled Scene under each requested transport.
    """
    known_ignored = {
        "data_mode",
        "library_mode",
        "data_url",
        "allowed_data_origins",
        "include_plotlyjs",
    }
    for key in known_ignored:
        if key in kwargs:
            if key == "include_plotlyjs":
                warnings.warn(
                    "include_plotlyjs is ignored by the comparison harness",
                    DeprecationWarning,
                    stacklevel=2,
                )
            kwargs.pop(key)

    if kwargs:
        unknown = ", ".join(sorted(kwargs))
        raise TypeError(f"export_html() got unexpected keyword argument(s): {unknown}")

    transports = _selected_transports()
    base = Path.cwd()
    export_path = Path(filename)
    if export_path.is_absolute():
        raise ValueError("comparison export filename must be relative")
    out_path = base / export_path
    stem = export_path.stem or "interactive"

    results_by_transport: dict[str, ExportResult] = {}
    provider_url = os.environ.get("STARPLOT_COMPARISON_PROVIDER_MANIFEST_URL")

    if "external" in transports:
        results_by_transport["external"] = _ORIG_EXPORT_HTML(
            self,
            export_path,
            width=width,
            height=height,
            transparent=transparent,
            data_mode="external",
            library_mode="directory",
        )
    if "inline" in transports:
        results_by_transport["inline"] = _ORIG_EXPORT_HTML(
            self,
            Path(f"{stem}_inline.html"),
            width=width,
            height=height,
            transparent=transparent,
            data_mode="inline",
            library_mode="inline",
        )
    if "provider" in transports:
        if not provider_url:
            raise RuntimeError(
                "STARPLOT_COMPARISON_PROVIDER_MANIFEST_URL is required for provider transport"
            )
        results_by_transport["provider"] = _ORIG_EXPORT_HTML(
            self,
            Path(f"{stem}_provider.html"),
            width=width,
            height=height,
            transparent=transparent,
            data_mode="remote",
            library_mode="inline",
            data_url=provider_url,
        )

    if not results_by_transport:
        raise RuntimeError("at least one transport must be selected")
    primary = next(iter(results_by_transport.values()))
    for other in results_by_transport.values():
        if other is primary:
            continue
        if primary.scene_hash != other.scene_hash:
            raise AssertionError("transport scene hashes differ")
        if primary.manifest_bytes != other.manifest_bytes:
            raise AssertionError("transport manifest bytes differ")
        if primary.layer_bytes != other.layer_bytes:
            raise AssertionError("transport layer bytes differ")

    plotly_png = base / "plotly.png"
    if importlib.util.find_spec("kaleido") is None:
        plotly_png = None
    else:
        plotly_width, plotly_height = PlotlyRenderer(
            self._recorder.projection_info,
            self._recorder.style_info,
            width=width,
            height=height,
        )._reference_dimensions()
        fig = self.to_plotly(
            width=plotly_width, height=plotly_height, transparent=transparent
        )
        plotly_width = int(plotly_width)
        plotly_height = int(plotly_height)
        fig.update_layout(width=plotly_width, height=plotly_height)
        fig.write_image(str(plotly_png), width=plotly_width, height=plotly_height)

    (base / "comparison-exports.json").write_text(
        json.dumps(
            {
                "filename": str(out_path.relative_to(base)),
                "external_html": (
                    str(results_by_transport["external"].html_path.relative_to(base))
                    if "external" in results_by_transport
                    else None
                ),
                "external_bundle": (
                    str(results_by_transport["external"].bundle_path.relative_to(base))
                    if "external" in results_by_transport
                    and results_by_transport["external"].bundle_path
                    else None
                ),
                "inline_html": (
                    str(results_by_transport["inline"].html_path.relative_to(base))
                    if "inline" in results_by_transport
                    else None
                ),
                "provider_html": (
                    str(results_by_transport["provider"].html_path.relative_to(base))
                    if "provider" in results_by_transport
                    else None
                ),
                "plotly_png": (
                    str(plotly_png.relative_to(base))
                    if plotly_png is not None and plotly_png.exists()
                    else None
                ),
                "scene_hash": primary.scene_hash,
                "manifest_sha256": hashlib.sha256(primary.manifest_bytes).hexdigest(),
                "layers": [
                    {
                        "id": layer_id,
                        "bytes": len(data),
                        "sha256": hashlib.sha256(data).hexdigest(),
                    }
                    for layer_id, data in primary.layer_bytes.items()
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return primary


def main() -> None:
    """Command-line entry point for the interactive example runner."""
    if len(sys.argv) != 2:
        raise SystemExit("Usage: _example_runner.py <interactive_example.py>")
    interactive_path = Path(sys.argv[1])
    if not interactive_path.is_file():
        raise SystemExit(f"interactive example not found: {interactive_path}")

    with mock.patch.object(
        plots._InteractiveMixin, "export_html", _comparison_export
    ):
        runpy.run_path(str(interactive_path), run_name="__main__")


if __name__ == "__main__":
    main()
