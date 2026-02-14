"""PlotlyRenderer — replays DrawingCommands as a Plotly Figure."""

try:
    import plotly.graph_objects as go
except ImportError as e:
    raise ImportError(
        "plotly is required for interactive export. "
        "Install it with: pip install starplot[interactive]"
    ) from e

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
            showticklabels=False,
            showline=False,
        )
        yaxis_cfg = dict(
            showgrid=False,
            zeroline=False,
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
            showlegend=True,
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
        # V1: gradient is approximated by the plot's background_color.
        # A full gradient implementation would use Heatmap or layered shapes.
        pass

    # ------------------------------------------------------------------
    # Interactive features
    # ------------------------------------------------------------------

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
