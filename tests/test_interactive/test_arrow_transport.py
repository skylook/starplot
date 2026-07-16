"""Deterministic Arrow IPC Stream contracts for every Scene primitive."""

from __future__ import annotations

from dataclasses import replace
import hashlib

import numpy as np
import pyarrow as pa
import pytest

import starplot.interactive.arrow_transport as arrow_transport
from starplot.interactive.arrow_transport import (
    decode_layer_stream,
    encode_layer_stream,
    encode_table_stream,
    layer_content_hash,
    layer_to_table,
)
from starplot.interactive.commands import CoordinateSpace
from starplot.interactive.scene import (
    ColumnarData,
    CoordinateEncoding,
    CoordinateEncodingKind,
    InteractionPolicy,
    SceneKind,
    SceneLayer,
)
from starplot.interactive.scene_manifest import (
    CapabilitiesModel,
    LayerManifestModel,
    PaletteAssetModel,
    SceneManifestModel,
    StyleAssetModel,
    build_scene_manifest,
    canonical_manifest_bytes,
)


def _scene_layers() -> tuple[SceneLayer, ...]:
    absolute = {
        "x": CoordinateEncoding(CoordinateEncodingKind.ABSOLUTE_F64),
        "y": CoordinateEncoding(CoordinateEncodingKind.ABSOLUTE_F64),
    }
    relative = {
        "x": CoordinateEncoding(
            CoordinateEncodingKind.RELATIVE_F32, origin=100.0, scale=20.0
        ),
        "y": CoordinateEncoding(
            CoordinateEncodingKind.RELATIVE_F32, origin=-50.0, scale=10.0
        ),
    }
    common = {
        "zorder": 2.0,
        "load_priority": 20,
        "space": CoordinateSpace.DATA,
        "clip_id": "plot",
        "required": True,
    }
    return (
        SceneLayer(
            id="scatter",
            kind=SceneKind.SCATTER,
            style={"palette_id": "palette-scatter", "marker": {"line_width": 0}},
            data=ColumnarData.from_mapping(
                {
                    "x": np.array([0.0, 0.5], dtype=np.float32),
                    "y": np.array([0.0, 1.0], dtype=np.float32),
                    "size": np.array([4.0, 8.0], dtype=np.float32),
                    "color_index": np.array([0, 1], dtype=np.uint8),
                    "opacity": np.array([1.0, 0.5], dtype=np.float32),
                    "symbol_index": np.array([0, 2], dtype=np.uint8),
                    "object_id": np.array(["star:1", None], dtype=object),
                    "name": np.array(["Sirius", "Sirius"], dtype="U6"),
                    "magnitude": np.array([-1.46, np.nan], dtype=np.float32),
                    "ra": np.array([101.2, 110.4], dtype=np.float64),
                    "dec": np.array([-16.7, -18.0], dtype=np.float64),
                }
            ),
            group_id="stars",
            interaction=InteractionPolicy.HOVER_AND_DETAIL,
            hover_fields=("name", "object_id", "magnitude", "ra", "dec"),
            coordinate_encoding=relative,
            palette=("#ffffff", "#ff0000"),
            **common,
        ),
        SceneLayer(
            id="line",
            kind=SceneKind.LINE,
            style={"color": "#fff", "width": 1.5},
            data=ColumnarData.from_mapping(
                {
                    "path_id": np.array([0, 0, 1], dtype=np.uint32),
                    "vertex_index": np.array([0, 1, 0], dtype=np.uint32),
                    "x": np.array([1.0, 2.0, 3.0], dtype=np.float64),
                    "y": np.array([4.0, 5.0, 6.0], dtype=np.float64),
                    "style_id": np.array([0, 0, 1], dtype=np.uint16),
                    "object_id": np.array(["a", None, "b"], dtype=object),
                }
            ),
            coordinate_encoding=absolute,
            **common,
        ),
        SceneLayer(
            id="line-collection",
            kind=SceneKind.LINE_COLLECTION,
            style={"color": "#aaa"},
            data=ColumnarData.from_mapping(
                {
                    "path_id": np.array([0, 0, 1, 1], dtype=np.uint32),
                    "vertex_index": np.array([0, 1, 0, 1], dtype=np.uint32),
                    "x": np.array([1, 2, 3, 4], dtype=np.float64),
                    "y": np.array([5, 6, 7, 8], dtype=np.float64),
                }
            ),
            coordinate_encoding=absolute,
            **common,
        ),
        SceneLayer(
            id="polygon",
            kind=SceneKind.POLYGON,
            style={"facecolor": "#123456"},
            data=ColumnarData.from_mapping(
                {
                    "polygon_id": np.array([0, 0, 0], dtype=np.uint32),
                    "ring_id": np.array([0, 0, 0], dtype=np.uint32),
                    "vertex_index": np.array([0, 1, 2], dtype=np.uint32),
                    "x": np.array([0, 1, 0], dtype=np.float64),
                    "y": np.array([0, 0, 1], dtype=np.float64),
                }
            ),
            coordinate_encoding=absolute,
            **common,
        ),
        SceneLayer(
            id="text",
            kind=SceneKind.TEXT,
            style={"color": "#fff", "font_size": 8},
            data=ColumnarData.from_mapping(
                {
                    "x": np.array([0.1, 0.2], dtype=np.float64),
                    "y": np.array([0.3, 0.4], dtype=np.float64),
                    "text": np.array(["Orion", "Orion"], dtype="U5"),
                    "rotation": np.array([0, 15], dtype=np.float32),
                    "x_offset": np.array([1, 2], dtype=np.float32),
                    "y_offset": np.array([-1, -2], dtype=np.float32),
                    "style_id": np.array([0, 0], dtype=np.uint16),
                    "object_id": np.array([None, "label:2"], dtype=object),
                }
            ),
            interaction=InteractionPolicy.HOVER,
            hover_fields=("object_id",),
            coordinate_encoding=absolute,
            **common,
        ),
        SceneLayer(
            id="gradient",
            kind=SceneKind.GRADIENT,
            style={
                "direction": "radial",
                "color_stops": ((0.0, "#000"), (1.0, "#fff")),
                "center": (0.5, 0.5),
                "radius": 1.0,
            },
            data=ColumnarData.from_mapping({}),
            **common,
        ),
        SceneLayer(
            id="info-table",
            kind=SceneKind.INFO_TABLE,
            style={"color": "#fff"},
            data=ColumnarData.from_mapping(
                {
                    "column": np.array(["Name", "Magnitude"], dtype="U9"),
                    "value": np.array(["Sirius", "-1.46"], dtype="U6"),
                    "width": np.array([0.4, 0.6], dtype=np.float32),
                }
            ),
            space=CoordinateSpace.PAPER,
            clip_id=None,
            zorder=10,
            load_priority=10,
            required=True,
            group_id="info",
        ),
    )


def _manifest_for(layer: SceneLayer, payload: bytes):
    manifest = build_scene_manifest(
        scene_id="transport-test",
        layers=(layer,),
        layer_bytes={layer.id: payload},
        viewport={"reference_width": 1200, "reference_height": 800},
        coordinate_spaces={"data": {}, "paper": {}},
        clips=(),
        capabilities=CapabilitiesModel(
            viewport_query=False,
            lod=False,
            magnitude_filter=False,
            catalog_detail=False,
            max_batch_rows=250_000,
        ),
    )
    serialized = canonical_manifest_bytes(manifest)
    parsed = SceneManifestModel.model_validate_json(serialized)
    return parsed.resolve_layer(layer.id)


def _unchecked_manifest_for(layer: SceneLayer, payload: bytes):
    """Construct test-only resolver context for intentionally malformed IPC."""
    style_id = f"style-{layer.id}" if layer.style else None
    styles = (
        (StyleAssetModel(id=style_id, value=layer.style),)
        if style_id is not None
        else ()
    )
    palettes = ()
    if layer.palette is not None:
        palettes = (
            PaletteAssetModel(id=layer.style["palette_id"], colors=layer.palette),
        )
    wire = LayerManifestModel.from_layer(
        layer,
        byte_length=len(payload),
        content_hash=layer_content_hash(payload),
        data_source={"format": "arrow-ipc-stream", "uri": f"{layer.id}.arrow"},
        style_id=style_id,
    )
    manifest = SceneManifestModel.model_construct(
        schema_version="1.0",
        scene_id="malformed-transport-test",
        content_hash="sha256:" + "0" * 64,
        minimum_loader_version="1.0",
        viewport={},
        coordinate_spaces={},
        clips=(),
        styles=styles,
        palettes=palettes,
        layers=(wire,),
        capabilities=CapabilitiesModel(
            viewport_query=False,
            lod=False,
            magnitude_filter=False,
            catalog_detail=False,
            max_batch_rows=250_000,
        ),
        extensions={},
    )
    return manifest.resolve_layer(layer.id)


def _assert_layer_equal(restored: SceneLayer, expected: SceneLayer) -> None:
    assert restored.id == expected.id
    assert restored.kind is expected.kind
    assert restored.group_id == expected.group_id
    assert restored.zorder == expected.zorder
    assert restored.load_priority == expected.load_priority
    assert restored.space is expected.space
    assert restored.clip_id == expected.clip_id
    assert restored.style == expected.style
    assert restored.interaction is expected.interaction
    assert restored.hover_fields == expected.hover_fields
    assert restored.required is expected.required
    assert restored.coordinate_encoding == expected.coordinate_encoding
    assert restored.palette == expected.palette
    assert restored.data.row_count == expected.data.row_count
    assert set(restored.data.columns) == set(expected.data.columns)
    for name, original in expected.data.columns.items():
        decoded = restored.data[name]
        assert decoded.dtype == original.dtype
        assert decoded.flags.c_contiguous
        assert not decoded.flags.writeable
        if original.dtype.kind == "O":
            assert decoded.tolist() == original.tolist()
        else:
            np.testing.assert_array_equal(decoded, original)


@pytest.mark.parametrize("layer", _scene_layers(), ids=lambda layer: layer.kind.value)
def test_arrow_stream_round_trip_preserves_every_immutable_scene_layer(layer):
    payload = encode_layer_stream(layer, max_chunksize=1)

    restored = decode_layer_stream(payload, _manifest_for(layer, payload))

    _assert_layer_equal(restored, layer)


def test_round_trip_preserves_exact_interaction_policy_after_wire_parse():
    for layer in _scene_layers():
        payload = encode_layer_stream(layer)
        restored = decode_layer_stream(payload, _manifest_for(layer, payload))

        assert restored.interaction is layer.interaction


def test_arrow_stream_is_deterministic_and_not_ipc_file_format():
    layer = _scene_layers()[0]
    first = encode_layer_stream(layer, max_chunksize=1)
    second = encode_layer_stream(layer, max_chunksize=1)

    assert first == second
    assert first[:4] == b"\xff\xff\xff\xff"
    assert first[:6] != b"ARROW1"
    assert layer_content_hash(first) == layer_content_hash(second)
    assert layer_content_hash(first) == "sha256:" + hashlib.sha256(first).hexdigest()
    with pa.ipc.open_stream(first) as reader:
        assert reader.read_all().num_rows == layer.data.row_count


def test_equivalent_column_insertion_order_has_identical_stream_bytes():
    layer = _scene_layers()[0]
    reversed_data = ColumnarData.from_mapping(
        dict(reversed(tuple(layer.data.columns.items())))
    )
    equivalent = replace(layer, data=reversed_data)

    first = encode_layer_stream(layer, max_chunksize=1)
    second = encode_layer_stream(equivalent, max_chunksize=1)

    assert first == second
    assert layer_content_hash(first) == layer_content_hash(second)
    assert layer_to_table(layer).column_names == [
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
    ]


def test_arrow_schema_has_exact_protocol_types_dictionary_columns_and_metadata():
    scatter = layer_to_table(_scene_layers()[0])
    text = layer_to_table(_scene_layers()[4])

    assert scatter.schema.field("x").type == pa.float32()
    assert scatter.schema.field("y").type == pa.float32()
    assert scatter.schema.field("size").type == pa.float32()
    assert scatter.schema.field("color_index").type == pa.uint8()
    assert scatter.schema.field("opacity").type == pa.float32()
    assert pa.types.is_dictionary(scatter.schema.field("name").type)
    assert pa.types.is_dictionary(text.schema.field("text").type)
    assert scatter.column("object_id").null_count == 1
    assert text.column("object_id").null_count == 1
    assert scatter.schema.metadata[b"starplot_schema_version"] == b"1.0"
    assert scatter.schema.metadata[b"layer_id"] == b"scatter"
    assert scatter.schema.metadata[b"kind"] == b"scatter"
    assert scatter.schema.metadata[b"coordinate_encoding"]
    assert scatter.schema.metadata[b"origin_x"] == b"100.0"
    assert scatter.schema.metadata[b"scale_y"] == b"10.0"


def test_transport_modes_reuse_the_identical_bytes_object_and_decode_contract():
    layer = _scene_layers()[0]
    payload = encode_layer_stream(layer)
    manifest = _manifest_for(layer, payload)
    transport_inputs = {
        "inline": payload,
        "static": payload,
        "api": payload,
    }

    assert all(value is payload for value in transport_inputs.values())
    assert len({layer_content_hash(value) for value in transport_inputs.values()}) == 1
    for value in transport_inputs.values():
        _assert_layer_equal(decode_layer_stream(value, manifest), layer)


def test_decode_rejects_wrong_length_hash_identity_and_manifest_schema():
    layer = _scene_layers()[0]
    payload = encode_layer_stream(layer)
    manifest = _manifest_for(layer, payload)

    with pytest.raises(ValueError, match="byte_length"):
        decode_layer_stream(payload[:-1], manifest)
    with pytest.raises(ValueError, match="content hash"):
        modified = payload[:100] + bytes([payload[100] ^ 1]) + payload[101:]
        decode_layer_stream(modified, manifest)
    wrong_layer = replace(layer, id="wrong")
    wrong_manifest = _unchecked_manifest_for(wrong_layer, payload)
    with pytest.raises(ValueError, match="layer id"):
        decode_layer_stream(payload, wrong_manifest)


def test_layer_to_table_rejects_missing_required_column_and_invalid_protocol_dtype():
    layer = _scene_layers()[0]
    missing = SceneLayer(
        **{
            **layer.__dict__,
            "data": ColumnarData.from_mapping(
                {
                    name: value
                    for name, value in layer.data.columns.items()
                    if name != "size"
                }
            ),
        }
    )
    wrong_dtype = SceneLayer(
        **{
            **layer.__dict__,
            "data": ColumnarData.from_mapping(
                {
                    **layer.data.columns,
                    "color_index": np.array([0, 1], dtype=np.uint32),
                }
            ),
        }
    )

    with pytest.raises(ValueError, match="required columns.*size"):
        layer_to_table(missing)
    with pytest.raises(ValueError, match="color_index"):
        layer_to_table(wrong_dtype)


def test_decode_rejects_arrow_field_type_that_disagrees_with_protocol():
    layer = _scene_layers()[4]
    table = layer_to_table(layer)
    text_index = table.schema.get_field_index("text")
    original_field = table.schema.field(text_index)
    invalid_field = pa.field("text", pa.int32(), metadata=original_field.metadata)
    invalid_schema = table.schema.set(text_index, invalid_field)
    invalid_arrays = list(table.columns)
    invalid_arrays[text_index] = pa.chunked_array([[1, 2]], type=pa.int32())
    invalid_table = pa.Table.from_arrays(invalid_arrays, schema=invalid_schema)
    payload = encode_table_stream(invalid_table)
    manifest = _unchecked_manifest_for(layer, payload)

    with pytest.raises(ValueError, match="text.*dictionary"):
        decode_layer_stream(payload, manifest)


def test_decode_rejects_relative_origin_metadata_that_disagrees_with_manifest():
    layer = _scene_layers()[0]
    table = layer_to_table(layer)
    metadata = dict(table.schema.metadata)
    metadata[b"origin_x"] = b"999.0"
    invalid_table = table.replace_schema_metadata(metadata)
    payload = encode_table_stream(invalid_table)
    manifest = _unchecked_manifest_for(layer, payload)

    with pytest.raises(ValueError, match="origin_x"):
        decode_layer_stream(payload, manifest)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda payload: payload + b"junk", "trailing|EOS"),
        (lambda payload: payload[:-8], "EOS"),
        (lambda payload: payload[:40] + payload[-8:], "truncated|Arrow IPC"),
    ],
)
def test_decode_rejects_noncanonical_or_truncated_stream_framing(mutate, message):
    layer = _scene_layers()[1]
    payload = encode_layer_stream(layer)
    invalid = mutate(payload)
    manifest = _unchecked_manifest_for(layer, invalid)

    with pytest.raises(ValueError, match=message):
        decode_layer_stream(invalid, manifest)


def test_decode_rejects_ipc_file_container_even_with_matching_manifest():
    layer = _scene_layers()[1]
    table = layer_to_table(layer)
    sink = pa.BufferOutputStream()
    with pa.ipc.new_file(sink, table.schema) as writer:
        writer.write_table(table)
    payload = sink.getvalue().to_pybytes()
    manifest = _unchecked_manifest_for(layer, payload)

    with pytest.raises(ValueError, match="IPC Stream|EOS"):
        decode_layer_stream(payload, manifest)


def test_numeric_decode_never_materializes_python_scalar_lists(monkeypatch):
    layer = _scene_layers()[3]
    payload = encode_layer_stream(layer, max_chunksize=1)
    manifest = _manifest_for(layer, payload)

    def fail_on_to_pylist(_column):
        raise AssertionError("numeric columns must not call to_pylist")

    monkeypatch.setattr(arrow_transport, "_chunked_to_pylist", fail_on_to_pylist)

    restored = decode_layer_stream(payload, manifest)

    _assert_layer_equal(restored, layer)


@pytest.mark.parametrize("kind", [SceneKind.SCATTER, SceneKind.LINE, SceneKind.TEXT])
def test_coordinate_bearing_manifest_requires_exactly_x_and_y_encodings(kind):
    layer = next(item for item in _scene_layers() if item.kind is kind)
    payload = encode_layer_stream(layer)
    manifest = build_scene_manifest(
        scene_id="encoding-test",
        layers=(layer,),
        layer_bytes={layer.id: payload},
        viewport={},
        coordinate_spaces={"data": {}},
        clips=(),
        capabilities=CapabilitiesModel(
            viewport_query=False,
            lod=False,
            magnitude_filter=False,
            catalog_detail=False,
            max_batch_rows=250_000,
        ),
    )
    raw = manifest.model_dump(mode="json")
    raw["layers"][0]["coordinate_encoding"].pop("y")

    with pytest.raises(ValueError, match="coordinate_encoding.*x.*y"):
        SceneManifestModel.model_validate(raw)


def test_info_table_width_is_a_documented_required_scene_1_0_column():
    layer = _scene_layers()[-1]
    table = layer_to_table(layer)

    assert table.column_names == ["column", "value", "width"]
    assert table.schema.field("width").type == pa.float32()


def test_manifest_builder_rejects_arbitrary_or_wrong_layer_payload_bytes():
    layer = _scene_layers()[1]
    other = _scene_layers()[2]
    capabilities = CapabilitiesModel(
        viewport_query=False,
        lod=False,
        magnitude_filter=False,
        catalog_detail=False,
        max_batch_rows=250_000,
    )

    with pytest.raises(ValueError, match="IPC Stream|EOS"):
        build_scene_manifest(
            scene_id="invalid",
            layers=(layer,),
            layer_bytes={layer.id: b"not-arrow-at-all"},
            viewport={},
            coordinate_spaces={},
            clips=(),
            capabilities=capabilities,
        )
    with pytest.raises(ValueError, match="layer id"):
        build_scene_manifest(
            scene_id="wrong-layer",
            layers=(layer,),
            layer_bytes={layer.id: encode_layer_stream(other)},
            viewport={},
            coordinate_spaces={},
            clips=(),
            capabilities=capabilities,
        )

    altered_columns = dict(layer.data.columns)
    altered_columns["x"] = np.array([9.0, 8.0, 7.0], dtype=np.float64)
    altered = replace(layer, data=ColumnarData.from_mapping(altered_columns))
    with pytest.raises(ValueError, match="data does not match"):
        build_scene_manifest(
            scene_id="same-schema-altered-data",
            layers=(layer,),
            layer_bytes={layer.id: encode_layer_stream(altered)},
            viewport={},
            coordinate_spaces={},
            clips=(),
            capabilities=capabilities,
        )


def test_manifest_builder_enforces_palette_id_bidirectionally():
    scatter = _scene_layers()[0]
    no_palette = replace(scatter, id="no-palette", palette=None)
    no_palette_id = replace(scatter, id="no-palette-id", style={"marker": {}})
    capabilities = CapabilitiesModel(
        viewport_query=False,
        lod=False,
        magnitude_filter=False,
        catalog_detail=False,
        max_batch_rows=250_000,
    )

    with pytest.raises(ValueError, match="palette_id.*palette"):
        build_scene_manifest(
            scene_id="style-only-palette",
            layers=(scatter, no_palette),
            layer_bytes={
                scatter.id: encode_layer_stream(scatter),
                no_palette.id: encode_layer_stream(no_palette),
            },
            viewport={},
            coordinate_spaces={},
            clips=(),
            capabilities=capabilities,
        )
    with pytest.raises(ValueError, match="palette.*palette_id"):
        build_scene_manifest(
            scene_id="data-only-palette",
            layers=(no_palette_id,),
            layer_bytes={no_palette_id.id: encode_layer_stream(no_palette_id)},
            viewport={},
            coordinate_spaces={},
            clips=(),
            capabilities=capabilities,
        )
