"""Offline and rebuild safety checks for the pinned Plotly bundle."""

import hashlib
import tempfile
from pathlib import Path

import pytest

import tools.build_plotly_bundle as build


def _fixture(tmp_path: Path, content: bytes) -> tuple[Path, Path]:
    provenance = build.DEFAULT_PROVENANCE.read_text(encoding="utf-8")
    provenance = provenance.replace(
        build.bundle_contract().provenance["output_sha256"],
        hashlib.sha256(content).hexdigest(),
    ).replace(
        build.bundle_contract().provenance["output_sri"],
        build._sri_sha384_bytes(content),
    ).replace(
        "Output bytes: 1533024", f"Output bytes: {len(content)}"
    )
    provenance_path = tmp_path / "PLOTLY_CUSTOM_BUNDLE.txt"
    provenance_path.write_text(provenance, encoding="utf-8")
    bundle = tmp_path / build.bundle_contract(provenance_path).output_filename
    bundle.write_bytes(content)
    return provenance_path, bundle


def test_offline_verifier_rejects_missing_version_banner_even_when_hashes_match(tmp_path):
    provenance, bundle = _fixture(tmp_path, b"/* no version */\n")
    (tmp_path / "PLOTLY_LICENSE.txt").write_text("MIT License\n", encoding="utf-8")

    with pytest.raises(ValueError, match="version banner"):
        build.verify_existing_bundle(provenance)

    assert bundle.is_file()


def test_offline_verifier_rejects_missing_plotly_license(tmp_path):
    provenance, _ = _fixture(
        tmp_path,
        b"/**\n* plotly.js (starplot - minified) v3.3.1\n* Licensed under the MIT license\n*/\n",
    )

    with pytest.raises(ValueError, match="PLOTLY_LICENSE.txt"):
        build.verify_existing_bundle(provenance)


def test_rebuild_cli_requires_temp_work_dir_and_never_targets_vendor(monkeypatch, tmp_path):
    built: list[dict] = []
    monkeypatch.setattr(build, "build_bundle", lambda **kwargs: built.append(kwargs))

    with pytest.raises(SystemExit):
        build.main(["--rebuild"])

    work_dir = Path("/private/tmp") / f"starplot-plotly-test-{tmp_path.name}"
    assert build.main(["--rebuild", "--work-dir", str(work_dir)]) == 0
    assert len(built) == 1
    assert built[0]["output_path"].parent == work_dir
    assert built[0]["output_path"] != (
        build.DEFAULT_PROVENANCE.parent / build.bundle_contract().output_filename
    )


def test_rebuild_cli_reports_comparison_with_existing_bundle(monkeypatch, tmp_path, capsys):
    content = b"/** plotly.js (starplot - minified) v3.3.1 */"
    provenance, _ = _fixture(tmp_path, content)

    def fake_build_bundle(**kwargs):
        kwargs["output_path"].write_bytes(content)

    monkeypatch.setattr(build, "build_bundle", fake_build_bundle)
    with tempfile.TemporaryDirectory(dir="/private/tmp") as work_dir:
        assert build.main([
            "--provenance", str(provenance), "--rebuild", "--work-dir", work_dir
        ]) == 0

    assert "byte-for-byte identical to tracked bundle" in capsys.readouterr().out
