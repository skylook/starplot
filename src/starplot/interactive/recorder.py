import numpy as np

from starplot.interactive.commands import CoordinateSpace, DrawingCommand
from starplot.interactive.scene import readonly_array
from starplot.styles import ZOrderEnum


def _materialize_column(value, *, iterator_dtype, name):
    """Materialize an array-like or one-shot iterable exactly once."""
    if isinstance(value, np.ndarray):
        array = readonly_array(value)
    else:
        array = np.asarray(value)
        if array.ndim == 0 and not np.isscalar(value):
            array = np.fromiter(value, dtype=iterator_dtype)
        array = readonly_array(array)

    if array.ndim != 1:
        raise ValueError(f"Scatter {name} must be a one-dimensional column")
    return array


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
            colors = readonly_array(np.full(row_count, colors))
        else:
            colors = _materialize_column(
                colors,
                iterator_dtype=object,
                name="colors",
            )
        if _is_scalar_like(alphas):
            alphas = readonly_array(np.full(row_count, alphas))
        else:
            alphas = _materialize_column(
                alphas,
                iterator_dtype=np.float64,
                name="alphas",
            )

        if len({len(x), len(y), len(sizes), len(colors), len(alphas)}) > 1:
            raise ValueError("Scatter columns must have the same row count")

        self.commands.append(DrawingCommand(
            kind="scatter",
            data={
                "x": x,
                "y": y,
                "sizes": sizes,
                "colors": colors,
                "alphas": alphas,
            },
            style=dict(style_dict) if style_dict else {},
            metadata=tuple(metadata),
            gid=gid,
            zorder=zorder,
            space=space,
            clip_id=clip_id,
        ))

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
        data = {"points": list(points)}
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
