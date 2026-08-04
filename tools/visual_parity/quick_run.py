#!/usr/bin/env python3
"""Quickly run a single example pair with the inline transport.

Usage:
    python tools/visual_parity/quick_run.py horizon_sgr

This is a thin wrapper around ``gen_comparison.py`` that only runs the inline
browser transport, producing the same per-example directory layout but skipping
the full external/provider comparison cycle.
"""

from __future__ import annotations

import re
import sys

if __package__:
    from . import gen_comparison
else:
    import gen_comparison

_EXAMPLE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def main(name: str) -> None:
    if not name or not _EXAMPLE_NAME_RE.fullmatch(name):
        raise ValueError(f"invalid example name: {name!r}")
    gen_comparison.run_example(name, ("inline",))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python quick_run.py <example_name>")
        print("Examples: horizon_sgr, map_orion, star_chart_basic")
        sys.exit(1)
    main(sys.argv[1])
