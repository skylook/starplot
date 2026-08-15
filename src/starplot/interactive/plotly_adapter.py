"""Plotly 6 adapter for backend-neutral compiled interactive Scenes."""

from __future__ import annotations

import ast
import html
from typing import Any

import numpy as np
import shapely.errors
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

# Expected errors when converting one Scene layer to a Plotly trace.  These are
# narrower than ``Exception`` and still let real programming errors surface.
_LAYER_RENDER_ERRORS = (
    AttributeError, KeyError, LookupError, TypeError, ValueError, IndexError,
    shapely.errors.ShapelyError,
)

_KALEIDO_MARKER_SCALE = 1.0
_KALEIDO_STROKE_SCALE = 1.0
_MAX_INTERACTIVE_HOVER_POINTS = 100_000
_PLOTLY_MIN_MARKER_DIAMETER = np.float32(1.5)
_SCATTERGL_MIN_MARKER_DIAMETER = np.float32(1.0)
_SCATTERGL_SUBPIXEL_COVERAGE_SCALE = np.float32(2.0)
_MAX_SVG_ZORDER_POINTS = 100_000
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


def _html_escape(value) -> str:
    """Escape a user-supplied value for safe use inside Plotly text/annotations."""
    return html.escape(str(value), quote=True)


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
        self._mixed_svg_zorder_plane = self._needs_svg_zorder_plane(scene)
        self._force_svg_trace_plane = (
            self._mixed_svg_zorder_plane
            or self._requires_svg_trace_plane(scene)
        )
        self._svg_zorders = (
            {layer.id: index for index, layer in enumerate(scene.layers)}
            if self._mixed_svg_zorder_plane
            else None
        )

    @staticmethod
    def _is_scattergl_candidate(layer: SceneLayer) -> bool:
        if layer.kind is SceneKind.SCATTER:
            return layer.group_id == "stars" or layer.data.row_count > 1000
        return layer.kind is SceneKind.LINE_COLLECTION

    @classmethod
    def _needs_svg_zorder_plane(cls, scene: ScenePackage) -> bool:
        """Match the browser's one-plane rule for small mixed SVG/GL scenes."""
        gl_layers = [
            layer for layer in scene.layers if cls._is_scattergl_candidate(layer)
        ]
        if not gl_layers:
            return False
        has_svg_geometry = any(
            layer.kind in {SceneKind.SCATTER, SceneKind.LINE, SceneKind.POLYGON}
            and not cls._is_scattergl_candidate(layer)
            for layer in scene.layers
        )
        largest_gl_layer = max(layer.data.row_count for layer in gl_layers)
        return has_svg_geometry and largest_gl_layer <= _MAX_SVG_ZORDER_POINTS

    @staticmethod
    def _requires_svg_trace_plane(scene: ScenePackage) -> bool:
        """Return whether hole topology requires one z-orderable trace plane."""
        for layer in scene.layers:
            if (
                layer.kind is not SceneKind.POLYGON
                or layer.space is not CoordinateSpace.DATA
            ):
                continue
            if (layer.style.get("xref"), layer.style.get("yref")) == (
                "paper",
                "paper",
            ):
                continue
            polygon_ids = layer.data.columns.get("polygon_id")
            ring_ids = layer.data.columns.get("ring_id")
            if polygon_ids is None or ring_ids is None:
                continue
            if any(
                len(np.unique(ring_ids[polygon_ids == polygon_id])) > 1
                for polygon_id in np.unique(polygon_ids)
            ):
                return True
        return False

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
        except _LAYER_RENDER_ERRORS as error:
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
                text=_html_escape(legend_title),
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
            # Auxiliary axes for paper-coordinate shapes.  Range [0, 1] with
            # domain [0, 1] maps matplotlib transAxes coordinates to the axes
            # area (after margins), not the full figure.
            xaxis3=dict(
                range=[0, 1], overlaying="x", visible=False, fixedrange=True,
            ),
            yaxis3=dict(
                range=[0, 1], overlaying="y", visible=False, fixedrange=True,
            ),
            hovermode="closest",
            dragmode="pan",
            showlegend=self.style_info.get("show_legend", False),
            legend=legend,
            margin=dict(
                self.viewport.get(
                    "margin", dict(l=10, r=10, t=30, b=10, autoexpand=False)
                )
            ),
            autosize=False,
            width=int(round(self.viewport.get("reference_width", 1000))),
            height=int(round(self.viewport.get("reference_height", 1000))),
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
        if self.viewport.get("margin"):
            # A tight Matplotlib export has already recorded the final space
            # occupied by horizon labels.  Applying the historical synthetic
            # footer a second time shrinks the sky viewport and clips gradients.
            return
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

    def _point_to_pixel_scale(self) -> float:
        """Convert PostScript points (1/72 inch) to pixels using the export dpi."""
        try:
            return float(self.style_info.get("dpi", 100.0)) / 72.0
        except (TypeError, ValueError):
            return 1.0

    def _width_ratio(self) -> float:
        """Return target/output axes width divided by source figure axes width.

        Marker sizes are already calibrated to this ratio in the Scene compiler,
        but fonts, stroke widths, and offsets are recorded in original figure
        points and must be scaled by the same ratio to stay visually proportional
        when the output dimensions differ from the source figure.
        """
        target = self.viewport.get("target_axes_width") or self.viewport.get(
            "reference_width", 1.0
        )
        source = (
            self.viewport.get("source_axes_width")
            or self.style_info.get("source_axes_width")
            or self.style_info.get("resolution")
            or target
        )
        try:
            return float(target) / float(source)
        except (TypeError, ValueError, ZeroDivisionError):
            return 1.0

    def _font_pixel_scale(self) -> float:
        """Return the combined point-to-pixel and target-size scale for fonts."""
        return self._point_to_pixel_scale() * self._width_ratio()

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
        name = _html_escape(
            label if label is not None else _group_name(layer.group_id)
        )
        if not self.fig.layout.showlegend:
            return name, False
        explicit_labels = self.style_info.get("legend_labels")
        if explicit_labels is not None:
            escaped_labels = {_html_escape(lbl) for lbl in explicit_labels}
            if name not in escaped_labels or name in self._shown_legend_labels:
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
        use_webgl = not self._force_svg_trace_plane and (
            layer.group_id == "stars" or layer.data.row_count > 1000
        )
        hover_text = self._hover_text(layer)
        customdata = self._customdata(layer)
        plotly_size = np.asarray(layer.data["size"], dtype=np.float32)
        if _KALEIDO_MARKER_SCALE != 1.0:
            plotly_size = np.multiply(
                plotly_size,
                np.float32(_KALEIDO_MARKER_SCALE),
                dtype=np.float32,
            )
        if use_webgl:
            coverage = np.multiply(
                plotly_size,
                plotly_size,
                dtype=np.float32,
            )
            coverage *= _SCATTERGL_SUBPIXEL_COVERAGE_SCALE
            np.minimum(np.float32(1.0), coverage, out=coverage)
            marker_opacity = np.asarray(
                layer.data["opacity"] * coverage,
                dtype=np.float32,
            )
            # Opacity has consumed the subpixel coverage values, so the same
            # dense work buffer can hold Plotly's minimum marker diameters.
            # Avoid retaining another row-sized array while Figure validates
            # and copies the trace.
            np.maximum(
                plotly_size,
                _SCATTERGL_MIN_MARKER_DIAMETER,
                out=coverage,
            )
            marker_size = coverage
        else:
            marker_opacity = layer.data["opacity"]
            marker_size = np.maximum(
                plotly_size,
                _PLOTLY_MIN_MARKER_DIAMETER,
            ).astype(np.float32, copy=False)
        edge_width = (layer.style.get("edge_width", 0) or 0) * self._stroke_pixel_scale()
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
        trace = dict(
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
        if use_webgl:
            trace["type"] = "scattergl"
            self.fig.add_trace(trace)
        else:
            self.fig.add_trace(go.Scatter(**trace))
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
            name = _html_escape(columns["name"][index]) if "name" in columns else ""
            parts = [f"<b>{name}</b>"] if name else []
            if "bayer" in columns and columns["bayer"][index]:
                parts.append(_html_escape(columns["bayer"][index]))
            if "dso_type" in columns and columns["dso_type"][index]:
                parts.append(f"Type: {_html_escape(columns['dso_type'][index])}")
            if "magnitude" in columns and np.isfinite(columns["magnitude"][index]):
                digits = 1 if kind == "dso" else 2
                parts.append(
                    "Magnitude: "
                    + _html_escape(
                        format(float(columns["magnitude"][index]), f".{digits}f")
                    )
                )
            if "ra" in columns and "dec" in columns:
                ra = columns["ra"][index]
                dec = columns["dec"][index]
                if np.isfinite(ra) and np.isfinite(dec):
                    parts.append(
                        f"RA: {_html_escape(format(float(ra) / 15, '.4f'))}h  "
                        f"DEC: {_html_escape(format(float(dec), '.4f'))}°"
                    )
            if "constellation" in columns and columns["constellation"][index]:
                parts.append(f"Constellation: {_html_escape(columns['constellation'][index])}")
            result.append("<br>".join(parts))
        return result

    def _customdata(self, layer: SceneLayer):
        if layer.interaction is InteractionPolicy.NONE or not layer.hover_fields:
            return None
        return np.column_stack([layer.data[name] for name in layer.hover_fields])

    def _line_style(self, layer: SceneLayer) -> dict[str, Any]:
        line_style = layer.style.get("line_style", "solid")
        if isinstance(line_style, (list, tuple)):
            # A LineCollection may return a homogeneous list of style strings.
            # A tuple/list of numbers is a Matplotlib dash tuple.
            if (
                line_style
                and all(isinstance(item, str) for item in line_style)
                and len(set(line_style)) == 1
            ):
                str_style = str(line_style[0]).strip().lower()
                dash = LINE_STYLE_MAP.get(str_style, "solid")
            else:
                dash = "dash"
        else:
            str_style = str(line_style).strip().lower()
            # Matplotlib may serialize custom dash tuples as strings like
            # "(0, (1, 2))"; parse them so they render as dashed in Plotly.
            try:
                parsed = ast.literal_eval(str_style)
                dash = (
                    "dash"
                    if isinstance(parsed, (list, tuple))
                    else LINE_STYLE_MAP.get(str_style, "solid")
                )
            except (ValueError, SyntaxError):
                dash = LINE_STYLE_MAP.get(str_style, "solid")
        return dict(
            color=_sanitize_color(layer.style.get("color", "#777777")),
            width=max(
                0.25,
                layer.style.get("width", 1) * self._stroke_pixel_scale(),
            ),
            dash=dash,
        )

    def _svg_zorder(self, layer: SceneLayer) -> dict[str, int]:
        if self._svg_zorders is not None:
            return {"zorder": self._svg_zorders[layer.id]}
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
            hover = [None if row < 0 else _html_escape(names[row]) for row in source_rows]
        trace_type = (
            go.Scattergl
            if not self._force_svg_trace_plane
            and (layer.data.row_count > 1000 or layer.kind is SceneKind.LINE_COLLECTION)
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
        edge_dash: str,
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
        outline_line = dict(color=edge_color, width=max(0, edge_width))
        if edge_dash != "solid":
            outline_line["dash"] = edge_dash
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
                    line=outline_line,
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
        edge_dash = self._line_style(layer)["dash"]
        edge_line = dict(color=edge_color, width=edge_width)
        if edge_dash != "solid":
            edge_line["dash"] = edge_dash
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
                edge_dash=edge_dash,
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
                # Use x3/y3 axes for paper-coordinate shapes so they map to
                # the axes area (matching matplotlib transAxes), not the full
                # figure (which includes margins).
                shape_xref = "x3" if xref == "paper" else xref
                shape_yref = "y3" if yref == "paper" else yref
                self.fig.add_shape(
                    type="path",
                    path=path.strip(),
                    xref=shape_xref,
                    yref=shape_yref,
                    fillcolor=fill_color if has_fill else "rgba(0,0,0,0)",
                    fillrule="evenodd",
                    line=edge_line,
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
                        line={**edge_line, "width": max(0, edge_width)},
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
        text = _html_escape(str(layer.data["text"][0])).replace("\n", "<br>")
        weight = style.get("font_weight", "normal")
        _WEIGHT_MAP = {
            "normal": 400, "bold": 700, "light": 300, "medium": 500,
            "semibold": 600, "heavy": 800, "extra bold": 800, "black": 900,
        }
        numeric_weight = _WEIGHT_MAP.get(str(weight).lower())
        if numeric_weight is None:
            try:
                numeric_weight = int(weight)
            except (ValueError, TypeError):
                numeric_weight = 400
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
            steps = 512
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
                mask = self._gradient_clip_mask(layer, xx, yy)
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
        elif direction == "linear":
            clip = self.scene.clips.get(layer.clip_id) if layer.clip_id else None
            steps = 512 if clip is not None else 2000
            x = np.linspace(float(x_min), float(x_max), 512 if clip is not None else 2)
            y = np.linspace(float(y_min), float(y_max), steps)
            xx, yy = np.meshgrid(x, y)
            z = np.repeat(
                np.linspace(0.0, 1.0, steps, dtype=np.float64).reshape(-1, 1),
                len(x),
                axis=1,
            )
            if clip is not None:
                z = np.where(self._gradient_clip_mask(layer, xx, yy), z, np.nan)
            zsmooth = False
        elif direction == "mollweide":
            steps = 512
            x = np.linspace(float(x_min), float(x_max), steps)
            y = np.linspace(float(y_min), float(y_max), steps)
            xx, yy = np.meshgrid(x, y)
            x_mid = (float(x_min) + float(x_max)) / 2.0
            y_mid = (float(y_min) + float(y_max)) / 2.0
            x_radius = max((float(x_max) - float(x_min)) / 2.0, 1e-12)
            y_radius = max((float(y_max) - float(y_min)) / 2.0, 1e-12)
            x_normalized = (xx - x_mid) / x_radius
            y_normalized = (yy - y_mid) / y_radius
            theta = np.arcsin(np.clip(y_normalized, -1.0, 1.0))
            cos_theta = np.cos(theta)
            longitude = np.zeros_like(xx)
            np.divide(
                np.pi * x_normalized,
                cos_theta,
                out=longitude,
                where=np.abs(cos_theta) > 1e-12,
            )
            latitude = np.arcsin(
                np.clip((2.0 * theta + np.sin(2.0 * theta)) / np.pi, -1.0, 1.0)
            )
            cos_latitude = np.cos(latitude)
            equatorial = np.stack(
                [
                    cos_latitude * np.cos(longitude),
                    -cos_latitude * np.sin(longitude),
                    -np.sin(latitude),
                ],
                axis=-1,
            )
            rotation = np.asarray(
                [
                    [-0.0548755604162154, -0.8734370902348850, -0.4838350155487132],
                    [0.4941094278755837, -0.4448296299600112, 0.7469822444972189],
                    [-0.8676661490190047, -0.1980763734312015, 0.4559837761750669],
                ],
                dtype=np.float64,
            )
            galactic = equatorial @ rotation.T
            z = (np.arcsin(np.clip(galactic[..., 2], -1.0, 1.0)) + np.pi / 2) / np.pi
            mask = (
                (np.abs(y_normalized) <= 1.0)
                & (np.abs(longitude) <= np.pi)
                & (np.abs(cos_theta) > 1e-12)
            )
            if layer.clip_id and layer.clip_id in self.scene.clips:
                mask &= self._gradient_clip_mask(layer, xx, yy)
            z = np.where(mask, z, np.nan)
            zsmooth = "best"
        else:
            raise ValueError(f"unsupported gradient direction: {direction}")
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

    def _gradient_clip_mask(
        self, layer: SceneLayer, xx: np.ndarray, yy: np.ndarray
    ) -> np.ndarray:
        clip = self.scene.clips.get(layer.clip_id) if layer.clip_id else None
        if clip is None:
            return np.ones(xx.shape, dtype=np.bool_)
        return scatter_clip_mask(xx.ravel(), yy.ravel(), clip).reshape(xx.shape)

    def _add_info_table(self, layer: SceneLayer) -> None:
        columns = [_html_escape(value) for value in layer.data["column"]]
        values = [_html_escape(value) for value in layer.data["value"]]
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
            legend_title_font = dict(
                color=self.style_info.get("legend_font_color", "#ffffff"),
                size=max(
                    8,
                    self.style_info.get("legend_title_font_size", 11)
                    * self._font_pixel_scale(),
                ),
            )
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
                        name=_html_escape(label),
                        legendgroup="star-magnitude-scale",
                        legendgrouptitle=(
                            dict(
                                text=_html_escape(
                                    magnitude_scale.get("title", "Star Magnitude")
                                ),
                                font=legend_title_font,
                            )
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
