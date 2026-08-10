"""Unit tests for the visual parity comparison harness helpers."""

import hashlib
import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

pytest.importorskip("starplot")
from starplot.interactive.scene import (
    ColumnarData,
    CoordinateEncoding,
    CoordinateEncodingKind,
    CoordinateSpace,
    InteractionPolicy,
    SceneKind,
    SceneLayer,
    ScenePackage,
)
from starplot.interactive.web_export import export_scene_html
import tools.visual_parity.gen_comparison as gen
import tools.visual_parity._example_runner as runner


def _ls_files_response(root: Path) -> str:
    """Return a fake ``git ls-files`` listing for the visual code scope."""
    tracked = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if rel.startswith("src/starplot/interactive/") or rel == "pyproject.toml":
            tracked.append(rel)
    return "\n".join(tracked) + "\n"


@pytest.fixture
def fake_root(tmp_path, monkeypatch):
    """Build a fake repo tree with all files referenced by provenance."""
    files = {
        "src/starplot/interactive/__init__.py": b"init",
        "src/starplot/interactive/extra/scene.py": b"scene",
        "src/starplot/interactive/assets/starplot-scene-loader.js": b"loader",
        "src/starplot/interactive/assets/plotly-scene-adapter.js": b"adapter",
        "src/starplot/interactive/assets/vendor/plotly-starplot-3.3.1.min.js": b"plotly",
        "src/starplot/interactive/assets/vendor/PLOTLY_CUSTOM_BUNDLE.txt": b"bundle",
        "src/starplot/interactive/assets/vendor/apache-arrow.min.js": b"arrow",
        "pyproject.toml": b"[project]",
        "examples/horizon_double_cluster.py": b"original",
        "examples/interactive/horizon_double_cluster_interactive.py": b"interactive",
        "tools/visual_parity/gen_comparison.py": b"harness",
        "tools/visual_parity/_example_runner.py": b"runner",
        "tools/visual_parity/crops.py": b"crops",
        "tools/visual_parity/server.py": b"server",
    }
    for rel, content in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    monkeypatch.setattr(
        gen,
        "_runtime_versions",
        lambda: {
            "python": "3.12.0",
            "matplotlib": "3.8.0",
            "plotly": "6.0.0",
            "kaleido": "0.2.0",
            "numpy": "1.26.0",
            "pyarrow": "14.0.0",
            "playwright": "1.50.0",
        },
    )
    monkeypatch.setattr(gen, "_platform_info", lambda: "Darwin-test")
    monkeypatch.setattr(gen, "_browser_info", lambda: {"engine": "chromium", "version": "120.0"})

    return tmp_path


def _fake_git_stdout(fake_root: Path, dirty: bool = False):
    """Return a fake ``_git_stdout`` closure for ``fake_root``."""

    def _git_stdout(root, *args):
        assert root == fake_root
        if args == ("rev-parse", "HEAD"):
            return "a" * 40 + "\n"
        if args == ("status", "--porcelain", "--untracked-files=no"):
            return " M src/starplot/interactive/__init__.py\n" if dirty else ""
        if args[:2] == ("ls-files", "--"):
            return _ls_files_response(root)
        raise AssertionError(args)

    return _git_stdout


class TestProvenanceSnapshot:
    """Tests for the fail-closed provenance snapshot."""

    def test_snapshot_provenance_binds_revision_dirty_state_and_assets(
        self, monkeypatch, fake_root
    ):
        monkeypatch.setattr(gen, "_git_stdout", _fake_git_stdout(fake_root, dirty=True))

        prov = gen._snapshot_provenance(fake_root, "horizon_double_cluster")

        assert prov["git_revision"] == "a" * 40
        assert prov["tracked_dirty"] is True
        assert prov["source_fingerprint"].startswith("sha256:")
        assert prov["source_fingerprint_scope"] == [
            "pyproject.toml",
            "src/starplot/interactive/__init__.py",
            "src/starplot/interactive/assets/plotly-scene-adapter.js",
            "src/starplot/interactive/assets/starplot-scene-loader.js",
            "src/starplot/interactive/assets/vendor/PLOTLY_CUSTOM_BUNDLE.txt",
            "src/starplot/interactive/assets/vendor/apache-arrow.min.js",
            "src/starplot/interactive/assets/vendor/plotly-starplot-3.3.1.min.js",
            "src/starplot/interactive/extra/scene.py",
        ]
        assert prov["assets"] == {
            "src/starplot/interactive/assets/starplot-scene-loader.js": hashlib.sha256(
                b"loader"
            ).hexdigest(),
            "src/starplot/interactive/assets/plotly-scene-adapter.js": hashlib.sha256(
                b"adapter"
            ).hexdigest(),
            "src/starplot/interactive/assets/vendor/apache-arrow.min.js": hashlib.sha256(
                b"arrow"
            ).hexdigest(),
            "src/starplot/interactive/assets/vendor/PLOTLY_CUSTOM_BUNDLE.txt": hashlib.sha256(
                b"bundle"
            ).hexdigest(),
            "src/starplot/interactive/assets/vendor/plotly-starplot-3.3.1.min.js": hashlib.sha256(
                b"plotly"
            ).hexdigest(),
        }
        assert prov["runtime_versions"] == {
            "python": "3.12.0",
            "matplotlib": "3.8.0",
            "plotly": "6.0.0",
            "kaleido": "0.2.0",
            "numpy": "1.26.0",
            "pyarrow": "14.0.0",
            "playwright": "1.50.0",
        }
        assert prov["browser"] == {"engine": "chromium", "version": "120.0"}
        assert prov["platform"] == "Darwin-test"
        assert prov["example_scripts"] == {
            "original": hashlib.sha256(b"original").hexdigest(),
            "interactive": hashlib.sha256(b"interactive").hexdigest(),
        }
        assert prov["runner_code"] == {
            "tools/visual_parity/_example_runner.py": hashlib.sha256(b"runner").hexdigest(),
            "tools/visual_parity/crops.py": hashlib.sha256(b"crops").hexdigest(),
            "tools/visual_parity/gen_comparison.py": hashlib.sha256(b"harness").hexdigest(),
            "tools/visual_parity/server.py": hashlib.sha256(b"server").hexdigest(),
        }

    def test_tracked_dirty_tree_raises_before_generation(self, monkeypatch):
        def fake_snapshot(root, name):
            return {"tracked_dirty": True}

        monkeypatch.setattr(gen, "_snapshot_provenance", fake_snapshot)

        with pytest.raises(RuntimeError, match="tracked source tree is dirty"):
            gen.run_example("horizon_double_cluster", ("inline",))

    def test_key_asset_change_causes_post_mismatch(self, monkeypatch, fake_root):
        monkeypatch.setattr(gen, "_git_stdout", _fake_git_stdout(fake_root, dirty=False))

        pre = gen._snapshot_provenance(fake_root, "horizon_double_cluster")
        (fake_root / "src/starplot/interactive/assets/starplot-scene-loader.js").write_text(
            "modified loader"
        )
        post = gen._snapshot_provenance(fake_root, "horizon_double_cluster")

        with pytest.raises(RuntimeError, match="provenance changed"):
            gen._assert_snapshots_equal(pre, post)

    def test_pre_post_consistency_succeeds_when_unchanged(self, monkeypatch, fake_root):
        monkeypatch.setattr(gen, "_git_stdout", _fake_git_stdout(fake_root, dirty=False))

        pre = gen._snapshot_provenance(fake_root, "horizon_double_cluster")
        post = gen._snapshot_provenance(fake_root, "horizon_double_cluster")

        gen._assert_snapshots_equal(pre, post)
        assert pre == post

    def test_untracked_docs_do_not_trigger_dirty(self, monkeypatch, fake_root):
        (fake_root / "INTERACTIVE_BACKEND_FINAL_REVIEW_HANDOFF.md").write_text("docs")
        calls = []

        def fake_git_stdout(root, *args):
            calls.append(args)
            if args == ("rev-parse", "HEAD"):
                return "a" * 40 + "\n"
            if args == ("status", "--porcelain", "--untracked-files=no"):
                return ""
            if args[:2] == ("ls-files", "--"):
                return _ls_files_response(root)
            raise AssertionError(args)

        monkeypatch.setattr(gen, "_git_stdout", fake_git_stdout)

        prov = gen._snapshot_provenance(fake_root, "horizon_double_cluster")

        assert prov["tracked_dirty"] is False
        status_calls = [c for c in calls if c and c[0] == "status"]
        assert all("--untracked-files=no" in c for c in status_calls)

    def test_tracked_dirty_detects_modified_tracked_file(self, monkeypatch, fake_root):
        monkeypatch.setattr(gen, "_git_stdout", _fake_git_stdout(fake_root, dirty=True))

        prov = gen._snapshot_provenance(fake_root, "horizon_double_cluster")

        assert prov["tracked_dirty"] is True

    def test_require_clean_tree(self):
        gen._require_clean_tree({"tracked_dirty": False})

        with pytest.raises(RuntimeError, match="tracked source tree is dirty"):
            gen._require_clean_tree({"tracked_dirty": True})


class TestAtomicPublish:
    """Tests for the staging/atomic publish logic."""

    def test_atomic_publish_moves_staging_to_new_final(self, monkeypatch, tmp_path):
        output = tmp_path / "comparison_outputs"
        output.mkdir()
        monkeypatch.setattr(gen, "OUTPUT", output)

        staging_root = output / ".staging"
        staging_root.mkdir()
        staging = staging_root / "example-abc"
        staging.mkdir()
        (staging / "file.txt").write_text("new")

        final = output / "example"
        backup = staging_root / "example-abc-backup"

        gen._atomic_publish(staging, final, backup)

        assert not staging.exists()
        assert not backup.exists()
        assert final.is_dir()
        assert (final / "file.txt").read_text() == "new"

    def test_atomic_publish_replaces_existing_final(self, monkeypatch, tmp_path):
        output = tmp_path / "comparison_outputs"
        output.mkdir()
        monkeypatch.setattr(gen, "OUTPUT", output)

        staging_root = output / ".staging"
        staging_root.mkdir()
        staging = staging_root / "example-abc"
        staging.mkdir()
        (staging / "file.txt").write_text("new")

        final = output / "example"
        final.mkdir()
        (final / "old.txt").write_text("old")

        backup = staging_root / "example-abc-backup"

        gen._atomic_publish(staging, final, backup)

        assert not staging.exists()
        assert not backup.exists()
        assert (final / "file.txt").read_text() == "new"
        assert not (final / "old.txt").exists()

    def test_atomic_publish_restores_backup_on_publish_failure(self, monkeypatch, tmp_path):
        original_replace = os.replace

        output = tmp_path / "comparison_outputs"
        output.mkdir()
        monkeypatch.setattr(gen, "OUTPUT", output)

        staging_root = output / ".staging"
        staging_root.mkdir()
        staging = staging_root / "example-abc"
        staging.mkdir()
        (staging / "new.txt").write_text("new")

        final = output / "example"
        final.mkdir()
        (final / "old.txt").write_text("old")

        backup = staging_root / "example-abc-backup"

        def failing_replace(src, dst):
            if Path(src) == staging and Path(dst) == final:
                raise OSError("publish failed")
            original_replace(src, dst)

        monkeypatch.setattr(os, "replace", failing_replace)

        with pytest.raises(OSError, match="publish failed"):
            gen._atomic_publish(staging, final, backup)

        assert (final / "old.txt").read_text() == "old"
        assert not (final / "new.txt").exists()
        assert staging.exists()

    def test_safe_remove_staging_only_removes_allowed_paths(self, tmp_path):
        staging_root = tmp_path / ".staging"
        staging_root.mkdir()

        allowed = staging_root / "example-123"
        allowed.mkdir()
        (allowed / "file.txt").write_text("x")

        outside = tmp_path / "example-456"
        outside.mkdir()
        (outside / "file.txt").write_text("y")

        gen._safe_remove_staging(allowed, staging_root=staging_root)
        assert not allowed.exists()

        gen._safe_remove_staging(outside, staging_root=staging_root)
        assert outside.exists()


def test_snapshot_pngs_lists_only_png_files(tmp_path):
    (tmp_path / "a.png").write_text("")
    (tmp_path / "b.png").write_text("")
    (tmp_path / "c.txt").write_text("")
    assert gen._snapshot_pngs(tmp_path) == {
        tmp_path / "a.png",
        tmp_path / "b.png",
    }


def test_find_new_png_prefers_expected_name(tmp_path):
    before = gen._snapshot_pngs(tmp_path)
    (tmp_path / "expected.png").write_text("")
    (tmp_path / "other.png").write_text("")
    found = gen._find_new_png(tmp_path, before, preferred_name="expected.png")
    assert found == tmp_path / "expected.png"


def test_find_new_png_ignores_excluded_files(tmp_path):
    before = frozenset()
    (tmp_path / "plotly.png").write_text("")
    (tmp_path / "wanted.png").write_text("")
    found = gen._find_new_png(
        tmp_path, before, excluded={"plotly.png"}
    )
    assert found == tmp_path / "wanted.png"


def test_find_new_png_rejects_multiple_new_candidates(tmp_path):
    before = frozenset()
    (tmp_path / "a.png").write_text("")
    (tmp_path / "b.png").write_text("")
    with pytest.raises(RuntimeError, match="expected one new PNG"):
        gen._find_new_png(tmp_path, before)


def test_find_new_png_rejects_no_output(tmp_path):
    before = frozenset()
    with pytest.raises(RuntimeError, match="no PNG was produced"):
        gen._find_new_png(tmp_path, before)


def test_read_inline_export_decodes_base64_canonical_manifest(tmp_path):
    layer = SceneLayer(
        id="x</script><script>globalThis.pwn=1</script><script>",
        kind=SceneKind.SCATTER,
        zorder=1,
        load_priority=1,
        space=CoordinateSpace.DATA,
        clip_id=None,
        style={"marker": {"symbol": "circle"}, "palette_id": "stars"},
        palette=("#ffffff",),
        interaction=InteractionPolicy.HOVER,
        hover_fields=(),
        coordinate_encoding={
            "x": CoordinateEncoding(CoordinateEncodingKind.ABSOLUTE_F64),
            "y": CoordinateEncoding(CoordinateEncodingKind.ABSOLUTE_F64),
        },
        data=ColumnarData.from_mapping(
            {
                "x": np.array([1.0]),
                "y": np.array([2.0]),
                "size": np.array([3.0], dtype=np.float32),
                "color_index": np.array([0], dtype=np.uint8),
                "opacity": np.array([1.0], dtype=np.float32),
            }
        ),
    )
    scene = ScenePackage(
        layers=(layer,),
        projection_info={},
        style_info={},
        viewport={"reference_width": 100, "reference_height": 100},
        clips={},
        palettes={"stars": ("#ffffff",)},
    )
    exported = export_scene_html(
        scene,
        tmp_path / "chart.html",
        data_mode="inline",
        library_mode="cdn",
    )

    manifest_bytes, layer_bytes = gen._read_inline_export(exported.html_path)

    assert manifest_bytes == exported.manifest_bytes
    assert layer_bytes == exported.layer_bytes


def test_comparison_runner_passes_relative_output_paths_to_safe_export(monkeypatch, tmp_path):
    """The harness must not turn example filenames into unsafe absolute paths."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("STARPLOT_COMPARISON_TRANSPORTS", "inline,external")
    monkeypatch.setattr(runner.importlib.util, "find_spec", lambda _name: None)
    received = []

    def fake_export(_plot, filename, **_kwargs):
        received.append(Path(filename))
        return runner.ExportResult(
            html_path=tmp_path / filename,
            bundle_path=tmp_path / "chart.scene",
            scene_hash="scene",
            manifest_bytes=b"manifest",
            layer_bytes={"layer": b"payload"},
        )

    monkeypatch.setattr(runner, "_ORIG_EXPORT_HTML", fake_export)
    runner._comparison_export(SimpleNamespace(), "chart.html")

    assert received == [Path("chart.html"), Path("chart_inline.html")]
    assert all(not path.is_absolute() for path in received)
