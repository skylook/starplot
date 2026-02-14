from dataclasses import dataclass, field


@dataclass
class DrawingCommand:
    """Backend-agnostic drawing instruction.

    Attributes:
        kind: One of "scatter", "line", "polygon", "text", "line_collection", "gradient"
        data: Coordinate data dict:
            - scatter: {x, y, sizes, colors, alphas}
            - line: {x, y}
            - polygon: {points}  # list of (x,y) tuples
            - text: {text, x, y}
            - line_collection: {lines}  # list of [(x1,y1),(x2,y2)] pairs
            - gradient: {direction, color_stops}
        style: Backend-agnostic style dict:
            color, edge_color, line_width, line_style, alpha, fill_color,
            font_size, font_weight, font_color, font_name, anchor_point, etc.
        metadata: Per-object metadata for tooltips:
            - star: {name, magnitude, hip, bayer, constellation, ra, dec, type:"star"}
            - dso: {name, dso_type, magnitude, size, m, ngc, ra, dec, type:"dso"}
            - planet: {name, magnitude, ra, dec, type:"planet"}
            - constellation: {name, iau_id, type:"constellation"}
        zorder: Layer ordering (higher = on top)
        gid: Element group ID (matches matplotlib gid)
    """

    kind: str
    data: dict = field(default_factory=dict)
    style: dict = field(default_factory=dict)
    metadata: list = field(default_factory=list)
    zorder: int = 0
    gid: str = ""
