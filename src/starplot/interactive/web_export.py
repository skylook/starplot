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


_ASSETS = Path(__file__).with_name("assets")
_ARROW_CDN = "https://cdn.jsdelivr.net/npm/apache-arrow@21.1.0/Arrow.es2015.min.js"


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


def _libraries(mode: LibraryMode, bundle: Path | None) -> tuple[str, str]:
    try:
        from plotly.offline import get_plotlyjs, get_plotlyjs_version
    except ImportError as error:  # pragma: no cover - optional extra boundary
        raise RuntimeError("plotly is required for interactive HTML export") from error
    plotly_version = get_plotlyjs_version()
    if mode is LibraryMode.CDN:
        return f"https://cdn.plot.ly/plotly-{plotly_version}.min.js", _ARROW_CDN
    if mode is LibraryMode.INLINE:
        return get_plotlyjs(), (_ASSETS / "vendor" / "apache-arrow.min.js").read_text(encoding="utf-8")
    assert bundle is not None
    assets = bundle / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    plotly_filename = f"plotly-{plotly_version}.min.js"
    _atomic_write(assets / plotly_filename, get_plotlyjs().encode())
    shutil.copyfile(_ASSETS / "vendor" / "apache-arrow.min.js", assets / "apache-arrow-21.1.0.min.js")
    shutil.copyfile(_ASSETS / "starplot-scene-loader.js", assets / "starplot-scene-loader.js")
    shutil.copyfile(_ASSETS / "plotly-scene-adapter.js", assets / "plotly-scene-adapter.js")
    return f"assets/{plotly_filename}", "assets/apache-arrow-21.1.0.min.js"


def _html_shell(*, mode: DataMode, libraries: LibraryMode, manifest: dict | None,
                manifest_json: str | None, layers: Mapping[str, bytes], base_url: str | None,
                allowed_data_origins: tuple[str, ...], bundle: Path | None,
                asset_prefix: str = "") -> str:
    plotly, arrow = _libraries(libraries, bundle)
    directory = libraries is LibraryMode.DIRECTORY
    script_prefix = "" if directory else ""
    if libraries is LibraryMode.INLINE:
        library_tags = f"<script>{plotly}</script><script>{arrow}</script>"
        runtime_tags = (
            f"<script>{(_ASSETS / 'starplot-scene-loader.js').read_text(encoding='utf-8')}</script>"
            f"<script>{(_ASSETS / 'plotly-scene-adapter.js').read_text(encoding='utf-8')}</script>"
        )
    elif directory:
        library_tags = f'<script src="{asset_prefix}{plotly}"></script><script src="{asset_prefix}{arrow}"></script>'
        runtime_tags = (
            f'<script src="{asset_prefix}assets/starplot-scene-loader.js"></script>'
            f'<script src="{asset_prefix}assets/plotly-scene-adapter.js"></script>'
        )
    else:
        library_tags = f'<script src="{plotly}"></script><script src="{arrow}"></script>'
        runtime_tags = (
            f"<script>{(_ASSETS / 'starplot-scene-loader.js').read_text(encoding='utf-8')}</script>"
            f"<script>{(_ASSETS / 'plotly-scene-adapter.js').read_text(encoding='utf-8')}</script>"
        )
    del script_prefix
    payload_tags = ""
    if mode is DataMode.INLINE:
        safe_manifest = manifest_json.replace("</", "<\\/")
        payload_tags = f'<script id="starplot-manifest" type="application/json">{safe_manifest}</script>'
        payload_tags += "".join(
            f'<script id="starplot-layer-{index}" type="application/vnd.apache.arrow.stream">{base64.b64encode(data).decode("ascii")}</script>'
            for index, (_layer_id, data) in enumerate(sorted(layers.items()))
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
    return f"""<!doctype html><html><head><meta charset=\"utf-8\"><title>Starplot chart</title></head>
<body><div id=\"starplot-chart\" style=\"width:100%;height:100vh\"></div>{payload_tags}{library_tags}{runtime_tags}
<script>{bootstrap} StarplotScene.renderScene(document.getElementById('starplot-chart'),source).catch(error=>{{console.error(error);document.body.dataset.starplotError=error.message;}});</script>
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
        scene_id=output.stem,
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
            if backup.exists(): shutil.rmtree(backup)
            if bundle.exists(): os.replace(bundle, backup)
            try:
                os.replace(temporary, bundle)
            except Exception:
                if backup.exists(): os.replace(backup, bundle)
                raise
            finally:
                if backup.exists(): shutil.rmtree(backup)
        finally:
            if temporary.exists(): shutil.rmtree(temporary)
    else:
        html = _html_shell(mode=mode, libraries=libraries, manifest=manifest_value,
                           manifest_json=manifest_bytes.decode(), layers=layer_bytes,
                           base_url=remote_url, allowed_data_origins=origins, bundle=None)
    _atomic_write(output, html.encode("utf-8"))
    return ExportResult(output, bundle, manifest.content_hash, manifest_bytes, layer_bytes)
