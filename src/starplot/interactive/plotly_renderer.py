"""PlotlyRenderer — replays DrawingCommands as a Plotly Figure."""

try:
    import plotly.graph_objects as go
except ImportError as e:
    raise ImportError(
        "plotly is required for interactive export. "
        "Install it with: pip install starplot[interactive]"
    ) from e

import numpy as np

from starplot.interactive.commands import DrawingCommand
from starplot.interactive.style_converter import (
    MARKER_SYMBOL_MAP,
    LINE_STYLE_MAP,
    ANCHOR_MAP,
    calibrate_marker_size,
)


class PlotlyRenderer:
    """Renders a list of DrawingCommands into a Plotly Figure."""

    def __init__(self, projection_info: dict, style_info: dict):
        self.projection_info = projection_info
        self.style_info = style_info
        self._trace_groups: dict[str, list[int]] = {}
        self.fig = go.Figure()
        self._setup_layout()

    def render(self, commands: list[DrawingCommand]) -> go.Figure:
        """Render all commands sorted by zorder."""
        for cmd in sorted(commands, key=lambda c: c.zorder):
            handler = {
                "scatter": self._render_scatter,
                "line": self._render_line,
                "polygon": self._render_polygon,
                "text": self._render_text,
                "line_collection": self._render_line_collection,
                "gradient": self._render_gradient,
                "info_table": self._render_info_table,
            }.get(cmd.kind)
            if handler:
                try:
                    handler(cmd)
                except Exception:
                    pass  # Silently skip rendering errors to not break the whole export
        self._add_interactive_features()
        return self.fig

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _setup_layout(self):
        bg = self.style_info.get("background_color", "#ffffff")
        fig_bg = self.style_info.get("figure_background_color", "#ffffff")

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

        self.fig.update_layout(
            plot_bgcolor=bg,
            paper_bgcolor=fig_bg,
            xaxis=xaxis_cfg,
            yaxis=yaxis_cfg,
            hovermode="closest",
            dragmode="pan",
            showlegend=False,
            legend=dict(
                bgcolor="rgba(0,0,0,0.5)",
                font=dict(color="#ffffff", size=11),
                bordercolor="rgba(255,255,255,0.2)",
                borderwidth=1,
            ),
            margin=dict(l=10, r=10, t=30, b=10),
        )

    # ------------------------------------------------------------------
    # Scatter (stars, markers, DSOs)
    # ------------------------------------------------------------------

    def _render_scatter(self, cmd: DrawingCommand):
        hover_texts = self._build_hover_texts(cmd.metadata)
        colors = cmd.data.get("colors", [])
        alphas = cmd.data.get("alphas", [1.0])
        sizes_raw = cmd.data.get("sizes", [])
        resolution = self.style_info.get("resolution", 4096)
        sizes = [calibrate_marker_size(s, resolution=resolution) for s in sizes_raw]

        # Per-point alpha via rgba string if needed
        # For simplicity use the first alpha value for the whole trace
        alpha = alphas[0] if isinstance(alphas, (list, tuple)) and alphas else alphas if isinstance(alphas, (int, float)) else 1.0

        self.fig.add_trace(go.Scattergl(
            x=cmd.data.get("x"),
            y=cmd.data.get("y"),
            mode="markers",
            marker=dict(
                size=sizes,
                color=colors,
                opacity=float(alpha),
                symbol=MARKER_SYMBOL_MAP.get(cmd.style.get("symbol", "circle"), "circle"),
                line=dict(
                    color=cmd.style.get("edge_color", "rgba(0,0,0,0)"),
                    width=cmd.style.get("edge_width", 0) * 0.3,
                ),
            ),
            text=hover_texts,
            hoverinfo="text",
            name=self._gid_to_legend_name(cmd.gid),
            legendgroup=cmd.gid,
            showlegend=cmd.gid not in self._trace_groups,
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

        self.fig.add_trace(go.Scattergl(
            x=x_all,
            y=y_all,
            mode="lines",
            line=dict(
                color=cmd.style.get("color", "#aaaaaa"),
                width=max(0.5, cmd.style.get("width", 1) * 0.3),
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
        x = [p[0] for p in points] + [points[0][0]]
        y = [p[1] for p in points] + [points[0][1]]
        fill_color = cmd.style.get("fill_color")
        self.fig.add_trace(go.Scatter(
            x=x,
            y=y,
            mode="lines",
            fill="toself" if fill_color else None,
            fillcolor=fill_color,
            line=dict(
                color=cmd.style.get("edge_color", "rgba(0,0,0,0)"),
                width=max(0, cmd.style.get("edge_width", 0) * 0.3),
            ),
            opacity=cmd.style.get("alpha", 1.0),
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
        self.fig.add_annotation(
            x=cmd.data.get("x"),
            y=cmd.data.get("y"),
            text=cmd.data.get("text", ""),
            showarrow=False,
            font=dict(
                size=max(8, cmd.style.get("font_size", 12) * 0.4),
                color=cmd.style.get("font_color", "#ffffff"),
                family=cmd.style.get("font_name", "Inter, Arial, sans-serif"),
            ),
            xanchor=xanchor,
            yanchor=yanchor,
            opacity=cmd.style.get("alpha", 1.0),
        )

    # ------------------------------------------------------------------
    # Line (ecliptic, celestial equator, custom lines)
    # ------------------------------------------------------------------

    def _render_line(self, cmd: DrawingCommand):
        style = cmd.style
        self.fig.add_trace(go.Scattergl(
            x=cmd.data.get("x"),
            y=cmd.data.get("y"),
            mode="lines",
            line=dict(
                color=style.get("color", "#777777"),
                width=max(0.5, style.get("width", 1) * 0.3),
                dash=LINE_STYLE_MAP.get(str(style.get("line_style", "solid")), "solid"),
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
        color_stops = self._normalize_color_stops(cmd.data.get("color_stops", []))
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
            steps = 600
            ys = np.linspace(float(y_min), float(y_max), steps)
            z = np.linspace(0.0, 1.0, steps, dtype=float).reshape(-1, 1)
            z = np.repeat(z, 2, axis=1)

        self.fig.add_trace(go.Heatmap(
            x=[float(x_min), float(x_max)],
            y=ys,
            z=z,
            colorscale=color_stops,
            showscale=False,
            hoverinfo="skip",
            zsmooth="best",
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
        font_name = style.get("font_name", "Inter, Arial, sans-serif")
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
