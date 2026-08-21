"""Unit tests for the Plotly.js custom bundle reproducibility script."""

import base64
import hashlib
import io
import json
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

import tools.build_plotly_bundle as build


PROVENANCE_TEMPLATE = """\
Starplot Plotly.js custom bundle provenance
===========================================

Source package: plotly.js@3.3.1 from the npm registry
Source npm shasum: {shasum}
Source tarball SHA-256: {tarball_sha256}
Build dependency lock: tools/plotly_bundle_locks/plotly.js-3.3.1-package-lock.json
Build dependency lock SHA-256: {lock_sha256}
Build Node.js version: v26.5.0
Build npm version: 11.17.0
Build command: npm run custom-bundle -- --out starplot --traces {traces}
Build kind: official non-strict custom bundle
Included traces: {traces}
Output filename: plotly-starplot-3.3.1.min.js
Output bytes: {bytes}
Output SHA-256: {sha256}
Output SHA-384 SRI: {sri}

The bundle is generated, not hand-edited. Rebuild it only from the exact
source version above, review the trace list, and update all hashes together.
Plotly.js is distributed under the MIT license in PLOTLY_LICENSE.txt.
"""


def _make_tarball(content: bytes, filename: str = "plotly.js-3.3.1.tgz") -> tuple[Path, str, str]:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        info = tarfile.TarInfo(name="package/bundle.js")
        info.size = len(content)
        archive.addfile(info, io.BytesIO(content))
    tarball_bytes = buffer.getvalue()
    shasum = hashlib.sha1(tarball_bytes).hexdigest()  # noqa: S324
    sha256 = hashlib.sha256(tarball_bytes).hexdigest()
    return tarball_bytes, shasum, sha256


def _bundle_content() -> bytes:
    return b"/* starplot custom plotly bundle */"


def _bundle_hashes(content: bytes) -> tuple[str, str]:
    sha256 = hashlib.sha256(content).hexdigest()
    sri = build._sri_sha384_bytes(content)
    return sha256, sri


def _write_provenance(
    path: Path,
    tarball_bytes: bytes,
    bundle_bytes: bytes,
    traces: str,
    *,
    lock_bytes: bytes = b'{"lockfileVersion": 3}\n',
) -> None:
    shasum = hashlib.sha1(tarball_bytes).hexdigest()  # noqa: S324
    tarball_sha256 = hashlib.sha256(tarball_bytes).hexdigest()
    sha256, sri = _bundle_hashes(bundle_bytes)
    path.write_text(
        PROVENANCE_TEMPLATE.format(
            shasum=shasum,
            tarball_sha256=tarball_sha256,
            lock_sha256=hashlib.sha256(lock_bytes).hexdigest(),
            traces=traces,
            bytes=len(bundle_bytes),
            sha256=sha256,
            sri=sri,
        ),
        encoding="utf-8",
    )


def _fake_run_factory(
    tarball: bytes,
    bundle: bytes,
    traces: str,
):
    def fake_run(*args, cwd, **kwargs):
        cmd = list(args)
        completed = SimpleNamespace(returncode=0, stdout="", stderr="")

        if cmd[1:3] == ["pack", "plotly.js@3.3.1"]:
            dest = Path(cmd[4])
            dest.mkdir(parents=True, exist_ok=True)
            (dest / "plotly.js-3.3.1.tgz").write_bytes(tarball)
            completed.stdout = json.dumps(
                [
                    {
                        "id": "plotly.js@3.3.1",
                        "shasum": hashlib.sha1(tarball).hexdigest(),  # noqa: S324
                        "filename": "plotly.js-3.3.1.tgz",
                    }
                ]
            )
            return completed

        if cmd[1] == "ci":
            return completed

        if cmd[1:4] == ["run", "custom-bundle", "--"]:
            package_root = cwd / "dist"
            package_root.mkdir(parents=True, exist_ok=True)
            (package_root / "plotly-starplot.min.js").write_bytes(bundle)
            return completed

        raise AssertionError(f"unexpected command: {cmd}")

    return fake_run


def test_bundle_provenance_parser():
    content = b"/* bundle */"
    tarball, shasum, tarball_sha = _make_tarball(content)
    sha, sri = _bundle_hashes(content)
    provenance = Path("/tmp/fake-provenance.txt")
    _write_provenance(provenance, tarball, content, "scatter,scattergl,heatmap,table")

    parsed = build._bundle_provenance(provenance)

    assert parsed["source_npm_shasum"] == shasum
    assert parsed["source_tarball_sha256"] == tarball_sha
    assert parsed["included_traces"] == "scatter,scattergl,heatmap,table"
    assert parsed["output_sha256"] == sha
    assert parsed["output_sri"] == sri


def test_bundle_contract_is_derived_from_and_validated_against_provenance(tmp_path):
    bundle = _bundle_content()
    tarball, *_ = _make_tarball(bundle)
    provenance_path = tmp_path / "PLOTLY_CUSTOM_BUNDLE.txt"
    _write_provenance(
        provenance_path, tarball, bundle, "heatmap,scatter,scattergl,table"
    )

    contract = build.bundle_contract(provenance_path)

    assert contract.version == "3.3.1"
    assert contract.out_name == "starplot"
    assert contract.traces == ("heatmap", "scatter", "scattergl", "table")
    assert contract.output_filename == "plotly-starplot-3.3.1.min.js"


def test_bundle_contract_rejects_a_build_command_that_disagrees_with_traces(tmp_path):
    bundle = _bundle_content()
    tarball, *_ = _make_tarball(bundle)
    provenance_path = tmp_path / "PLOTLY_CUSTOM_BUNDLE.txt"
    _write_provenance(provenance_path, tarball, bundle, "heatmap,scatter")
    provenance_path.write_text(
        provenance_path.read_text(encoding="utf-8").replace(
            "--traces heatmap,scatter", "--traces scatter,heatmap"
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Build command"):
        build.bundle_contract(provenance_path)


def test_validate_build_environment_checks_the_locked_toolchain(monkeypatch, tmp_path):
    bundle = _bundle_content()
    tarball, *_ = _make_tarball(bundle)
    lock_path = tmp_path / "tools/plotly_bundle_locks/plotly.js-3.3.1-package-lock.json"
    lock_path.parent.mkdir(parents=True)
    lock_path.write_text('{"lockfileVersion": 3}\n', encoding="utf-8")
    provenance_path = tmp_path / "PLOTLY_CUSTOM_BUNDLE.txt"
    _write_provenance(
        provenance_path,
        tarball,
        bundle,
        "scatter,scattergl,heatmap,table",
        lock_bytes=lock_path.read_bytes(),
    )
    monkeypatch.setattr(build, "ROOT", tmp_path)
    monkeypatch.setattr(build, "_node_path", lambda: "node")

    def fake_run(*args, **_):
        versions = {"node": "v26.5.0", "npm": "11.17.0"}
        return SimpleNamespace(stdout=versions[args[0]] + "\n", stderr="")

    monkeypatch.setattr(build, "_run", fake_run)

    assert build.validate_build_environment(
        build.bundle_contract(provenance_path), npm="npm"
    ) == lock_path


def test_bundle_provenance_rejects_missing_field(tmp_path):
    path = tmp_path / "provenance.txt"
    path.write_text("Starplot Plotly.js custom bundle provenance\n", encoding="utf-8")

    with pytest.raises(ValueError, match="missing Source package"):
        build._bundle_provenance(path)


def test_sri_sha384_matches_recorded_format():
    content = b"test content"
    expected = (
        "sha384-"
        + base64.b64encode(hashlib.sha384(content).digest()).decode("ascii")
    )
    assert build._sri_sha384_bytes(content) == expected


def test_inline_css_ids_are_normalized_to_package_relative_paths(tmp_path):
    plugin = tmp_path / build._INLINE_CSS_PLUGIN
    plugin.parent.mkdir(parents=True)
    plugin.write_text(
        "const path = require('path');\n"
        f"{build._INLINE_CSS_ABSOLUTE_ID}\n",
        encoding="utf-8",
    )

    build.normalize_inline_css_ids(tmp_path)

    normalized = plugin.read_text(encoding="utf-8")
    assert build._INLINE_CSS_ABSOLUTE_ID not in normalized
    assert build._INLINE_CSS_RELATIVE_ID in normalized

    with pytest.raises(ValueError, match="expected absolute-path hash"):
        build.normalize_inline_css_ids(tmp_path)


def test_build_bundle_passes_with_matching_hashes(monkeypatch, tmp_path):
    bundle = _bundle_content()
    tarball, *_ = _make_tarball(bundle)
    provenance_path = tmp_path / "PLOTLY_CUSTOM_BUNDLE.txt"
    _write_provenance(provenance_path, tarball, bundle, "scatter,scattergl,heatmap,table")

    monkeypatch.setattr(build, "_run", _fake_run_factory(tarball, bundle, "scatter,scattergl,heatmap,table"))
    monkeypatch.setattr(build, "normalize_inline_css_ids", lambda *_: None)
    lock_path = tmp_path / "package-lock.json"
    lock_path.write_text('{"lockfileVersion": 3}\n', encoding="utf-8")
    monkeypatch.setattr(build, "validate_build_environment", lambda *_, **__: lock_path)

    output = tmp_path / "plotly-starplot-3.3.1.min.js"
    build.build_bundle(
        plotly_version="3.3.1",
        output_path=output,
        provenance_path=provenance_path,
    )

    assert output.is_file()
    assert output.read_bytes() == bundle


def test_build_bundle_fails_when_output_hash_differs(monkeypatch, tmp_path):
    bundle = _bundle_content()
    bad_bundle = bundle.replace(b"custom", b"tamper")
    tarball, *_ = _make_tarball(bundle)
    provenance_path = tmp_path / "PLOTLY_CUSTOM_BUNDLE.txt"
    _write_provenance(provenance_path, tarball, bundle, "scatter,scattergl,heatmap,table")

    monkeypatch.setattr(build, "_run", _fake_run_factory(tarball, bad_bundle, "scatter,scattergl,heatmap,table"))
    monkeypatch.setattr(build, "normalize_inline_css_ids", lambda *_: None)
    lock_path = tmp_path / "package-lock.json"
    lock_path.write_text('{"lockfileVersion": 3}\n', encoding="utf-8")
    monkeypatch.setattr(build, "validate_build_environment", lambda *_, **__: lock_path)

    output = tmp_path / "plotly-starplot-3.3.1.min.js"
    with pytest.raises(ValueError, match="bundle SHA-256 mismatch"):
        build.build_bundle(
            plotly_version="3.3.1",
            output_path=output,
            provenance_path=provenance_path,
        )


def test_build_bundle_does_not_replace_existing_output_when_verification_fails(
    monkeypatch, tmp_path
):
    bundle = _bundle_content()
    tarball, *_ = _make_tarball(bundle)
    provenance_path = tmp_path / "PLOTLY_CUSTOM_BUNDLE.txt"
    _write_provenance(provenance_path, tarball, bundle, "scatter,scattergl,heatmap,table")
    monkeypatch.setattr(
        build,
        "_run",
        _fake_run_factory(tarball, bundle.replace(b"custom", b"tamper"), ""),
    )
    monkeypatch.setattr(build, "normalize_inline_css_ids", lambda *_: None)
    lock_path = tmp_path / "package-lock.json"
    lock_path.write_text('{"lockfileVersion": 3}\n', encoding="utf-8")
    monkeypatch.setattr(build, "validate_build_environment", lambda *_, **__: lock_path)
    output = tmp_path / "plotly-starplot-3.3.1.min.js"
    output.write_bytes(b"known-good-bundle")

    with pytest.raises(ValueError, match="bundle SHA-256 mismatch"):
        build.build_bundle(
            plotly_version="3.3.1",
            output_path=output,
            provenance_path=provenance_path,
        )

    assert output.read_bytes() == b"known-good-bundle"


def test_main_without_rebuild_verifies_existing_bundle_without_npm(monkeypatch, tmp_path):
    bundle = _bundle_content()
    tarball, *_ = _make_tarball(bundle)
    provenance_path = tmp_path / "PLOTLY_CUSTOM_BUNDLE.txt"
    _write_provenance(provenance_path, tarball, bundle, "scatter,scattergl,heatmap,table")
    output = tmp_path / "plotly-starplot-3.3.1.min.js"
    output.write_bytes(bundle)
    monkeypatch.setattr(build, "_npm_path", lambda *_: pytest.fail("npm called"))

    assert build.main(["--provenance", str(provenance_path)]) == 0


def test_main_requires_explicit_rebuild_before_calling_builder(monkeypatch, tmp_path):
    bundle = _bundle_content()
    tarball, *_ = _make_tarball(bundle)
    provenance_path = tmp_path / "PLOTLY_CUSTOM_BUNDLE.txt"
    _write_provenance(provenance_path, tarball, bundle, "scatter,scattergl,heatmap,table")
    output = tmp_path / "plotly-starplot-3.3.1.min.js"
    output.write_bytes(bundle)
    rebuilt: list[dict] = []
    monkeypatch.setattr(build, "build_bundle", lambda **kwargs: rebuilt.append(kwargs))

    build.main(["--provenance", str(provenance_path)])
    assert rebuilt == []

    build.main(["--provenance", str(provenance_path), "--rebuild"])
    assert len(rebuilt) == 1


def test_main_cli_rebuild_derives_the_output_path_from_provenance(monkeypatch, tmp_path):
    bundle = _bundle_content()
    tarball, *_ = _make_tarball(bundle)
    provenance_path = tmp_path / "PLOTLY_CUSTOM_BUNDLE.txt"
    _write_provenance(provenance_path, tarball, bundle, "scatter,scattergl,heatmap,table")

    built: list[dict] = []

    def fake_build_bundle(**kwargs):
        built.append(kwargs)
        return {}

    monkeypatch.setattr(build, "build_bundle", fake_build_bundle)

    build.main([
        "--provenance",
        str(provenance_path),
        "--rebuild",
    ])

    assert built[0]["output_path"] == tmp_path / "plotly-starplot-3.3.1.min.js"


def test_main_cli_rejects_unrecorded_trace_overrides(tmp_path):
    bundle = _bundle_content()
    tarball, *_ = _make_tarball(bundle)
    provenance_path = tmp_path / "PLOTLY_CUSTOM_BUNDLE.txt"
    _write_provenance(provenance_path, tarball, bundle, "scatter, scattergl, heatmap, table")

    with pytest.raises(SystemExit):
        build.main([
            "--provenance",
            str(provenance_path),
            "--rebuild",
            "--traces",
            "scatter,heatmap",
        ])


def test_npm_path_requires_existing_executable():
    with pytest.raises(RuntimeError, match="npm executable not found"):
        build._npm_path("/does/not/exist/npm")
