#!/usr/bin/env python3
"""Reproduce the Starplot custom Plotly.js bundle from a pinned npm release.

By default, the script is read-only and verifies the tracked bundle using its
provenance record.  ``--rebuild`` is required to download the pinned source,
run the recorded custom-bundle command, and atomically replace the output only
after its recorded hashes match.
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
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROVENANCE = (
    ROOT / "src/starplot/interactive/assets/vendor/PLOTLY_CUSTOM_BUNDLE.txt"
)
DEFAULT_TRACES = ("scatter", "scattergl", "heatmap", "table")
DEFAULT_OUT_NAME = "starplot"
_INLINE_CSS_PLUGIN = Path("node_modules/esbuild-plugin-inline-css/index.js")
_INLINE_CSS_ABSOLUTE_ID = "const styleID = sha256(sourcePath);"
_INLINE_CSS_RELATIVE_ID = (
    "const styleID = sha256(path.relative(process.cwd(), sourcePath));"
)


@dataclass(frozen=True)
class BundleContract:
    """All rebuild inputs derived from the checked-in provenance record."""

    provenance: dict[str, str]
    version: str
    out_name: str
    traces: tuple[str, ...]
    output_filename: str
    lock_relative_path: Path


def _bundle_provenance(path: Path) -> dict[str, str]:
    """Parse the human-readable bundle provenance file."""
    text = path.read_text(encoding="utf-8")
    provenance: dict[str, str] = {}
    for label, key in (
        ("Source package", "source_package"),
        ("Source npm shasum", "source_npm_shasum"),
        ("Source tarball SHA-256", "source_tarball_sha256"),
        ("Build dependency lock", "build_dependency_lock"),
        ("Build dependency lock SHA-256", "build_dependency_lock_sha256"),
        ("Build Node.js version", "build_node_version"),
        ("Build npm version", "build_npm_version"),
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


def bundle_contract(provenance_path: Path = DEFAULT_PROVENANCE) -> BundleContract:
    """Derive and cross-check immutable rebuild inputs from provenance."""
    provenance = _bundle_provenance(provenance_path)
    source = re.fullmatch(r"plotly\.js@([^ ]+) from the npm registry", provenance["source_package"])
    if not source:
        raise ValueError("Source package must be 'plotly.js@<version> from the npm registry'")
    version = source.group(1)
    traces = tuple(trace.strip() for trace in provenance["included_traces"].split(","))
    if not traces or any(not trace for trace in traces) or len(set(traces)) != len(traces):
        raise ValueError("Included traces must be a non-empty comma-separated list without duplicates")

    command = re.fullmatch(
        r"npm run custom-bundle -- --out(?:=| )([^ ]+) --traces(?:=| )([^ ]+)",
        provenance["build_command"],
    )
    if not command:
        raise ValueError("Build command is not a canonical custom-bundle command")
    out_name, command_traces = command.groups()
    if tuple(command_traces.split(",")) != traces:
        raise ValueError("Build command traces do not match Included traces")

    output_filename = provenance["output_filename"]
    expected_filename = _versioned_bundle_name(version, out_name)
    if output_filename != expected_filename:
        raise ValueError(
            "Output filename does not match source package version and build command: "
            f"expected {expected_filename}, got {output_filename}"
        )
    lock_relative_path = Path(provenance["build_dependency_lock"])
    if lock_relative_path.is_absolute() or ".." in lock_relative_path.parts:
        raise ValueError("Build dependency lock must be a repository-relative path")
    for key in ("source_tarball_sha256", "build_dependency_lock_sha256", "output_sha256"):
        if not re.fullmatch(r"[0-9a-f]{64}", provenance[key], re.IGNORECASE):
            raise ValueError(f"{key} must be a SHA-256 digest")
    if not re.fullmatch(r"sha384-[A-Za-z0-9+/]+={0,2}", provenance["output_sri"]):
        raise ValueError("Output SHA-384 SRI is invalid")
    return BundleContract(
        provenance=provenance,
        version=version,
        out_name=out_name,
        traces=traces,
        output_filename=output_filename,
        lock_relative_path=lock_relative_path,
    )


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


def _node_path() -> str:
    found = shutil.which("node")
    if not found:
        raise RuntimeError("node is required to build the Plotly bundle. Install Node.js.")
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


def validate_build_environment(contract: BundleContract, *, npm: str) -> Path:
    """Validate the committed lock and exact Node/npm versions before building."""
    lock_path = (ROOT / contract.lock_relative_path).resolve()
    if ROOT not in lock_path.parents or not lock_path.is_file():
        raise ValueError(f"Build dependency lock is missing: {contract.lock_relative_path}")
    actual_lock_hash = _sha256(lock_path)
    expected_lock_hash = contract.provenance["build_dependency_lock_sha256"].lower()
    if actual_lock_hash != expected_lock_hash:
        raise ValueError(
            "Build dependency lock SHA-256 mismatch: "
            f"expected {expected_lock_hash}, got {actual_lock_hash}"
        )
    node_version = _run(_node_path(), "--version", cwd=ROOT).stdout.strip()
    npm_version = _run(npm, "--version", cwd=ROOT).stdout.strip()
    if node_version != contract.provenance["build_node_version"]:
        raise ValueError(
            f"Node.js version mismatch: expected {contract.provenance['build_node_version']}, got {node_version}"
        )
    if npm_version != contract.provenance["build_npm_version"]:
        raise ValueError(
            f"npm version mismatch: expected {contract.provenance['build_npm_version']}, got {npm_version}"
        )
    return lock_path


def install_build_dependencies(package_root: Path, *, npm: str, lock_path: Path) -> None:
    """Install exactly the committed Plotly build dependencies with npm ci."""
    shutil.copyfile(lock_path, package_root / "package-lock.json")
    _run(npm, "ci", cwd=package_root)


def normalize_inline_css_ids(package_root: Path) -> None:
    """Remove the extraction path from generated inline-style identifiers.

    Plotly's build dependency hashes each CSS file's absolute source path into
    the bundle.  Temporary extraction directories therefore produce different
    bytes despite identical source, lock, and toolchain.  Patch the one pinned
    plugin statement to hash a package-relative path and fail closed if the
    locked dependency no longer has the expected implementation.
    """
    plugin_path = package_root / _INLINE_CSS_PLUGIN
    source = plugin_path.read_text(encoding="utf-8")
    if source.count(_INLINE_CSS_ABSOLUTE_ID) != 1:
        raise ValueError(
            "pinned inline-CSS plugin no longer has the expected absolute-path hash"
        )
    plugin_path.write_text(
        source.replace(_INLINE_CSS_ABSOLUTE_ID, _INLINE_CSS_RELATIVE_ID),
        encoding="utf-8",
    )


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


def publish_bundle(bundle_path: Path, output_path: Path, provenance: dict[str, str]) -> None:
    """Verify a same-filesystem temporary copy, then atomically publish it."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=output_path.parent,
        prefix=f".{output_path.name}.",
        suffix=".tmp",
        delete=False,
    ) as temporary:
        temporary_path = Path(temporary.name)
    try:
        shutil.copyfile(bundle_path, temporary_path)
        verify_output_bundle(temporary_path, provenance)
        os.replace(temporary_path, output_path)
    finally:
        temporary_path.unlink(missing_ok=True)


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
    output_path: Path,
    provenance_path: Path = DEFAULT_PROVENANCE,
    npm: str | None = None,
    keep_source: Path | None = None,
    plotly_version: str | None = None,
    out_name: str | None = None,
    traces: Iterable[str] | None = None,
) -> dict[str, str]:
    """Build and verify a reproducible Plotly.js custom bundle.

    Returns the provenance record used for verification.
    """
    contract = bundle_contract(provenance_path)
    provenance = contract.provenance
    if plotly_version is not None and plotly_version != contract.version:
        raise ValueError("plotly_version must match the provenance Source package")
    if out_name is not None and out_name != contract.out_name:
        raise ValueError("out_name must match the provenance Build command")
    if traces is not None and tuple(traces) != contract.traces:
        raise ValueError("traces must match the provenance Included traces")
    expected_output = provenance_path.parent / contract.output_filename
    if output_path != expected_output:
        raise ValueError(f"output_path must be the provenance output: {expected_output}")
    npm_path = _npm_path(npm)
    lock_path = validate_build_environment(contract, npm=npm_path)

    if keep_source:
        temp_pack = keep_source / "pack"
        temp_source = keep_source / "source"
    else:
        temp_pack = Path(tempfile.mkdtemp(prefix="plotly-pack-"))
        temp_source = Path(tempfile.mkdtemp(prefix="plotly-source-"))

    try:
        tarball, pack_meta = fetch_plotly_tarball(
            version=contract.version,
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
        install_build_dependencies(package_root, npm=npm_path, lock_path=lock_path)
        normalize_inline_css_ids(package_root)
        bundle_path = build_custom_bundle(
            package_root,
            out_name=contract.out_name,
            traces=contract.traces,
            npm=npm_path,
        )
        publish_bundle(bundle_path, output_path, provenance)
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
        "--rebuild",
        action="store_true",
        help="download and rebuild the bundle after validating the pinned toolchain",
    )
    parser.add_argument(
        "--provenance",
        type=Path,
        default=DEFAULT_PROVENANCE,
        help="path to PLOTLY_CUSTOM_BUNDLE.txt",
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

    contract = bundle_contract(args.provenance)
    output = args.provenance.parent / contract.output_filename
    if not args.rebuild:
        verify_output_bundle(output, contract.provenance)
        print(f"Verified existing bundle: {output}")
        return 0

    build_bundle(
        output_path=output,
        provenance_path=args.provenance,
        npm=args.npm,
        keep_source=args.keep_source,
    )
    print(f"Rebuilt and verified bundle: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
