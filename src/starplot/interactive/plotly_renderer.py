"""PlotlyRenderer — replays DrawingCommands as a Plotly Figure."""

try:
    import plotly.graph_objects as go
except ImportError as e:
    raise ImportError(
        "plotly is required for interactive export. "
        "Install it with: pip install starplot[interactive]"
    ) from e

import logging

import numpy as np
from matplotlib.colors import to_rgba

from starplot.interactive.commands import CoordinateSpace, DrawingCommand
from starplot.interactive.style_converter import (
    MARKER_SYMBOL_MAP,
    LINE_STYLE_MAP,
    ANCHOR_MAP,
    calibrate_marker_size,
)

LOGGER = logging.getLogger("starplot.interactive")

# Kaleido renders Plotly marker and annotation glyphs noticeably smaller than
# Matplotlib for the same nominal CSS-pixel diameter.  This is a renderer-unit
# calibration (not a chart-specific scale): apply it uniformly after converting
# the source Matplotlib point units.
_KALEIDO_MARKER_SCALE = 1.15
_KALEIDO_TEXT_SCALE = 1.35
# Kaleido's rasterized Plotly strokes are about half the visible thickness of
# Matplotlib strokes after both are normalized to the same output viewport.
# Keep this renderer-unit calibration separate from marker/font calibration.
_KALEIDO_STROKE_SCALE = 2.0
_MAX_INTERACTIVE_HOVER_POINTS = 50_000
# A one-pixel WebGL circle sprite applies its own edge coverage after marker
# alpha.  Matplotlib instead rasterizes at export resolution and downsamples.
# Normalize the total emitted area for theoretical subpixel diameters; this is
# a backend calibration shared by every high-volume scatter trace.
_WEBGL_SUBPIXEL_COVERAGE_SCALE = 6.0

# matplotlib uses "none" to indicate no color; Plotly requires a transparent rgba.
_MATPLOTLIB_NONE_COLORS = frozenset({"none", "None", "NONE", ""})


def _is_transparent_color(value):
    """Return True if a color value represents a fully transparent color."""
    if value is None or (isinstance(value, str) and value in _MATPLOTLIB_NONE_COLORS):
        return True
    value_str = str(value).lower()
    if value_str.startswith("rgba"):
        try:
            alpha = value_str.split(",")[-1].strip().rstrip(")")
            return float(alpha) <= 0
        except Exception:
            pass
    if value_str.startswith("rgba"):
        return True
    return False


def _sanitize_color(value, default="rgba(0,0,0,0)"):
    """Convert matplotlib 'none' color sentinel and Color objects to a Plotly-compatible color."""
    if value is None or (isinstance(value, str) and value in _MATPLOTLIB_NONE_COLORS):
        return default
    if hasattr(value, "as_hex"):
        return value.as_hex()
    return str(value)


def _sanitize_colors(colors):
    """Sanitize a list of colors or a single color string."""
    if isinstance(colors, (list, tuple, np.ndarray)):
        return [_sanitize_color(c) for c in colors]
    if isinstance(colors, str):
        return _sanitize_color(colors)
    if colors is None:
        return "rgba(0,0,0,0)"
    if hasattr(colors, "as_hex"):
        return colors.as_hex()
    try:
        return _sanitize_color(colors)
    except Exception:
        return "rgba(0,0,0,0)"


def _font_family(value):
    """Ensure recorded font names retain a browser-safe sans-serif fallback."""
    family = str(value or "Inter")
    return family if "," in family else f"{family}, Arial, sans-serif"


def _colors_with_alphas(colors, alphas, count):
    """Return Plotly colors that preserve Matplotlib's per-point alpha."""
    if isinstance(colors, (list, tuple, np.ndarray)):
        color_values = list(colors)
    else:
        color_values = [colors] * count

    if isinstance(alphas, (list, tuple, np.ndarray)):
        alpha_values = list(alphas)
    else:
        alpha_values = [alphas] * count

    if len(color_values) < count:
        color_values.extend([color_values[-1]] * (count - len(color_values)))
    if len(alpha_values) < count:
        alpha_values.extend([alpha_values[-1]] * (count - len(alpha_values)))

    result = []
    for color, alpha in zip(color_values[:count], alpha_values[:count]):
        if _is_transparent_color(color):
            result.append("rgba(0,0,0,0)")
            continue
        try:
            red, green, blue, base_alpha = to_rgba(color)
            opacity = min(1.0, max(0.0, base_alpha * float(alpha)))
            # Plotly's color validator rejects scientific notation inside
            # CSS rgba(), which subpixel coverage naturally produces.
            css_alpha = f"{opacity:.8f}".rstrip("0").rstrip(".") or "0"
            result.append(
                f"rgba({round(red * 255)},{round(green * 255)},"
                f"{round(blue * 255)},{css_alpha})"
            )
        except (TypeError, ValueError):
            result.append(_sanitize_color(color))
    return result


_KNOWN_LEGEND_GIDS = frozenset({
    "stars", "constellations-line", "constellations-border",
    "constellations-label-name", "ecliptic-line", "celestial-equator-line",
    "planet-marker", "moon-marker", "sun-marker", "marker", "dso",
    "dso_galaxy", "dso_nebula", "dso_open_cluster", "dso_globular_cluster",
})


def _is_finite(x, y):
    """Check if both coordinates are finite numbers."""
    import math
    try:
        return math.isfinite(float(x)) and math.isfinite(float(y))
    except (TypeError, ValueError):
        return False


def _append_geom_coords(xs, ys, geom):
    """Append coordinates from a Shapely geometry to xs/ys lists.

    Handles LineString, MultiLineString, and Point geometries.
    Inserts None separators between disjoint segments for Plotly.
    """
    from shapely.geometry import LineString, MultiLineString, Point, MultiPoint

    if isinstance(geom, Point):
        xs.append(geom.x)
        ys.append(geom.y)
    elif isinstance(geom, LineString):
        coords = list(geom.coords)
        for x, y in coords:
            xs.append(x)
            ys.append(y)
        xs.append(None)
        ys.append(None)
    elif isinstance(geom, MultiLineString):
        for line in geom.geoms:
            for x, y in line.coords:
                xs.append(x)
                ys.append(y)
            xs.append(None)
            ys.append(None)
    elif isinstance(geom, MultiPoint):
        for pt in geom.geoms:
            xs.append(pt.x)
            ys.append(pt.y)
        xs.append(None)
        ys.append(None)


def _append_geom_as_segments(lines_list, geom):
    """Append segments from a Shapely geometry to a list of line segments."""
    from shapely.geometry import LineString, MultiLineString, Point

    if isinstance(geom, Point):
        pass  # A single point can't form a line segment
    elif isinstance(geom, LineString):
        lines_list.append(list(geom.coords))
    elif isinstance(geom, MultiLineString):
        for line in geom.geoms:
            lines_list.append(list(line.coords))


class PlotlyRenderer:
    """Renders a list of DrawingCommands into a Plotly Figure."""

    def __init__(self, projection_info: dict, style_info: dict,
                 width: float = None, height: float = None,
                 transparent: bool = False):
        self.projection_info = projection_info
        self.style_info = style_info
        self.width = width
        self.height = height
        self._marker_viewport_width = width or 1000.0
        self._horizon_footer_offset = 0.0
        self._side_margin = 10
        self._paper_x_bounds = (0.0, 1.0)
        self._paper_y_bounds = (0.0, 1.0)
        self.transparent = transparent
        self._trace_groups: dict[str, list[int]] = {}
        self._shown_legend_labels: set[str] = set()
        self.fig = go.Figure()
        self._clip_polygons = self._build_clip_polygons()
        self._setup_layout()

    def _build_clip_polygons(self):
        """Build Shapely polygons from clip_geometries for intersection tests."""
        from shapely.geometry import Polygon
        clips = self.projection_info.get("clip_geometries", {})
        polygons = {}
        for clip_id, geom in clips.items():
            if geom is None or geom.kind == "none" or len(geom.points) < 3:
                continue
            try:
                polygons[clip_id] = Polygon(list(geom.points))
            except Exception:
                pass
        return polygons

    def _clip_command(self, cmd: DrawingCommand) -> DrawingCommand | None:
        """Clip a spatial DATA-space command against its clip polygon.

        Returns a new DrawingCommand with clipped geometry, or None if
        the command is entirely outside the clip region.
        """
        if cmd.space != CoordinateSpace.DATA:
            return cmd
        clip_id = cmd.clip_id
        if clip_id is None or clip_id not in self._clip_polygons:
            return cmd

        clip_poly = self._clip_polygons[clip_id]

        if cmd.kind == "scatter":
            return self._clip_scatter(cmd, clip_poly)
        elif cmd.kind == "line":
            return self._clip_line(cmd, clip_poly)
        elif cmd.kind == "line_collection":
            return self._clip_line_collection(cmd, clip_poly)
        elif cmd.kind == "polygon":
            return self._clip_polygon(cmd, clip_poly)
        elif cmd.kind == "gradient":
            return self._clip_gradient(cmd, clip_poly)
        return cmd

    def _clip_scatter(self, cmd, clip_poly):
        """Filter scatter points to those inside the clip polygon."""
        from shapely.geometry import Point
        xs = cmd.data.get("x", [])
        ys = cmd.data.get("y", [])
        sizes = cmd.data.get("sizes", [])
        colors = cmd.data.get("colors", [])
        alphas = cmd.data.get("alphas", [])
        metadata = cmd.metadata

        mask = []
        for x, y in zip(xs, ys):
            if x is None or y is None:
                mask.append(False)
            else:
                mask.append(clip_poly.contains(Point(x, y)))

        if not any(mask):
            return None

        def masked_values(values):
            if np.ndim(values) == 0:
                return values
            if len(values) != len(mask):
                raise ValueError("Scatter columns must align before clipping")
            if isinstance(values, np.ndarray):
                return values[np.asarray(mask, dtype=np.bool_)]
            return [value for value, keep in zip(values, mask) if keep]

        new_data = {
            "x": [x for x, m in zip(xs, mask) if m],
            "y": [y for y, m in zip(ys, mask) if m],
            "sizes": masked_values(sizes),
            "colors": masked_values(colors),
            "alphas": masked_values(alphas),
        }
        new_metadata = [m for m, keep in zip(metadata, mask) if keep] if metadata else []
        return DrawingCommand(
            kind=cmd.kind, data=new_data, style=cmd.style,
            metadata=new_metadata, zorder=cmd.zorder, gid=cmd.gid,
            space=cmd.space, clip_id=cmd.clip_id,
        )

    def _clip_line(self, cmd, clip_poly):
        """Clip a line against the clip polygon, preserving segments."""
        from shapely.geometry import LineString
        xs = cmd.data.get("x", [])
        ys = cmd.data.get("y", [])
        if not xs:
            return cmd

        # Split into segments at non-finite points
        segments = []
        current_x, current_y = [], []
        for x, y in zip(xs, ys):
            if x is None or y is None or not _is_finite(x, y):
                if len(current_x) > 1:
                    segments.append((current_x, current_y))
                current_x, current_y = [], []
            else:
                current_x.append(float(x))
                current_y.append(float(y))
        if len(current_x) > 1:
            segments.append((current_x, current_y))

        new_x, new_y = [], []
        for seg_x, seg_y in segments:
            try:
                line = LineString(list(zip(seg_x, seg_y)))
                clipped = line.intersection(clip_poly)
                if clipped.is_empty:
                    continue
                _append_geom_coords(new_x, new_y, clipped)
            except Exception:
                # If clipping fails, keep original segment
                new_x.extend(seg_x)
                new_y.extend(seg_y)
                new_x.append(None)
                new_y.append(None)

        if not new_x:
            return None

        return DrawingCommand(
            kind=cmd.kind, data={"x": new_x, "y": new_y}, style=cmd.style,
            metadata=cmd.metadata, zorder=cmd.zorder, gid=cmd.gid,
            space=cmd.space, clip_id=cmd.clip_id,
        )

    def _clip_line_collection(self, cmd, clip_poly):
        """Clip a line collection against the clip polygon."""
        from shapely.geometry import LineString
        lines = cmd.data.get("lines", [])
        new_lines = []
        new_metadata = []
        for i, seg in enumerate(lines):
            if len(seg) < 2:
                continue
            try:
                line = LineString(seg)
                clipped = line.intersection(clip_poly)
                if clipped.is_empty:
                    continue
                _append_geom_as_segments(new_lines, clipped)
                meta = cmd.metadata[i] if i < len(cmd.metadata) else {}
                new_metadata.append(meta)
            except Exception:
                new_lines.append(seg)
                meta = cmd.metadata[i] if i < len(cmd.metadata) else {}
                new_metadata.append(meta)

        if not new_lines:
            return None

        return DrawingCommand(
            kind=cmd.kind, data={"lines": new_lines}, style=cmd.style,
            metadata=new_metadata, zorder=cmd.zorder, gid=cmd.gid,
            space=cmd.space, clip_id=cmd.clip_id,
        )

    def _clip_polygon(self, cmd, clip_poly):
        """Clip a polygon against the clip polygon."""
        from shapely.geometry import Polygon as ShapelyPolygon
        rings = cmd.data.get("rings") or [cmd.data.get("points", [])]
        if not any(len(points) >= 3 for points in rings):
            return cmd
        try:
            clipped_rings = []
            for points in rings:
                if len(points) < 3:
                    continue
                clipped = ShapelyPolygon(points).intersection(clip_poly)
                if clipped.is_empty:
                    continue
                geometries = [clipped] if hasattr(clipped, "exterior") else getattr(clipped, "geoms", [])
                for geometry in geometries:
                    new_points = list(geometry.exterior.coords)
                    if len(new_points) > 1 and new_points[0] == new_points[-1]:
                        new_points = new_points[:-1]
                    if len(new_points) >= 3:
                        clipped_rings.append(new_points)
            if not clipped_rings:
                return None
            return DrawingCommand(
                kind=cmd.kind, data={"points": clipped_rings[0], "rings": clipped_rings}, style=cmd.style,
                metadata=cmd.metadata, zorder=cmd.zorder, gid=cmd.gid,
                space=cmd.space, clip_id=cmd.clip_id,
            )
        except Exception:
            return cmd

    def _clip_gradient(self, cmd, clip_poly):
        """Gradient clipping is handled in the renderer via nan masking."""
        return cmd

    def render(self, commands: list[DrawingCommand]) -> go.Figure:
        """Render all commands sorted by zorder."""
        self._reserve_horizon_footer(commands)
        self._reserve_map_gridline_gutters(commands)
        self._reserve_title_space(commands)
        for cmd in sorted(commands, key=lambda c: c.zorder if c.zorder is not None else 0):
            # Clip spatial commands before dispatch
            clipped = self._clip_command(cmd)
            if clipped is None:
                continue
            handler = {
                "scatter": self._render_scatter,
                "line": self._render_line,
                "polygon": self._render_polygon,
                "text": self._render_text,
                "line_collection": self._render_line_collection,
                "gradient": self._render_gradient,
                "info_table": self._render_info_table,
            }.get(clipped.kind)
            if handler:
                try:
                    handler(clipped)
                except Exception as e:
                    raise RuntimeError(
                        "Failed to render "
                        f"{clipped.kind} command (gid={clipped.gid})"
                    ) from e
        self._add_interactive_features()
        return self.fig

    def _reserve_title_space(self, commands: list[DrawingCommand]):
        """Reproduce Matplotlib's tight-bbox space above axes titles."""
        title_tops = [
            float(command.style["axes_domain_top"])
            for command in commands
            if command.gid == "title"
            and command.style.get("axes_domain_top") is not None
        ]
        if not title_tops:
            return
        current = self.fig.layout.yaxis.domain or (0.0, 1.0)
        self.fig.update_yaxes(
            domain=[float(current[0]), min(float(current[1]), min(title_tops))]
        )

    def _reserve_horizon_footer(self, commands: list[DrawingCommand]):
        """Keep HorizonPlot's negative axes-coordinate footer inside Plotly paper."""
        footer_y_values = []
        for cmd in commands:
            if cmd.gid != "horizon-bottom":
                continue
            footer_y_values.extend(point[1] for point in cmd.data.get("points", []))

        if not footer_y_values:
            return

        self._horizon_footer_offset = max(0.0, -min(footer_y_values))
        if self._horizon_footer_offset:
            self.fig.update_yaxes(domain=[self._horizon_footer_offset, 1.0])
        if any(command.gid == "gridlines-label" for command in commands):
            # Side altitude labels require paper room on both sides; the
            # projected plot width itself is controlled by the y-domain and
            # ``scaleanchor`` below, not by reducing this margin.
            self._side_margin = 50
            self.fig.update_layout(margin=dict(l=50, r=50, t=30, b=10))

    def _reserve_map_gridline_gutters(self, commands: list[DrawingCommand]):
        """Keep Matplotlib map tick labels outside the axes inside Plotly paper.

        Cartopy's Gridliner deliberately places labels just beyond the axes
        rectangle.  Matplotlib's export padding includes them, while Plotly
        clips paper-coordinate annotations outside ``[0, 1]``.  Derive a
        shared paper viewport from the final rendered label artists and move
        the axes domain inward by the same affine mapping.
        """
        if self.projection_info.get("plot_kind") != "map":
            return
        labels = [
            command for command in commands
            if command.gid == "gridlines-label"
            and command.space == CoordinateSpace.PAPER
        ]
        if not labels:
            return

        xs = [float(command.data["x"]) for command in labels]
        ys = [float(command.data["y"]) for command in labels]
        # One percent of the source paper span leaves room for glyph ascent,
        # descent, and the point-based label offset on every plot scale.
        pad = 0.015
        x0, x1 = min(0.0, min(xs)) - pad, max(1.0, max(xs)) + pad
        y0, y1 = min(0.0, min(ys)) - pad, max(1.0, max(ys)) + pad
        self._paper_x_bounds = (x0, x1)
        self._paper_y_bounds = (y0, y1)
        self.fig.update_xaxes(domain=[(0.0 - x0) / (x1 - x0), (1.0 - x0) / (x1 - x0)])
        self.fig.update_yaxes(domain=[(0.0 - y0) / (y1 - y0), (1.0 - y0) / (y1 - y0)])

    def _paper_x(self, value):
        """Map a recorded Matplotlib figure x coordinate into Plotly paper."""
        x0, x1 = self._paper_x_bounds
        return (value - x0) / (x1 - x0)

    def _paper_y(self, value, gid, style=None):
        """Translate the HorizonPlot footer from negative axes space into paper."""
        if gid in {"horizon-bottom", "horizon-label"} or (style or {}).get("footer"):
            value += self._horizon_footer_offset
        y0, y1 = self._paper_y_bounds
        return (value - y0) / (y1 - y0)

    def _target_axes_width(self):
        """Return the drawable Plotly width after the fixed side margins."""
        return max(1.0, self._marker_viewport_width - 2.0 * self._side_margin)

    def _font_pixel_scale(self):
        """Convert final Matplotlib point sizes to target CSS pixels.

        Recorded font sizes already include the plot's style scale.  Applying
        ``plot_scale`` or the line/marker Kaleido calibration again makes
        labels disproportionately large on lower-resolution HTML exports.
        """
        source_width = self.style_info.get("source_axes_width")
        if not source_width:
            return 1.0
        return (
            float(self.style_info.get("dpi", 100.0))
            / 72.0
            * self._target_axes_width()
            / float(source_width)
        )

    def _stroke_pixel_scale(self):
        """Convert Matplotlib point linewidths to calibrated Plotly pixels."""
        return self._font_pixel_scale() * _KALEIDO_STROKE_SCALE

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _setup_layout(self):
        bg = self.style_info.get("background_color", "#ffffff")
        fig_bg = self.style_info.get("figure_background_color", "#ffffff")

        # Matplotlib's ``savefig(transparent=True)`` makes the figure paper
        # transparent but preserves the explicit axes facecolor recorded by
        # starplot styles.  Keeping the Plotly plot background opaque also
        # preserves light-map Gridliner text and chart interior alpha.
        if self.transparent:
            fig_bg = "rgba(0,0,0,0)"

        # Use matplotlib's projected axis limits so Plotly renders in the same
        # coordinate space (Cartopy projection units for MapPlot/ZenithPlot,
        # or AZ/ALT degrees for HorizonPlot, etc.)
        x_min = self.projection_info.get("x_min")
        x_max = self.projection_info.get("x_max")
        y_min = self.projection_info.get("y_min")
        y_max = self.projection_info.get("y_max")

        xaxis_cfg = dict(
            showgrid=False,
            zeroline=False,
            scaleanchor="y",
            scaleratio=1,
            constrain="domain",
            showticklabels=False,
            showline=False,
        )
        yaxis_cfg = dict(
            showgrid=False,
            zeroline=False,
            constrain="domain",
            showticklabels=False,
            showline=False,
        )
        if x_min is not None and x_max is not None:
            xaxis_cfg["range"] = [x_min, x_max]
        if y_min is not None and y_max is not None:
            yaxis_cfg["range"] = [y_min, y_max]

        show_legend = self.style_info.get("show_legend", False)
        legend_title = self.style_info.get("legend_title")
        legend_cfg = dict(
            bgcolor=self.style_info.get(
                "legend_background_color", "rgba(0,0,0,0.5)"
            ),
            font=dict(
                color=self.style_info.get("legend_font_color", "#ffffff"),
                size=max(
                    8,
                    self.style_info.get("legend_font_size", 11)
                    * self._font_pixel_scale()
                    * _KALEIDO_TEXT_SCALE,
                ),
            ),
            bordercolor=self.style_info.get(
                "legend_border_color", "rgba(255,255,255,0.2)"
            ),
            borderwidth=1,
        )
        if legend_title:
            legend_cfg["title"] = dict(
                text=str(legend_title),
                font=dict(
                    color=self.style_info.get("legend_font_color", "#ffffff"),
                    size=max(
                        8,
                        self.style_info.get("legend_title_font_size", 11)
                        * self._font_pixel_scale()
                        * _KALEIDO_TEXT_SCALE,
                    ),
                ),
            )

        self.fig.update_layout(
            plot_bgcolor=bg,
            paper_bgcolor=fig_bg,
            xaxis=xaxis_cfg,
            yaxis=yaxis_cfg,
            hovermode="closest",
            dragmode="pan",
            showlegend=show_legend,
            legend=legend_cfg,
            margin=dict(l=10, r=10, t=30, b=10),
            autosize=False,
        )
        if self.width is not None or self.height is not None:
            self.fig.update_layout(width=self.width, height=self.height)
        self._add_clipped_plot_background(bg)

    def _add_clipped_plot_background(self, background_color):
        """Paint the axes face inside the recorded Matplotlib clip boundary."""
        clip = self._clip_polygons.get("plot")
        if clip is None or clip.is_empty:
            return
        points = list(clip.exterior.coords)
        if len(points) < 4:
            return
        path = f"M {points[0][0]},{points[0][1]}"
        path += "".join(f" L {x},{y}" for x, y in points[1:])
        path += " Z"
        self.fig.update_layout(plot_bgcolor="rgba(0,0,0,0)")
        self.fig.add_shape(
            type="path",
            path=path,
            xref="x",
            yref="y",
            fillcolor=background_color,
            line=dict(width=0),
            layer="below",
        )

    # ------------------------------------------------------------------
    # Scatter (stars, markers, DSOs)
    # ------------------------------------------------------------------

    def _should_show_legend_entry(self, label, gid):
        """Use Matplotlib's final de-duplicated legend labels when available."""
        if not self.fig.layout.showlegend:
            return False
        explicit_labels = self.style_info.get("legend_labels")
        if explicit_labels is not None:
            if label not in explicit_labels or label in self._shown_legend_labels:
                return False
            self._shown_legend_labels.add(label)
            return True
        return (
            label is not None or gid in _KNOWN_LEGEND_GIDS
        ) and gid not in self._trace_groups

    def _render_scatter(self, cmd: DrawingCommand):
        point_count = len(cmd.data.get("x", []))
        high_volume = point_count > _MAX_INTERACTIVE_HOVER_POINTS
        has_hover = (
            point_count <= _MAX_INTERACTIVE_HOVER_POINTS
            and bool(cmd.metadata)
        )
        hover_texts = self._build_hover_texts(cmd.metadata) if has_hover else None
        colors = _sanitize_colors(cmd.data.get("colors", []))
        alphas = cmd.data.get("alphas", [1.0])
        sizes_raw = cmd.data.get("sizes", [])
        resolution = self.style_info.get("resolution", 4096)
        theoretical_sizes = [
            calibrate_marker_size(
                s,
                resolution=resolution,
                width=self._target_axes_width(),
                dpi=self.style_info.get("dpi", 100.0),
                source_axes_width=self.style_info.get("source_axes_width"),
                min_size=0.0 if high_volume else 1.5,
            ) * _KALEIDO_MARKER_SCALE
            for s in sizes_raw
        ]
        if high_volume:
            # WebGL rasterizes every point to at least one physical pixel.
            # Preserve Matplotlib's subpixel area by moving the fractional
            # coverage into alpha instead of inflating every faint star.
            coverage = [
                min(1.0, size * size * _WEBGL_SUBPIXEL_COVERAGE_SCALE)
                for size in theoretical_sizes
            ]
            sizes = [max(1.0, size) for size in theoretical_sizes]
            if np.isscalar(alphas):
                alpha_values = [float(alphas)] * point_count
            else:
                alpha_values = [float(alpha) for alpha in alphas]
                if len(alpha_values) < point_count:
                    fallback = alpha_values[-1] if alpha_values else 1.0
                    alpha_values.extend(
                        [fallback] * (point_count - len(alpha_values))
                    )
            alphas = [
                float(alpha) * factor
                for alpha, factor in zip(alpha_values, coverage)
            ]
        else:
            sizes = theoretical_sizes

        edge_color = _sanitize_color(cmd.style.get("edge_color", "rgba(0,0,0,0)"))
        edge_width = 0 if high_volume else (cmd.style.get("edge_width", 0) or 0)

        # Determine marker fill color: if fill is none or colors are transparent,
        # use a transparent fill so only the outline is visible.
        fill = str(cmd.style.get("fill", "")).lower()
        if fill == "none" or _is_transparent_color(colors):
            marker_color = "rgba(0,0,0,0)"
        else:
            marker_color = _colors_with_alphas(colors, alphas, len(cmd.data.get("x", [])))

        legend_label = cmd.style.get("legend_label")
        name = legend_label if legend_label is not None else self._gid_to_legend_name(cmd.gid)
        show_legend_trace = self._should_show_legend_entry(
            legend_label if legend_label is not None else name,
            cmd.gid,
        )

        trace_type = (
            go.Scattergl
            if cmd.gid == "stars" or len(cmd.data.get("x", [])) > 1000
            else go.Scatter
        )
        self.fig.add_trace(trace_type(
            x=cmd.data.get("x"),
            y=cmd.data.get("y"),
            mode="markers",
            marker=dict(
                size=sizes,
                color=marker_color,
                opacity=1.0,
                symbol=MARKER_SYMBOL_MAP.get(cmd.style.get("symbol", "circle"), "circle"),
                line=dict(
                    color=edge_color,
                    width=edge_width * self._stroke_pixel_scale(),
                ),
            ),
            text=hover_texts,
            hoverinfo="text" if has_hover else "skip",
            name=name,
            legendgroup=cmd.gid,
            showlegend=show_legend_trace,
        ))
        self._trace_groups.setdefault(cmd.gid, []).append(len(self.fig.data) - 1)

    # ------------------------------------------------------------------
    # Line collection (constellation lines)
    # ------------------------------------------------------------------

    def _render_line_collection(self, cmd: DrawingCommand):
        x_all, y_all, hover_all = [], [], []
        for i, seg in enumerate(cmd.data.get("lines", [])):
            for pt in seg:
                x_all.append(pt[0])
                y_all.append(pt[1])
                meta = cmd.metadata[i] if i < len(cmd.metadata) else {}
                hover_all.append(meta.get("name", ""))
            # None separator between segments
            x_all.append(None)
            y_all.append(None)
            hover_all.append(None)

        line_style = cmd.style.get("line_style", "solid")
        if isinstance(line_style, (list, tuple)):
            dash = "solid"
        else:
            dash = LINE_STYLE_MAP.get(str(line_style), "solid")

        self.fig.add_trace(go.Scattergl(
            x=x_all,
            y=y_all,
            mode="lines",
            line=dict(
                color=_sanitize_color(cmd.style.get("color", "#aaaaaa")),
                width=max(0.25, cmd.style.get("width", 1) * self._stroke_pixel_scale()),
                dash=dash,
            ),
            opacity=cmd.style.get("alpha", 1.0),
            text=hover_all,
            hoverinfo="text",
            name=self._gid_to_legend_name(cmd.gid),
            legendgroup=cmd.gid,
            showlegend=self._should_show_legend_entry(
                self._gid_to_legend_name(cmd.gid), cmd.gid
            ),
        ))
        self._trace_groups.setdefault(cmd.gid, []).append(len(self.fig.data) - 1)

    # ------------------------------------------------------------------
    # Polygon (milky way, DSO outlines, custom shapes)
    # ------------------------------------------------------------------

    def _render_polygon(self, cmd: DrawingCommand):
        rings = cmd.data.get("rings") or [cmd.data.get("points", [])]
        rings = [ring for ring in rings if len(ring) >= 3]
        if not rings:
            return
        raw_fill = cmd.style.get("fill_color")
        has_fill = raw_fill is not None and (
            not isinstance(raw_fill, str) or raw_fill.lower() not in _MATPLOTLIB_NONE_COLORS
        )
        fill_color = _sanitize_color(raw_fill)
        edge_color = _sanitize_color(cmd.style.get("edge_color", "rgba(0,0,0,0)"))
        edge_width = cmd.style.get("edge_width", 0) or 0
        alpha = cmd.style.get("alpha", 1.0)
        xref = cmd.style.get("xref", "x")
        yref = cmd.style.get("yref", "y")
        is_paper = xref == "paper" and yref == "paper"

        if is_paper:
            # Use a Plotly shape for axes/paper-coordinate polygons (e.g. the
            # HorizonPlot bottom bar and arrow polygons).
            def _build_path(pts):
                if not pts:
                    return ""
                path = f"M {self._paper_x(pts[0][0])},{self._paper_y(pts[0][1], cmd.gid, cmd.style)}"
                for x, y in pts[1:]:
                    path += f" L {self._paper_x(x)},{self._paper_y(y, cmd.gid, cmd.style)}"
                path += " Z"
                return path

            for points in rings:
                self.fig.add_shape(
                    type="path",
                    path=_build_path(points),
                    xref="paper",
                    yref="paper",
                    fillcolor=fill_color if has_fill else "rgba(0,0,0,0)",
                    line=dict(
                        color=edge_color,
                        width=edge_width * self._stroke_pixel_scale(),
                    ),
                    opacity=alpha,
                )
        else:
            for points in rings:
                x = [p[0] for p in points] + [points[0][0]]
                y = [p[1] for p in points] + [points[0][1]]
                self.fig.add_trace(go.Scatter(
                    x=x,
                    y=y,
                    mode="lines",
                    fill="toself" if has_fill else None,
                    fillcolor=fill_color,
                    line=dict(
                        color=edge_color,
                        width=max(0, edge_width * self._stroke_pixel_scale()),
                    ),
                    opacity=alpha,
                    hoverinfo="none",
                    legendgroup=cmd.gid,
                    showlegend=False,
                ))

    # ------------------------------------------------------------------
    # Text annotation
    # ------------------------------------------------------------------

    def _render_text(self, cmd: DrawingCommand):
        va = cmd.style.get("va", "center")
        ha = cmd.style.get("ha", "center")
        yanchor, xanchor = ANCHOR_MAP.get((va, ha), ("middle", "center"))
        # Horizontal alignment is defined in screen space.  Reversing the
        # data axis changes where the anchor is drawn, not which direction
        # the glyphs extend from it.
        xanchor = {"left": "left", "right": "right", "center": "center"}.get(
            ha, "center"
        )
        coordinate_refs = {
            CoordinateSpace.DATA: ("x", "y"),
            CoordinateSpace.AXES: ("x domain", "y domain"),
            CoordinateSpace.PAPER: ("paper", "paper"),
        }
        xref, yref = coordinate_refs[cmd.space]

        # Convert the final Matplotlib point offset into target CSS pixels.
        # It must use the same source→target scale as the font itself; using
        # source DPI alone exaggerates collision-handler placements when a
        # 4096px source chart is replayed into a 1000px Plotly viewport.
        offset_points = cmd.data.get("offset_points", (0.0, 0.0))
        point_scale = self._font_pixel_scale()
        xshift = offset_points[0] * point_scale
        yshift = offset_points[1] * point_scale

        # Apply any explicit xshift/yshift from style (overrides offset)
        xshift = cmd.style.get("xshift", xshift)
        yshift = cmd.style.get("yshift", yshift)

        rotation = cmd.style.get("rotation", 0.0)
        # Plotly annotations render HTML line breaks, while a literal newline
        # is collapsed to whitespace.  Preserve Matplotlib's multiline labels.
        text = str(cmd.data.get("text", "")).replace("\n", "<br>")

        font = dict(
            size=max(
                8,
                cmd.style.get("font_size", 12)
                * self._font_pixel_scale()
                * _KALEIDO_TEXT_SCALE,
            ),
            color=_sanitize_color(cmd.style.get("font_color", "#ffffff")),
            family=_font_family(cmd.style.get("font_name")),
        )
        # Plotly's current annotation font schema supports CSS weights.  Keep
        # this conditional for older versions that do not expose the property.
        if "weight" in go.layout.annotation.Font()._valid_props:
            weight = cmd.style.get("font_weight", "normal")
            if isinstance(weight, str):
                weight = {"normal": 400, "bold": 700}.get(weight.lower(), 400)
            font["weight"] = weight
        else:
            weight = cmd.style.get("font_weight", "normal")

        # Kaleido's Plotly annotation backend can ignore ``font.weight`` for
        # locally installed fonts.  Its HTML text parser reliably preserves a
        # Matplotlib bold label, including in static PNG export.
        if weight == "bold" or (isinstance(weight, (int, float)) and weight >= 600):
            text = f"<b>{text}</b>"
            # Plotly/Kaleido versions that accept ``font.weight`` still do
            # not consistently select the bold face for a locally resolved
            # family.  Put a widely available bold face first so static PNG
            # output retains the source label hierarchy.
            font["family"] = "Arial Black, Arial, sans-serif"

        self.fig.add_annotation(
            x=(self._paper_x(cmd.data.get("x")) if xref == "paper" else cmd.data.get("x")),
            y=(
                self._paper_y(cmd.data.get("y"), cmd.gid, cmd.style)
                if yref == "paper"
                else cmd.data.get("y")
            ),
            text=text,
            showarrow=False,
            font=font,
            xanchor=xanchor,
            yanchor=yanchor,
            xshift=xshift,
            yshift=yshift,
            textangle=rotation,
            xref=xref,
            yref=yref,
            opacity=cmd.style.get("font_alpha", cmd.style.get("alpha", 1.0)),
        )

    # ------------------------------------------------------------------
    # Line (ecliptic, celestial equator, custom lines)
    # ------------------------------------------------------------------

    def _render_line(self, cmd: DrawingCommand):
        style = cmd.style
        line_style = style.get("line_style", "solid")
        if isinstance(line_style, (list, tuple)):
            dash = "solid"
        else:
            dash = LINE_STYLE_MAP.get(str(line_style), "solid")

        # Matplotlib lines with clip_on=False are decorations outside the
        # data viewport (for example the Zenith horizon ring).  A Plotly
        # layout shape preserves that unclipped contract and remains below
        # layout annotations; a trace can obscure annotations across the
        # SVG/WebGL layer boundary even when its command zorder is lower.
        if cmd.clip_id is None:
            path_parts = []
            drawing = False
            for x, y in zip(cmd.data.get("x", []), cmd.data.get("y", [])):
                if x is None or y is None:
                    drawing = False
                    continue
                path_parts.append(f"{'L' if drawing else 'M'} {x},{y}")
                drawing = True
            if path_parts:
                self.fig.add_shape(
                    type="path",
                    path=" ".join(path_parts),
                    xref="x",
                    yref="y",
                    line=dict(
                        color=_sanitize_color(style.get("color", "#777777")),
                        width=max(
                            0.25,
                            style.get("width", 1) * self._stroke_pixel_scale(),
                        ),
                        dash=dash,
                    ),
                    opacity=style.get("alpha", 1.0),
                    layer="above",
                )
            return

        # A single Matplotlib Line2D is an SVG-layer artist.  Keep it on
        # Plotly's SVG layer as well so annotations and shapes obey the same
        # visual stacking order.  Scattergl's canvas can cover annotations
        # even when their zorder is higher (notably Zenith cardinal labels).
        self.fig.add_trace(go.Scatter(
            x=cmd.data.get("x"),
            y=cmd.data.get("y"),
            mode="lines",
            line=dict(
                color=_sanitize_color(style.get("color", "#777777")),
                width=max(0.25, style.get("width", 1) * self._stroke_pixel_scale()),
                dash=dash,
            ),
            opacity=style.get("alpha", 1.0),
            hoverinfo="none",
            name=self._gid_to_legend_name(cmd.gid),
            legendgroup=cmd.gid,
            showlegend=self._should_show_legend_entry(
                self._gid_to_legend_name(cmd.gid), cmd.gid
            ),
        ))
        self._trace_groups.setdefault(cmd.gid, []).append(len(self.fig.data) - 1)

    # ------------------------------------------------------------------
    # Gradient (first version: skip rendering, use solid background)
    # ------------------------------------------------------------------

    def _render_gradient(self, cmd: DrawingCommand):
        color_stops = [
            [float(s[0]), str(s[1])]
            for s in self._normalize_color_stops(cmd.data.get("color_stops", []))
        ]
        if len(color_stops) < 2:
            return

        x_min = self.projection_info.get("x_min")
        x_max = self.projection_info.get("x_max")
        y_min = self.projection_info.get("y_min")
        y_max = self.projection_info.get("y_max")
        if None in (x_min, x_max, y_min, y_max):
            return

        direction = str(cmd.data.get("direction", "linear")).lower()

        # Plotly has no native gradient plot background. We render one as a low-z
        # heatmap in the chart coordinate system so it aligns with axis bounds.
        if direction == "radial":
            # Mirror GradientBackgroundMixin: radial stop positions divide by
            # two with final position one; colors reverse; value is radius^2.
            # Center (r=0) → z=1.0 (last color stop), edge (r=1) → z=0.0.
            steps = 220
            xs = np.linspace(float(x_min), float(x_max), steps)
            ys = np.linspace(float(y_min), float(y_max), steps)
            xx, yy = np.meshgrid(xs, ys)
            # Use the recorded center and radius if available
            center = cmd.data.get("center")
            if center is not None:
                cx, cy = float(center[0]), float(center[1])
            else:
                cx = (float(x_min) + float(x_max)) / 2.0
                cy = (float(y_min) + float(y_max)) / 2.0
            radius = cmd.data.get("radius")
            if radius is not None:
                r = float(radius)
            elif cmd.clip_id in self._clip_polygons:
                clip_x0, clip_y0, clip_x1, clip_y1 = self._clip_polygons[
                    cmd.clip_id
                ].bounds
                cx = (clip_x0 + clip_x1) / 2.0
                cy = (clip_y0 + clip_y1) / 2.0
                r = min(clip_x1 - clip_x0, clip_y1 - clip_y0) / 2.0
            else:
                r = max(abs(float(x_max) - cx), abs(float(y_max) - cy))
            rx = max(r, 1e-9)
            ry = max(r, 1e-9)

            rr = ((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2
            z = np.where(rr <= 1.0, rr, np.nan)

            # Match GradientBackgroundMixin._create_colormap exactly:
            # radial positions are halved (except the final stop, which stays
            # at one) and the resulting Matplotlib colormap is reversed.
            radial_positions = [float(stop[0]) / 2.0 for stop in color_stops]
            radial_positions[-1] = 1.0
            color_stops = [
                [1.0 - radial_positions[index], color_stops[index][1]]
                for index in reversed(range(len(color_stops)))
            ]
        else:
            # Linear gradients in starplot go from stop=0 at the bottom to stop=1 at the top.
            # Use a two-column heatmap so zsmooth works in both directions, matching
            # matplotlib's gouraud shading. y values are cell centers for 2000 rows and
            # x values are cell centers for 2 columns; zsmooth fills the axis range.
            steps = 2000
            ys = np.linspace(float(y_min), float(y_max), steps)
            z = np.linspace(0.0, 1.0, steps, dtype=float).reshape(-1, 1)
            z = np.repeat(z, 2, axis=1)

        self.fig.add_trace(go.Heatmap(
            x=xs if direction == "radial" else [float(x_min), float(x_max)],
            y=ys.tolist(),
            z=z.tolist(),
            colorscale=color_stops,
            showscale=False,
            hoverinfo="skip",
            zsmooth="best" if direction == "radial" else False,
            zmin=0.0,
            zmax=1.0,
            showlegend=False,
            name="",
        ))

    # ------------------------------------------------------------------
    # Interactive features
    # ------------------------------------------------------------------

    def _render_info_table(self, cmd: DrawingCommand):
        columns = [str(c) for c in cmd.data.get("columns", [])]
        values = [str(v) for v in cmd.data.get("values", [])]
        count = min(len(columns), len(values))
        if count <= 0:
            return

        raw_widths = list(cmd.data.get("widths", []))[:count]
        parsed_widths = []
        for w in raw_widths:
            try:
                parsed_widths.append(max(0.0, float(w)))
            except Exception:
                parsed_widths.append(0.0)
        if len(parsed_widths) < count:
            parsed_widths.extend([1.0] * (count - len(parsed_widths)))

        total = sum(parsed_widths)
        if total <= 0:
            widths = [1.0 / count] * count
        else:
            widths = [w / total for w in parsed_widths]

        style = cmd.style
        font_color = style.get("font_color", "#111111")
        font_name = _font_family(style.get("font_name"))
        font_alpha = float(style.get("font_alpha", 1.0))
        base_size = float(style.get("font_size", 12))
        font_scale = self._font_pixel_scale()
        header_size = max(11, base_size * 1.2 * font_scale)
        value_size = max(10, base_size * font_scale)
        bg_color = style.get(
            "background_color",
            self.style_info.get("figure_background_color", "#ffffff"),
        )
        line_color = style.get("line_color", "#999999")

        margin = self.fig.layout.margin
        self.fig.update_layout(
            margin=dict(
                l=margin.l if margin.l is not None else 10,
                r=margin.r if margin.r is not None else 10,
                t=margin.t if margin.t is not None else 30,
                b=max(margin.b if margin.b is not None else 10, 105),
            )
        )

        table_top = -0.01
        header_y = -0.03
        value_y = -0.068
        table_bottom = -0.09

        self.fig.add_shape(
            type="rect",
            xref="paper",
            yref="paper",
            x0=0,
            x1=1,
            y0=table_bottom,
            y1=table_top,
            line=dict(color=line_color, width=1),
            fillcolor=bg_color,
            layer="above",
        )

        x_left = 0.0
        for idx in range(count):
            width = widths[idx]
            x_right = x_left + width
            x_center = (x_left + x_right) / 2.0

            if idx > 0:
                self.fig.add_shape(
                    type="line",
                    xref="paper",
                    yref="paper",
                    x0=x_left,
                    x1=x_left,
                    y0=table_bottom,
                    y1=table_top,
                    line=dict(color=line_color, width=1),
                    layer="above",
                )

            self.fig.add_annotation(
                x=x_center,
                y=header_y,
                xref="paper",
                yref="paper",
                text=f"<b>{columns[idx]}</b>",
                showarrow=False,
                xanchor="center",
                yanchor="middle",
                font=dict(size=header_size, color=font_color, family=font_name),
                opacity=font_alpha,
            )
            self.fig.add_annotation(
                x=x_center,
                y=value_y,
                xref="paper",
                yref="paper",
                text=values[idx],
                showarrow=False,
                xanchor="center",
                yanchor="middle",
                font=dict(size=value_size, color=font_color, family=font_name),
                opacity=font_alpha,
            )

            x_left = x_right

    def _add_interactive_features(self):
        magnitude_scale = self.style_info.get("magnitude_scale")
        if self.fig.layout.showlegend and magnitude_scale:
            labels = magnitude_scale.get("labels", [])
            sizes = magnitude_scale.get("sizes", [])
            for index, (label, size) in enumerate(zip(labels, sizes)):
                self.fig.add_trace(go.Scatter(
                    x=[None],
                    y=[None],
                    mode="markers",
                    marker=dict(
                        symbol="circle",
                        size=max(
                            1.5,
                            float(size)
                            * self._font_pixel_scale()
                            * _KALEIDO_MARKER_SCALE,
                        ),
                        color=magnitude_scale.get("color", "#000000"),
                        line=dict(
                            color=magnitude_scale.get("edge_color", "#000000"),
                            width=0,
                        ),
                    ),
                    name=str(label),
                    legendgroup="star-magnitude-scale",
                    legendgrouptitle_text=(
                        str(magnitude_scale.get("title", "Star Magnitude"))
                        if index == 0 else None
                    ),
                    legendrank=2000 + index,
                    showlegend=True,
                    hoverinfo="skip",
                ))
        self.fig.update_layout(
            modebar=dict(
                add=["zoom", "pan", "select", "lasso2d", "resetScale2d"],
            ),
            clickmode="event+select",
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_color_stops(raw_stops) -> list[list]:
        stops = []
        for stop in raw_stops:
            pos = None
            color = None

            if isinstance(stop, (list, tuple)) and len(stop) == 2:
                pos, color = stop
            elif isinstance(stop, dict):
                pos = stop.get("position")
                color = stop.get("color")

            if pos is None or color is None:
                continue

            try:
                p = float(pos)
            except Exception:
                continue

            if hasattr(color, "as_hex"):
                c = color.as_hex()
            else:
                c = str(color)

            stops.append([min(1.0, max(0.0, p)), c])

        if not stops:
            return []

        stops.sort(key=lambda s: s[0])
        if stops[0][0] > 0:
            stops.insert(0, [0.0, stops[0][1]])
        if stops[-1][0] < 1:
            stops.append([1.0, stops[-1][1]])

        return stops

    def _build_hover_texts(self, metadata: list) -> list[str]:
        texts = []
        for meta in metadata:
            t = meta.get("type", "")
            if t == "star":
                name = meta.get("name") or ""
                mag = meta.get("magnitude")
                ra = meta.get("ra")
                dec = meta.get("dec")
                bayer = meta.get("bayer") or ""
                const = meta.get("constellation") or ""
                parts = [f"<b>{name}</b>"] if name else []
                if bayer:
                    parts.append(bayer)
                if mag is not None:
                    parts.append(f"Magnitude: {mag:.2f}" if isinstance(mag, float) else f"Magnitude: {mag}")
                if ra is not None and dec is not None:
                    parts.append(f"RA: {ra/15:.4f}h  DEC: {dec:.4f}°")
                if const:
                    parts.append(f"Constellation: {const}")
                texts.append("<br>".join(parts) if parts else "")
            elif t == "dso":
                name = meta.get("name") or "DSO"
                parts = [f"<b>{name}</b>"]
                if meta.get("dso_type"):
                    parts.append(f"Type: {meta['dso_type']}")
                if meta.get("magnitude") is not None:
                    parts.append(f"Magnitude: {meta['magnitude']:.1f}")
                ra = meta.get("ra")
                dec = meta.get("dec")
                if ra is not None and dec is not None:
                    parts.append(f"RA: {ra/15:.4f}h  DEC: {dec:.4f}°")
                texts.append("<br>".join(parts))
            elif t == "planet":
                name = meta.get("name") or "Planet"
                parts = [f"<b>{name}</b>"]
                if meta.get("magnitude") is not None:
                    parts.append(f"Magnitude: {meta['magnitude']:.2f}")
                texts.append("<br>".join(parts))
            else:
                texts.append("")
        return texts

    @staticmethod
    def _gid_to_legend_name(gid: str) -> str:
        return {
            "stars": "Stars",
            "constellations-line": "Constellations",
            "constellations-border": "Borders",
            "constellations-label-name": "Labels",
            "ecliptic-line": "Ecliptic",
            "celestial-equator-line": "Celestial Equator",
            "planet-marker": "Planets",
            "moon-marker": "Moon",
            "sun-marker": "Sun",
            "marker": "Markers",
            "dso": "DSOs",
            "dso_galaxy": "Galaxies",
            "dso_nebula": "Nebulae",
            "dso_open_cluster": "Open Clusters",
            "dso_globular_cluster": "Globular Clusters",
        }.get(gid, gid.replace("-", " ").replace("_", " ").title())
