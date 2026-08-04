"""Delivery-mode contracts for Scene HTML exports."""

from __future__ import annotations

import base64
from dataclasses import replace
import json
import re

import numpy as np
import pytest
from plotly.offline import get_plotlyjs_version

from starplot.interactive import (
    ColumnarData,
    DataMode,
    InteractionPolicy,
    LibraryMode,
    SceneKind,
    SceneLayer,
    ScenePackage,
    export_scene_html,
)
from starplot.interactive.commands import CoordinateSpace
from starplot.interactive.scene import CoordinateEncoding, CoordinateEncodingKind
import starplot.interactive.web_export as web_export


@pytest.fixture(autouse=True)
def _chdir(tmp_path, monkeypatch):
    """Make every test run with ``tmp_path`` as the current directory.

    ``export_scene_html`` only accepts relative output paths; this lets the
    test suite continue to use ``tmp_path`` for assertions.
    """
    monkeypatch.chdir(tmp_path)


def _scene(layer_id="stars") -> ScenePackage:
    layer = SceneLayer(
        id=layer_id,
        kind=SceneKind.SCATTER,
        zorder=1,
        load_priority=1,
        space=CoordinateSpace.DATA,
        clip_id=None,
        style={"marker": {"symbol": "circle"}, "palette_id": "stars"},
        palette=("#ffffff",),
        interaction=InteractionPolicy.HOVER,
        hover_fields=("name",),
        coordinate_encoding={
            "x": CoordinateEncoding(CoordinateEncodingKind.ABSOLUTE_F64),
            "y": CoordinateEncoding(CoordinateEncodingKind.ABSOLUTE_F64),
        },
        data=ColumnarData.from_mapping({
            "x": np.array([1.0]), "y": np.array([2.0]),
            "size": np.array([3.0], dtype=np.float32),
            "color_index": np.array([0], dtype=np.uint8),
            "opacity": np.array([1.0], dtype=np.float32),
            "name": np.array(["Rigel"]),
        }),
    )
    return ScenePackage(
        layers=(layer,), projection_info={}, style_info={},
        viewport={"reference_width": 100, "reference_height": 100}, clips={},
        palettes={"stars": ("#ffffff",)},
    )


@pytest.mark.parametrize(
    ("data_mode", "library_mode"),
    [
        (DataMode.INLINE, LibraryMode.CDN),
        (DataMode.EXTERNAL, LibraryMode.CDN),
        (DataMode.REMOTE, LibraryMode.CDN),
    ],
)
def test_modes_preserve_identical_scene_hash(tmp_path, data_mode, library_mode):
    expected = export_scene_html(
        _scene(), "chart.html", data_mode=DataMode.INLINE,
        library_mode=LibraryMode.CDN,
    )
    result = export_scene_html(
        _scene(), "chart.html", data_mode=data_mode,
        library_mode=library_mode,
        data_url="https://example.test/api/scenes/rigel",
    )
    assert result.scene_hash == expected.scene_hash
    assert result.manifest_bytes == expected.manifest_bytes
    assert result.layer_bytes["stars"]


def test_external_default_writes_hashed_arrow_bundle(tmp_path):
    result = export_scene_html(_scene(), "chart.html")
    assert result.bundle_path == tmp_path / "chart.scene"
    manifest = json.loads((result.bundle_path / "manifest.json").read_bytes())
    arrow = result.bundle_path / manifest["layers"][0]["data_source"]["uri"]
    assert arrow.read_bytes() == result.layer_bytes["stars"]
    assert manifest["layers"][0]["data_source"]["uri"].endswith(".arrow")
    assert len(manifest["layers"][0]["data_source"]["uri"].split("-")[1].split(".")[0]) == 64
    assert (result.bundle_path / "palettes.json").is_file()


def test_inline_embeds_exact_arrow_payload(tmp_path):
    result = export_scene_html(_scene(), "chart.html", data_mode="inline", library_mode="cdn")
    html = result.html_path.read_text(encoding="utf-8")
    payload = base64.b64encode(result.layer_bytes["stars"]).decode("ascii")
    assert payload in html
    assert 'application/vnd.apache.arrow.stream' in html


def test_inline_bootstrap_reads_canonical_manifest_text_directly(tmp_path):
    result = export_scene_html(
        _scene(), "chart.html", data_mode="inline", library_mode="cdn"
    )
    html = result.html_path.read_text(encoding="utf-8")

    assert (
        "const manifestJson=document.getElementById('starplot-manifest').textContent;"
        in html
    )
    assert '.textContent.split("<"+String.fromCharCode(92)+"/")' not in html


def test_inline_payload_indexes_follow_manifest_order_not_opaque_layer_id_order(tmp_path):
    first = _scene("z-layer").layers[0]
    second = replace(
        first,
        id="a-layer",
        zorder=0,
        data=ColumnarData.from_mapping({
            **first.data.columns,
            "x": np.array([42.0]),
        }),
    )
    scene = replace(_scene("z-layer"), layers=(first, second))
    result = export_scene_html(
        scene, "inline.html", data_mode="inline", library_mode="cdn"
    )
    manifest = json.loads(result.manifest_bytes)
    payloads = re.findall(
        r'id="starplot-layer-\d+" type="application/vnd.apache.arrow.stream">([^<]+)</script>',
        result.html_path.read_text(encoding="utf-8"),
    )
    assert [base64.b64decode(value) for value in payloads] == [
        result.layer_bytes[layer["id"]] for layer in manifest["layers"]
    ]


@pytest.mark.parametrize("data_mode", [DataMode.INLINE, DataMode.EXTERNAL, DataMode.REMOTE])
def test_every_export_shell_has_full_viewport_and_render_completion_signal(tmp_path, data_mode):
    result = export_scene_html(
        _scene(),
        f"{data_mode}.html",
        data_mode=data_mode,
        library_mode=LibraryMode.CDN,
        data_url="https://example.test/api/scenes/rigel",
    )
    html = result.html_path.read_text(encoding="utf-8")
    assert "html,body,#starplot-chart{width:100%;height:100%;margin:0;overflow:hidden}" in html
    assert "window.__starplotRenderPromise=StarplotScene.renderScene" in html
    assert "document.body.dataset.starplotRendered='true'" in html
    assert "document.body.dataset.starplotError=error.message" in html


def test_remote_requires_safe_absolute_url(tmp_path):
    with pytest.raises(ValueError, match="data_url"):
        export_scene_html(_scene(), "chart.html", data_mode="remote")
    with pytest.raises(ValueError, match="http"):
        export_scene_html(_scene(), "chart.html", data_mode="remote", data_url="file:///tmp/scene")
    with pytest.raises(ValueError, match=".html"):
        export_scene_html(_scene(), "..", data_mode="inline")


def test_remote_shell_uses_exact_manifest_url(tmp_path):
    result = export_scene_html(
        _scene(), "chart.html", data_mode="remote",
        data_url="https://example.test/api/scenes/rigel",
    )
    html = result.html_path.read_text(encoding="utf-8")
    assert "RemoteSceneSource" in html
    assert "https://example.test/api/scenes/rigel" in html
    assert '"https://example.test"' in html
    assert "application/vnd.apache.arrow.stream" not in html


def test_allowed_data_origins_reject_paths_and_normalize_duplicates(tmp_path):
    with pytest.raises(ValueError, match="allowed_data_origins"):
        export_scene_html(
            _scene(), "chart.html", data_mode="remote",
            data_url="https://example.test/manifest.json",
            allowed_data_origins=("https://example.test/path",),
        )
    result = export_scene_html(
        _scene(), "chart.html", data_mode="remote",
        data_url="https://example.test/manifest.json",
        allowed_data_origins=("https://cdn.test/", "https://cdn.test"),
    )
    assert result.html_path.read_text(encoding="utf-8").count('"https://cdn.test"') == 1


def test_remote_includes_manifest_origin_in_allowed_data_origins(tmp_path):
    result = export_scene_html(
        _scene(), "chart.html", data_mode="remote",
        data_url="https://example.test/manifest.json",
        allowed_data_origins=("https://cdn.test/",),
    )
    html = result.html_path.read_text(encoding="utf-8")
    assert '"https://example.test"' in html
    assert '"https://cdn.test"' in html


def test_directory_libraries_are_written_inside_the_owned_bundle(tmp_path):
    result = export_scene_html(
        _scene(), "chart.html", library_mode=LibraryMode.DIRECTORY
    )
    html = result.html_path.read_text(encoding="utf-8")
    assert f'src="chart.scene/assets/plotly-{get_plotlyjs_version()}.min.js"' in html
    assert (result.bundle_path / "assets" / "starplot-scene-loader.js").is_file()
    assert (result.bundle_path / "assets" / "apache-arrow-21.1.0.min.js").is_file()


def test_cdn_integrity_is_version_pinned_and_does_not_depend_on_downloaded_bytes(
    monkeypatch,
):
    monkeypatch.setattr(
        "plotly.offline.get_plotlyjs", lambda: "globalThis.tampered = true;"
    )
    monkeypatch.setattr(
        web_export,
        "urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("CDN export must not fetch scripts to derive their SRI")
        ),
        raising=False,
    )

    result = export_scene_html(
        _scene(), "chart.html", data_mode="inline", library_mode="cdn"
    )
    html = result.html_path.read_text(encoding="utf-8")

    assert (
        'integrity="sha384-8cEu0XVLh4s92OG4Ua4ZS75MN//b+0KqyCrhQqaXgHMVHnKC3DNVhwUyH5spa1J2"'
        in html
    )
    assert (
        'integrity="sha384-ZLJeD2tDjUehiBbpE2rlA9XezXOj3fe6wSDijZ2/fB3S+vLWujzDGYI4GfPY5Bqz"'
        in html
    )


def test_untrusted_layer_ids_never_control_paths_or_html_ids(tmp_path):
    layer_id = 'x/../../escaped"></script><script>globalThis.pwn=1</script><script id="z'
    external = export_scene_html(_scene(layer_id), "chart.html")
    arrow_names = [path.name for path in external.bundle_path.glob("*.arrow")]
    assert len(arrow_names) == 1
    assert arrow_names[0].startswith("layer-")
    assert "/" not in arrow_names[0]
    inline = export_scene_html(_scene(layer_id), "inline.html", data_mode="inline", library_mode="cdn")
    html = inline.html_path.read_text(encoding="utf-8")
    assert "starplot-layer-0" in html
    assert "<script>globalThis.pwn=1</script>" not in html


def test_untrusted_layer_ids_escape_uppercase_script_end_tags(tmp_path):
    layer_id = 'x"></SCRIPT><script nonce="PWN">alert(1)</script><script id="z'
    inline = export_scene_html(_scene(layer_id), "inline.html", data_mode="inline", library_mode="cdn")
    html = inline.html_path.read_text(encoding="utf-8")
    assert "starplot-layer-0" in html
    assert "</SCRIPT>" not in html
    assert '<script nonce="PWN">alert(1)</script>' not in html


def test_remote_rejects_unsafe_data_url_host_characters(tmp_path):
    with pytest.raises(ValueError, match="unsafe"):
        export_scene_html(
            _scene(), "chart.html", data_mode="remote",
            data_url='https://examp"le.test/manifest.json',
        )


def test_remote_rejects_unsafe_data_url_characters(tmp_path):
    for bad in (
        "https://example.com/foo<bar",
        "https://example.com/foo bar",
        "https://example.com/foo{bar",
    ):
        with pytest.raises(ValueError, match="unsafe"):
            export_scene_html(_scene(), "chart.html", data_mode="remote", data_url=bad)


def test_remote_accepts_valid_url_specials(tmp_path):
    # Single quotes, at-signs in paths, and percent-encoding are valid URL characters.
    result = export_scene_html(
        _scene(), "chart.html", data_mode="remote",
        data_url="https://example.com/user'file%20name@tag?x=a'b",
    )
    html = result.html_path.read_text(encoding="utf-8")
    assert "https://example.com/user'file%20name@tag?x=a'b" in html


def test_remote_rejects_userinfo_and_fragments_and_bad_percent_encoding(tmp_path):
    with pytest.raises(ValueError, match="userinfo"):
        export_scene_html(
            _scene(), "chart.html", data_mode="remote",
            data_url="https://user:pass@example.test/manifest.json",
        )
    with pytest.raises(ValueError, match="fragment"):
        export_scene_html(
            _scene(), "chart.html", data_mode="remote",
            data_url="https://example.test/manifest.json#fragment",
        )
    with pytest.raises(ValueError, match="percent-encoding"):
        export_scene_html(
            _scene(), "chart.html", data_mode="remote",
            data_url="https://example.test/manifest%GH.json",
        )


def test_allowed_data_origins_reject_unsafe_host_characters(tmp_path):
    with pytest.raises(ValueError, match="unsafe"):
        export_scene_html(
            _scene(), "chart.html", data_mode="remote",
            data_url="https://example.test/manifest.json",
            allowed_data_origins=("https://examp\"le.test",),
        )
    with pytest.raises(ValueError, match="unsafe"):
        export_scene_html(
            _scene(), "chart.html", data_mode="remote",
            data_url="https://example.test/manifest.json",
            allowed_data_origins=("https://trusted.test@evil.test",),
        )


def test_directory_script_src_is_html_escaped(tmp_path):
    result = export_scene_html(
        _scene(), "foo&bar.html", library_mode=LibraryMode.DIRECTORY,
    )
    html = result.html_path.read_text(encoding="utf-8")
    assert 'src="foo&amp;bar.scene/assets/' in html
    assert 'src="foo&bar.scene/assets/' not in html
    assert "<script" in html


def test_unsafe_filename_characters_are_rejected(tmp_path):
    with pytest.raises(ValueError, match="unsafe"):
        export_scene_html(_scene(), "foo#bar.html")


def test_remote_csp_meta_attribute_is_well_formed(tmp_path):
    result = export_scene_html(
        _scene(), "chart.html", data_mode="remote",
        data_url="https://example.test/api/scenes/rigel",
        allowed_data_origins=("https://cdn.test/",),
    )
    html = result.html_path.read_text(encoding="utf-8")
    m = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)">', html)
    assert m, "CSP meta tag is malformed or unterminated"
    policy = m.group(1)
    assert "'self'" in policy
    assert "https://example.test" in policy
    assert "https://cdn.test" in policy


def test_remote_accepts_tilde_in_url_path(tmp_path):
    # Tilde is a valid RFC 3986 unreserved character, most common in paths.
    result = export_scene_html(
        _scene(), "chart.html", data_mode="remote",
        data_url="https://example.com/~user/manifest.json",
    )
    html = result.html_path.read_text(encoding="utf-8")
    assert "https://example.com/~user/manifest.json" in html


def test_remote_accepts_ipv6_and_underscore_hosts(tmp_path):
    for valid in (
        "https://[2001:db8::1]:8080/manifest.json",
        "https://foo_bar.test/manifest.json",
    ):
        result = export_scene_html(_scene(), "chart.html", data_mode="remote", data_url=valid)
        assert valid in result.html_path.read_text(encoding="utf-8")


def test_remote_rejects_malformed_host_port(tmp_path):
    for bad in (
        "https://example:test.com:8080/manifest.json",
        "https://example.test:abc/manifest.json",
        "https://example.com:80.evil.com/manifest.json",
    ):
        with pytest.raises(ValueError, match="unsafe|invalid"):
            export_scene_html(_scene(), "chart.html", data_mode="remote", data_url=bad)


def test_allowed_data_origins_reject_malformed_host_port(tmp_path):
    for bad in (
        "https://example:test.com:8080",
        "https://example.test:abc",
        "https://example.com:80.evil.com",
    ):
        with pytest.raises(ValueError, match="unsafe|invalid"):
            export_scene_html(
                _scene(), "chart.html", data_mode="remote",
                data_url="https://example.test/manifest.json",
                allowed_data_origins=(bad,),
            )


def test_absolute_output_paths_are_accepted(tmp_path):
    """Absolute paths are a legitimate use case for library callers."""
    abs_path = tmp_path / "abs.html"
    result = export_scene_html(_scene(), abs_path)
    assert result.html_path == abs_path.resolve()
    assert abs_path.exists()


def test_relative_path_traversal_is_rejected(tmp_path, monkeypatch):
    """Relative paths containing ``..`` that escape cwd must be rejected."""
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="current working directory"):
        export_scene_html(_scene(), "../escaped.html")


def test_directory_library_mode_requires_external_data_mode(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="library_mode='directory' requires data_mode='external'"):
        export_scene_html(
            _scene(), "chart.html", data_mode="inline", library_mode=LibraryMode.DIRECTORY,
        )


def test_inline_payload_escapes_less_than_sign_to_prevent_script_breakout(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    malicious_id = 'x</script><script>alert(1)</script>'
    result = export_scene_html(
        _scene(malicious_id), "chart.html", data_mode="inline", library_mode=LibraryMode.CDN,
    )
    html = result.html_path.read_text(encoding="utf-8")
    # The malicious payload must not appear as an executable script tag.
    assert "<script>alert(1)</script>" not in html
    assert "</script><script>alert(1)</script>" not in html
    # The payload text is safely escaped inside the JSON and still present
    # so the assertion above proves it cannot break out of the script block.
    assert "alert(1)" in html
    assert r"\u003c" in html
