#!/usr/bin/env python3
"""Reproduce the Starplot custom Plotly.js bundle from a pinned npm release.

Usage::

    python tools/build_plotly_bundle.py --plotly-version 3.3.1 \
        --output src/starplot/interactive/assets/vendor/plotly-starplot-3.3.1.min.js

The script downloads the exact plotly.js tarball from npm, installs its
build-time dependencies, runs the same ``custom-bundle`` task recorded in
``PLOTLY_CUSTOM_BUNDLE.txt``, and verifies the resulting minified bundle
matches the recorded SHA-256 and SHA-384 SRI.  It fails closed on any
mismatch so the tracked bundle can only be updated deliberately.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
from collections.abc import Iterable
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROVENANCE = (
    ROOT / "src/starplot/interactive/assets/vendor/PLOTLY_CUSTOM_BUNDLE.txt"
)
DEFAULT_TRACES = ("scatter", "scattergl", "heatmap", "table")
DEFAULT_OUT_NAME = "starplot"


def _bundle_provenance(path: Path) -> dict[str, str]:
    """Parse the human-readable bundle provenance file."""
    text = path.read_text(encoding="utf-8")
    provenance: dict[str, str] = {}
    for label, key in (
        ("Source package", "source_package"),
        ("Source npm shasum", "source_npm_shasum"),
        ("Source tarball SHA-256", "source_tarball_sha256"),
        ("Build command", "build_command"),
        ("Build kind", "build_kind"),
        ("Included traces", "included_traces"),
        ("Output filename", "output_filename"),
        ("Output bytes", "output_bytes"),
        ("Output SHA-256", "output_sha256"),
        ("Output SHA-384 SRI", "output_sri"),
    ):
        match = re.search(rf"^{re.escape(label)}: (.*)$", text, re.MULTILINE)
        if not match:
            raise ValueError(f"{path} is missing {label}")
        provenance[key] = match.group(1).strip()
    return provenance


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha1(path: Path) -> str:
    digest = hashlib.sha1()  # noqa: S324
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sri_sha384_bytes(content: bytes) -> str:
    digest = hashlib.sha384(content)
    return "sha384-" + base64.b64encode(digest.digest()).decode("ascii")


def _sri_sha384(path: Path) -> str:
    return _sri_sha384_bytes(path.read_bytes())


def _npm_path(npm: str | None = None) -> str:
    if npm:
        if not shutil.which(npm):
            raise RuntimeError(f"npm executable not found: {npm}")
        return npm
    found = shutil.which("npm")
    if not found:
        raise RuntimeError(
            "npm is required to build the Plotly bundle. Install Node.js and npm."
        )
    return found


def _run(
    *args: str,
    cwd: Path,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess:
    """Run a command in a working directory, using the requested npm binary."""
    full_env = {**dict(os.environ), **(env or {})}
    return subprocess.run(
        list(args),
        cwd=cwd,
        check=check,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=full_env,
    )


def fetch_plotly_tarball(
    *,
    version: str,
    destination: Path,
    npm: str | None = None,
) -> tuple[Path, dict[str, object]]:
    """Download the plotly.js tarball from npm and return its path plus npm metadata.

    The metadata dict includes the keys returned by ``npm pack --json``:
    ``shasum``, ``integrity``, ``filename``, etc.
    """
    npm_path = _npm_path(npm)
    destination.mkdir(parents=True, exist_ok=True)
    result = _run(
        npm_path,
        "pack",
        f"plotly.js@{version}",
        "--pack-destination",
        str(destination),
        "--json",
        cwd=destination,
    )
    try:
        pack_info = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(
            f"npm pack produced invalid JSON: {result.stdout[:500]}"
        ) from error
    if not isinstance(pack_info, list) or not pack_info:
        raise RuntimeError(f"npm pack returned unexpected output: {result.stdout[:500]}")
    meta = pack_info[0]
    filename = meta.get("filename")
    if not isinstance(filename, str):
        raise RuntimeError(f"npm pack did not return a filename: {meta}")
    tarball = destination / filename
    if not tarball.is_file():
        raise RuntimeError(f"npm pack did not create {tarball}")
    return tarball, meta


def verify_source_tarball(
    tarball: Path,
    provenance: dict[str, str],
) -> None:
    """Verify the downloaded tarball matches the provenance record."""
    expected_sha1 = provenance["source_npm_shasum"].lower()
    expected_sha256 = provenance["source_tarball_sha256"].lower()
    actual_sha1 = _sha1(tarball)
    actual_sha256 = _sha256(tarball)
    if actual_sha1 != expected_sha1:
        raise ValueError(
            f"npm tarball SHA-1 mismatch: expected {expected_sha1}, got {actual_sha1}"
        )
    if actual_sha256 != expected_sha256:
        raise ValueError(
            f"npm tarball SHA-256 mismatch: expected {expected_sha256}, got {actual_sha256}"
        )


def extract_source(tarball: Path, source_dir: Path) -> Path:
    """Extract the plotly.js source tarball and return the package root."""
    source_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tarball, "r:gz") as archive:
        archive.extractall(source_dir)
    package_root = source_dir / "package"
    if not package_root.is_dir():
        raise RuntimeError("tarball did not extract a 'package' directory")
    return package_root


def install_build_dependencies(package_root: Path, *, npm: str) -> None:
    """Install the plotly.js build-time dependencies."""
    _run(npm, "install", cwd=package_root)


def build_custom_bundle(
    package_root: Path,
    *,
    out_name: str,
    traces: Iterable[str],
    npm: str,
) -> Path:
    """Run the plotly.js ``custom-bundle`` task and return the minified output path."""
    trace_list = ",".join(traces)
    _run(
        npm,
        "run",
        "custom-bundle",
        "--",
        f"--out={out_name}",
        f"--traces={trace_list}",
        cwd=package_root,
    )
    bundle_path = package_root / "dist" / f"plotly-{out_name}.min.js"
    if not bundle_path.is_file():
        raise RuntimeError(f"custom-bundle did not create {bundle_path}")
    return bundle_path


def publish_bundle(bundle_path: Path, output_path: Path) -> None:
    """Copy the built bundle to the requested output path, creating parents."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(bundle_path, output_path)


def verify_output_bundle(output_path: Path, provenance: dict[str, str]) -> None:
    """Fail unless the built bundle matches the recorded hashes."""
    expected_sha256 = provenance["output_sha256"].lower()
    expected_sri = provenance["output_sri"]
    expected_bytes = provenance.get("output_bytes")

    actual_bytes = str(output_path.stat().st_size)
    if expected_bytes is not None and actual_bytes != expected_bytes:
        raise ValueError(
            f"bundle size mismatch: expected {expected_bytes} bytes, got {actual_bytes}"
        )

    actual_sha256 = _sha256(output_path)
    if actual_sha256 != expected_sha256:
        raise ValueError(
            f"bundle SHA-256 mismatch: expected {expected_sha256}, got {actual_sha256}"
        )

    actual_sri = _sri_sha384(output_path)
    if actual_sri != expected_sri:
        raise ValueError(
            f"bundle SRI mismatch: expected {expected_sri}, got {actual_sri}"
        )


def build_bundle(
    *,
    plotly_version: str,
    output_path: Path,
    provenance_path: Path = DEFAULT_PROVENANCE,
    out_name: str = DEFAULT_OUT_NAME,
    traces: Iterable[str] | None = None,
    npm: str | None = None,
    keep_source: Path | None = None,
) -> dict[str, str]:
    """Build and verify a reproducible Plotly.js custom bundle.

    Returns the provenance record used for verification.
    """
    provenance = _bundle_provenance(provenance_path)
    npm_path = _npm_path(npm)
    requested_traces = traces or DEFAULT_TRACES

    if keep_source:
        temp_pack = keep_source / "pack"
        temp_source = keep_source / "source"
    else:
        temp_pack = Path(tempfile.mkdtemp(prefix="plotly-pack-"))
        temp_source = Path(tempfile.mkdtemp(prefix="plotly-source-"))

    try:
        tarball, pack_meta = fetch_plotly_tarball(
            version=plotly_version,
            destination=temp_pack,
            npm=npm_path,
        )
        if pack_meta.get("shasum") != provenance["source_npm_shasum"]:
            raise ValueError(
                "npm pack shasum does not match provenance: "
                f"expected {provenance['source_npm_shasum']}, "
                f"got {pack_meta.get('shasum')}"
            )
        verify_source_tarball(tarball, provenance)
        package_root = extract_source(tarball, temp_source)
        if keep_source:
            # source extraction is already inside keep_source, no further action
            pass
        install_build_dependencies(package_root, npm=npm_path)
        bundle_path = build_custom_bundle(
            package_root,
            out_name=out_name,
            traces=requested_traces,
            npm=npm_path,
        )
        publish_bundle(bundle_path, output_path)
        verify_output_bundle(output_path, provenance)
    finally:
        if not keep_source:
            shutil.rmtree(temp_pack, ignore_errors=True)
            shutil.rmtree(temp_source, ignore_errors=True)

    return provenance


def _versioned_bundle_name(version: str, out_name: str = DEFAULT_OUT_NAME) -> str:
    return f"plotly-{out_name}-{version}.min.js"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--plotly-version",
        required=True,
        help="plotly.js npm version to build (e.g. 3.3.1)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="destination path for the built bundle (default: vendor directory)",
    )
    parser.add_argument(
        "--provenance",
        type=Path,
        default=DEFAULT_PROVENANCE,
        help="path to PLOTLY_CUSTOM_BUNDLE.txt",
    )
    parser.add_argument(
        "--out-name",
        default=DEFAULT_OUT_NAME,
        help="name passed to plotly.js custom-bundle --out",
    )
    parser.add_argument(
        "--traces",
        help="comma-separated trace list (default: from provenance file)",
    )
    parser.add_argument(
        "--npm",
        help="path to npm executable (default: from PATH)",
    )
    parser.add_argument(
        "--keep-source",
        type=Path,
        help="keep downloaded source and build artifacts in this directory",
    )
    args = parser.parse_args(argv)

    provenance = _bundle_provenance(args.provenance)
    traces = (
        tuple(t.strip() for t in args.traces.split(",") if t.strip())
        if args.traces
        else tuple(t.strip() for t in provenance["included_traces"].split(","))
    )

    output = args.output
    if output is None:
        output = (
            args.provenance.parent
            / _versioned_bundle_name(args.plotly_version, args.out_name)
        )

    build_bundle(
        plotly_version=args.plotly_version,
        output_path=output,
        provenance_path=args.provenance,
        out_name=args.out_name,
        traces=traces,
        npm=args.npm,
        keep_source=args.keep_source,
    )
    print(f"Verified bundle written to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
