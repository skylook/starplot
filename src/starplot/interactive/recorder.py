import numpy as np

from starplot.interactive.commands import CoordinateSpace, DrawingCommand
from starplot.interactive.scene import _seal_owned_array, readonly_array
from starplot.styles import ZOrderEnum


def _materialize_column(value, *, iterator_dtype, name):
    """Materialize an array-like or one-shot iterable exactly once."""
    if isinstance(value, np.ndarray):
        array = readonly_array(value)
    elif isinstance(value, (list, tuple)):
        array = np.array(
            value,
            copy=True,
            order="C",
            subok=False,
        )
    elif np.isscalar(value):
        array = np.array(
            value,
            copy=True,
            order="C",
            subok=False,
        )
    else:
        array = np.fromiter(value, dtype=iterator_dtype)

    return _seal_owned_column(array, name=name)


def _seal_owned_column(array, *, name):
    """Validate and seal a newly owned one-dimensional scatter column."""
    if array.ndim != 1:
        raise ValueError(f"Scatter {name} must be a one-dimensional column")
    return _seal_owned_array(array)


def _is_scalar_like(value):
    """Return whether color/alpha input should be broadcast across rows."""
    if np.isscalar(value):
        return True
    return isinstance(value, np.ndarray) and np.ndim(value) == 0


class DrawingRecorder:
    """Records drawing commands without modifying the drawing pipeline."""

    def __init__(self):
        self.commands: list[DrawingCommand] = []
        self.projection_info: dict = {}
        # Keys: type, ra_min, ra_max, dec_min, dec_max,
        #       x_min, x_max, y_min, y_max (projected coordinate range)
        self.style_info: dict = {}
        # Keys: background_color, figure_background_color, resolution

    def record_scatter(
        self, x, y, sizes, colors, alphas, metadata, style_dict=None,
        gid="scatter", zorder=0, *,
        space=CoordinateSpace.DATA, clip_id="plot",
    ):
        x = _materialize_column(x, iterator_dtype=np.float64, name="x")
        y = _materialize_column(y, iterator_dtype=np.float64, name="y")
        sizes = _materialize_column(
            sizes,
            iterator_dtype=np.float64,
            name="sizes",
        )
        row_count = len(x)
        if _is_scalar_like(colors):
            colors = _seal_owned_column(
                np.full(row_count, colors),
                name="colors",
            )
        else:
            colors = _materialize_column(
                colors,
                iterator_dtype=object,
                name="colors",
            )
        if _is_scalar_like(alphas):
            alphas = _seal_owned_column(
                np.full(row_count, alphas),
                name="alphas",
            )
        else:
            alphas = _materialize_column(
                alphas,
                iterator_dtype=np.float64,
                name="alphas",
            )

        if len({len(x), len(y), len(sizes), len(colors), len(alphas)}) > 1:
            raise ValueError("Scatter columns must have the same row count")

        metadata = tuple(metadata)
        command = DrawingCommand(
            kind="scatter",
            data={
                "x": x,
                "y": y,
                "sizes": sizes,
                "colors": colors,
                "alphas": alphas,
            },
            style=dict(style_dict) if style_dict else {},
            metadata=metadata,
            gid=gid,
            zorder=zorder,
            space=space,
            clip_id=clip_id,
        )
        self.commands.append(command)

    def coalesced_scatter_commands(self):
        """Return commands with adjacent equivalent scatters concatenated once.

        Recording must remain O(n): some large charts issue one scatter call
        per object, so concatenating on every call would copy an ever-growing
        array quadratically.  Scene consumers call this finalization pass once
        after Matplotlib has finished drawing.
        """
        result = []
        pending = []

        def flush_pending():
            if not pending:
                return
            if len(pending) == 1:
                result.append(pending[0])
            else:
                first = pending[0]
                result.append(DrawingCommand(
                    kind="scatter",
                    data={
                        name: _seal_owned_array(np.concatenate([item.data[name] for item in pending]))
                        for name in ("x", "y", "sizes", "colors", "alphas")
                    },
                    style=dict(first.style),
                    metadata=tuple(item for command in pending for item in command.metadata),
                    gid=first.gid,
                    zorder=first.zorder,
                    space=first.space,
                    clip_id=first.clip_id,
                ))
            pending.clear()

        for command in self.commands:
            if pending and not self._can_coalesce_scatter(pending[-1], command):
                flush_pending()
            if command.kind == "scatter":
                pending.append(command)
            else:
                flush_pending()
                result.append(command)
        flush_pending()
        return tuple(result)

    @staticmethod
    def _can_coalesce_scatter(previous, current):
        """Return whether two adjacent recorded scatter calls share semantics."""
        return (
            previous.kind == current.kind == "scatter"
            and previous.style == current.style
            and previous.gid == current.gid
            and previous.zorder == current.zorder
            and previous.space == current.space
            and previous.clip_id == current.clip_id
        )

    def record_line(
        self, x, y, style_dict, gid, zorder, *,
        space=CoordinateSpace.DATA, clip_id="plot",
    ):
        self.commands.append(DrawingCommand(
            kind="line",
            data={"x": list(x), "y": list(y)},
            style=dict(style_dict),
            gid=gid,
            zorder=zorder,
            space=space,
            clip_id=clip_id,
        ))

    def record_polygon(
        self, points, style_dict, gid, zorder, *, rings=None,
        space=CoordinateSpace.DATA, clip_id="plot",
    ):
        # These coordinates come from final Matplotlib artists.  Unlike the
        # low-level public DrawingCommand contract, a legal Matplotlib Path may
        # be self-intersecting and rely on its fill rule; preserve that origin
        # so the Scene compiler can normalize it before geometric clipping.
        data = {"points": list(points), "final_artist": True}
        if rings is not None:
            data["rings"] = [list(ring) for ring in rings]
        self.commands.append(DrawingCommand(
            kind="polygon",
            data=data,
            style=dict(style_dict),
            gid=gid,
            zorder=zorder,
            space=space,
            clip_id=clip_id,
        ))

    def record_text(
        self, text, x, y, style_dict, gid, zorder, *,
        space, clip_id=None,
    ):
        """Record a text command.

        ``space`` is required (not defaulted) because text can live in DATA,
        AXES, or PAPER coordinates depending on context.
        ``clip_id`` defaults to None because text is rarely clipped.
        """
        self.commands.append(DrawingCommand(
            kind="text",
            data={"text": text, "x": float(x), "y": float(y)},
            style=dict(style_dict),
            gid=gid,
            zorder=zorder,
            space=space,
            clip_id=clip_id,
        ))

    def record_line_collection(
        self, lines, style_dict, gid, zorder, metadata=None, *,
        space=CoordinateSpace.DATA, clip_id="plot",
    ):
        self.commands.append(DrawingCommand(
            kind="line_collection",
            data={"lines": list(lines)},
            style=dict(style_dict),
            metadata=list(metadata) if metadata else [],
            gid=gid,
            zorder=zorder,
            space=space,
            clip_id=clip_id,
        ))

    def record_gradient(
        self, direction, color_stops, gid="gradient", zorder=None, *,
        space=CoordinateSpace.DATA, clip_id="plot",
    ):
        self.commands.append(DrawingCommand(
            kind="gradient",
            data={"direction": direction, "color_stops": list(color_stops)},
            gid=gid,
            zorder=zorder if zorder is not None else ZOrderEnum.LAYER_1 - 1000,
            space=space,
            clip_id=clip_id,
        ))

    def record_info_table(
        self, columns, values, widths, style_dict, gid="info-table", zorder=0, *,
        space=CoordinateSpace.PAPER, clip_id=None,
    ):
        self.commands.append(DrawingCommand(
            kind="info_table",
            data={
                "columns": list(columns),
                "values": list(values),
                "widths": list(widths),
            },
            style=dict(style_dict),
            gid=gid,
            zorder=zorder,
            space=space,
            clip_id=clip_id,
        ))

    def clear(self):
        """Clear all recorded commands."""
        self.commands.clear()
