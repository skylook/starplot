"""Deterministic Apache Arrow IPC Stream encoding for Scene layers."""

from __future__ import annotations

import hashlib
import json
from typing import Mapping

import numpy as np
import pyarrow as pa

from starplot.interactive.scene import (
    ColumnarData,
    CoordinateEncodingKind,
    SceneKind,
    SceneLayer,
)
from starplot.interactive.scene_manifest import (
    SCENE_SCHEMA_VERSION,
    LayerManifestModel,
    _ResolvedLayerContext,
)
from starplot.interactive.scene_validation import DEFAULT_LOADER_LIMITS, LoaderLimits, validate_layer_bytes


_STREAM_PREFIX = b"\xff\xff\xff\xff"
_STREAM_EOS = b"\xff\xff\xff\xff\x00\x00\x00\x00"
_NUMERIC_TYPES: Mapping[str, pa.DataType] = {
    "size": pa.float32(),
    "color_index": pa.uint8(),  # uint16 is the other validated palette form
    "opacity": pa.float32(),
    "symbol_index": pa.uint8(),
    "magnitude": pa.float32(),
    "ra": pa.float64(),
    "dec": pa.float64(),
    "path_id": pa.uint32(),
    "vertex_index": pa.uint32(),
    "style_id": pa.uint16(),
    "polygon_id": pa.uint32(),
    "ring_id": pa.uint32(),
    "rotation": pa.float32(),
    "x_offset": pa.float32(),
    "y_offset": pa.float32(),
    # Starplot Scene 1.0 retains per-cell info-table width for exact parity.
    "width": pa.float32(),
}
_DICTIONARY_COLUMNS = frozenset({"name", "text", "column", "value"})
_STRING_COLUMNS = frozenset({"object_id"})
_CANONICAL_COLUMNS: Mapping[SceneKind, tuple[str, ...]] = {
    SceneKind.SCATTER: (
        "x",
        "y",
        "size",
        "color_index",
        "opacity",
        "symbol_index",
        "object_id",
        "name",
        "magnitude",
        "ra",
        "dec",
    ),
    SceneKind.LINE: ("path_id", "vertex_index", "x", "y", "style_id", "object_id"),
    SceneKind.LINE_COLLECTION: (
        "path_id",
        "vertex_index",
        "x",
        "y",
        "style_id",
        "object_id",
    ),
    SceneKind.POLYGON: ("polygon_id", "ring_id", "vertex_index", "x", "y"),
    SceneKind.TEXT: (
        "x",
        "y",
        "text",
        "rotation",
        "x_offset",
        "y_offset",
        "style_id",
        "object_id",
    ),
    SceneKind.GRADIENT: (),
    SceneKind.INFO_TABLE: ("column", "value", "width", "object_id"),
}
_REQUIRED_COLUMNS: Mapping[SceneKind, frozenset[str]] = {
    SceneKind.SCATTER: frozenset({"x", "y", "size", "color_index", "opacity"}),
    SceneKind.LINE: frozenset({"path_id", "vertex_index", "x", "y"}),
    SceneKind.LINE_COLLECTION: frozenset({"path_id", "vertex_index", "x", "y"}),
    SceneKind.POLYGON: frozenset({"polygon_id", "ring_id", "vertex_index", "x", "y"}),
    SceneKind.TEXT: frozenset(
        {"x", "y", "text", "rotation", "x_offset", "y_offset", "style_id"}
    ),
    SceneKind.GRADIENT: frozenset(),
    # `width` is current Scene 1.0 data, not an invented transport-only field.
    SceneKind.INFO_TABLE: frozenset({"column", "value", "width"}),
}
_OPTIONAL_COLUMNS: Mapping[SceneKind, frozenset[str]] = {
    SceneKind.SCATTER: frozenset(
        {"symbol_index", "object_id", "name", "magnitude", "ra", "dec"}
    ),
    SceneKind.LINE: frozenset({"style_id", "object_id"}),
    SceneKind.LINE_COLLECTION: frozenset({"style_id", "object_id"}),
    SceneKind.POLYGON: frozenset(),
    SceneKind.TEXT: frozenset({"object_id"}),
    SceneKind.GRADIENT: frozenset(),
    SceneKind.INFO_TABLE: frozenset({"object_id"}),
}


def layer_to_table(layer: SceneLayer) -> pa.Table:
    """Validate and convert one immutable Scene layer to a canonical table."""
    if not isinstance(layer, SceneLayer):
        raise TypeError("layer must be a SceneLayer")
    _validate_layer_columns(layer)
    arrays = []
    fields = []
    for name in _canonical_column_names(layer):
        values = layer.data[name]
        arrow_array = _column_to_arrow(name, values)
        arrays.append(arrow_array)
        fields.append(
            pa.field(
                name,
                arrow_array.type,
                nullable=arrow_array.null_count > 0,
                metadata={b"numpy_dtype": values.dtype.str.encode("ascii")},
            )
        )
    schema = pa.schema(fields, metadata=_schema_metadata(layer))
    return pa.Table.from_arrays(arrays, schema=schema)


def encode_table_stream(table: pa.Table, max_chunksize: int = 250_000) -> bytes:
    """Encode a table using canonical IPC Stream batches and EOS framing."""
    if not isinstance(table, pa.Table):
        raise TypeError("table must be a pyarrow.Table")
    if not isinstance(max_chunksize, int) or max_chunksize <= 0:
        raise ValueError("max_chunksize must be a positive integer")
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, table.schema) as writer:
        writer.write_table(table, max_chunksize=max_chunksize)
    payload = sink.getvalue().to_pybytes()
    if not payload.startswith(_STREAM_PREFIX) or not payload.endswith(_STREAM_EOS):
        raise RuntimeError("PyArrow did not emit canonical IPC Stream framing")
    return payload


def encode_layer_stream(layer: SceneLayer, max_chunksize: int = 250_000) -> bytes:
    return encode_table_stream(layer_to_table(layer), max_chunksize=max_chunksize)


def decode_layer_stream(
    data: bytes,
    resolved_layer: _ResolvedLayerContext,
    *,
    limits: LoaderLimits = DEFAULT_LOADER_LIMITS,
) -> SceneLayer:
    """Validate exact IPC bytes and reconstruct one immutable Scene layer."""
    if not isinstance(data, bytes):
        raise TypeError("data must be bytes")
    if not isinstance(resolved_layer, _ResolvedLayerContext):
        raise TypeError(
            "manifest layer must be resolved by SceneManifestModel.resolve_layer()"
        )
    manifest_layer = resolved_layer.wire
    validate_layer_bytes(data, manifest_layer, limits)
    if len(data) != manifest_layer.byte_length:
        raise ValueError("Arrow payload byte_length does not match the manifest")
    if layer_content_hash(data) != manifest_layer.content_hash:
        raise ValueError("Arrow payload content hash does not match the manifest")
    if not data.startswith(_STREAM_PREFIX):
        raise ValueError("payload is not a canonical Arrow IPC Stream")
    if not data.endswith(_STREAM_EOS):
        raise ValueError("Arrow IPC Stream is missing the canonical EOS marker")

    source = pa.BufferReader(data)
    try:
        with pa.ipc.open_stream(source) as reader:
            table = reader.read_all()
        consumed = source.tell()
    except (pa.ArrowInvalid, pa.ArrowIOError, OSError) as error:
        raise ValueError(
            "payload is truncated or is not a valid Arrow IPC Stream"
        ) from error
    if consumed != len(data):
        raise ValueError("Arrow IPC Stream contains trailing bytes after EOS")

    metadata = table.schema.metadata or {}
    expected_metadata = _wire_schema_metadata(manifest_layer)
    if metadata.get(b"layer_id") != expected_metadata[b"layer_id"]:
        raise ValueError("Arrow schema layer id does not match the manifest")
    if metadata != expected_metadata:
        mismatched = sorted(
            key.decode("ascii", errors="replace")
            for key in set(metadata) | set(expected_metadata)
            if metadata.get(key) != expected_metadata.get(key)
        )
        raise ValueError(f"Arrow schema metadata does not match manifest: {mismatched}")
    if table.num_rows != manifest_layer.row_count:
        raise ValueError("Arrow row count does not match the manifest")
    _validate_arrow_schema(table.schema, manifest_layer)
    _validate_string_columns(table, limits)

    columns = {}
    for field, column in zip(table.schema, table.columns):
        dtype_bytes = (field.metadata or {}).get(b"numpy_dtype")
        if dtype_bytes is None:
            raise ValueError(
                f"Arrow field {field.name!r} is missing NumPy dtype metadata"
            )
        try:
            dtype = np.dtype(dtype_bytes.decode("ascii"))
        except (UnicodeDecodeError, TypeError) as error:
            raise ValueError(
                f"Arrow field {field.name!r} has invalid dtype metadata"
            ) from error
        columns[field.name] = _arrow_to_numpy(column, dtype, field.name)

    scene_layer = SceneLayer(
        id=manifest_layer.id,
        kind=manifest_layer.kind,
        group_id=manifest_layer.group_id,
        zorder=manifest_layer.zorder,
        load_priority=manifest_layer.load_priority,
        space=manifest_layer.coordinate_space,
        clip_id=manifest_layer.clip_id,
        style=resolved_layer.style,
        data=ColumnarData.from_mapping(columns),
        interaction=manifest_layer.interaction,
        hover_fields=manifest_layer.hover_fields,
        required=manifest_layer.required,
        coordinate_encoding={
            name: value.to_scene()
            for name, value in manifest_layer.coordinate_encoding.items()
        },
        palette=resolved_layer.palette,
    )
    _validate_layer_columns(scene_layer)
    return scene_layer


def _validate_string_columns(table: pa.Table, limits: LoaderLimits) -> None:
    """Avoid materializing an unbounded string cell after IPC decoding."""
    for field, column in zip(table.schema, table.columns):
        if not (pa.types.is_string(field.type) or pa.types.is_dictionary(field.type)):
            continue
        for chunk in column.iterchunks():
            for value in chunk.to_pylist():
                if value is not None and len(str(value).encode("utf-8")) > limits.max_string_bytes:
                    raise ValueError(
                        f"Arrow field {field.name!r} contains a string exceeding the configured byte limit"
                    )


def layer_content_hash(data: bytes) -> str:
    if not isinstance(data, bytes):
        raise TypeError("data must be bytes")
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _canonical_column_names(layer: SceneLayer) -> tuple[str, ...]:
    known = _CANONICAL_COLUMNS[layer.kind]
    names = set(layer.data.columns)
    ordered_known = tuple(name for name in known if name in names)
    hover_extensions = tuple(sorted(names - set(known)))
    return ordered_known + hover_extensions


def _validate_layer_columns(layer: SceneLayer) -> None:
    names = set(layer.data.columns)
    required = _REQUIRED_COLUMNS[layer.kind]
    missing = sorted(required - names)
    if missing:
        raise ValueError(f"{layer.kind.value} required columns are missing: {missing}")
    allowed = required | _OPTIONAL_COLUMNS[layer.kind] | set(layer.hover_fields)
    unexpected = sorted(names - allowed)
    if unexpected:
        raise ValueError(
            f"{layer.kind.value} contains unsupported columns: {unexpected}"
        )
    expected_encodings = {"x", "y"} if "x" in required else set()
    if set(layer.coordinate_encoding) != expected_encodings:
        raise ValueError("coordinate-bearing layers require exactly x/y encodings")
    for name in ("x", "y"):
        if name not in layer.data.columns:
            continue
        encoding = layer.coordinate_encoding[name]
        expected = (
            np.dtype(np.float32)
            if encoding.kind is CoordinateEncodingKind.RELATIVE_F32
            else np.dtype(np.float64)
        )
        if layer.data[name].dtype != expected:
            raise ValueError(
                f"{name} must use {expected.name} for its coordinate encoding"
            )
    for name, arrow_type in _NUMERIC_TYPES.items():
        if name not in layer.data.columns:
            continue
        dtype = layer.data[name].dtype
        if name == "color_index":
            if dtype not in (np.dtype(np.uint8), np.dtype(np.uint16)):
                raise ValueError("color_index must use uint8 or uint16")
        elif dtype != np.dtype(arrow_type.to_pandas_dtype()):
            raise ValueError(f"{name} must use {arrow_type}")


def _validate_arrow_schema(
    schema: pa.Schema, manifest_layer: LayerManifestModel
) -> None:
    expected_names = _wire_column_names(manifest_layer, tuple(schema.names))
    if tuple(schema.names) != expected_names:
        raise ValueError("Arrow fields are not in canonical Scene column order")
    for field in schema:
        name = field.name
        if set(field.metadata or {}) != {b"numpy_dtype"}:
            raise ValueError(f"Arrow field {name!r} has noncanonical metadata")
        dtype_bytes = field.metadata[b"numpy_dtype"]
        try:
            numpy_dtype = np.dtype(dtype_bytes.decode("ascii"))
        except (UnicodeDecodeError, TypeError) as error:
            raise ValueError(
                f"Arrow field {name!r} has invalid dtype metadata"
            ) from error
        if name in _DICTIONARY_COLUMNS:
            if not pa.types.is_dictionary(field.type) or not pa.types.is_string(
                field.type.value_type
            ):
                raise ValueError(
                    f"Arrow field {name!r} must be dictionary-encoded utf8"
                )
            continue
        if name in _STRING_COLUMNS or numpy_dtype.kind in {"U", "S", "O"}:
            if not (
                pa.types.is_string(field.type)
                or (
                    pa.types.is_dictionary(field.type)
                    and pa.types.is_string(field.type.value_type)
                )
            ):
                raise ValueError(f"Arrow field {name!r} must use utf8 values")
            continue
        try:
            expected_type = pa.from_numpy_dtype(numpy_dtype)
        except pa.ArrowNotImplementedError as error:
            raise ValueError(
                f"Arrow field {name!r} has unsupported dtype metadata"
            ) from error
        if field.type != expected_type:
            raise ValueError(
                f"Arrow field {name!r} type {field.type} does not match "
                f"NumPy dtype {numpy_dtype}"
            )


def _wire_column_names(
    manifest_layer: LayerManifestModel, actual_names: tuple[str, ...]
) -> tuple[str, ...]:
    known = _CANONICAL_COLUMNS[manifest_layer.kind]
    names = set(actual_names)
    allowed = (
        _REQUIRED_COLUMNS[manifest_layer.kind]
        | _OPTIONAL_COLUMNS[manifest_layer.kind]
        | set(manifest_layer.hover_fields)
    )
    missing = sorted(_REQUIRED_COLUMNS[manifest_layer.kind] - names)
    unexpected = sorted(names - allowed)
    if missing:
        raise ValueError(f"required Arrow columns are missing: {missing}")
    if unexpected:
        raise ValueError(f"unsupported Arrow columns: {unexpected}")
    return tuple(name for name in known if name in names) + tuple(
        sorted(names - set(known))
    )


def _column_to_arrow(name: str, values: np.ndarray) -> pa.Array:
    if name in _DICTIONARY_COLUMNS:
        return _string_array(values, name).dictionary_encode()
    if name in _STRING_COLUMNS or values.dtype.kind in {"U", "S", "O"}:
        return _string_array(values, name)
    if name == "color_index":
        arrow_type = pa.uint8() if values.dtype == np.uint8 else pa.uint16()
    elif name in {"x", "y"}:
        arrow_type = pa.float32() if values.dtype == np.float32 else pa.float64()
    else:
        arrow_type = _NUMERIC_TYPES.get(name)
    if arrow_type is None:
        if values.dtype.kind not in {"b", "i", "u", "f"}:
            raise ValueError(f"hover column {name!r} has an unsupported dtype")
        return pa.array(values)
    return pa.array(values, type=arrow_type)


def _string_array(values: np.ndarray, name: str) -> pa.Array:
    items = values.tolist()
    if not all(value is None or isinstance(value, (str, bytes)) for value in items):
        raise ValueError(f"{name} must contain only strings or nulls")
    normalized = [
        value.decode("utf-8") if isinstance(value, bytes) else value for value in items
    ]
    return pa.array(normalized, type=pa.string())


def _schema_metadata(layer: SceneLayer) -> Mapping[bytes, bytes]:
    metadata: dict[bytes, bytes] = {
        b"starplot_schema_version": SCENE_SCHEMA_VERSION.encode("ascii"),
        b"layer_id": layer.id.encode("utf-8"),
        b"kind": layer.kind.value.encode("ascii"),
        b"coordinate_encoding": _canonical_encoding_json(layer.coordinate_encoding),
    }
    for axis in ("x", "y"):
        encoding = layer.coordinate_encoding.get(axis)
        if encoding is None or encoding.kind is not CoordinateEncodingKind.RELATIVE_F32:
            continue
        metadata[f"origin_{axis}".encode()] = repr(encoding.origin).encode("ascii")
        metadata[f"scale_{axis}".encode()] = repr(encoding.scale).encode("ascii")
    return metadata


def _wire_schema_metadata(layer: LayerManifestModel) -> Mapping[bytes, bytes]:
    metadata: dict[bytes, bytes] = {
        b"starplot_schema_version": SCENE_SCHEMA_VERSION.encode("ascii"),
        b"layer_id": layer.id.encode("utf-8"),
        b"kind": layer.kind.value.encode("ascii"),
        b"coordinate_encoding": _canonical_encoding_json(layer.coordinate_encoding),
    }
    for axis in ("x", "y"):
        encoding = layer.coordinate_encoding.get(axis)
        if encoding is None or encoding.kind is not CoordinateEncodingKind.RELATIVE_F32:
            continue
        metadata[f"origin_{axis}".encode()] = repr(encoding.origin).encode("ascii")
        metadata[f"scale_{axis}".encode()] = repr(encoding.scale).encode("ascii")
    return metadata


def _canonical_encoding_json(encodings: Mapping) -> bytes:
    value = {}
    for name, encoding in encodings.items():
        if hasattr(encoding, "model_dump"):
            item = encoding.model_dump(mode="json")
        else:
            item = {
                "kind": encoding.kind.value,
                "origin": encoding.origin,
                "scale": encoding.scale,
                "max_error_pixels": encoding.max_error_pixels,
            }
        value[name] = item
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _arrow_to_numpy(column: pa.ChunkedArray, dtype: np.dtype, name: str) -> np.ndarray:
    if dtype.kind in {"O", "U", "S"}:
        values = _chunked_to_pylist(column)
        if dtype.kind in {"U", "S"} and any(value is None for value in values):
            raise ValueError(f"Arrow field {name!r} cannot restore nulls into {dtype}")
        return np.asarray(values, dtype=dtype)
    if column.null_count:
        raise ValueError(f"Arrow numeric field {name!r} cannot contain nulls")
    chunks = [
        np.asarray(chunk.to_numpy(zero_copy_only=False), dtype=dtype)
        for chunk in column.chunks
    ]
    if not chunks:
        return np.empty(0, dtype=dtype)
    if len(chunks) == 1:
        return np.ascontiguousarray(chunks[0], dtype=dtype)
    return np.concatenate(chunks).astype(dtype, copy=False)


def _chunked_to_pylist(column: pa.ChunkedArray) -> list:
    """Bounded materialization path used only for string/dictionary columns."""
    return column.to_pylist()
