#!/usr/bin/env python3
"""Reproducibly synchronize the pinned Apache Arrow browser distribution."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "web" / "package-lock.json"
UPSTREAM_PATH = (
    ROOT / "web" / "node_modules" / "apache-arrow" / "Arrow.es2015.min.js"
)
VENDORED_PATH = (
    ROOT
    / "src"
    / "starplot"
    / "interactive"
    / "assets"
    / "vendor"
    / "apache-arrow.min.js"
)
EXPECTED_VERSION = "21.1.0"
EXPECTED_SHA256 = "d3f0ded2a2bdd1208232b942f8e4810f7a402564fac3c78b4574158cd542acb9"
UPSTREAM_LEGAL = {
    "LICENSE.txt": "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30",
    "NOTICE.txt": "f4cdb3db59bdaccc1447eae829905cde61dfd7508dca5c4ebff98a998c036ae6",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _locked_arrow_version() -> str:
    try:
        lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
        return lock["packages"]["node_modules/apache-arrow"]["version"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise RuntimeError(f"cannot read Apache Arrow version from {LOCK_PATH}") from error


def synchronize(*, check: bool) -> None:
    version = _locked_arrow_version()
    if version != EXPECTED_VERSION:
        raise RuntimeError(
            f"package lock has apache-arrow {version!r}; expected {EXPECTED_VERSION!r}"
        )
    if not UPSTREAM_PATH.is_file():
        raise RuntimeError(
            f"official Arrow browser distribution is missing: {UPSTREAM_PATH}; "
            "run `npm install` in web/"
        )
    upstream_hash = _sha256(UPSTREAM_PATH)
    if upstream_hash != EXPECTED_SHA256:
        raise RuntimeError(
            "official Arrow browser distribution checksum changed: "
            f"expected {EXPECTED_SHA256}, got {upstream_hash}"
        )
    if check:
        if not VENDORED_PATH.is_file():
            raise RuntimeError(f"vendored Arrow browser distribution is missing: {VENDORED_PATH}")
        vendored_hash = _sha256(VENDORED_PATH)
        if vendored_hash != EXPECTED_SHA256:
            raise RuntimeError(
                f"vendored Arrow checksum mismatch: expected {EXPECTED_SHA256}, "
                f"got {vendored_hash}"
            )
        if VENDORED_PATH.read_bytes() != UPSTREAM_PATH.read_bytes():
            raise RuntimeError("vendored Arrow bytes differ from the official distribution")
        for filename, expected_hash in UPSTREAM_LEGAL.items():
            upstream = UPSTREAM_PATH.parent / filename
            vendored = VENDORED_PATH.parent / filename
            if not upstream.is_file() or _sha256(upstream) != expected_hash:
                raise RuntimeError(f"official Arrow {filename} checksum changed")
            if not vendored.is_file() or _sha256(vendored) != expected_hash or vendored.read_bytes() != upstream.read_bytes():
                raise RuntimeError(f"vendored Arrow {filename} is not synchronized")
        print(f"Arrow JS {version} asset is synchronized ({vendored_hash})")
        return

    VENDORED_PATH.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{VENDORED_PATH.name}.", dir=VENDORED_PATH.parent
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        shutil.copyfile(UPSTREAM_PATH, temporary_path)
        temporary_path.chmod(0o644)
        if _sha256(temporary_path) != EXPECTED_SHA256:
            raise RuntimeError("copied Arrow browser distribution failed checksum validation")
        os.replace(temporary_path, VENDORED_PATH)
    finally:
        temporary_path.unlink(missing_ok=True)
    for filename, expected_hash in UPSTREAM_LEGAL.items():
        upstream = UPSTREAM_PATH.parent / filename
        if not upstream.is_file() or _sha256(upstream) != expected_hash:
            raise RuntimeError(f"official Arrow {filename} checksum changed")
        destination = VENDORED_PATH.parent / filename
        shutil.copyfile(upstream, destination)
        destination.chmod(0o644)
    print(f"Synchronized Arrow JS {version} asset ({EXPECTED_SHA256})")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the vendored bytes without modifying them",
    )
    arguments = parser.parse_args()
    try:
        synchronize(check=arguments.check)
    except RuntimeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
