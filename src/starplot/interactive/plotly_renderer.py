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
    if isinstance(colors, (list, tuple)):
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
    if isinstance(colors, (list, tuple)):
        color_values = list(colors)
    else:
        color_values = [colors] * count

    if isinstance(alphas, (list, tuple)):
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
            opacity = base_alpha * float(alpha)
            result.append(
                f"rgba({round(red * 255)},{round(green * 255)},{round(blue * 255)},{opacity:g})"
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
        self.transparent = transparent
        self._trace_groups: dict[str, list[int]] = {}
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

        new_data = {
            "x": [x for x, m in zip(xs, mask) if m],
            "y": [y for y, m in zip(ys, mask) if m],
            "sizes": [s for s, m in zip(sizes, mask) if m] if sizes else [],
            "colors": [c for c, m in zip(colors, mask) if m] if isinstance(colors, list) else colors,
            "alphas": [a for a, m in zip(alphas, mask) if m] if isinstance(alphas, list) else alphas,
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
        points = cmd.data.get("points", [])
        if len(points) < 3:
            return cmd
        try:
            poly = ShapelyPolygon(points)
            clipped = poly.intersection(clip_poly)
            if clipped.is_empty:
                return None
            # Extract exterior coordinates
            if hasattr(clipped, 'exterior'):
                new_points = list(clipped.exterior.coords)
            elif hasattr(clipped, 'geoms'):
                # MultiPolygon — use the largest
                largest = max(clipped.geoms, key=lambda g: g.area)
                new_points = list(largest.exterior.coords)
            else:
                return cmd
            # Remove closing point if present
            if len(new_points) > 1 and new_points[0] == new_points[-1]:
                new_points = new_points[:-1]
            return DrawingCommand(
                kind=cmd.kind, data={"points": new_points}, style=cmd.style,
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
                    LOGGER.warning(
                        "Failed to render %s command (gid=%s): %s: %s",
                        clipped.kind, clipped.gid, type(e).__name__, e,
                    )
        self._add_interactive_features()
        return self.fig

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
            self._side_margin = 50
            self.fig.update_layout(margin=dict(l=50, r=50, t=30, b=10))

    def _paper_y(self, value, gid, style=None):
        """Translate the HorizonPlot footer from negative axes space into paper."""
        if gid in {"horizon-bottom", "horizon-label"} or (style or {}).get("footer"):
            return value + self._horizon_footer_offset
        return value

    def _target_axes_width(self):
        """Return the drawable Plotly width after the fixed side margins."""
        return max(1.0, self._marker_viewport_width - 2.0 * self._side_margin)

    def _style_pixel_scale(self):
        """Convert recorded Matplotlib point-based style units into Plotly pixels."""
        source_width = self.style_info.get("source_axes_width")
        if not source_width:
            return 0.5
        return (
            float(self.style_info.get("plot_scale", 1.0))
            * float(self.style_info.get("dpi", 100.0))
            / 72.0
            * self._target_axes_width()
            / float(source_width)
        )

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _setup_layout(self):
        bg = self.style_info.get("background_color", "#ffffff")
        fig_bg = self.style_info.get("figure_background_color", "#ffffff")

        # When transparent=True, match matplotlib's transparent=True export:
        # only the paper (figure) background becomes transparent, while the
        # plot (axes) background keeps its color.  This matches matplotlib's
        # behavior where transparent=True affects the figure facecolor but
        # not the axes facecolor.
        if self.transparent:
            fig_bg = "rgba(255,255,255,0)"

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
            bgcolor="rgba(0,0,0,0.5)",
            font=dict(color="#ffffff", size=11),
            bordercolor="rgba(255,255,255,0.2)",
            borderwidth=1,
        )
        if legend_title:
            legend_cfg["title"] = dict(text=str(legend_title), font=dict(color="#ffffff"))

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

    # ------------------------------------------------------------------
    # Scatter (stars, markers, DSOs)
    # ------------------------------------------------------------------

    def _render_scatter(self, cmd: DrawingCommand):
        hover_texts = self._build_hover_texts(cmd.metadata)
        colors = _sanitize_colors(cmd.data.get("colors", []))
        alphas = cmd.data.get("alphas", [1.0])
        sizes_raw = cmd.data.get("sizes", [])
        resolution = self.style_info.get("resolution", 4096)
        sizes = [
            calibrate_marker_size(
                s,
                resolution=resolution,
                width=self._target_axes_width(),
                dpi=self.style_info.get("dpi", 100.0),
                source_axes_width=self.style_info.get("source_axes_width"),
            )
            for s in sizes_raw
        ]

        edge_color = _sanitize_color(cmd.style.get("edge_color", "rgba(0,0,0,0)"))
        edge_width = cmd.style.get("edge_width", 0) or 0

        # Determine marker fill color: if fill is none or colors are transparent,
        # use a transparent fill so only the outline is visible.
        fill = str(cmd.style.get("fill", "")).lower()
        if fill == "none" or _is_transparent_color(colors):
            marker_color = "rgba(0,0,0,0)"
        else:
            marker_color = _colors_with_alphas(colors, alphas, len(cmd.data.get("x", [])))

        legend_label = cmd.style.get("legend_label")
        name = legend_label if legend_label is not None else self._gid_to_legend_name(cmd.gid)
        show_legend = self.fig.layout.showlegend
        show_legend_trace = (
            show_legend
            and (legend_label is not None or cmd.gid in _KNOWN_LEGEND_GIDS)
            and cmd.gid not in self._trace_groups
        )

        self.fig.add_trace(go.Scattergl(
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
                    width=edge_width * self._style_pixel_scale(),
                ),
            ),
            text=hover_texts,
            hoverinfo="text",
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
                width=max(0.5, cmd.style.get("width", 1) * self._style_pixel_scale()),
                dash=dash,
            ),
            opacity=cmd.style.get("alpha", 1.0),
            text=hover_all,
            hoverinfo="text",
            name=self._gid_to_legend_name(cmd.gid),
            legendgroup=cmd.gid,
            showlegend=cmd.gid not in self._trace_groups,
        ))
        self._trace_groups.setdefault(cmd.gid, []).append(len(self.fig.data) - 1)

    # ------------------------------------------------------------------
    # Polygon (milky way, DSO outlines, custom shapes)
    # ------------------------------------------------------------------

    def _render_polygon(self, cmd: DrawingCommand):
        points = cmd.data.get("points", [])
        if not points:
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
                path = f"M {pts[0][0]},{self._paper_y(pts[0][1], cmd.gid, cmd.style)}"
                for x, y in pts[1:]:
                    path += f" L {x},{self._paper_y(y, cmd.gid, cmd.style)}"
                path += " Z"
                return path

            path_str = _build_path(points)
            self.fig.add_shape(
                type="path",
                path=path_str,
                xref="paper",
                yref="paper",
                fillcolor=fill_color if has_fill else "rgba(0,0,0,0)",
                line=dict(
                    color=edge_color,
                    width=edge_width * self._style_pixel_scale(),
                ),
                opacity=alpha,
            )
        else:
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
                    width=max(0, edge_width * self._style_pixel_scale()),
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
        xref = cmd.style.get("xref", "x")
        yref = cmd.style.get("yref", "y")

        # Convert offset_points (Matplotlib points) to pixels
        offset_points = cmd.data.get("offset_points", (0.0, 0.0))
        dpi = self.style_info.get("dpi", 100)
        xshift = offset_points[0] / 72.0 * dpi
        yshift = offset_points[1] / 72.0 * dpi

        # Apply any explicit xshift/yshift from style (overrides offset)
        xshift = cmd.style.get("xshift", xshift)
        yshift = cmd.style.get("yshift", yshift)

        rotation = cmd.style.get("rotation", 0.0)

        self.fig.add_annotation(
            x=cmd.data.get("x"),
            y=(
                self._paper_y(cmd.data.get("y"), cmd.gid, cmd.style)
                if yref == "paper"
                else cmd.data.get("y")
            ),
            text=cmd.data.get("text", ""),
            showarrow=False,
            font=dict(
                size=max(8, cmd.style.get("font_size", 12) * self._style_pixel_scale()),
                color=_sanitize_color(cmd.style.get("font_color", "#ffffff")),
                family=_font_family(cmd.style.get("font_name")),
            ),
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
        self.fig.add_trace(go.Scattergl(
            x=cmd.data.get("x"),
            y=cmd.data.get("y"),
            mode="lines",
            line=dict(
                color=_sanitize_color(style.get("color", "#777777")),
                width=max(0.5, style.get("width", 1) * self._style_pixel_scale()),
                dash=dash,
            ),
            opacity=style.get("alpha", 1.0),
            hoverinfo="none",
            name=self._gid_to_legend_name(cmd.gid),
            legendgroup=cmd.gid,
            showlegend=cmd.gid not in self._trace_groups,
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
            steps = 220
            xs = np.linspace(float(x_min), float(x_max), steps)
            ys = np.linspace(float(y_min), float(y_max), steps)
            xx, yy = np.meshgrid(xs, ys)
            cx = (float(x_min) + float(x_max)) / 2.0
            cy = (float(y_min) + float(y_max)) / 2.0
            rx = max(abs(float(x_max) - cx), 1e-9)
            ry = max(abs(float(y_max) - cy), 1e-9)

            rr = np.sqrt(((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2)
            z = np.clip(1.0 - rr, 0.0, 1.0)
            z = np.flipud(z)
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
            zsmooth=False,
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
        header_size = max(11, base_size * 0.55)
        value_size = max(10, base_size * 0.48)
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
                b=max(margin.b if margin.b is not None else 10, 170),
            )
        )

        table_top = -0.01
        header_y = -0.045
        value_y = -0.09
        table_bottom = -0.125

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
