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
    InteractionPolicy,
    SceneKind,
    SceneLayer,
)
from starplot.interactive.scene_manifest import (
    SCENE_SCHEMA_VERSION,
    LayerManifestModel,
)


_NUMERIC_TYPES: Mapping[str, pa.DataType] = {
    "size": pa.float32(),
    "color_index": pa.uint8(),  # uint16 is validated as the other allowed form
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
    "width": pa.float32(),
}
_DICTIONARY_COLUMNS = frozenset({"name", "text", "column", "value"})
_STRING_COLUMNS = frozenset({"object_id"})
_REQUIRED_COLUMNS: Mapping[SceneKind, frozenset[str]] = {
    SceneKind.SCATTER: frozenset({"x", "y", "size", "color_index", "opacity"}),
    SceneKind.LINE: frozenset({"path_id", "vertex_index", "x", "y"}),
    SceneKind.LINE_COLLECTION: frozenset({"path_id", "vertex_index", "x", "y"}),
    SceneKind.POLYGON: frozenset({"polygon_id", "ring_id", "vertex_index", "x", "y"}),
    SceneKind.TEXT: frozenset(
        {"x", "y", "text", "rotation", "x_offset", "y_offset", "style_id"}
    ),
    SceneKind.GRADIENT: frozenset(),
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
    """Validate and convert one immutable Scene layer to an Arrow table."""
    if not isinstance(layer, SceneLayer):
        raise TypeError("layer must be a SceneLayer")
    _validate_layer_columns(layer)
    arrays = []
    fields = []
    for name, values in layer.data.columns.items():
        arrow_array = _column_to_arrow(layer, name, values)
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
    """Encode a table using IPC Stream format with deterministic batches."""
    if not isinstance(table, pa.Table):
        raise TypeError("table must be a pyarrow.Table")
    if not isinstance(max_chunksize, int) or max_chunksize <= 0:
        raise ValueError("max_chunksize must be a positive integer")
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, table.schema) as writer:
        writer.write_table(table, max_chunksize=max_chunksize)
    return sink.getvalue().to_pybytes()


def encode_layer_stream(layer: SceneLayer, max_chunksize: int = 250_000) -> bytes:
    return encode_table_stream(layer_to_table(layer), max_chunksize=max_chunksize)


def decode_layer_stream(data: bytes, manifest_layer: LayerManifestModel) -> SceneLayer:
    """Validate exact IPC bytes and reconstruct an immutable Scene layer."""
    if not isinstance(data, bytes):
        raise TypeError("data must be bytes")
    if not isinstance(manifest_layer, LayerManifestModel):
        manifest_layer = LayerManifestModel.model_validate(manifest_layer)
    if len(data) != manifest_layer.byte_length:
        raise ValueError("Arrow payload byte_length does not match the manifest")
    if layer_content_hash(data) != manifest_layer.content_hash:
        raise ValueError("Arrow payload content hash does not match the manifest")
    try:
        with pa.ipc.open_stream(data) as reader:
            table = reader.read_all()
    except (pa.ArrowInvalid, pa.ArrowIOError) as error:
        raise ValueError("payload is not a valid Arrow IPC Stream") from error
    metadata = table.schema.metadata or {}
    if metadata.get(b"starplot_schema_version") != SCENE_SCHEMA_VERSION.encode():
        raise ValueError(
            "Arrow schema version does not match the supported Scene schema"
        )
    if metadata.get(b"layer_id") != manifest_layer.id.encode("utf-8"):
        raise ValueError("Arrow schema layer id does not match the manifest")
    if metadata.get(b"kind") != manifest_layer.kind.value.encode("ascii"):
        raise ValueError("Arrow schema kind does not match the manifest")
    if table.num_rows != manifest_layer.row_count:
        raise ValueError("Arrow row count does not match the manifest")
    expected_encoding = _canonical_encoding_json(manifest_layer.coordinate_encoding)
    if metadata.get(b"coordinate_encoding") != expected_encoding:
        raise ValueError("Arrow coordinate encoding does not match the manifest")
    _validate_arrow_schema(table.schema, manifest_layer)

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
        group_id=manifest_layer.resolved_group_id,
        zorder=manifest_layer.zorder,
        load_priority=manifest_layer.load_priority,
        space=manifest_layer.coordinate_space,
        clip_id=manifest_layer.clip_id,
        style=manifest_layer.resolved_style,
        data=ColumnarData.from_mapping(columns),
        interaction=_resolved_interaction(manifest_layer),
        hover_fields=manifest_layer.hover_fields,
        required=manifest_layer.required,
        coordinate_encoding={
            name: value.to_scene()
            for name, value in manifest_layer.coordinate_encoding.items()
        },
        palette=manifest_layer.resolved_palette,
    )
    _validate_layer_columns(scene_layer)
    return scene_layer


def _resolved_interaction(manifest_layer: LayerManifestModel) -> InteractionPolicy:
    if manifest_layer.resolved_interaction is not None:
        return manifest_layer.resolved_interaction
    if not manifest_layer.interactive:
        return InteractionPolicy.NONE
    if "object_id" in manifest_layer.hover_fields:
        return InteractionPolicy.HOVER_AND_DETAIL
    return InteractionPolicy.HOVER


def layer_content_hash(data: bytes) -> str:
    if not isinstance(data, bytes):
        raise TypeError("data must be bytes")
    return "sha256:" + hashlib.sha256(data).hexdigest()


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
    for name in ("x", "y"):
        if name not in layer.data.columns:
            continue
        encoding = layer.coordinate_encoding.get(name)
        expected = (
            np.dtype(np.float32)
            if encoding is not None
            and encoding.kind is CoordinateEncodingKind.RELATIVE_F32
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
    """Reject type/metadata substitution before allocating NumPy columns."""
    for axis, encoding in manifest_layer.coordinate_encoding.items():
        if encoding.kind is not CoordinateEncodingKind.RELATIVE_F32:
            continue
        for component, value in (
            ("origin", encoding.origin),
            ("scale", encoding.scale),
        ):
            key = f"{component}_{axis}".encode("ascii")
            expected = repr(value).encode("ascii")
            actual = (schema.metadata or {}).get(key)
            if actual != expected:
                raise ValueError(
                    f"Arrow schema {key.decode()} does not match the manifest"
                )

    for field in schema:
        name = field.name
        dtype_bytes = (field.metadata or {}).get(b"numpy_dtype")
        if dtype_bytes is None:
            raise ValueError(f"Arrow field {name!r} is missing NumPy dtype metadata")
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


def _column_to_arrow(layer: SceneLayer, name: str, values: np.ndarray) -> pa.Array:
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
    values = column.to_pylist()
    if dtype.kind == "O":
        return np.asarray(values, dtype=object)
    if dtype.kind in {"U", "S"}:
        if any(value is None for value in values):
            raise ValueError(f"Arrow field {name!r} cannot restore nulls into {dtype}")
        return np.asarray(values, dtype=dtype)
    if column.null_count:
        raise ValueError(f"Arrow numeric field {name!r} cannot contain nulls")
    return np.asarray(values, dtype=dtype)
