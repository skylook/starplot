from starplot.interactive.commands import CoordinateSpace, DrawingCommand
from starplot.styles import ZOrderEnum


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
        self.commands.append(DrawingCommand(
            kind="scatter",
            data={"x": list(x), "y": list(y), "sizes": list(sizes),
                  "colors": list(colors) if not isinstance(colors, str) else [colors] * len(list(x)),
                  "alphas": list(alphas) if not isinstance(alphas, (int, float)) else [alphas] * len(list(x))},
            style=dict(style_dict) if style_dict else {},
            metadata=list(metadata),
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
        self, points, style_dict, gid, zorder, *,
        space=CoordinateSpace.DATA, clip_id="plot",
    ):
        self.commands.append(DrawingCommand(
            kind="polygon",
            data={"points": list(points)},
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
