"""Unit tests for DrawingRecorder."""

import numpy as np
import pytest
import starplot.interactive.recorder as recorder_module
from starplot.interactive.recorder import DrawingRecorder


def test_recorder_initial_state():
    rec = DrawingRecorder()
    assert rec.commands == []
    assert rec.projection_info == {}
    assert rec.style_info == {}


def test_recorder_records_scatter():
    rec = DrawingRecorder()
    rec.record_scatter(
        x=[1, 2, 3], y=[4, 5, 6],
        sizes=[10, 20, 30],
        colors=["#ffffff", "#aaaaaa", "#000000"],
        alphas=[1.0, 0.8, 0.6],
        metadata=[{"name": "Sirius"}],
        gid="stars",
        zorder=1,
    )
    assert len(rec.commands) == 1
    cmd = rec.commands[0]
    assert cmd.kind == "scatter"
    assert cmd.gid == "stars"
    assert cmd.zorder == 1
    np.testing.assert_array_equal(cmd.data["x"], [1, 2, 3])
    np.testing.assert_array_equal(cmd.data["sizes"], [10, 20, 30])
    assert not cmd.data["x"].flags.writeable


def test_recorder_records_scatter_with_single_color():
    """record_scatter should broadcast a single string color to a column."""
    rec = DrawingRecorder()
    rec.record_scatter(
        x=[1, 2], y=[3, 4],
        sizes=[10, 20],
        colors="#ffffff",  # single color
        alphas=1.0,  # single alpha
        metadata=[],
        gid="stars",
        zorder=0,
    )
    cmd = rec.commands[0]
    assert isinstance(cmd.data["colors"], np.ndarray)
    assert len(cmd.data["colors"]) == 2


def test_recorder_coalesces_adjacent_equivalent_scatter_commands_on_finalization():
    recorder = DrawingRecorder()
    common = {
        "sizes": [4], "colors": ["#fff"], "alphas": [1.0],
        "style_dict": {"symbol": "circle"}, "gid": "dso-marker", "zorder": -1,
    }
    recorder.record_scatter(x=[1], y=[2], metadata=[{"name": "A"}], **common)
    recorder.record_scatter(x=[3], y=[4], metadata=[{"name": "B"}], **common)

    assert len(recorder.commands) == 2
    commands = recorder.coalesced_scatter_commands()
    assert len(commands) == 1
    command = commands[0]
    np.testing.assert_array_equal(command.data["x"], [1, 3])
    np.testing.assert_array_equal(command.data["y"], [2, 4])
    assert command.metadata == ({"name": "A"}, {"name": "B"})
    assert not command.data["x"].flags.writeable


def test_recorder_keeps_different_scatter_rendering_contracts_separate():
    recorder = DrawingRecorder()
    for gid in ("dso-galaxy", "dso-cluster"):
        recorder.record_scatter(
            x=[1], y=[2], sizes=[4], colors=["#fff"], alphas=[1.0],
            metadata=[], gid=gid, zorder=-1,
        )
    assert len(recorder.commands) == 2


def test_record_scatter_preserves_numpy_columns():
    recorder = DrawingRecorder()
    recorder.record_scatter(
        x=np.array([1, 2], dtype=np.float32),
        y=np.array([3, 4], dtype=np.float32),
        sizes=np.array([5, 6], dtype=np.float32),
        colors=np.array(["#fff", "#000"]),
        alphas=np.array([1, 0.5], dtype=np.float32),
        metadata=[],
    )

    command = recorder.commands[0]
    assert isinstance(command.data["x"], np.ndarray)
    assert command.data["x"].dtype == np.float32
    assert command.data["x"].flags.c_contiguous
    assert not command.data["x"].flags.writeable
    assert command.metadata == ()


def test_record_scatter_detaches_all_numpy_columns_from_callers():
    x_base = np.array([1, 99, 2, 99], dtype=np.float32)
    inputs = {
        "x": x_base[::2],
        "y": np.array([3, 4], dtype=np.float64),
        "sizes": np.array([5, 6], dtype=np.float32),
        "colors": np.array(["#fff", "#000"]),
        "alphas": np.array([1, 0.5], dtype=np.float32),
    }
    expected = {name: value.copy() for name, value in inputs.items()}
    recorder = DrawingRecorder()

    recorder.record_scatter(**inputs, metadata=[])

    command = recorder.commands[0]
    for name, source in inputs.items():
        retained = command.data[name]
        assert source.flags.writeable
        assert retained.flags.c_contiguous
        assert retained.flags.owndata
        assert not retained.flags.writeable
        assert not np.shares_memory(retained, source)
        source[0] = source[-1]
        np.testing.assert_array_equal(retained, expected[name])
        with pytest.raises(ValueError):
            retained[0] = retained[-1]

    x_base[0] = 42
    np.testing.assert_array_equal(command.data["x"], [1, 2])


def test_record_scatter_broadcasts_zero_dimensional_color_and_alpha_arrays():
    recorder = DrawingRecorder()

    recorder.record_scatter(
        x=[1.0, 2.0, 3.0],
        y=[4.0, 5.0, 6.0],
        sizes=[7.0, 8.0, 9.0],
        colors=np.array("#fff", dtype="<U4"),
        alphas=np.array(0.5, dtype=np.float32),
        metadata=[],
    )

    command = recorder.commands[0]
    colors = command.data["colors"]
    alphas = command.data["alphas"]
    assert colors.shape == (3,)
    assert colors.dtype == np.dtype("<U4")
    np.testing.assert_array_equal(colors, ["#fff", "#fff", "#fff"])
    assert alphas.shape == (3,)
    assert alphas.dtype == np.float32
    np.testing.assert_array_equal(alphas, [0.5, 0.5, 0.5])
    assert not colors.flags.writeable
    assert not alphas.flags.writeable


@pytest.mark.parametrize("name", ["x", "y", "sizes"])
def test_record_scatter_rejects_zero_dimensional_geometry_columns(name):
    values = {
        "x": [1.0, 2.0],
        "y": [3.0, 4.0],
        "sizes": [5.0, 6.0],
        "colors": ["#fff", "#000"],
        "alphas": [1.0, 0.5],
        "metadata": [],
    }
    values[name] = np.array(1.0)

    with pytest.raises(ValueError, match="one-dimensional"):
        DrawingRecorder().record_scatter(**values)


def test_record_scatter_list_columns_allocate_once_and_are_sealed_in_place(
    monkeypatch,
):
    original_array = recorder_module.np.array
    original_asarray = recorder_module.np.asarray
    allocations = []
    asarray_calls = []

    def array_spy(*args, **kwargs):
        result = original_array(*args, **kwargs)
        allocations.append(result)
        return result

    def asarray_spy(*args, **kwargs):
        asarray_calls.append(args[0])
        return original_asarray(*args, **kwargs)

    monkeypatch.setattr(recorder_module.np, "array", array_spy)
    monkeypatch.setattr(recorder_module.np, "asarray", asarray_spy)
    recorder = DrawingRecorder()
    recorder.record_scatter(
        x=[1.0, 2.0],
        y=[3.0, 4.0],
        sizes=[5.0, 6.0],
        colors=["#fff", "#000"],
        alphas=[1.0, 0.5],
        metadata=[],
    )
    monkeypatch.setattr(recorder_module.np, "array", original_array)
    monkeypatch.setattr(recorder_module.np, "asarray", original_asarray)

    assert asarray_calls == []
    assert len(allocations) == 5
    for name, allocation in zip(
        ("x", "y", "sizes", "colors", "alphas"),
        allocations,
    ):
        assert recorder.commands[0].data[name] is allocation
        assert allocation.flags.owndata
        assert not allocation.flags.writeable


def test_record_scatter_generator_columns_allocate_once_and_are_sealed_in_place(
    monkeypatch,
):
    original_array = recorder_module.np.array
    original_asarray = recorder_module.np.asarray
    original_fromiter = recorder_module.np.fromiter
    array_calls = []
    asarray_calls = []
    allocations = []

    def array_spy(*args, **kwargs):
        array_calls.append(args[0])
        return original_array(*args, **kwargs)

    def asarray_spy(*args, **kwargs):
        asarray_calls.append(args[0])
        return original_asarray(*args, **kwargs)

    def fromiter_spy(*args, **kwargs):
        result = original_fromiter(*args, **kwargs)
        allocations.append(result)
        return result

    monkeypatch.setattr(recorder_module.np, "array", array_spy)
    monkeypatch.setattr(recorder_module.np, "asarray", asarray_spy)
    monkeypatch.setattr(recorder_module.np, "fromiter", fromiter_spy)
    recorder = DrawingRecorder()
    recorder.record_scatter(
        x=(value for value in [1.0, 2.0]),
        y=(value for value in [3.0, 4.0]),
        sizes=(value for value in [5.0, 6.0]),
        colors=(value for value in ["#fff", "#000"]),
        alphas=(value for value in [1.0, 0.5]),
        metadata=[],
    )
    monkeypatch.setattr(recorder_module.np, "array", original_array)
    monkeypatch.setattr(recorder_module.np, "asarray", original_asarray)
    monkeypatch.setattr(recorder_module.np, "fromiter", original_fromiter)

    assert array_calls == []
    assert asarray_calls == []
    assert len(allocations) == 5
    for name, allocation in zip(
        ("x", "y", "sizes", "colors", "alphas"),
        allocations,
    ):
        assert recorder.commands[0].data[name] is allocation
        assert allocation.flags.owndata
        assert not allocation.flags.writeable


def test_record_scatter_scalar_broadcasts_allocate_once_and_are_sealed_in_place(
    monkeypatch,
):
    color = np.array("#fff", dtype="<U4")
    alpha = np.array(0.5, dtype=np.float32)
    original_array = recorder_module.np.array
    original_full = recorder_module.np.full
    array_allocations = []
    full_allocations = []

    def array_spy(*args, **kwargs):
        result = original_array(*args, **kwargs)
        array_allocations.append(result)
        return result

    def full_spy(*args, **kwargs):
        result = original_full(*args, **kwargs)
        full_allocations.append(result)
        return result

    monkeypatch.setattr(recorder_module.np, "array", array_spy)
    monkeypatch.setattr(recorder_module.np, "full", full_spy)
    recorder = DrawingRecorder()
    recorder.record_scatter(
        x=[1.0, 2.0],
        y=[3.0, 4.0],
        sizes=[5.0, 6.0],
        colors=color,
        alphas=alpha,
        metadata=[],
    )
    monkeypatch.setattr(recorder_module.np, "array", original_array)
    monkeypatch.setattr(recorder_module.np, "full", original_full)

    assert len(array_allocations) == 3
    assert len(full_allocations) == 2
    assert recorder.commands[0].data["colors"] is full_allocations[0]
    assert recorder.commands[0].data["alphas"] is full_allocations[1]
    assert all(allocation.flags.owndata for allocation in full_allocations)
    assert all(not allocation.flags.writeable for allocation in full_allocations)


def test_record_scatter_materializes_each_iterable_once():
    class SinglePass:
        def __init__(self, values):
            self.values = values
            self.iterations = 0

        def __iter__(self):
            self.iterations += 1
            if self.iterations > 1:
                raise AssertionError("iterable materialized more than once")
            return iter(self.values)

    x = SinglePass([1.0, 2.0])
    recorder = DrawingRecorder()

    recorder.record_scatter(
        x=x,
        y=[3.0, 4.0],
        sizes=[5.0, 6.0],
        colors=["#fff", "#000"],
        alphas=[1.0, 0.5],
        metadata=[],
    )

    assert x.iterations == 1
    np.testing.assert_array_equal(recorder.commands[0].data["x"], [1.0, 2.0])


def test_record_scatter_rejects_misaligned_inputs():
    recorder = DrawingRecorder()

    with pytest.raises(ValueError, match="same row count"):
        recorder.record_scatter(
            x=[1.0, 2.0],
            y=[3.0],
            sizes=[5.0, 6.0],
            colors=["#fff", "#000"],
            alphas=[1.0, 0.5],
            metadata=[],
        )


def test_recorder_records_line():
    rec = DrawingRecorder()
    rec.record_line(
        x=[0.0, 1.0, 2.0], y=[0.0, 0.5, 1.0],
        style_dict={"color": "#ff0000", "width": 2},
        gid="ecliptic-line",
        zorder=5,
    )
    assert len(rec.commands) == 1
    cmd = rec.commands[0]
    assert cmd.kind == "line"
    assert cmd.style["color"] == "#ff0000"
    assert cmd.gid == "ecliptic-line"


def test_recorder_records_polygon():
    rec = DrawingRecorder()
    pts = [(0.0, 0.0), (1.0, 0.0), (0.5, 1.0)]
    rec.record_polygon(
        points=pts,
        style_dict={"fill_color": "#223344", "alpha": 0.5},
        gid="milky-way",
        zorder=2,
    )
    assert len(rec.commands) == 1
    cmd = rec.commands[0]
    assert cmd.kind == "polygon"
    assert cmd.data["points"] == pts
    assert cmd.style["alpha"] == 0.5


def test_recorder_records_text():
    rec = DrawingRecorder()
    rec.record_text(
        text="Sirius",
        x=10.5, y=-5.0,
        style_dict={"font_size": 12, "font_color": "#ffffff"},
        gid="stars-label",
        zorder=10,
        space="data",
    )
    assert len(rec.commands) == 1
    cmd = rec.commands[0]
    assert cmd.kind == "text"
    assert cmd.data["text"] == "Sirius"
    assert cmd.data["x"] == 10.5


def test_recorder_records_line_collection():
    rec = DrawingRecorder()
    lines = [[(0, 0), (1, 1)], [(2, 2), (3, 3)]]
    metadata = [{"name": "Orion"}, {"name": "Orion"}]
    rec.record_line_collection(
        lines=lines,
        style_dict={"color": "#cccccc", "width": 1},
        gid="constellations-line",
        zorder=3,
        metadata=metadata,
    )
    cmd = rec.commands[0]
    assert cmd.kind == "line_collection"
    assert len(cmd.data["lines"]) == 2
    assert len(cmd.metadata) == 2


def test_recorder_records_gradient():
    rec = DrawingRecorder()
    rec.record_gradient(
        direction="vertical",
        color_stops=[(0.0, "#000000"), (1.0, "#000080")],
    )
    cmd = rec.commands[0]
    assert cmd.kind == "gradient"
    assert cmd.data["direction"] == "vertical"


def test_recorder_clear():
    rec = DrawingRecorder()
    rec.record_line(x=[1], y=[2], style_dict={}, gid="line", zorder=0)
    rec.record_text(text="A", x=1, y=2, style_dict={}, gid="text", zorder=0, space="data")
    assert len(rec.commands) == 2
    rec.clear()
    assert len(rec.commands) == 0


def test_recorder_multiple_commands():
    rec = DrawingRecorder()
    rec.record_scatter(x=[1], y=[2], sizes=[10], colors=["#fff"], alphas=[1.0],
                       metadata=[], gid="stars", zorder=1)
    rec.record_line(x=[0, 1], y=[0, 0], style_dict={}, gid="equator", zorder=2)
    rec.record_text(text="A", x=1, y=1, style_dict={}, gid="label", zorder=3, space="data")
    assert len(rec.commands) == 3
    assert [c.kind for c in rec.commands] == ["scatter", "line", "text"]
