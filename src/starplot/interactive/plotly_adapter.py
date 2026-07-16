"""Plotly 6 adapter for backend-neutral compiled interactive Scenes."""

from __future__ import annotations

from typing import Any

import numpy as np
from shapely.geometry import Polygon
from shapely.ops import polygonize, triangulate, unary_union

try:
    import plotly.graph_objects as go
except ImportError as error:  # pragma: no cover - optional dependency guard
    raise ImportError(
        "plotly is required for interactive export. "
        "Install it with: pip install starplot[interactive]"
    ) from error

from starplot.interactive.commands import CoordinateSpace
from starplot.interactive.scene import (
    CoordinateEncodingKind,
    InteractionPolicy,
    SceneKind,
    SceneLayer,
    ScenePackage,
)
from starplot.interactive.scene_compiler import scatter_clip_mask
from starplot.interactive.style_converter import (
    ANCHOR_MAP,
    LINE_STYLE_MAP,
    MARKER_SYMBOL_MAP,
)


_KALEIDO_MARKER_SCALE = 1.15
_KALEIDO_STROKE_SCALE = 2.0
_MAX_INTERACTIVE_HOVER_POINTS = 100_000
_PLOTLY_MIN_MARKER_DIAMETER = np.float32(1.5)
_SCATTERGL_MIN_MARKER_DIAMETER = np.float32(1.0)
_SCATTERGL_SUBPIXEL_COVERAGE_SCALE = np.float32(6.0)
_MATPLOTLIB_NONE_COLORS = frozenset({"none", "None", "NONE", ""})
_KNOWN_LEGEND_GROUPS = frozenset(
    {
        "stars",
        "constellations-line",
        "constellations-border",
        "constellations-label-name",
        "ecliptic-line",
        "celestial-equator-line",
        "planet-marker",
        "moon-marker",
        "sun-marker",
        "marker",
        "dso",
        "dso_galaxy",
        "dso_nebula",
        "dso_open_cluster",
        "dso_globular_cluster",
    }
)


def _sanitize_color(value, default="rgba(0,0,0,0)") -> str:
    if value is None or (isinstance(value, str) and value in _MATPLOTLIB_NONE_COLORS):
        return default
    if hasattr(value, "as_hex"):
        return value.as_hex()
    return str(value)


def _is_no_color(value) -> bool:
    return value is None or (
        isinstance(value, str) and value in _MATPLOTLIB_NONE_COLORS
    )


def _font_family(value) -> str:
    family = str(value or "Inter")
    return family if "," in family else f"{family}, Arial, sans-serif"


def _group_name(group_id: str) -> str:
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
    }.get(group_id, group_id.replace("-", " ").replace("_", " ").title())


def _discrete_colorscale(palette: tuple[str, ...]) -> list[list[Any]]:
    if not palette:
        return [[0.0, "rgba(0,0,0,0)"], [1.0, "rgba(0,0,0,0)"]]
    if len(palette) == 1:
        return [[0.0, palette[0]], [1.0, palette[0]]]
    scale = []
    count = len(palette)
    for index, color in enumerate(palette):
        left = index / count
        right = (index + 1) / count
        scale.append([left, color])
        scale.append([right, color])
    scale[-1][0] = 1.0
    return scale


class PlotlySceneAdapter:
    """Render a complete :class:`ScenePackage` without DrawingCommand access."""

    def render(self, scene: ScenePackage) -> go.Figure:
        if not isinstance(scene, ScenePackage):
            raise TypeError("scene must be a ScenePackage")
        return _PlotlyRenderContext(scene).render()


class _PlotlyRenderContext:
    """Private one-shot state for one Scene-to-Plotly render."""

    def __init__(self, scene: ScenePackage):
        self.scene = scene
        self.projection_info = scene.projection_info
        self.style_info = scene.style_info
        self.viewport = scene.viewport
        self.fig = go.Figure()
        self._shown_groups: set[str] = set()
        self._shown_legend_labels: set[str] = set()
        self._paper_x_bounds = (0.0, 1.0)
        self._paper_y_bounds = (0.0, 1.0)
        self._horizon_footer_offset = 0.0
        self._side_margin = 10.0

    def render(self) -> go.Figure:
        self._setup_layout()
        self._reserve_scene_space()
        for layer in self.scene.layers:
            self._add_layer(layer)
        self._add_interactive_features()
        return self.fig

    def _add_layer(self, layer: SceneLayer) -> None:
        if layer.kind not in {SceneKind.GRADIENT} and layer.data.row_count == 0:
            return
        handler = {
            SceneKind.SCATTER: self._add_scatter,
            SceneKind.LINE: self._add_line,
            SceneKind.LINE_COLLECTION: self._add_line_collection,
            SceneKind.POLYGON: self._add_polygon,
            SceneKind.TEXT: self._add_text,
            SceneKind.GRADIENT: self._add_gradient,
            SceneKind.INFO_TABLE: self._add_info_table,
        }[layer.kind]
        try:
            handler(layer)
        except Exception as error:
            raise RuntimeError(
                f"Failed to render {layer.kind.value} Scene layer "
                f"(group_id={layer.group_id})"
            ) from error

    def _coordinate(self, layer: SceneLayer, name: str) -> np.ndarray:
        values = layer.data[name]
        encoding = layer.coordinate_encoding.get(name)
        if encoding is None:
            return values
        if encoding.kind is CoordinateEncodingKind.ABSOLUTE_F64:
            return values
        if encoding.origin == 0.0 and encoding.scale == 1.0:
            return values
        return np.ascontiguousarray(
            values.astype(np.float64, copy=False) * encoding.scale + encoding.origin,
            dtype=np.float64,
        )

    def _path_coordinates(
        self, layer: SceneLayer
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        x = self._coordinate(layer, "x")
        y = self._coordinate(layer, "y")
        path_id = layer.data["path_id"]
        if len(path_id) < 2 or not np.any(path_id[1:] != path_id[:-1]):
            return x, y, np.arange(len(x), dtype=np.intp)
        breaks = np.flatnonzero(path_id[1:] != path_id[:-1]) + 1
        dtype = np.result_type(x.dtype, y.dtype, np.float32)
        output_count = len(x) + len(breaks)
        x_output = np.empty(output_count, dtype=dtype)
        y_output = np.empty(output_count, dtype=dtype)
        source_rows = np.empty(output_count, dtype=np.intp)
        source_start = output_start = 0
        for source_stop in (*breaks.tolist(), len(x)):
            length = source_stop - source_start
            x_output[output_start : output_start + length] = x[source_start:source_stop]
            y_output[output_start : output_start + length] = y[source_start:source_stop]
            source_rows[output_start : output_start + length] = np.arange(
                source_start, source_stop
            )
            output_start += length
            if source_stop != len(x):
                x_output[output_start] = np.nan
                y_output[output_start] = np.nan
                source_rows[output_start] = -1
                output_start += 1
            source_start = source_stop
        return x_output, y_output, source_rows

    def _setup_layout(self) -> None:
        background = self.viewport.get(
            "axes_background", self.style_info.get("background_color", "#ffffff")
        )
        paper_background = self.viewport.get(
            "paper_background",
            self.style_info.get("figure_background_color", "#ffffff"),
        )
        transparent = bool(self.viewport.get("transparent", False))
        if transparent:
            paper_background = "rgba(0,0,0,0)"

        bounds = self.viewport.get("data_bounds", {})
        xaxis = dict(
            showgrid=False,
            zeroline=False,
            scaleanchor="y",
            scaleratio=1,
            constrain="domain",
            showticklabels=False,
            showline=False,
        )
        yaxis = dict(
            showgrid=False,
            zeroline=False,
            constrain="domain",
            showticklabels=False,
            showline=False,
        )
        if bounds.get("x_min") is not None and bounds.get("x_max") is not None:
            xaxis["range"] = [bounds["x_min"], bounds["x_max"]]
        if bounds.get("y_min") is not None and bounds.get("y_max") is not None:
            yaxis["range"] = [bounds["y_min"], bounds["y_max"]]

        legend = dict(
            bgcolor=self.style_info.get("legend_background_color", "rgba(0,0,0,0.5)"),
            font=dict(
                color=self.style_info.get("legend_font_color", "#ffffff"),
                size=max(
                    8,
                    self.style_info.get("legend_font_size", 11)
                    * self._font_pixel_scale(),
                ),
            ),
            bordercolor=self.style_info.get(
                "legend_border_color", "rgba(255,255,255,0.2)"
            ),
            borderwidth=1,
        )
        legend_title = self.style_info.get("legend_title")
        if legend_title:
            legend["title"] = dict(
                text=str(legend_title),
                font=dict(
                    color=self.style_info.get("legend_font_color", "#ffffff"),
                    size=max(
                        8,
                        self.style_info.get("legend_title_font_size", 11)
                        * self._font_pixel_scale(),
                    ),
                ),
            )

        self.fig.update_layout(
            plot_bgcolor=background,
            paper_bgcolor=paper_background,
            xaxis=xaxis,
            yaxis=yaxis,
            hovermode="closest",
            dragmode="pan",
            showlegend=self.style_info.get("show_legend", False),
            legend=legend,
            margin=dict(l=10, r=10, t=30, b=10),
            autosize=False,
            width=self.viewport.get("reference_width"),
            height=self.viewport.get("reference_height"),
        )
        self._add_clipped_plot_background(background)

    def _add_clipped_plot_background(self, background: str) -> None:
        clip = self.scene.clips.get("plot")
        if clip is None:
            return
        points = tuple(clip.points)
        if clip.kind == "rect" and len(points) == 2:
            (x0, y0), (x1, y1) = points
            points = ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
        if len(points) < 3:
            return
        path = self._ring_path(points, lambda value: value, lambda value: value)
        self.fig.update_layout(plot_bgcolor="rgba(0,0,0,0)")
        self.fig.add_shape(
            type="path",
            path=path,
            xref="x",
            yref="y",
            fillcolor=background,
            line=dict(width=0),
            layer="below",
        )

    def _reserve_scene_space(self) -> None:
        footer_values = []
        for layer in self.scene.layers:
            if layer.group_id == "horizon-bottom" and "y" in layer.data.columns:
                footer_values.extend(self._coordinate(layer, "y").tolist())
        if footer_values:
            self._horizon_footer_offset = max(0.0, -min(footer_values))
            if self._horizon_footer_offset:
                self.fig.update_yaxes(domain=[self._horizon_footer_offset, 1.0])
            if any(layer.group_id == "gridlines-label" for layer in self.scene.layers):
                self._side_margin = 50.0
                self.fig.update_layout(margin=dict(l=50, r=50, t=30, b=10))

        if self.projection_info.get("plot_kind") == "map":
            paper_labels = [
                layer
                for layer in self.scene.layers
                if layer.kind is SceneKind.TEXT
                and layer.group_id == "gridlines-label"
                and self._coordinate_refs(layer) == ("paper", "paper")
                and layer.data.row_count
            ]
            if paper_labels:
                xs = [float(self._coordinate(layer, "x")[0]) for layer in paper_labels]
                ys = [float(self._coordinate(layer, "y")[0]) for layer in paper_labels]
                pad = 0.015
                x0, x1 = min(0.0, min(xs)) - pad, max(1.0, max(xs)) + pad
                y0, y1 = min(0.0, min(ys)) - pad, max(1.0, max(ys)) + pad
                self._paper_x_bounds = (x0, x1)
                self._paper_y_bounds = (y0, y1)
                self.fig.update_xaxes(
                    domain=[(0.0 - x0) / (x1 - x0), (1.0 - x0) / (x1 - x0)]
                )
                self.fig.update_yaxes(
                    domain=[(0.0 - y0) / (y1 - y0), (1.0 - y0) / (y1 - y0)]
                )

        title_tops = [
            float(layer.style["axes_domain_top"])
            for layer in self.scene.layers
            if layer.group_id == "title"
            and layer.style.get("axes_domain_top") is not None
        ]
        if title_tops:
            current = self.fig.layout.yaxis.domain or (0.0, 1.0)
            self.fig.update_yaxes(
                domain=[float(current[0]), min(float(current[1]), min(title_tops))]
            )

    def _paper_x(self, value: float) -> float:
        x0, x1 = self._paper_x_bounds
        return (value - x0) / (x1 - x0)

    def _paper_y(self, value: float, layer: SceneLayer) -> float:
        if layer.group_id in {"horizon-bottom", "horizon-label"} or layer.style.get(
            "footer"
        ):
            value += self._horizon_footer_offset
        y0, y1 = self._paper_y_bounds
        return (value - y0) / (y1 - y0)

    def _font_pixel_scale(self) -> float:
        source_width = self.style_info.get("source_axes_width")
        if not source_width:
            return 1.0
        reference_width = float(self.viewport.get("reference_width", source_width))
        target_width = max(1.0, reference_width - 2.0 * self._side_margin)
        return (
            float(self.style_info.get("dpi", 100.0))
            / 72.0
            * target_width
            / float(source_width)
        )

    def _stroke_pixel_scale(self) -> float:
        return self._font_pixel_scale() * _KALEIDO_STROKE_SCALE

    def _coordinate_refs(self, layer: SceneLayer) -> tuple[str, str]:
        explicit = (layer.style.get("xref"), layer.style.get("yref"))
        if layer.space is CoordinateSpace.DATA and explicit == ("paper", "paper"):
            return explicit
        return {
            CoordinateSpace.DATA: ("x", "y"),
            CoordinateSpace.AXES: ("x domain", "y domain"),
            CoordinateSpace.PAPER: ("paper", "paper"),
        }[layer.space]

    def _legend(self, layer: SceneLayer) -> tuple[str, bool]:
        label = layer.style.get("legend_label")
        name = str(label) if label is not None else _group_name(layer.group_id)
        if not self.fig.layout.showlegend:
            return name, False
        explicit_labels = self.style_info.get("legend_labels")
        if explicit_labels is not None:
            if name not in explicit_labels or name in self._shown_legend_labels:
                return name, False
            self._shown_legend_labels.add(name)
            return name, True
        show = (
            label is not None or layer.group_id in _KNOWN_LEGEND_GROUPS
        ) and layer.group_id not in self._shown_groups
        return name, show

    def _record_group(self, layer: SceneLayer) -> None:
        self._shown_groups.add(layer.group_id)

    def _add_scatter(self, layer: SceneLayer) -> None:
        palette = layer.palette or self.scene.palettes.get(
            layer.style.get("palette_id"), ()
        )
        fill = str(layer.style.get("fill", "")).lower()
        if fill == "none":
            color: Any = "rgba(0,0,0,0)"
            colorscale = None
            cmin = cmax = None
        else:
            color = layer.data["color_index"]
            colorscale = _discrete_colorscale(tuple(palette))
            cmin = -0.5
            cmax = max(0.5, len(palette) - 0.5)

        name, showlegend = self._legend(layer)
        use_webgl = layer.group_id == "stars" or layer.data.row_count > 1000
        trace_type = go.Scattergl if use_webgl else go.Scatter
        hover_text = self._hover_text(layer)
        customdata = self._customdata(layer)
        source_size = layer.data["size"]
        if use_webgl:
            coverage = np.minimum(
                np.float32(1.0),
                source_size * source_size * _SCATTERGL_SUBPIXEL_COVERAGE_SCALE,
            )
            marker_size = np.maximum(
                source_size, _SCATTERGL_MIN_MARKER_DIAMETER
            ).astype(np.float32, copy=False)
            marker_opacity = np.asarray(
                layer.data["opacity"] * coverage,
                dtype=np.float32,
            )
            edge_width = 0.0
        else:
            marker_size = np.maximum(source_size, _PLOTLY_MIN_MARKER_DIAMETER).astype(
                np.float32, copy=False
            )
            marker_opacity = layer.data["opacity"]
            edge_width = (layer.style.get("edge_width", 0) or 0) * (
                self._stroke_pixel_scale()
            )
        marker = dict(
            size=marker_size,
            color=color,
            opacity=marker_opacity,
            symbol=MARKER_SYMBOL_MAP.get(layer.style.get("symbol", "circle"), "circle"),
            line=dict(
                color=_sanitize_color(layer.style.get("edge_color")),
                width=edge_width,
            ),
        )
        if colorscale is not None:
            marker.update(colorscale=colorscale, cmin=cmin, cmax=cmax, showscale=False)
        trace_kwargs = {}
        if not use_webgl:
            trace_kwargs.update(self._svg_zorder(layer))
        self.fig.add_trace(
            trace_type(
                x=self._coordinate(layer, "x"),
                y=self._coordinate(layer, "y"),
                mode="markers",
                marker=marker,
                text=hover_text,
                customdata=customdata,
                hoverinfo="text" if hover_text is not None else "skip",
                name=name,
                legendgroup=layer.group_id,
                showlegend=showlegend,
                **trace_kwargs,
            )
        )
        self._record_group(layer)

    def _hover_text(self, layer: SceneLayer):
        if (
            layer.interaction is InteractionPolicy.NONE
            or layer.data.row_count > _MAX_INTERACTIVE_HOVER_POINTS
        ):
            return None
        columns = layer.data.columns
        result = []
        for index in range(layer.data.row_count):
            kind = (
                str(columns.get("type", np.array([""]))[index])
                if "type" in columns
                else ""
            )
            name = str(columns["name"][index]) if "name" in columns else ""
            parts = [f"<b>{name}</b>"] if name else []
            if "bayer" in columns and columns["bayer"][index]:
                parts.append(str(columns["bayer"][index]))
            if "dso_type" in columns and columns["dso_type"][index]:
                parts.append(f"Type: {columns['dso_type'][index]}")
            if "magnitude" in columns and np.isfinite(columns["magnitude"][index]):
                digits = 1 if kind == "dso" else 2
                parts.append(
                    f"Magnitude: {float(columns['magnitude'][index]):.{digits}f}"
                )
            if "ra" in columns and "dec" in columns:
                ra = columns["ra"][index]
                dec = columns["dec"][index]
                if np.isfinite(ra) and np.isfinite(dec):
                    parts.append(f"RA: {float(ra) / 15:.4f}h  DEC: {float(dec):.4f}°")
            if "constellation" in columns and columns["constellation"][index]:
                parts.append(f"Constellation: {columns['constellation'][index]}")
            result.append("<br>".join(parts))
        return result

    def _customdata(self, layer: SceneLayer):
        if layer.interaction is InteractionPolicy.NONE or not layer.hover_fields:
            return None
        return np.column_stack([layer.data[name] for name in layer.hover_fields])

    def _line_style(self, layer: SceneLayer) -> dict[str, Any]:
        line_style = layer.style.get("line_style", "solid")
        dash = (
            "solid"
            if isinstance(line_style, (list, tuple))
            else LINE_STYLE_MAP.get(str(line_style), "solid")
        )
        return dict(
            color=_sanitize_color(layer.style.get("color", "#777777")),
            width=max(
                0.25,
                layer.style.get("width", 1) * self._stroke_pixel_scale(),
            ),
            dash=dash,
        )

    @staticmethod
    def _svg_zorder(layer: SceneLayer) -> dict[str, int]:
        value = int(layer.zorder)
        return {"zorder": value} if value else {}

    def _add_line(self, layer: SceneLayer) -> None:
        x, y, _ = self._path_coordinates(layer)
        name, showlegend = self._legend(layer)
        if layer.clip_id is None:
            parts = []
            drawing = False
            for x_value, y_value in zip(x, y):
                if not np.isfinite(x_value) or not np.isfinite(y_value):
                    drawing = False
                    continue
                parts.append(f"{'L' if drawing else 'M'} {x_value},{y_value}")
                drawing = True
            if parts:
                self.fig.add_shape(
                    type="path",
                    path=" ".join(parts),
                    xref="x",
                    yref="y",
                    line=self._line_style(layer),
                    opacity=layer.style.get("alpha", 1.0),
                    layer="above",
                )
            return
        self.fig.add_trace(
            go.Scatter(
                x=x,
                y=y,
                mode="lines",
                line=self._line_style(layer),
                opacity=layer.style.get("alpha", 1.0),
                hoverinfo="none",
                name=name,
                legendgroup=layer.group_id,
                showlegend=showlegend,
                **self._svg_zorder(layer),
            )
        )
        self._record_group(layer)

    def _add_line_collection(self, layer: SceneLayer) -> None:
        x, y, source_rows = self._path_coordinates(layer)
        name, showlegend = self._legend(layer)
        hover = None
        if (
            layer.interaction is not InteractionPolicy.NONE
            and "name" in layer.data.columns
        ):
            names = layer.data["name"]
            hover = [None if row < 0 else str(names[row]) for row in source_rows]
        trace_type = (
            go.Scattergl
            if layer.data.row_count > 1000 or layer.kind is SceneKind.LINE_COLLECTION
            else go.Scatter
        )
        trace_kwargs = {}
        if trace_type is go.Scatter:
            trace_kwargs.update(self._svg_zorder(layer))
        self.fig.add_trace(
            trace_type(
                x=x,
                y=y,
                mode="lines",
                line=self._line_style(layer),
                opacity=layer.style.get("alpha", 1.0),
                text=hover,
                hoverinfo="text",
                name=name,
                legendgroup=layer.group_id,
                showlegend=showlegend,
                **trace_kwargs,
            )
        )
        self._record_group(layer)

    @staticmethod
    def _ring_path(points, x_map, y_map) -> str:
        if not points:
            return ""
        path = f"M {x_map(points[0][0])},{y_map(points[0][1])}"
        path += "".join(f" L {x_map(x)},{y_map(y)}" for x, y in points[1:])
        return path + " Z"

    @staticmethod
    def _append_closed_trace_path(x_values, y_values, points) -> None:
        if not points:
            return
        for x, y in (*points, points[0]):
            x_values.append(float(x))
            y_values.append(float(y))
        x_values.append(np.nan)
        y_values.append(np.nan)

    def _add_data_polygon_holes(
        self,
        layer: SceneLayer,
        polygons,
        *,
        has_fill: bool,
        fill_color: str,
        edge_color: str,
        edge_width: float,
    ) -> None:
        fill_x: list[float] = []
        fill_y: list[float] = []
        outline_x: list[float] = []
        outline_y: list[float] = []
        for rings in polygons:
            polygon = Polygon(rings[0], holes=rings[1:])
            if polygon.is_empty or not polygon.is_valid or polygon.area <= 0:
                raise ValueError("DATA polygon must be valid and have positive area")
            if has_fill:
                edges = triangulate(polygon, tolerance=0.0, edges=True)
                faces = [
                    face
                    for face in polygonize(unary_union([polygon.boundary, *edges]))
                    if face.area > 0 and polygon.covers(face.representative_point())
                ]
                if not faces or not polygon.equals(unary_union(faces)):
                    raise ValueError("DATA polygon tessellation must cover the polygon")
                for face in faces:
                    if face.interiors or not face.equals(face.convex_hull):
                        raise ValueError(
                            "DATA polygon tessellation cells must be convex and hole-free"
                        )
                    triangles = triangulate(face, tolerance=0.0, edges=False)
                    if not triangles or not face.equals(unary_union(triangles)):
                        raise ValueError(
                            "DATA polygon tessellation cells must be fully triangulated"
                        )
                    for triangle in triangles:
                        points = list(triangle.exterior.coords)[:-1]
                        if (
                            triangle.area <= 0
                            or len(set(points)) != 3
                            or not face.covers(triangle)
                        ):
                            raise ValueError(
                                "DATA polygon tessellation emitted an invalid triangle"
                            )
                        self._append_closed_trace_path(fill_x, fill_y, points)
            for ring in rings:
                self._append_closed_trace_path(outline_x, outline_y, ring)

        common = dict(
            mode="lines",
            opacity=layer.style.get("alpha", 1.0),
            hoverinfo="none",
            legendgroup=layer.group_id,
            showlegend=False,
            **self._svg_zorder(layer),
        )
        if fill_x:
            self.fig.add_trace(
                go.Scatter(
                    x=np.asarray(fill_x, dtype=np.float64),
                    y=np.asarray(fill_y, dtype=np.float64),
                    fill="toself",
                    fillcolor=fill_color,
                    line=dict(color=fill_color, width=0),
                    **common,
                )
            )
        if outline_x:
            self.fig.add_trace(
                go.Scatter(
                    x=np.asarray(outline_x, dtype=np.float64),
                    y=np.asarray(outline_y, dtype=np.float64),
                    line=dict(color=edge_color, width=max(0, edge_width)),
                    **common,
                )
            )

    def _add_polygon(self, layer: SceneLayer) -> None:
        x = self._coordinate(layer, "x")
        y = self._coordinate(layer, "y")
        polygon_ids = layer.data["polygon_id"]
        ring_ids = layer.data["ring_id"]
        raw_fill = layer.style.get("fill_color")
        has_fill = not _is_no_color(raw_fill)
        fill_color = _sanitize_color(raw_fill)
        edge_color = _sanitize_color(layer.style.get("edge_color"))
        edge_width = (
            layer.style.get("edge_width", 0) or 0
        ) * self._stroke_pixel_scale()
        xref, yref = self._coordinate_refs(layer)
        use_shapes = (xref, yref) != ("x", "y")

        polygons = []
        for polygon_id in np.unique(polygon_ids):
            polygon_mask = polygon_ids == polygon_id
            rings = []
            for ring_id in np.unique(ring_ids[polygon_mask]):
                mask = polygon_mask & (ring_ids == ring_id)
                points = list(zip(x[mask].tolist(), y[mask].tolist()))
                if len(points) >= 3:
                    rings.append(points)
            if rings:
                polygons.append(rings)

        if not use_shapes and any(len(rings) > 1 for rings in polygons):
            self._add_data_polygon_holes(
                layer,
                polygons,
                has_fill=has_fill,
                fill_color=fill_color,
                edge_color=edge_color,
                edge_width=edge_width,
            )
            return

        for rings in polygons:
            path = ""
            for points in rings:
                path += " " + self._ring_path(
                    points,
                    self._paper_x if xref == "paper" else lambda value: value,
                    (
                        (lambda value: self._paper_y(value, layer))
                        if yref == "paper"
                        else lambda value: value
                    ),
                )
            if not rings:
                continue
            if use_shapes:
                self.fig.add_shape(
                    type="path",
                    path=path.strip(),
                    xref=xref,
                    yref=yref,
                    fillcolor=fill_color if has_fill else "rgba(0,0,0,0)",
                    fillrule="evenodd",
                    line=dict(color=edge_color, width=edge_width),
                    opacity=layer.style.get("alpha", 1.0),
                )
            else:
                points = rings[0]
                x_values = np.asarray([point[0] for point in points] + [points[0][0]])
                y_values = np.asarray([point[1] for point in points] + [points[0][1]])
                self.fig.add_trace(
                    go.Scatter(
                        x=x_values,
                        y=y_values,
                        mode="lines",
                        fill="toself" if has_fill else None,
                        fillcolor=fill_color,
                        line=dict(color=edge_color, width=max(0, edge_width)),
                        opacity=layer.style.get("alpha", 1.0),
                        hoverinfo="none",
                        legendgroup=layer.group_id,
                        showlegend=False,
                        **self._svg_zorder(layer),
                    )
                )

    def _add_text(self, layer: SceneLayer) -> None:
        style = layer.style
        vertical = style.get("va", "center")
        horizontal = style.get("ha", "center")
        yanchor, _ = ANCHOR_MAP.get((vertical, horizontal), ("middle", "center"))
        xanchor = {"left": "left", "right": "right", "center": "center"}.get(
            horizontal, "center"
        )
        xref, yref = self._coordinate_refs(layer)
        x = float(self._coordinate(layer, "x")[0])
        y = float(self._coordinate(layer, "y")[0])
        if xref == "paper":
            x = self._paper_x(x)
        if yref == "paper":
            y = self._paper_y(y, layer)
        point_scale = self._font_pixel_scale()
        xshift = style.get("xshift", float(layer.data["x_offset"][0]) * point_scale)
        yshift = style.get("yshift", float(layer.data["y_offset"][0]) * point_scale)
        text = str(layer.data["text"][0]).replace("\n", "<br>")
        weight = style.get("font_weight", "normal")
        numeric_weight = {"normal": 400, "bold": 700}.get(str(weight).lower(), weight)
        font = dict(
            size=max(8, style.get("font_size", 12) * point_scale),
            color=_sanitize_color(style.get("font_color", "#ffffff")),
            family=_font_family(style.get("font_name")),
        )
        if "weight" in go.layout.annotation.Font()._valid_props:
            font["weight"] = numeric_weight
        if numeric_weight == 700 or (
            isinstance(numeric_weight, (int, float)) and numeric_weight >= 600
        ):
            text = f"<b>{text}</b>"
            font["family"] = "Arial Black, Arial, sans-serif"
        self.fig.add_annotation(
            x=x,
            y=y,
            text=text,
            showarrow=False,
            font=font,
            xanchor=xanchor,
            yanchor=yanchor,
            xshift=xshift,
            yshift=yshift,
            textangle=float(layer.data["rotation"][0]),
            xref=xref,
            yref=yref,
            opacity=style.get("font_alpha", style.get("alpha", 1.0)),
        )

    def _add_gradient(self, layer: SceneLayer) -> None:
        stops = [
            [float(position), str(color)]
            for position, color in layer.style.get("color_stops", ())
        ]
        if len(stops) < 2:
            return
        bounds = self.viewport.get("data_bounds", {})
        x_min, x_max = bounds.get("x_min"), bounds.get("x_max")
        y_min, y_max = bounds.get("y_min"), bounds.get("y_max")
        if None in (x_min, x_max, y_min, y_max):
            return
        direction = layer.style.get("direction", "linear")
        if direction == "radial":
            steps = 220
            x = np.linspace(float(x_min), float(x_max), steps)
            y = np.linspace(float(y_min), float(y_max), steps)
            xx, yy = np.meshgrid(x, y)
            center = layer.style.get("center")
            radius = layer.style.get("radius")
            clip = self.scene.clips.get(layer.clip_id) if layer.clip_id else None
            if clip is not None:
                points = np.asarray(clip.points, dtype=np.float64)
                clip_x0, clip_y0 = np.min(points, axis=0)
                clip_x1, clip_y1 = np.max(points, axis=0)
                default_center = (
                    (clip_x0 + clip_x1) / 2,
                    (clip_y0 + clip_y1) / 2,
                )
                default_radius = min(clip_x1 - clip_x0, clip_y1 - clip_y0) / 2
            else:
                default_center = (
                    (float(x_min) + float(x_max)) / 2,
                    (float(y_min) + float(y_max)) / 2,
                )
                default_radius = max(
                    abs(float(x_max) - default_center[0]),
                    abs(float(y_max) - default_center[1]),
                )
            if center is None:
                center = default_center
            if radius is None:
                radius = default_radius
            radius = max(float(radius), 1e-9)
            rr = ((xx - float(center[0])) / radius) ** 2 + (
                (yy - float(center[1])) / radius
            ) ** 2
            if clip is not None:
                mask = scatter_clip_mask(xx.ravel(), yy.ravel(), clip).reshape(xx.shape)
            else:
                mask = rr <= 1.0
            z = np.where(mask, np.minimum(rr, 1.0), np.nan)
            radial_positions = [float(stop[0]) / 2.0 for stop in stops]
            radial_positions[-1] = 1.0
            stops = [
                [1.0 - radial_positions[index], stops[index][1]]
                for index in reversed(range(len(stops)))
            ]
            zsmooth: Any = "best"
        else:
            steps = 2000
            x = np.asarray([float(x_min), float(x_max)], dtype=np.float64)
            y = np.linspace(float(y_min), float(y_max), steps)
            z = np.repeat(
                np.linspace(0.0, 1.0, steps, dtype=np.float64).reshape(-1, 1),
                2,
                axis=1,
            )
            zsmooth = False
        self.fig.add_trace(
            go.Heatmap(
                x=x,
                y=y,
                z=z,
                colorscale=stops,
                showscale=False,
                hoverinfo="skip",
                zsmooth=zsmooth,
                zmin=0.0,
                zmax=1.0,
                showlegend=False,
                name="",
            )
        )

    def _add_info_table(self, layer: SceneLayer) -> None:
        columns = [str(value) for value in layer.data["column"]]
        values = [str(value) for value in layer.data["value"]]
        count = min(len(columns), len(values))
        if not count:
            return
        raw_widths = np.maximum(layer.data["width"][:count], 0.0)
        total = float(np.sum(raw_widths))
        widths = (
            np.full(count, 1.0 / count)
            if total <= 0
            else raw_widths.astype(np.float64) / total
        )
        style = layer.style
        font_color = style.get("font_color", "#111111")
        font_name = _font_family(style.get("font_name"))
        font_alpha = float(style.get("font_alpha", 1.0))
        base_size = float(style.get("font_size", 12))
        font_scale = self._font_pixel_scale()
        header_size = max(11, base_size * 1.2 * font_scale)
        value_size = max(10, base_size * font_scale)
        background = style.get(
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
        table_top, header_y, value_y, table_bottom = -0.01, -0.03, -0.068, -0.09
        self.fig.add_shape(
            type="rect",
            xref="paper",
            yref="paper",
            x0=0,
            x1=1,
            y0=table_bottom,
            y1=table_top,
            line=dict(color=line_color, width=1),
            fillcolor=background,
            layer="above",
        )
        x_left = 0.0
        for index, width in enumerate(widths):
            x_right = x_left + float(width)
            x_center = (x_left + x_right) / 2
            if index:
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
            for text, y, size in (
                (f"<b>{columns[index]}</b>", header_y, header_size),
                (values[index], value_y, value_size),
            ):
                self.fig.add_annotation(
                    x=x_center,
                    y=y,
                    xref="paper",
                    yref="paper",
                    text=text,
                    showarrow=False,
                    xanchor="center",
                    yanchor="middle",
                    font=dict(size=size, color=font_color, family=font_name),
                    opacity=font_alpha,
                )
            x_left = x_right

    def _add_interactive_features(self) -> None:
        magnitude_scale = self.style_info.get("magnitude_scale")
        if self.fig.layout.showlegend and magnitude_scale:
            for index, (label, size) in enumerate(
                zip(magnitude_scale.get("labels", ()), magnitude_scale.get("sizes", ()))
            ):
                self.fig.add_trace(
                    go.Scatter(
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
                            if index == 0
                            else None
                        ),
                        legendrank=2000 + index,
                        showlegend=True,
                        hoverinfo="skip",
                    )
                )
        self.fig.update_layout(
            modebar=dict(add=["zoom", "pan", "select", "lasso2d", "resetScale2d"]),
            clickmode="event+select",
        )
