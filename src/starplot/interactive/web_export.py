"""Transport-neutral HTML exports for compiled interactive Scenes.

The HTML shell is deliberately small: all three data modes feed the browser's
``SceneSource`` implementation the same canonical manifest and Arrow streams.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import tempfile
from typing import Mapping
from urllib.parse import urlparse

from starplot.interactive.arrow_transport import encode_layer_stream
from starplot.interactive.scene import ScenePackage
from starplot.interactive.scene_manifest import (
    CapabilitiesModel,
    DataSourceModel,
    build_scene_manifest,
    canonical_manifest_bytes,
    parse_scene_manifest,
)


class DataMode(StrEnum):
    INLINE = "inline"
    EXTERNAL = "external"
    REMOTE = "remote"


class LibraryMode(StrEnum):
    CDN = "cdn"
    DIRECTORY = "directory"
    INLINE = "inline"


@dataclass(frozen=True)
class ExportResult:
    html_path: Path
    bundle_path: Path | None
    scene_hash: str
    manifest_bytes: bytes
    layer_bytes: Mapping[str, bytes]


@dataclass(frozen=True)
class _LibraryAssets:
    """Resolved Plotly/Arrow delivery with optional SRI hashes."""

    plotly: str  # URL when external, raw JS text when inline
    arrow: str
    plotly_integrity: str | None
    arrow_integrity: str | None
    cross_origin: bool
    directory: bool


_ASSETS = Path(__file__).with_name("assets")
_ARROW_CDN = "https://cdn.jsdelivr.net/npm/apache-arrow@21.1.0/Arrow.es2015.min.js"


def _sri_hash(data: bytes) -> str:
    """Return a sha384 Subresource Integrity hash for ``data``."""
    digest = base64.b64encode(hashlib.sha384(data).digest()).decode("ascii")
    return f"sha384-{digest}"


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _safe_output_path(filename: str | Path) -> Path:
    path = Path(filename)
    if path.name in {"", ".", ".."} or path.suffix.lower() != ".html":
        raise ValueError("filename must name an .html file")
    return path.resolve()


def _data_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("data_url must be an absolute http(s) URL")
    return value


def _allowed_origins(values: tuple[str, ...], manifest_url: str | None) -> tuple[str, ...]:
    """Normalize explicit HTTP(S) origins; remote defaults to its manifest origin."""
    origins = tuple(values)
    if not origins and manifest_url is not None:
        parsed = urlparse(manifest_url)
        origins = (f"{parsed.scheme}://{parsed.netloc}",)
    normalized = []
    for origin in origins:
        parsed = urlparse(origin)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.path not in {"", "/"}
            or parsed.params
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("allowed_data_origins must contain only absolute HTTP(S) origins")
        normalized.append(f"{parsed.scheme}://{parsed.netloc}")
    return tuple(dict.fromkeys(normalized))


def _json_script(value: object) -> str:
    """Embed JSON as inert text without permitting a closing-script escape."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def _escape_inline_script(text: str) -> str:
    """Escape any ``</`` sequence so it cannot close the containing ``<script>``."""
    return text.replace("</", "<\\/")


def _scene_id(layer_bytes: Mapping[str, bytes]) -> str:
    """Stable transport identity, deliberately independent of the output path."""
    digest = hashlib.sha256()
    for layer_id in sorted(layer_bytes):
        digest.update(layer_id.encode("utf-8"))
        digest.update(layer_bytes[layer_id])
    return f"scene-{digest.hexdigest()[:16]}"


def _libraries(mode: LibraryMode, bundle: Path | None) -> _LibraryAssets:
    try:
        from plotly.offline import get_plotlyjs, get_plotlyjs_version
    except ImportError as error:  # pragma: no cover - optional extra boundary
        raise RuntimeError("plotly is required for interactive HTML export") from error
    plotly_version = get_plotlyjs_version()
    plotly_content = get_plotlyjs().encode()
    arrow_content = (_ASSETS / "vendor" / "apache-arrow.min.js").read_bytes()
    if mode is LibraryMode.CDN:
        return _LibraryAssets(
            plotly=f"https://cdn.plot.ly/plotly-{plotly_version}.min.js",
            arrow=_ARROW_CDN,
            plotly_integrity=_sri_hash(plotly_content),
            arrow_integrity=_sri_hash(arrow_content),
            cross_origin=True,
            directory=False,
        )
    if mode is LibraryMode.INLINE:
        return _LibraryAssets(
            plotly=plotly_content.decode("utf-8"),
            arrow=arrow_content.decode("utf-8"),
            plotly_integrity=None,
            arrow_integrity=None,
            cross_origin=False,
            directory=False,
        )
    assert bundle is not None
    assets = bundle / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    plotly_filename = f"plotly-{plotly_version}.min.js"
    _atomic_write(assets / plotly_filename, plotly_content)
    _atomic_write(assets / "apache-arrow-21.1.0.min.js", arrow_content)
    shutil.copyfile(_ASSETS / "starplot-scene-loader.js", assets / "starplot-scene-loader.js")
    shutil.copyfile(_ASSETS / "plotly-scene-adapter.js", assets / "plotly-scene-adapter.js")
    return _LibraryAssets(
        plotly=f"assets/{plotly_filename}",
        arrow="assets/apache-arrow-21.1.0.min.js",
        plotly_integrity=_sri_hash(plotly_content),
        arrow_integrity=_sri_hash(arrow_content),
        cross_origin=False,
        directory=True,
    )


def _script_src(src: str, *, integrity: str | None, cross_origin: bool, nonce: str) -> str:
    attrs = f'src="{src}" nonce="{nonce}"'
    if integrity:
        attrs += f' integrity="{integrity}"'
    if cross_origin:
        attrs += ' crossorigin="anonymous"'
    return f"<script {attrs}></script>"


def _script_inline(
    content: str,
    *,
    nonce: str,
    script_type: str | None = None,
    element_id: str | None = None,
) -> str:
    # Order: nonce first, then optional id/type, so tests and browsers can still
    # locate ``id="..." type="..."`` patterns for inline payloads.
    attrs = f'nonce="{nonce}"'
    if element_id:
        attrs += f' id="{element_id}"'
    if script_type:
        attrs += f' type="{script_type}"'
    return f"<script {attrs}>{_escape_inline_script(content)}</script>"


def _csp_header(
    nonce: str,
    *,
    libraries: LibraryMode,
    mode: DataMode,
    base_url: str | None,
    allowed_data_origins: tuple[str, ...],
) -> str:
    """Build a Content-Security-Policy for the exported page."""
    script_src = ["'self'", f"'nonce-{nonce}'", "'unsafe-eval'"]
    if libraries is LibraryMode.CDN:
        script_src.extend(["https://cdn.plot.ly", "https://cdn.jsdelivr.net"])

    connect_src = ["'self'"]
    if mode is DataMode.REMOTE and base_url is not None:
        parsed = urlparse(base_url)
        if parsed.scheme and parsed.netloc:
            connect_src.append(f"{parsed.scheme}://{parsed.netloc}")
        connect_src.extend(allowed_data_origins)
    elif mode is DataMode.INLINE:
        connect_src = ["'none'"]

    policy = (
        f"default-src 'self'; "
        f"script-src {' '.join(script_src)}; "
        f"connect-src {' '.join(connect_src)}; "
        f"style-src 'self' 'unsafe-inline'; "
        f"img-src 'self' data: blob:; "
        f"font-src 'self' data:; "
        f"base-uri 'self'; "
        f"form-action 'none'"
    )
    return f'<meta http-equiv="Content-Security-Policy" content="{policy}">'


def _html_shell(*, mode: DataMode, libraries: LibraryMode, manifest: dict | None,
                manifest_json: str | None, layers: Mapping[str, bytes], base_url: str | None,
                allowed_data_origins: tuple[str, ...], bundle: Path | None,
                asset_prefix: str = "") -> str:
    nonce = secrets.token_urlsafe(16)
    csp = _csp_header(
        nonce,
        libraries=libraries,
        mode=mode,
        base_url=base_url,
        allowed_data_origins=allowed_data_origins,
    )

    lib_assets = _libraries(libraries, bundle)

    def external_src(path: str, integrity: str | None) -> str:
        return _script_src(asset_prefix + path, integrity=integrity, cross_origin=lib_assets.cross_origin, nonce=nonce)

    if libraries is LibraryMode.INLINE:
        library_tags = (
            _script_inline(lib_assets.plotly, nonce=nonce)
            + _script_inline(lib_assets.arrow, nonce=nonce)
        )
    else:
        library_tags = (
            external_src(lib_assets.plotly, lib_assets.plotly_integrity)
            + external_src(lib_assets.arrow, lib_assets.arrow_integrity)
        )

    loader_source = (_ASSETS / "starplot-scene-loader.js").read_text(encoding="utf-8")
    adapter_source = (_ASSETS / "plotly-scene-adapter.js").read_text(encoding="utf-8")
    if lib_assets.directory and bundle is not None:
        loader_integrity = _sri_hash((bundle / "assets" / "starplot-scene-loader.js").read_bytes())
        adapter_integrity = _sri_hash((bundle / "assets" / "plotly-scene-adapter.js").read_bytes())
        runtime_tags = (
            external_src("assets/starplot-scene-loader.js", loader_integrity)
            + external_src("assets/plotly-scene-adapter.js", adapter_integrity)
        )
    else:
        runtime_tags = (
            _script_inline(loader_source, nonce=nonce)
            + _script_inline(adapter_source, nonce=nonce)
        )

    payload_tags = ""
    if mode is DataMode.INLINE:
        safe_manifest = manifest_json.replace("</", "<\\/")
        payload_tags = _script_inline(
            safe_manifest,
            nonce=nonce,
            script_type="application/json",
            element_id="starplot-manifest",
        )
        payload_tags += "".join(
            _script_inline(
                base64.b64encode(data).decode("ascii"),
                nonce=nonce,
                script_type="application/vnd.apache.arrow.stream",
                element_id=f"starplot-layer-{index}",
            )
            for index, layer in enumerate(manifest["layers"])
            for data in (layers[layer["id"]],)
        )
        bootstrap = """const manifestJson=document.getElementById('starplot-manifest').textContent.split("<"+String.fromCharCode(92)+"/").join("</");
const manifest=JSON.parse(manifestJson); const layers={};
for(const [index,layer] of manifest.layers.entries()){layers[layer.id]=document.getElementById(`starplot-layer-${index}`).textContent;}
const source=new StarplotScene.InlineSceneSource({manifest,manifestJson,layers});"""
    else:
        assert base_url is not None
        source_type = "RemoteSceneSource" if mode is DataMode.REMOTE else "StaticSceneSource"
        manifest_option = (
            f",manifestUrl:{_json_script(base_url)}" if mode is DataMode.REMOTE else ""
        )
        bootstrap = (
            f"const source=new StarplotScene.{source_type}({{baseUrl:{_json_script(base_url)}"
            f"{manifest_option},allowedDataOrigins:{_json_script(allowed_data_origins)}}});"
        )

    main_script = (
        f"{bootstrap} window.__starplotRenderPromise=StarplotScene.renderScene("
        "document.getElementById('starplot-chart'),source).then(()=>{"
        "document.body.dataset.starplotRendered='true';}).catch(error=>{"
        "console.error(error);document.body.dataset.starplotError=error.message;throw error;});"
    )
    main_script_tag = _script_inline(main_script, nonce=nonce)

    return f"""<!doctype html><html><head><meta charset=\"utf-8\">{csp}<title>Starplot chart</title>
<style>html,body,#starplot-chart{{width:100%;height:100%;margin:0;overflow:hidden}}</style></head>
<body><div id=\"starplot-chart\"></div>{payload_tags}{library_tags}{runtime_tags}
{main_script_tag}
</body></html>"""


def export_scene_html(
    scene: ScenePackage,
    filename: str | Path,
    data_mode: DataMode | str = DataMode.EXTERNAL,
    library_mode: LibraryMode | str | None = None,
    data_url: str | None = None,
    allowed_data_origins: tuple[str, ...] = (),
) -> ExportResult:
    """Export one compiled Scene without changing its Arrow representation."""
    if not isinstance(scene, ScenePackage):
        raise TypeError("scene must be a ScenePackage")
    output = _safe_output_path(filename)
    mode = DataMode(data_mode)
    libraries = LibraryMode(library_mode) if library_mode is not None else (
        LibraryMode.INLINE if mode is DataMode.INLINE else LibraryMode.CDN
    )
    if mode is DataMode.REMOTE and not data_url:
        raise ValueError("data_url is required for remote export")
    remote_url = _data_url(data_url) if mode is DataMode.REMOTE else None
    origins = _allowed_origins(tuple(allowed_data_origins), remote_url)
    layer_bytes = {layer.id: encode_layer_stream(layer) for layer in scene.layers}
    bundle = output.with_suffix(".scene") if mode is DataMode.EXTERNAL else None
    # Data locations are transport-relative, never a delivery-mode input to the
    # canonical Scene.  A remote manifest resolves these same filenames against
    # its own URL; inline simply supplies their exact bytes from inert scripts.
    sources = {
        layer.id: DataSourceModel(
            format="arrow-ipc-stream",
            uri=f"layer-{hashlib.sha256(layer_bytes[layer.id]).hexdigest()}.arrow",
        )
        for layer in scene.layers
    }
    manifest = build_scene_manifest(
        scene_id=_scene_id(layer_bytes),
        layers=scene.layers,
        layer_bytes=layer_bytes,
        viewport=scene.viewport,
        coordinate_spaces={"data": {"authority": "projected-x-y"}},
        clips=tuple(
            {"id": key, "kind": value.kind, "points": value.points}
            for key, value in scene.clips.items()
        ),
        capabilities=CapabilitiesModel(**scene.capabilities.__dict__),
        data_sources=sources,
    )
    manifest_bytes = canonical_manifest_bytes(manifest)
    # Exercise the same bounded decoder that framework/API consumers use before
    # writing an export.  This is deliberately validation, not reserialization.
    parse_scene_manifest(manifest_bytes)
    manifest_value = json.loads(manifest_bytes)
    if mode is DataMode.EXTERNAL:
        temporary = Path(tempfile.mkdtemp(prefix=f".{bundle.name}.", dir=bundle.parent))
        try:
            _atomic_write(temporary / "manifest.json", manifest_bytes)
            _atomic_write(temporary / "palettes.json", _json_script(manifest_value["palettes"]).encode())
            for layer in manifest.layers:
                _atomic_write(temporary / layer.data_source.uri, layer_bytes[layer.id])
            html = _html_shell(mode=mode, libraries=libraries, manifest=None, manifest_json=None,
                               layers={}, base_url=f"{bundle.name}/", allowed_data_origins=origins,
                               bundle=temporary if libraries is LibraryMode.DIRECTORY else None,
                               asset_prefix=f"{bundle.name}/" if libraries is LibraryMode.DIRECTORY else "")
            backup = bundle.with_name(f".{bundle.name}.previous")
            if backup.exists():
                shutil.rmtree(backup)
            if bundle.exists():
                os.replace(bundle, backup)
            try:
                os.replace(temporary, bundle)
            except OSError:
                if backup.exists():
                    os.replace(backup, bundle)
                raise
            finally:
                if backup.exists():
                    shutil.rmtree(backup)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    else:
        html = _html_shell(mode=mode, libraries=libraries, manifest=manifest_value,
                           manifest_json=manifest_bytes.decode(), layers=layer_bytes,
                           base_url=remote_url, allowed_data_origins=origins, bundle=None)
    _atomic_write(output, html.encode("utf-8"))
    return ExportResult(output, bundle, manifest.content_hash, manifest_bytes, layer_bytes)
