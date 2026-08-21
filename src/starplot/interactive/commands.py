from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class _StringEnum(str, Enum):
    """Python 3.10-compatible string enum with ``StrEnum`` string behavior."""

    __str__ = str.__str__


class CoordinateSpace(_StringEnum):
    DATA = "data"  # final x/y in x_min/x_max/y_min/y_max
    AXES = "axes"  # normalized [0, 1] in Matplotlib axes
    PAPER = "paper"  # normalized [0, 1] in full figure


class CommandType(_StringEnum):
    SCATTER = "scatter"
    LINE = "line"
    LINE_COLLECTION = "line_collection"
    POLYGON = "polygon"
    TEXT = "text"
    GRADIENT = "gradient"
    INFO_TABLE = "info_table"


@dataclass(frozen=True)
class ClipGeometry:
    kind: str  # "none", "rect", "polygon"
    points: tuple[tuple[float, float], ...] = ()


@dataclass
class DrawingCommand:
    """Backend-agnostic drawing instruction.

    Attributes:
        kind: One of "scatter", "line", "polygon", "text", "line_collection", "gradient"
        data: Coordinate data dict. Large scatter columns remain contiguous,
            read-only NumPy arrays:
            - scatter: {x, y, sizes, colors, alphas}
            - line: {x, y}
            - polygon: {points, rings?}  # one or more independent paths
            - text: {text, x, y}
            - line_collection: {lines}  # list of [(x1,y1),(x2,y2)] pairs
            - gradient: {direction, color_stops}
        style: Backend-agnostic style dict:
            color, edge_color, line_width, line_style, alpha, fill_color,
            font_size, font_weight, font_color, font_name, anchor_point, etc.
        metadata: Per-object metadata for tooltips. The recorder retains this
            as a tuple until metadata becomes columnar:
            - star: {name, magnitude, hip, bayer, constellation, ra, dec, type:"star"}
            - dso: {name, dso_type, magnitude, size, m, ngc, ra, dec, type:"dso"}
            - planet: {name, magnitude, ra, dec, type:"planet"}
            - constellation: {name, iau_id, type:"constellation"}
        zorder: Layer ordering (higher = on top)
        gid: Element group ID (matches matplotlib gid)
        space: Coordinate space of this command's data.
        clip_id: Identifier of the clip geometry to apply, or None for no clip.
    """

    kind: CommandType
    data: dict = field(default_factory=dict)
    style: dict = field(default_factory=dict)
    metadata: list = field(default_factory=list)
    zorder: int = 0
    gid: str = ""
    space: CoordinateSpace = CoordinateSpace.DATA
    clip_id: str | None = "plot"

    def __post_init__(self):
        try:
            self.kind = CommandType(self.kind)
        except ValueError as error:
            raise ValueError(f"Unknown command type: {self.kind}") from error
        try:
            self.space = CoordinateSpace(self.space)
        except ValueError as error:
            raise ValueError(f"Unknown coordinate space: {self.space}") from error
