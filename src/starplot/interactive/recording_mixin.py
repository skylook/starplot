"""RecordingMixin — intercepts starplot drawing primitives and records them
as backend-agnostic DrawingCommands.

Must appear before the concrete Plot class in the MRO:

    class InteractiveMapPlot(RecordingMixin, MapPlot): ...
    # MRO: InteractiveMapPlot → RecordingMixin → MapPlot → BasePlot → ...

Each overridden method calls super() first (preserving matplotlib rendering),
then records a DrawingCommand for the Plotly renderer.
"""

import logging
import math
from typing import Optional

import shapely.errors

from starplot.interactive.recorder import DrawingRecorder
from starplot.interactive.commands import CoordinateSpace
from starplot.coordinates import CoordinateSystem
from starplot.data.translations import translate
from starplot.styles import ObjectStyle, PathStyle, LineStyle, LabelStyle, LegendStyle, ArrowStyle
from starplot.styles.helpers import use_style

LOGGER = logging.getLogger("starplot.interactive")

_MAX_INTERACTIVE_HOVER_POINTS = 50_000

# These are the errors we expect when reading Matplotlib/shapely state that may
# not be present or may be in an unexpected form.  They are much narrower than
# ``Exception``: they exclude RuntimeError, OSError, SystemExit, KeyboardInterrupt,
# MemoryError, NotImplementedError, etc., so real programming errors still propagate.
_RECORDING_ERRORS = (AttributeError, KeyError, LookupError, TypeError, ValueError, IndexError)
_GRIDLINE_ERRORS = (RuntimeError, *_RECORDING_ERRORS)
_CLIP_ERRORS = (shapely.errors.ShapelyError, *_RECORDING_ERRORS)


def _split_points(points):
    """Split a sequence of points into segments separated by non-finite coordinates."""
    segments = []
    current = []
    for x, y in points:
        if math.isfinite(x) and math.isfinite(y):
            current.append((float(x), float(y)))
        else:
            if len(current) > 1:
                segments.append(current)
            current = []
    if len(current) > 1:
        segments.append(current)
    return segments


def _transformed_path_segments(ax, transform, vertices, codes=None):
    """Return final-DATA segments from a Matplotlib path transform.

    Cartopy applies antimeridian splitting and extent clipping in
    ``transform_path_non_affine``.  Transforming an Nx2 endpoint array skips
    that path-only work and reconnects 359°→1° lines in Plotly.  Preserve each
    ``MOVETO`` as a separate segment after mapping the rendered path back to
    final axes data coordinates.
    """
    from matplotlib.path import Path

    path = Path(vertices, codes)
    rendered = transform.transform_path(path)
    data = ax.transData.inverted().transform(rendered.vertices)
    rendered_codes = rendered.codes
    if rendered_codes is None:
        return _split_points(data)

    segments, current = [], []
    for (x, y), code in zip(data, rendered_codes):
        if code == Path.MOVETO:
            if len(current) > 1:
                segments.append(current)
            current = []
        if math.isfinite(x) and math.isfinite(y):
            current.append((float(x), float(y)))
        elif len(current) > 1:
            segments.append(current)
            current = []
    if len(current) > 1:
        segments.append(current)
    return segments


def _transformed_path_rings(ax, transform, vertices, codes=None):
    """Return final-DATA polygon rings without reconnecting ``MOVETO`` paths."""
    return [
        segment for segment in _transformed_path_segments(ax, transform, vertices, codes)
        if len(segment) >= 3
    ]


def _rgba_to_hex(color):
    """Serialize a Matplotlib color without discarding its alpha channel."""
    try:
        from matplotlib.colors import to_hex, to_rgba
        red, green, blue, alpha = to_rgba(color)
        if alpha < 1.0:
            return (
                f"rgba({round(red * 255)},{round(green * 255)},"
                f"{round(blue * 255)},{alpha:g})"
            )
        return to_hex((red, green, blue))
    except _RECORDING_ERRORS:
        return "#ffffff"


def _rgb_string(color):
    """Return a CSS rgb(...) or hex color string with the alpha channel removed.

    Useful when the consumer (e.g. a Plotly trace) will apply a separate
    `opacity`/`alpha` value, so the alpha should not be embedded in the color.
    """
    try:
        from matplotlib.colors import to_hex, to_rgba
        red, green, blue, _ = to_rgba(color)
        hex_color = to_hex((red, green, blue))
        # Use hex when possible; for non-integer values fall back to rgb().
        return hex_color
    except _RECORDING_ERRORS:
        return "#ffffff"


def _edge_color_string(color):
    """Preserve a fully transparent Matplotlib edge as no edge at all."""
    try:
        from matplotlib.colors import to_rgba

        if to_rgba(color)[3] == 0:
            return None
    except _RECORDING_ERRORS:
        return None
    return _rgb_string(color)


class RecordingMixin:
    """Mixin that records drawing commands alongside matplotlib rendering."""

    def __init__(self, *args, **kwargs):
        self._recorder = DrawingRecorder()
        super().__init__(*args, **kwargs)
        # Metadata is recorded lazily in to_plotly() so __init__ does not
        # produce matplotlib side effects (e.g., drawing).

    # ------------------------------------------------------------------
    # Coordinate projection helper — sole conversion boundary
    # ------------------------------------------------------------------

    def _to_final_data(self, x, y, source_space):
        """Convert coordinates to final DATA-space values.

        This is the sole conversion boundary between source coordinate
        systems and the final projected DATA space that PlotlyRenderer
        consumes.  Raw RA/DEC/AZ/ALT must never bypass this method.

        Args:
            x, y: coordinates in the source space.
            source_space: "radec" for public RA/DEC arguments;
                          "prepared" for values already passed through
                          _prepare_coords (AZ/ALT or camera coords).
        Returns:
            (x, y) tuple in final projected DATA coordinates.
        """
        if source_space == "prepared":
            return tuple(map(float, self._proj.transform_point(x, y, self._crs)))
        if source_space == "radec":
            if self._coordinate_system == CoordinateSystem.AZ_ALT:
                az, alt = self._prepare_coords(x, y)
                return tuple(map(float, self._proj.transform_point(az, alt, self._crs)))
            return tuple(map(float, self._proj.transform_point(x, y, self._crs)))
        raise ValueError(f"Unknown interactive source space: {source_space}")

    def _artist_offsets_to_final_data(self, collection):
        """Extract a Collection's offsets and transform to final DATA coords.

        Matplotlib stores scatter locations in ``get_offset_transform()``,
        while ``get_transform()`` describes the marker path itself.  Reading
        the latter maps DATA offsets through an identity marker transform and
        then wrongly inverse-projects them a second time.
        """
        raw = collection.get_offsets()
        if len(raw) == 0:
            return [], []
        display = collection.get_offset_transform().transform(raw)
        data = self.ax.transData.inverted().transform(display)
        xs = [float(v) for v in data[:, 0]]
        ys = [float(v) for v in data[:, 1]]
        return xs, ys

    def _project_coords(self, ra, dec):
        """Transform RA/DEC to the plot's projected coordinate space.

        .. deprecated:: Use _to_final_data(ra, dec, 'radec') instead.
        Kept temporarily for callers not yet migrated.
        """
        if hasattr(self, '_proj') and hasattr(self, '_crs'):
            try:
                if self._coordinate_system == CoordinateSystem.AZ_ALT:
                    az, alt = self._prepare_coords(ra, dec)
                    x, y = self._proj.transform_point(az, alt, self._crs)
                else:
                    x, y = self._proj.transform_point(ra, dec, self._crs)
                if math.isfinite(x) and math.isfinite(y):
                    return float(x), float(y)
                return float('nan'), float('nan')
            except _RECORDING_ERRORS as e:
                LOGGER.debug("Projection failed for (%s, %s): %s", ra, dec, e)
                return float('nan'), float('nan')
        else:
            return self._prepare_coords(ra, dec)

    # ------------------------------------------------------------------
    # Plot metadata
    # ------------------------------------------------------------------

    def _record_plot_info(self):
        """Capture projection and style info after the plot is initialized."""
        # Determine plot kind through explicit isinstance checks
        from starplot.plots.map import MapPlot
        from starplot.plots.horizon import HorizonPlot
        from starplot.plots.zenith import ZenithPlot
        from starplot.plots.optic import OpticPlot

        if isinstance(self, OpticPlot):
            plot_kind = "optic"
        elif isinstance(self, ZenithPlot):
            plot_kind = "zenith"
        elif isinstance(self, HorizonPlot):
            plot_kind = "horizon"
        elif isinstance(self, MapPlot):
            plot_kind = "map"
        else:
            plot_kind = "unknown"

        proj_info = {
            "type": getattr(self, "projection", None).__class__.__name__
            if hasattr(self, "projection") and getattr(self, "projection") is not None
            else type(self).__name__,
            "ra_min": getattr(self, "ra_min", 0),
            "ra_max": getattr(self, "ra_max", 360),
            "dec_min": getattr(self, "dec_min", -90),
            "dec_max": getattr(self, "dec_max", 90),
            "plot_kind": plot_kind,
        }

        # Compute projected axis extents from matplotlib axes limits
        try:
            xlim = self.ax.get_xlim()
            ylim = self.ax.get_ylim()
            proj_info.update({
                "x_min": xlim[0],
                "x_max": xlim[1],
                "y_min": ylim[0],
                "y_max": ylim[1],
            })
        except _RECORDING_ERRORS as e:
            LOGGER.debug("Could not extract axis limits: %s", e)

        # Force a draw so axes position and window extent are final
        try:
            self.fig.draw_without_rendering()
        except _RECORDING_ERRORS as e:
            LOGGER.debug("Could not draw without rendering: %s", e)

        self._record_untracked_path_patches()

        # Record axes bbox and pixel dimensions.
        # _fit_to_ax sets the figure size in inches to the axes bbox.  The
        # exported PNG is rendered at self.dpi (the export dpi, typically
        # 100), while get_window_extent() returns display pixels at the
        # backend's figure dpi (which may be 200 on retina).  Convert to
        # export pixels so reference dimensions match the actual PNG output
        # used for visual comparison.
        try:
            ax_pos = self.ax.get_position()
            proj_info["axes_bbox"] = (
                float(ax_pos.x0), float(ax_pos.y0),
                float(ax_pos.width), float(ax_pos.height),
            )
            fig_width_in, fig_height_in = self.fig.get_size_inches()
            export_dpi = getattr(self, "dpi", 100) or 100
            proj_info["figure_pixels"] = (
                float(fig_width_in * export_dpi),
                float(fig_height_in * export_dpi),
            )
            proj_info["axes_pixels"] = (
                float(ax_pos.width * fig_width_in * export_dpi),
                float(ax_pos.height * fig_height_in * export_dpi),
            )
            export_geometry = getattr(self, "_last_export_geometry", None)
            if export_geometry:
                tight_x, tight_y, tight_width, tight_height = export_geometry[
                    "tight_bbox_inches"
                ]
                axes_x, axes_y, axes_width, axes_height = export_geometry[
                    "axes_bbox_inches"
                ]
                pad_inches = export_geometry["padding_inches"]
                recorded_dpi = export_geometry["dpi"]
                export_width = tight_width + 2 * pad_inches
                export_height = tight_height + 2 * pad_inches
                if export_width > 0 and export_height > 0:
                    proj_info["figure_pixels"] = (
                        float(export_width * recorded_dpi),
                        float(export_height * recorded_dpi),
                    )
                    proj_info["axes_bbox"] = (
                        float((axes_x - tight_x + pad_inches) / export_width),
                        float((axes_y - tight_y + pad_inches) / export_height),
                        float(axes_width / export_width),
                        float(axes_height / export_height),
                    )
                    proj_info["axes_pixels"] = (
                        float(axes_width * recorded_dpi),
                        float(axes_height * recorded_dpi),
                    )
        except _RECORDING_ERRORS as e:
            LOGGER.debug("Could not extract axes geometry: %s", e)
            proj_info["axes_bbox"] = (0.0, 0.0, 1.0, 1.0)
            proj_info["figure_pixels"] = (0.0, 0.0)
            proj_info["axes_pixels"] = (0.0, 0.0)

        # Record clip geometry
        proj_info["clip_geometries"] = {"plot": self._record_final_clip_geometry()}

        self._recorder.projection_info = proj_info

        try:
            has_gradient = (
                hasattr(self.style, "has_gradient_background")
                and self.style.has_gradient_background()
            )
            bg = (
                "#000000"
                if has_gradient
                else self.style.background_color.as_hex()
            )
            fig_bg = self.style.figure_background_color.as_hex()
        except _RECORDING_ERRORS as e:
            LOGGER.debug("Could not extract style info: %s", e)
            bg = "#ffffff"
            fig_bg = "#ffffff"

        self._recorder.style_info = {
            "background_color": bg,
            "figure_background_color": fig_bg,
            "resolution": getattr(self, "resolution", 2048),
            "dpi": getattr(self, "dpi", 100),
            "plot_scale": getattr(self, "scale", 1.0),
            "show_legend": self._legend is not None,
            "legend_title": (
                self._legend.get_title().get_text()
                if self._legend is not None
                else None
            ),
        }
        if self._legend is not None:
            legend_texts = self._legend.get_texts()
            legend_title = self._legend.get_title()
            frame = self._legend.get_frame()
            self._recorder.style_info.update({
                "legend_labels": list(self._legend_handles.keys()),
                "legend_background_color": _rgba_to_hex(frame.get_facecolor()),
                "legend_border_color": _rgba_to_hex(frame.get_edgecolor()),
                "legend_font_color": (
                    _rgba_to_hex(legend_texts[0].get_color())
                    if legend_texts else "#000000"
                ),
                "legend_font_size": (
                    float(legend_texts[0].get_fontsize())
                    if legend_texts else 11.0
                ),
                "legend_title_font_size": float(legend_title.get_fontsize()),
            })
        magnitude_scale = getattr(self, "_interactive_magnitude_scale", None)
        if magnitude_scale is not None:
            self._recorder.style_info["magnitude_scale"] = magnitude_scale
        try:
            ax_pos = self.ax.get_position()
            fig_width_in, fig_height_in = self.fig.get_size_inches()
            export_dpi = getattr(self, "dpi", 100) or 100
            self._recorder.style_info["source_axes_width"] = float(
                ax_pos.width * fig_width_in * export_dpi
            )
            self._recorder.style_info["source_axes_height"] = float(
                ax_pos.height * fig_height_in * export_dpi
            )
        except _RECORDING_ERRORS as e:
            LOGGER.debug("Could not extract axes width: %s", e)

    def _record_untracked_path_patches(self):
        """Capture user-added patch artists in final data coordinates.

        The public plotting API records its own primitives at call time, but
        Matplotlib also permits legitimate extensions via ``ax.add_patch``.
        Recording those artists here preserves custom marker outlines and
        border circles (e.g. ZenithPlot's horizon) without introducing
        example-specific drawing code.
        """
        try:
            import numpy as np
            from matplotlib.patches import Patch

            recorded = getattr(self, "_recorded_external_patch_ids", set())
            for patch in self.ax.patches:
                if id(patch) in recorded:
                    continue
                if not isinstance(patch, Patch):
                    continue
                if not patch.get_visible():
                    continue
                path = patch.get_path()
                if path.vertices.size == 0:
                    continue

                # Skip the background fill patch — it is handled by the clip
                # geometry and clipped plot background, not as a visible polygon.
                # Background fills have linewidth=0 and fill=True with no gid.
                lw = float(patch.get_linewidth() or 0)
                edge = patch.get_edgecolor()
                has_visible_edge = (
                    lw > 0
                    and edge is not None
                    and not (isinstance(edge, str) and edge.lower() == "none")
                )
                fill = patch.get_fill()
                gid = patch.get_gid()
                if not has_visible_edge and fill and not gid:
                    # Pure background fill, no border — skip.
                    continue
                if not has_visible_edge and not fill:
                    continue

                # Interpolate curved paths (Circle, Ellipse) so the recorded
                # polygon has enough vertices for a smooth Plotly rendering.
                # Estimate the pixel circumference from the transformed patch
                # bounding box and target ~1 pixel segment length.
                codes = path.codes
                has_curves = codes is not None and any(
                    code in (3, 4) for code in codes
                )
                if has_curves and len(path.vertices) < 64:
                    try:
                        import numpy as np
                        vertices = path.vertices
                        # Transform a sampling of vertices to display pixels.
                        # For Circle/Ellipse the extrema are in vertices, so
                        # even a coarse sample bounds the final shape.
                        sample = vertices[:: max(1, len(vertices) // 16)]
                        display = patch.get_transform().transform(sample)
                        widths = display[:, 0]
                        heights = display[:, 1]
                        px_width = float(np.max(widths) - np.min(widths))
                        px_height = float(np.max(heights) - np.min(heights))
                        pixel_radius = max(px_width, px_height) / 2.0
                        circumference = 2.0 * math.pi * max(pixel_radius, 1.0)
                        segment_count = max(64, int(round(circumference)))
                        # matplotlib's interpolated(n) inserts n points per
                        # original segment.  For a Circle there are ~4 segments.
                        original_segments = max(1, len(codes) - 1)
                        steps = max(
                            8,
                            min(2000, segment_count // original_segments),
                        )
                    except _RECORDING_ERRORS as e:
                        LOGGER.debug(
                            "Could not estimate patch interpolation: %s", e
                        )
                        steps = 8
                    path = path.interpolated(steps)

                rings = _transformed_path_rings(
                    self.ax, patch.get_transform(), path.vertices, path.codes
                )
                if not rings:
                    continue

                alpha = patch.get_alpha()
                fc = patch.get_facecolor()
                # Remove embedded alpha from the color strings; Plotly applies
                # the separate `alpha` style as trace/shape opacity, and we
                # don't want to multiply them.
                self._recorder.record_polygon(
                    points=rings[0],
                    rings=rings,
                    style_dict={
                        "fill_color": _rgb_string(fc) if fill else "none",
                        "edge_color": _edge_color_string(edge),
                        "edge_width": lw,
                        "alpha": float(alpha if alpha is not None else 1.0),
                        "line_style": str(patch.get_linestyle()),
                    },
                    gid=gid or "custom-patch",
                    zorder=int(patch.get_zorder() or 0),
                )
                recorded.add(id(patch))
            self._recorded_external_patch_ids = recorded
        except _RECORDING_ERRORS as e:
            LOGGER.debug("Could not record external path patches: %s", e)

    def _record_final_clip_geometry(self):
        """Extract the intersection of Matplotlib's final clipping patches.

        Cartopy's ``ax.patch`` carries the curved projection boundary (for
        example Mollweide), while starplot's ``_background_clip_path`` carries
        any explicit user clip.  Matplotlib applies both.  Recording only the
        latter turns curved maps into rectangles; recording their intersection
        preserves the final artist contract for every backend.
        """
        from starplot.interactive.commands import ClipGeometry

        try:
            from shapely.geometry import Polygon

            polygons = []
            for patch in (
                getattr(self, "_background_clip_path", None),
                getattr(self.ax, "patch", None),
            ):
                if patch is None:
                    continue
                # ``Path.interpolated`` subdivides cubic Bézier *control
                # points* linearly; using it for Circle patches produces an
                # octagonal-looking clip.  Matplotlib's Patch.get_verts()
                # instead returns its renderer-ready, flattened display
                # vertices.  Convert those final vertices back to the Scene's
                # final DATA coordinate space.
                display_verts = patch.get_verts()
                raw_verts = self.ax.transData.inverted().transform(display_verts)
                finite = [
                    (float(x), float(y))
                    for x, y in raw_verts
                    if math.isfinite(x) and math.isfinite(y)
                ]
                if len(finite) > 1 and finite[0] == finite[-1]:
                    finite = finite[:-1]
                if len(finite) >= 3:
                    polygon = Polygon(finite)
                    if polygon.is_valid and not polygon.is_empty:
                        polygons.append(polygon)

            if not polygons:
                return ClipGeometry(kind="none")
            final = polygons[0]
            for polygon in polygons[1:]:
                final = final.intersection(polygon)
            if final.is_empty:
                return ClipGeometry(kind="none")
            if not hasattr(final, "exterior"):
                candidates = [
                    geometry for geometry in getattr(final, "geoms", [])
                    if hasattr(geometry, "exterior")
                ]
                if not candidates:
                    return ClipGeometry(kind="none")
                final = max(candidates, key=lambda geometry: geometry.area)
            points = list(final.exterior.coords)
            if len(points) > 1 and points[0] == points[-1]:
                points = points[:-1]
            kind = "rect" if len(set(points)) == 4 else "polygon"
            return ClipGeometry(kind=kind, points=tuple(points))
        except _CLIP_ERRORS as e:
            LOGGER.warning("Failed to extract clip geometry: %s", e)
            return ClipGeometry(kind="none")

    # ------------------------------------------------------------------
    # Method 1: Stars scatter
    # ------------------------------------------------------------------

    def _scatter_stars(self, ras, decs, sizes, alphas, colors, style=None, **kwargs):
        _raw_legend_label = kwargs.pop("legend_label", "Star")
        legend_label = translate(_raw_legend_label, self.language) or _raw_legend_label
        # Capture values before super() pops them from kwargs.
        requested_zorder = kwargs.get("zorder")
        requested_edgecolors = kwargs.get("edgecolors")
        requested_symbol = kwargs.get("symbol")
        collections_before = len(self.ax.collections)
        result = super()._scatter_stars(ras, decs, sizes, alphas, colors, style, **kwargs)

        ras_list = list(ras)
        n = len(ras_list)

        metadata = []
        # Per-point hover strings dominate both memory and HTML size for
        # million-star catalogs.  Keep every visual point, but reserve rich
        # hover metadata for traces small enough to remain interactive.
        if n <= _MAX_INTERACTIVE_HOVER_POINTS:
            recent_stars = self._objects.stars[-n:] if n > 0 else []
            for s in recent_stars:
                label = ""
                try:
                    label = s.get_label(s) if callable(getattr(s, "get_label", None)) else ""
                except _RECORDING_ERRORS as e:
                    LOGGER.debug("Could not get star label: %s", e)
                metadata.append({
                    "name": label or "",
                    "magnitude": getattr(s, "magnitude", None),
                    "hip": getattr(s, "hip", None),
                    "bayer": getattr(s, "bayer", None),
                    "constellation": getattr(s, "constellation_id", None),
                    "ra": getattr(s, "ra", None),
                    "dec": getattr(s, "dec", None),
                    "type": "star",
                })

        # Extract final DATA coordinates from the newly created Matplotlib
        # artist, matching what Matplotlib actually displays.
        xs, ys = [], []
        if len(self.ax.collections) > collections_before:
            coll = self.ax.collections[collections_before]
            xs, ys = self._artist_offsets_to_final_data(coll)
        if not xs:
            # Fallback: project coordinates directly
            decs_list = list(decs)
            for ra, dec in zip(ras_list, decs_list):
                try:
                    x, y = self._proj.transform_point(ra, dec, self._crs)
                except _RECORDING_ERRORS:
                    x, y = float("nan"), float("nan")
                xs.append(float(x) if math.isfinite(x) else float("nan"))
                ys.append(float(y) if math.isfinite(y) else float("nan"))

        resolved_style = style or self.style.star
        symbol = requested_symbol or getattr(resolved_style.marker, "symbol", "circle")
        symbol = getattr(symbol, "value", symbol)
        edge_color = requested_edgecolors
        if not edge_color:
            if resolved_style.marker.edge_color:
                edge_color = resolved_style.marker.edge_color.as_hex()
            else:
                edge_color = "none"
        zorder = (
            requested_zorder
            if requested_zorder is not None
            else resolved_style.marker.zorder
        )
        style_dict = {
            "symbol": str(symbol),
            "edge_color": edge_color,
            "edge_width": getattr(resolved_style.marker, "edge_width", 0),
            "legend_label": legend_label,
            "fill": getattr(resolved_style.marker, "fill", "full"),
        }
        self._recorder.record_scatter(
            x=xs,
            y=ys,
            sizes=list(sizes),
            colors=colors,
            alphas=alphas,
            metadata=metadata,
            style_dict=style_dict,
            gid=kwargs.get("gid", "stars"),
            zorder=int(zorder),
        )
        return result

    # ------------------------------------------------------------------
    # Method 2: Polygons (milky way, DSO shapes, circles, ellipses, etc.)
    # ------------------------------------------------------------------

    def _polygon(self, points, style, **kwargs):
        patches_before = len(self.ax.patches)
        super()._polygon(points, style, **kwargs)
        try:
            if len(self.ax.patches) <= patches_before:
                return
            patch = self.ax.patches[patches_before]
            path = patch.get_path()
            rings = _transformed_path_rings(
                self.ax, patch.get_transform(), path.vertices, path.codes
            )
            if not rings:
                return
            style_dict = {
                # Strip embedded alpha from fill/edge colors; a separate
                # `alpha` is recorded and applied as Plotly trace opacity.
                "fill_color": _rgb_string(patch.get_facecolor()),
                "edge_color": _edge_color_string(patch.get_edgecolor()),
                "edge_width": float(patch.get_linewidth() or 0),
                "alpha": float(patch.get_alpha() if patch.get_alpha() is not None else 1.0),
                "line_style": str(patch.get_linestyle()),
                "legend_label": kwargs.get("legend_label"),
            }
        except _RECORDING_ERRORS as e:
            LOGGER.debug("Could not extract rendered polygon: %s", e)
            return
        self._recorder.record_polygon(
            points=rings[0],
            rings=rings,
            style_dict=style_dict,
            gid=patch.get_gid() or kwargs.get("gid", "polygon"),
            zorder=int(patch.get_zorder() or 0),
        )
        self._recorded_external_patch_ids = getattr(
            self, "_recorded_external_patch_ids", set()
        ) | {id(patch)}

    # ------------------------------------------------------------------
    # Method 3: Text labels (only records labels that survive collision detection)
    # ------------------------------------------------------------------

    def _text(self, x, y, text, **kwargs):
        result = super()._text(x, y, text, **kwargs)
        if result is not None:
            # _text_point() has already called _prepare_coords(). For Horizon
            # and Optic plots this means x/y are AZ/ALT (prepared coordinates),
            # so use the "prepared" source space to avoid double-conversion.
            px, py = self._to_final_data(x, y, source_space="prepared")

            # Extract final placement properties from the Annotation
            xytext = kwargs.get("xytext", (0, 0))
            rotation = kwargs.get("rotation", 0.0)
            # Read actual values from the annotation if available
            if hasattr(result, "get_rotation"):
                try:
                    rotation = float(result.get_rotation())
                except _RECORDING_ERRORS:
                    pass

            from starplot.interactive.commands import DrawingCommand, CoordinateSpace
            stroke_style = {}
            for effect in kwargs.get("path_effects", ()):
                gc = getattr(effect, "_gc", {})
                if gc.get("foreground") is not None and gc.get("linewidth"):
                    stroke_style = {
                        "stroke_color": _rgba_to_hex(gc["foreground"]),
                        "stroke_width": float(gc["linewidth"]),
                    }
                    break
            cmd = DrawingCommand(
                kind="text",
                data={
                    "text": str(text),
                    "x": px,
                    "y": py,
                    "offset_points": (float(xytext[0]), float(xytext[1])),
                },
                style={
                    "font_size": kwargs.get("fontsize", 12),
                    "font_color": kwargs.get("color", "#ffffff"),
                    "font_weight": kwargs.get("weight", "normal"),
                    "font_name": kwargs.get("fontname", "Inter"),
                    "ha": kwargs.get("ha", "center"),
                    "va": kwargs.get("va", "center"),
                    "alpha": kwargs.get("alpha", 1.0),
                    "rotation": float(rotation),
                    **stroke_style,
                },
                gid=kwargs.get("gid", "text"),
                zorder=kwargs.get("zorder", 0),
                space=CoordinateSpace.DATA,
                clip_id=None,
            )
            self._recorder.commands.append(cmd)

            # Patch remove(): _text_point calls _text once for bbox measurement;
            # if collision detected, it calls label.remove() and tries another
            # position.  Without this patch the first (failed) placement would
            # stay recorded.  By removing the DrawingCommand when the annotation
            # is removed we keep only the final, successfully-placed label.
            original_remove = result.remove
            def _patched_remove(*, _cmd=cmd, _orig=original_remove):
                try:
                    self._recorder.commands.remove(_cmd)
                except ValueError:
                    pass  # already removed or never added
                _orig()
            result.remove = _patched_remove

        return result

    # ------------------------------------------------------------------
    # Method 4: Generic line segments (ecliptic, celestial equator, etc.)
    # ------------------------------------------------------------------

    def line(self, style, coordinates=None, geometry=None, **kwargs):
        lines_before = len(self.ax.lines)
        super().line(style=style, coordinates=coordinates, geometry=geometry, **kwargs)
        try:
            self.fig.canvas.draw()
            segments = []
            artists = self.ax.lines[lines_before:]
            for artist in artists:
                path = artist.get_path()
                segments.extend(_transformed_path_segments(
                    self.ax, artist.get_transform(), path.vertices, path.codes
                ))
            if segments and artists:
                artist = artists[0]
                self._recorder.record_line_collection(
                    lines=segments,
                    style_dict={
                        "color": _rgba_to_hex(artist.get_color()),
                        "width": float(artist.get_linewidth()),
                        "line_style": artist.get_linestyle(),
                        "alpha": (
                            artist.get_alpha()
                            if artist.get_alpha() is not None
                            else 1.0
                        ),
                    },
                    metadata=[{"type": "line"} for _ in segments],
                    gid=kwargs.get("gid", "line"),
                    zorder=int(artist.get_zorder()),
                )
        except _RECORDING_ERRORS as e:
            LOGGER.warning("Failed to record line (gid=%s): %s", kwargs.get("gid", "line"), e)

    # ------------------------------------------------------------------
    # Method 4.5: Marker
    # ------------------------------------------------------------------

    @use_style(ObjectStyle)
    def marker(
        self,
        ra: float,
        dec: float,
        style: ObjectStyle,
        label: Optional[str] = None,
        legend_label: str = None,
        skip_bounds_check: bool = False,
        collision_handler=None,
        **kwargs,
    ) -> None:
        """Record a scatter command for every marker call.

        Extracts the final DATA-space position from the Matplotlib artist
        created by super().marker(), ensuring the recorded coordinate
        matches what Matplotlib actually displays.
        """
        collections_before = len(self.ax.collections)
        super().marker(
            ra=ra,
            dec=dec,
            style=style,
            label=label,
            legend_label=legend_label,
            skip_bounds_check=skip_bounds_check,
            collision_handler=collision_handler,
            **kwargs,
        )

        if not skip_bounds_check and not self.in_bounds(ra, dec):
            return

        # Extract final DATA coordinates from the newly created artist
        if len(self.ax.collections) <= collections_before:
            return
        coll = self.ax.collections[collections_before]
        xs, ys = self._artist_offsets_to_final_data(coll)
        if not xs:
            return
        x, y = xs[0], ys[0]
        if not (math.isfinite(x) and math.isfinite(y)):
            return

        style_kwargs = style.marker.matplot_scatter_kwargs(self.scale)
        facecolors = coll.get_facecolors()
        edgecolors = coll.get_edgecolors()
        linewidths = coll.get_linewidths()
        artist_sizes = coll.get_sizes()
        face_color = (
            _rgba_to_hex(facecolors[0]) if len(facecolors)
            else _rgba_to_hex(style_kwargs.get("c", "none"))
        )
        edge_color = (
            _rgba_to_hex(edgecolors[0]) if len(edgecolors)
            else _rgba_to_hex(style_kwargs.get("edgecolors", "none"))
        )
        face_alpha = float(facecolors[0][3]) if len(facecolors) else 0.0
        collection_alpha = coll.get_alpha()
        alpha = float(collection_alpha if collection_alpha is not None else face_alpha)
        style_dict = {
            "symbol": str(getattr(style.marker.symbol, "value", style.marker.symbol)),
            "edge_color": edge_color,
            "edge_width": float(linewidths[0]) if len(linewidths) else 0.0,
            "fill": "full" if face_alpha > 0 else "none",
            "legend_label": legend_label,
        }

        self._recorder.record_scatter(
            x=[x],
            y=[y],
            sizes=[float(artist_sizes[0]) if len(artist_sizes) else style_kwargs.get("s", 22)],
            colors=[face_color],
            alphas=[alpha],
            metadata=[{"type": "marker", "name": label or ""}],
            style_dict=style_dict,
            gid=kwargs.get("gid_marker") or "marker",
            zorder=int(
                style_kwargs.get("zorder")
                if style_kwargs.get("zorder") is not None
                else style.marker.zorder
            ),
        )

    # ------------------------------------------------------------------
    # Method 4.6: Gridlines (MapPlot and HorizonPlot)
    # ------------------------------------------------------------------

    @use_style(PathStyle, "gridlines")
    def gridlines(self, *args, **kwargs):
        """Record gridlines for MapPlot and HorizonPlot."""
        super().gridlines(*args, **kwargs)

        try:
            style = kwargs.get("style") or self.style.gridlines

            from starplot.plots.horizon import HorizonPlot
            from starplot.plots.map import MapPlot

            if isinstance(self, HorizonPlot):
                # Cartopy's Gridliner has already applied HorizonPlot's
                # azimuth -180° conversion, clipping, label padding, and
                # formatter.  Rebuilding these curves from user locations
                # loses those semantics.  Extract final rendered segments.
                self.fig.canvas.draw()
                gridliner = next(
                    (artist for artist in self.ax.artists
                     if type(artist).__name__ == "Gridliner"),
                    None,
                )
                if gridliner is None:
                    raise RuntimeError("Horizon gridliner artist was not created")

                lines = []
                for collection in [*gridliner.xline_artists, *gridliner.yline_artists]:
                    for segment in collection.get_segments():
                        lines.extend(_transformed_path_segments(
                            self.ax, collection.get_transform(), segment
                        ))

                if lines:
                    self._recorder.record_line_collection(
                        lines=lines,
                        style_dict={
                            "color": style.line.color.as_hex(),
                            "width": style.line.width,
                            "alpha": style.line.alpha,
                            "line_style": str(style.line.style),
                        },
                        gid="gridlines",
                        zorder=int(style.line.zorder or 0),
                        metadata=[{"type": "gridline"} for _ in lines],
                    )

                for label in gridliner.label_artists:
                    if not label.get_visible() or not label.get_text():
                        continue
                    bbox = label.get_window_extent(self.fig.canvas.get_renderer())
                    x, y = self.fig.transFigure.inverted().transform(
                        (bbox.x0 + bbox.width / 2, bbox.y0 + bbox.height / 2)
                    )
                    # HorizonPlot supplies lower azimuth labels separately
                    # below.  Gridliner's copies live at negative figure-y
                    # values, which Plotly clips; recording both creates a
                    # duplicate/off-canvas annotation pair.
                    if y < 0:
                        continue
                    self._recorder.record_text(
                        text=label.get_text(), x=x, y=y,
                        style_dict={
                            "font_size": label.get_fontsize(),
                            "font_color": _rgba_to_hex(label.get_color()),
                            "font_alpha": float(label.get_alpha() or 1.0),
                            "font_weight": label.get_fontweight(),
                            "font_name": label.get_fontname() or "Inter",
                            "ha": label.get_horizontalalignment(),
                            "va": label.get_verticalalignment(),
                        },
                        gid="gridlines-label",
                        zorder=int(style.label.zorder or 0),
                        space=CoordinateSpace.PAPER,
                    )

                # Gridliner does not expose HorizonPlot's lower azimuth labels,
                # divider, and tick annotations as label artists.  These are
                # separate axes-coordinate artists in HorizonPlot.gridlines().
                show_labels = kwargs.get("show_labels")
                if show_labels is None:
                    show_labels = ["left", "right", "bottom"]
                az_locations = kwargs.get("az_locations") or list(range(0, 360, 15))
                az_formatter = kwargs.get("az_formatter_fn") or (lambda az: f"{round(az)}° ")
                if "bottom" in show_labels:
                    for azimuth in az_locations:
                        if not (self.az[0] <= azimuth <= self.az[1]
                                or self.az[0] <= azimuth + 360 <= self.az[1]):
                            continue
                        x, _ = self._to_ax(azimuth, self.alt[0])
                        if not math.isfinite(x):
                            continue
                        self._recorder.record_text(
                            text=str(az_formatter(azimuth)), x=x,
                            y=-0.02 * self.scale,
                            style_dict={
                                "font_size": style.label.font_size,
                                "font_color": style.label.font_color.as_hex(),
                                "font_alpha": style.label.font_alpha,
                                "font_weight": style.label.font_weight,
                                "font_name": style.label.font_name,
                                "ha": "center", "va": "center", "footer": True,
                            },
                            gid="gridlines-label",
                            zorder=int(style.label.zorder or 0),
                            space=CoordinateSpace.PAPER,
                        )

                if kwargs.get("divider_line", True):
                    self._recorder.record_polygon(
                        points=[(0.0, -0.04 * self.scale), (1.0, -0.04 * self.scale),
                                (1.0, -0.041 * self.scale), (0.0, -0.041 * self.scale)],
                        style_dict={"fill_color": style.label.font_color.as_hex(),
                                    "edge_color": "none", "edge_width": 0,
                                    "alpha": 1.0, "footer": True},
                        gid="gridlines-divider", zorder=int(style.label.zorder or 0),
                        space=CoordinateSpace.PAPER, clip_id=None,
                    )
                return

            if isinstance(self, MapPlot):
                # MapPlot delegates all seam handling, polar redraws, edge
                # visibility and label placement to Cartopy's Gridliner.
                # Sampling RA/DEC ourselves loses those decisions, so replay
                # the artists Cartopy actually produced.
                self.fig.canvas.draw()
                gridliner = next(
                    (artist for artist in self.ax.artists
                     if type(artist).__name__ == "Gridliner"),
                    None,
                )
                if gridliner is None:
                    raise RuntimeError("Map gridliner artist was not created")

                lines = []
                for collection in [*gridliner.xline_artists, *gridliner.yline_artists]:
                    for segment in collection.get_segments():
                        lines.extend(_transformed_path_segments(
                            self.ax, collection.get_transform(), segment
                        ))
                # Near-polar MapPlot redraws missing RA lines with ax.plot().
                # They have the same gid and are already fully transformed.
                for artist in self.ax.lines:
                    if artist.get_gid() != "gridlines":
                        continue
                    path = artist.get_path()
                    lines.extend(_transformed_path_segments(
                        self.ax, artist.get_transform(), path.vertices, path.codes
                    ))

                if lines:
                    self._recorder.record_line_collection(
                        lines=lines,
                        style_dict={
                            "color": style.line.color.as_hex(),
                            "width": style.line.width,
                            "alpha": style.line.alpha,
                            "line_style": str(style.line.style),
                        },
                        gid="gridlines",
                        zorder=int(style.line.zorder or 0),
                        metadata=[{"type": "gridline"} for _ in lines],
                    )

                for label in gridliner.label_artists:
                    if not label.get_visible() or not label.get_text():
                        continue
                    bbox = label.get_window_extent(self.fig.canvas.get_renderer())
                    x, y = self.fig.transFigure.inverted().transform(
                        (bbox.x0 + bbox.width / 2, bbox.y0 + bbox.height / 2)
                    )
                    self._recorder.record_text(
                        text=label.get_text(), x=x, y=y,
                        style_dict={
                            "font_size": label.get_fontsize(),
                            "font_color": _rgba_to_hex(label.get_color()),
                            "font_alpha": float(label.get_alpha() or 1.0),
                            "font_weight": label.get_fontweight(),
                            "font_name": label.get_fontname() or "Inter",
                            "ha": label.get_horizontalalignment(),
                            "va": label.get_verticalalignment(),
                        },
                        gid="gridlines-label",
                        zorder=int(style.label.zorder or 0),
                        space=CoordinateSpace.PAPER,
                    )
                return

            show_labels = kwargs.get("show_labels")
            if show_labels is None:
                show_labels = (
                    ["left", "right", "bottom"]
                    if isinstance(self, HorizonPlot)
                    else True
                )
            labels_enabled = bool(show_labels)

            lines = []
            label_texts = []

            if isinstance(self, HorizonPlot):
                az = self.az
                alt = self.alt
                az_locations = kwargs.get("az_locations") or [x for x in range(0, 360, 15)]
                alt_locations = kwargs.get("alt_locations") or [d for d in range(-90, 90, 10)]
                az_formatter_fn = kwargs.get("az_formatter_fn") or (lambda a: f"{round(a)}\u00b0 ")
                alt_formatter_fn = kwargs.get("alt_formatter_fn") or (lambda a: f"{round(a)}\u00b0 ")

                # Azimuth lines (constant az, alt varies)
                for az_val in az_locations:
                    if not (az[0] <= az_val <= az[1] or az[0] <= az_val + 360 <= az[1]):
                        continue
                    alts = [alt[0] + (alt[1] - alt[0]) * i / 60 for i in range(61)]
                    points = [self._proj.transform_point(az_val, a, self._crs) for a in alts]
                    segs = _split_points(points)
                    for seg in segs:
                        lines.append(seg)

                # Altitude lines (constant alt, az varies)
                for alt_val in alt_locations:
                    if not (alt[0] <= alt_val <= alt[1]):
                        continue
                    azs = [az[0] + (az[1] - az[0]) * i / 60 for i in range(61)]
                    points = [self._proj.transform_point(a, alt_val, self._crs) for a in azs]
                    segs = _split_points(points)
                    for seg in segs:
                        lines.append(seg)

            elif isinstance(self, MapPlot):
                ra_min = self.ra_min
                ra_max = self.ra_max
                dec_min = self.dec_min
                dec_max = self.dec_max
                ra_locations = kwargs.get("ra_locations") or [x for x in range(0, 360, 15)]
                dec_locations = kwargs.get("dec_locations") or [d for d in range(-80, 90, 10)]
                ra_formatter_fn = kwargs.get("ra_formatter_fn") or (lambda r: f"{math.floor(r)}h")
                dec_formatter_fn = kwargs.get("dec_formatter_fn") or (lambda d: f"{round(d)}\u00b0 ")

                # RA meridians (constant RA, dec varies)
                for ra_val in ra_locations:
                    decs = [dec_min + (dec_max - dec_min) * i / 60 for i in range(61)]
                    points = [self._to_final_data(ra_val, d, source_space="radec") for d in decs]
                    segs = _split_points(points)
                    for seg in segs:
                        lines.append(seg)
                        if labels_enabled:
                            label_texts.append(
                                (seg[0][0], seg[0][1], ra_formatter_fn(ra_val))
                            )

                # DEC parallels (constant dec, ra varies)
                for dec_val in dec_locations:
                    ras = [ra_min + (ra_max - ra_min) * i / 60 for i in range(61)]
                    points = [self._to_final_data(r, dec_val, source_space="radec") for r in ras]
                    segs = _split_points(points)
                    for seg in segs:
                        lines.append(seg)
                        if labels_enabled:
                            label_texts.append(
                                (seg[0][0], seg[0][1], dec_formatter_fn(dec_val))
                            )

            if lines:
                self._recorder.record_line_collection(
                    lines=lines,
                    style_dict={
                        "color": style.line.color.as_hex(),
                        "width": style.line.width,
                        "alpha": style.line.alpha,
                        "line_style": str(style.line.style),
                    },
                    gid="gridlines",
                    zorder=int(style.line.zorder or 0),
                    metadata=[{"type": "gridline"} for _ in lines],
                )

            if labels_enabled:
                if isinstance(self, HorizonPlot):
                    label_style = {
                        "font_size": style.label.font_size,
                        "font_color": style.label.font_color.as_hex(),
                        "font_alpha": style.label.font_alpha,
                        "font_weight": style.label.font_weight,
                        "font_style": style.label.font_style,
                        "font_name": style.label.font_name,
                        "xref": "paper",
                        "yref": "paper",
                    }
                    for alt_val in alt_locations:
                        if not (alt[0] <= alt_val <= alt[1]):
                            continue
                        _, y = self._to_ax(az[0], alt_val)
                        if not math.isfinite(y):
                            continue
                        text = str(alt_formatter_fn(alt_val))
                        if "left" in show_labels:
                            self._recorder.record_text(
                                text=text, x=0, y=y,
                                style_dict={**label_style, "ha": "right", "va": "center", "xshift": -12},
                                gid="gridlines-label", zorder=int(style.label.zorder or 0),
                                space=CoordinateSpace.PAPER,
                            )
                        if "right" in show_labels:
                            self._recorder.record_text(
                                text=text, x=1, y=y,
                                style_dict={**label_style, "ha": "left", "va": "center", "xshift": 12},
                                gid="gridlines-label", zorder=int(style.label.zorder or 0),
                                space=CoordinateSpace.PAPER,
                            )
                    if "bottom" in show_labels:
                        for az_val in az_locations:
                            if not (az[0] <= az_val <= az[1] or az[0] <= az_val + 360 <= az[1]):
                                continue
                            x, _ = self._to_ax(az_val, alt[0])
                            if not math.isfinite(x):
                                continue
                            self._recorder.record_text(
                                text=str(az_formatter_fn(az_val)), x=x, y=-0.02 * self.scale,
                                style_dict={**label_style, "ha": "center", "va": "center", "footer": True},
                                gid="gridlines-label", zorder=int(style.label.zorder or 0),
                                space=CoordinateSpace.PAPER,
                            )
                for x, y, text in label_texts:
                    if not math.isfinite(x) or not math.isfinite(y) or not text:
                        continue
                    self._recorder.record_text(
                        text=str(text),
                        x=x,
                        y=y,
                        style_dict={
                            "font_size": style.label.font_size,
                            "font_color": style.label.font_color.as_hex(),
                            "font_alpha": style.label.font_alpha,
                            "font_weight": style.label.font_weight,
                            "font_style": style.label.font_style,
                            "font_name": style.label.font_name,
                        },
                        gid="gridlines-label",
                        zorder=int(style.label.zorder or 0),
                        space=CoordinateSpace.DATA,
                    )
        except _GRIDLINE_ERRORS as e:
            LOGGER.warning("Failed to record gridlines: %s", e)

    # ------------------------------------------------------------------
    # Method 5: Constellation lines (re-extract line data after super() renders)
    # ------------------------------------------------------------------

    def constellations(self, style=None, where=None, sql=None, catalog=None, **kwargs):
        collections_before = len(self.ax.collections)
        # Let matplotlib render fully first
        kw = {k: v for k, v in {"style": style, "where": where, "sql": sql, "catalog": catalog}.items() if v is not None}
        super().constellations(**kw, **kwargs)

        # Cartopy performs seam splitting and extent clipping while drawing the
        # LineCollection.  Rebuilding each source star pair here joins points
        # across the RA 0°/360° seam, creating a line through the whole Plotly
        # chart.  Extract the final artist segments instead.
        try:
            from matplotlib.collections import LineCollection

            self.fig.canvas.draw()
            segments = []
            for collection in self.ax.collections[collections_before:]:
                if not isinstance(collection, LineCollection):
                    continue
                for segment in collection.get_segments():
                    segments.extend(_transformed_path_segments(
                        self.ax, collection.get_transform(), segment
                    ))
        except _RECORDING_ERRORS as e:
            LOGGER.warning("Failed to extract rendered constellation lines: %s", e)
            return

        if segments:
            resolved_style = style or self.style.constellation_lines
            self._recorder.record_line_collection(
                lines=segments,
                style_dict={
                    "color": resolved_style.color.as_hex(),
                    "width": resolved_style.width,
                    "alpha": resolved_style.alpha,
                },
                metadata=[{"type": "constellation"} for _ in segments],
                gid="constellations-line",
                zorder=resolved_style.zorder,
            )

    # ------------------------------------------------------------------
    # Method 5.5: Constellation borders
    # ------------------------------------------------------------------

    @use_style(LineStyle, "constellation_borders")
    def constellation_borders(self, style=None, catalog=None, **kwargs):
        """Record constellation borders as a line collection."""
        collections_before = len(self.ax.collections)
        # Do not turn the base method's default catalog into an explicit
        # ``None``.  This mirrors the public constellation-lines wrapper and
        # preserves the base plotting contract when callers omit ``catalog``.
        base_kwargs = {"style": style}
        if catalog is not None:
            base_kwargs["catalog"] = catalog
        super().constellation_borders(**base_kwargs, **kwargs)

        try:
            from matplotlib.collections import LineCollection
            self.fig.canvas.draw()
            border_lines = []
            for collection in self.ax.collections[collections_before:]:
                if not isinstance(collection, LineCollection):
                    continue
                for segment in collection.get_segments():
                    border_lines.extend(_transformed_path_segments(
                        self.ax, collection.get_transform(), segment
                    ))

            if border_lines:
                resolved_style = style or self.style.constellation_borders
                self._recorder.record_line_collection(
                    lines=border_lines,
                    style_dict={
                        "color": resolved_style.color.as_hex(),
                        "width": resolved_style.width,
                        "alpha": resolved_style.alpha,
                        "line_style": str(resolved_style.style),
                    },
                    metadata=[{"type": "constellation-border"} for _ in border_lines],
                    gid="constellations-border",
                    zorder=int(resolved_style.zorder or 0),
                )
        except _RECORDING_ERRORS as e:
            LOGGER.warning("Failed to record constellation borders: %s", e)

    # ------------------------------------------------------------------
    # Method 6: Ecliptic line
    # ------------------------------------------------------------------

    def ecliptic(self, style=None, label="ECLIPTIC", collision_handler=None):
        lines_before = len(self.ax.lines)
        super().ecliptic(style=style, label=label, collision_handler=collision_handler)
        resolved_style = style or self.style.ecliptic
        self._record_rendered_line_artists(
            lines_before, resolved_style.line, "ecliptic-line"
        )

    # ------------------------------------------------------------------
    # Method 7: Celestial equator
    # ------------------------------------------------------------------

    def celestial_equator(
        self, style=None, label=None, num_labels=1, collision_handler=None
    ):
        lines_before = len(self.ax.lines)
        equator_kwargs = {
            "style": style,
            "num_labels": num_labels,
            "collision_handler": collision_handler,
        }
        if label is not None:
            equator_kwargs["label"] = label
        super().celestial_equator(**equator_kwargs)
        resolved_style = style or self.style.celestial_equator
        self._record_rendered_line_artists(
            lines_before, resolved_style.line,
            "celestial-equator-line",
        )

    def _record_rendered_line_artists(self, lines_before, style, gid):
        """Record final Cartopy-split ``Line2D`` artists created by a method."""
        try:
            self.fig.canvas.draw()
            segments = []
            artists = self.ax.lines[lines_before:]
            for artist in artists:
                path = artist.get_path()
                segments.extend(_transformed_path_segments(
                    self.ax, artist.get_transform(), path.vertices, path.codes
                ))
            if segments and artists:
                artist = artists[0]
                self._recorder.record_line_collection(
                    lines=segments,
                    style_dict={
                        "color": _rgba_to_hex(artist.get_color()),
                        "width": float(artist.get_linewidth()),
                        "line_style": artist.get_linestyle(),
                        "alpha": (
                            artist.get_alpha()
                            if artist.get_alpha() is not None
                            else 1.0
                        ),
                    },
                    metadata=[{"type": "line"} for _ in segments],
                    gid=gid,
                    zorder=int(artist.get_zorder()),
                )
        except _RECORDING_ERRORS as e:
            LOGGER.warning("Failed to record rendered line artists (gid=%s): %s", gid, e)

    # ------------------------------------------------------------------
    # Method 8: Horizon (MapPlot great circle, HorizonPlot bar, ZenithPlot circle)
    # ------------------------------------------------------------------

    @use_style(PathStyle, "horizon")
    def horizon(self, style=None, labels=None, **kwargs):
        """Record horizon elements for MapPlot, HorizonPlot, and ZenithPlot."""
        patches_before = len(self.ax.patches)
        texts_before = len(self.ax.texts)
        horizon_kwargs = {"style": style}
        if labels is not None:
            horizon_kwargs["labels"] = labels
        super().horizon(**horizon_kwargs, **kwargs)

        try:
            from starplot.plots.horizon import (
                HorizonPlot,
                DEFAULT_HORIZON_LABELS,
            )
            from starplot.plots.map import MapPlot
            from starplot.plots.zenith import ZenithPlot
            from starplot.data.translations import translate
            from starplot import geometry

            resolved_style = style or self.style.horizon

            if isinstance(self, HorizonPlot):
                labels = labels or DEFAULT_HORIZON_LABELS
                patch_y = -0.11 * self.scale

                # Bottom bar polygon in axes coordinates
                self._recorder.record_polygon(
                    points=[
                        (0, -0.04 * self.scale),
                        (1, -0.04 * self.scale),
                        (1, patch_y),
                        (0, patch_y),
                        (0, -0.04 * self.scale),
                    ],
                    style_dict={
                        "fill_color": resolved_style.line.color.as_hex(),
                        "edge_color": resolved_style.line.color.as_hex(),
                        "edge_width": 0,
                        "alpha": 1.0,
                        "xref": "paper",
                        "yref": "paper",
                    },
                    gid="horizon-bottom",
                    zorder=int(resolved_style.line.zorder or 0),
                    space=CoordinateSpace.PAPER,
                    clip_id=None,
                )

                # Cardinal/azimuth labels in axes coordinates
                if labels:
                    for az, label in labels.items():
                        az = int(az)
                        x, _ = self._to_ax(az, self.alt[0])
                        if x <= 0.03 or x >= 0.97 or math.isnan(x):
                            continue
                        self._recorder.record_text(
                            text=str(label),
                            x=x,
                            y=patch_y + 0.027,
                            style_dict={
                                "font_size": resolved_style.label.font_size,
                                "font_color": resolved_style.label.font_color.as_hex(),
                                "font_alpha": resolved_style.label.font_alpha,
                                "font_weight": resolved_style.label.font_weight,
                                "font_style": resolved_style.label.font_style,
                                "font_name": resolved_style.label.font_name,
                                "xref": "paper",
                                "yref": "paper",
                                "ha": "center",
                                "va": "center",
                            },
                            gid="horizon-label",
                            zorder=int(resolved_style.label.zorder or 0),
                            space=CoordinateSpace.PAPER,
                        )

            # ZenithPlot subclasses MapPlot, but its Matplotlib horizon is an
            # axes-space circle with fixed cardinal labels.  Exclude it from
            # the generic MapPlot great-circle branch so the replay uses the
            # same geometry and label positions as ZenithPlot.horizon().
            elif isinstance(self, MapPlot) and not isinstance(self, ZenithPlot):
                from skyfield.api import wgs84

                if self.observer is None:
                    return

                geographic = wgs84.latlon(
                    latitude_degrees=self.observer.lat,
                    longitude_degrees=self.observer.lon,
                )
                observer = geographic.at(self.observer.timescale)
                zenith = observer.from_altaz(alt_degrees=90, az_degrees=0)
                ra, dec, _ = zenith.radec()

                polygon = geometry.ellipse(
                    center=(ra.hours * 15, dec.degrees),
                    height_degrees=180,
                    width_degrees=180,
                    num_pts=100,
                )
                points = list(zip(*polygon.exterior.coords.xy))
                projected = [self._to_final_data(ra, dec, source_space="radec") for ra, dec in points]
                xs = [p[0] for p in projected if math.isfinite(p[0]) and math.isfinite(p[1])]
                ys = [p[1] for p in projected if math.isfinite(p[0]) and math.isfinite(p[1])]

                if xs:
                    self._recorder.record_line(
                        x=xs,
                        y=ys,
                        style_dict={
                            "color": resolved_style.line.color.as_hex(),
                            "width": resolved_style.line.width,
                            "line_style": str(resolved_style.line.style),
                            "alpha": resolved_style.line.alpha,
                        },
                        gid="horizon-circle",
                        zorder=int(resolved_style.line.zorder or 0),
                    )

                if labels:
                    labels = [translate(label, self.language) for label in labels]
                    cardinal_directions = [
                        observer.from_altaz(alt_degrees=0, az_degrees=0),
                        observer.from_altaz(alt_degrees=0, az_degrees=90),
                        observer.from_altaz(alt_degrees=0, az_degrees=180),
                        observer.from_altaz(alt_degrees=0, az_degrees=270),
                    ]
                    for label, position in zip(labels, cardinal_directions):
                        ra, dec, _ = position.radec()
                        x, y = self._to_final_data(ra.hours * 15, dec.degrees, source_space="radec")
                        if not math.isfinite(x) or not math.isfinite(y):
                            continue
                        self._recorder.record_text(
                            text=str(label),
                            x=x,
                            y=y,
                            style_dict={
                                "font_size": resolved_style.label.font_size,
                                "font_color": resolved_style.label.font_color.as_hex(),
                                "font_alpha": resolved_style.label.font_alpha,
                                "font_weight": resolved_style.label.font_weight,
                                "font_style": resolved_style.label.font_style,
                                "font_name": resolved_style.label.font_name,
                                "ha": "center",
                                "va": "center",
                            },
                            gid="horizon-label",
                            zorder=int(resolved_style.label.zorder or 0),
                            space=CoordinateSpace.DATA,
                        )

            elif isinstance(self, ZenithPlot):
                horizon_patch = (
                    self.ax.patches[patches_before]
                    if len(self.ax.patches) > patches_before
                    else None
                )

                # Derive the horizon circle in data coordinates from the
                # Matplotlib patch (ZenithPlot.horizon places a Circle with
                # radius 0.454 in axes coordinates).  This avoids hard-coding
                # the ratio between axes fractions and data units.
                xlim = self.ax.get_xlim()
                ylim = self.ax.get_ylim()
                if horizon_patch is not None:
                    # The patch is created with transform=self.ax.transAxes and
                    # center/radius in axes fractions.  Convert via transAxes
                    # directly; using horizon_patch.get_transform() would apply
                    # the patch's local Affine2D pre-transform and shift the
                    # center off the axes origin.
                    inv_data = self.ax.transData.inverted()
                    center = inv_data.transform(self.ax.transAxes.transform(horizon_patch.center))
                    edge = inv_data.transform(
                        self.ax.transAxes.transform(
                            (horizon_patch.center[0] + horizon_patch.radius, horizon_patch.center[1])
                        )
                    )
                    center_x, center_y = float(center[0]), float(center[1])
                    radius = math.hypot(edge[0] - center_x, edge[1] - center_y)
                else:
                    # Fallback if the patch is missing for any reason.
                    center_x = (xlim[0] + xlim[1]) / 2
                    center_y = (ylim[0] + ylim[1]) / 2
                    radius = (xlim[1] - xlim[0]) / 2 * 0.454 / 0.5

                import numpy as np
                theta = np.linspace(0, 2 * np.pi, 100)
                circle_x = center_x + radius * np.cos(theta)
                circle_y = center_y + radius * np.sin(theta)

                # The plotted horizon patch is used by Matplotlib for both the
                # visible ring and the outer clip boundary.  Record it as a
                # Plotly line so the ring is drawn once in data coordinates; add
                # the patch to the recorded set so _record_untracked_path_patches
                # does not render it again.
                if horizon_patch is not None:
                    recorded = getattr(self, "_recorded_external_patch_ids", set())
                    recorded.add(id(horizon_patch))
                    self._recorded_external_patch_ids = recorded

                self._recorder.record_line(
                    x=list(circle_x),
                    y=list(circle_y),
                    style_dict={
                        "color": (
                            _rgba_to_hex(horizon_patch.get_edgecolor())
                            if horizon_patch is not None
                            else resolved_style.line.color.as_hex()
                        ),
                        "width": (
                            float(horizon_patch.get_linewidth())
                            if horizon_patch is not None
                            else resolved_style.line.width
                        ),
                        "line_style": str(resolved_style.line.style),
                        "alpha": (
                            horizon_patch.get_alpha()
                            if horizon_patch is not None
                            and horizon_patch.get_alpha() is not None
                            else resolved_style.line.alpha
                        ),
                    },
                    gid="horizon-circle",
                    zorder=int(resolved_style.line.zorder or 0),
                    # ZenithPlot.horizon() explicitly uses clip_on=False: the
                    # thick ring sits just outside the map boundary and must
                    # remain behind the cardinal labels.
                    clip_id=None,
                )

                label_artists = self.ax.texts[texts_before:]
                if label_artists:
                    for artist in label_artists:
                        ax_x, ax_y = artist.xy
                        data_x = xlim[0] + (xlim[1] - xlim[0]) * ax_x
                        data_y = ylim[0] + (ylim[1] - ylim[0]) * ax_y
                        font_family = artist.get_fontfamily()
                        self._recorder.record_text(
                            text=artist.get_text(),
                            x=data_x,
                            y=data_y,
                            style_dict={
                                "font_size": float(artist.get_fontsize()),
                                "font_color": _rgba_to_hex(artist.get_color()),
                                "font_alpha": (
                                    artist.get_alpha()
                                    if artist.get_alpha() is not None
                                    else 1.0
                                ),
                                "font_weight": artist.get_fontweight(),
                                "font_style": artist.get_fontstyle(),
                                "font_name": (
                                    font_family[0]
                                    if font_family
                                    else resolved_style.label.font_name
                                ),
                                "ha": artist.get_horizontalalignment(),
                                "va": artist.get_verticalalignment(),
                            },
                            gid="horizon-label",
                            zorder=int(artist.get_zorder()),
                            space=CoordinateSpace.DATA,
                        )
        except _RECORDING_ERRORS as e:
            LOGGER.debug("Could not record horizon: %s", e)

    # ------------------------------------------------------------------
    # Method 8.3: Arrow
    # ------------------------------------------------------------------

    @use_style(ArrowStyle, "arrow")
    def arrow(
        self,
        origin: tuple[float, float] = None,
        target: tuple[float, float] = None,
        style: ArrowStyle = None,
        scale: float = 0.99,
        length: float = 5,
        max_attempts: int = 100,
        **kwargs,
    ):
        """Record the arrow polygon in axes coordinates."""
        patches_before = len(self.ax.patches)
        super().arrow(
            origin=origin,
            target=target,
            style=style,
            scale=scale,
            length=length,
            max_attempts=max_attempts,
            **kwargs,
        )

        try:
            if len(self.ax.patches) <= patches_before:
                return
            arrow_patch = self.ax.patches[patches_before]
            points = [
                (float(x), float(y))
                for x, y in arrow_patch.get_xy()
            ]
            # Capture the actual rendered linewidth/scaled style from the patch
            # so the Plotly trace matches Matplotlib, not the unscaled style.
            self._recorder.record_polygon(
                points=points,
                style_dict={
                    "fill_color": style.fill_color.as_hex() if style.fill_color else None,
                    "edge_color": style.edge_color.as_hex() if style.edge_color else None,
                    "edge_width": float(arrow_patch.get_linewidth() or 0),
                    "alpha": float(
                        arrow_patch.get_alpha()
                        if arrow_patch.get_alpha() is not None
                        else 1.0
                    ),
                    "line_style": str(arrow_patch.get_linestyle()),
                    "legend_label": kwargs.get("legend_label"),
                },
                gid=kwargs.get("gid") or "arrow",
                zorder=int(arrow_patch.get_zorder() or 0),
                space=CoordinateSpace.AXES,
                # Matplotlib clips this axes-space polygon against the plot's
                # background patch.  The compiler transforms that final-data
                # clip into axes coordinates before intersecting the polygon.
                clip_id="plot",
            )
            # Mark the patch as recorded so _record_untracked_path_patches
            # does not capture it a second time in data coordinates.
            self._recorded_external_patch_ids = getattr(
                self, "_recorded_external_patch_ids", set()
            ) | {id(arrow_patch)}
        except _RECORDING_ERRORS as e:
            LOGGER.debug("Could not record arrow: %s", e)

    # ------------------------------------------------------------------
    # Method 8.5: Title
    # ------------------------------------------------------------------

    @use_style(LabelStyle, "title")
    def title(self, text: str, style: LabelStyle = None, **kwargs):
        """Record the plot title as a paper-coordinate text annotation."""
        super().title(text=text, style=style, **kwargs)

        try:
            self.fig.canvas.draw()
            artist = self.ax.title
            figure_height = float(self.fig.bbox.height)
            anchor_x, anchor_y = self.fig.transFigure.inverted().transform(
                artist.get_transform().transform(artist.get_position())
            )
            title_bbox = artist.get_window_extent(
                renderer=self.fig.canvas.get_renderer()
            )
            paper_y_max = max(1.0, float(title_bbox.y1) / figure_height)
            paper_y = min(1.0, float(anchor_y) / paper_y_max)
            font_family = artist.get_fontfamily()
            self._recorder.record_text(
                text=artist.get_text(),
                x=float(anchor_x),
                y=paper_y,
                style_dict={
                    "font_size": float(artist.get_fontsize()),
                    "font_color": _rgba_to_hex(artist.get_color()),
                    "font_alpha": (
                        artist.get_alpha()
                        if artist.get_alpha() is not None
                        else 1.0
                    ),
                    "font_weight": artist.get_fontweight(),
                    "font_style": artist.get_fontstyle(),
                    "font_name": font_family[0] if font_family else style.font_name,
                    "xref": "paper",
                    "yref": "paper",
                    "ha": artist.get_horizontalalignment(),
                    "va": artist.get_verticalalignment(),
                    "axes_domain_top": 1.0 / paper_y_max,
                },
                gid="title",
                zorder=int(artist.get_zorder()),
                space=CoordinateSpace.PAPER,
            )
        except _RECORDING_ERRORS as e:
            LOGGER.debug("Could not record title: %s", e)

    # ------------------------------------------------------------------
    # Method 8.6: Legend
    # ------------------------------------------------------------------

    @use_style(LegendStyle, "legend")
    def legend(self, title: str = "Legend", style: LegendStyle = None, **kwargs):
        """Record legend state in style_info."""
        super().legend(title=title, style=style, **kwargs)
        self._recorder.style_info["show_legend"] = True
        self._recorder.style_info["legend_title"] = title

    @use_style(LegendStyle, "legend")
    def star_magnitude_scale(self, title: str = "Star Magnitude", style: LegendStyle = None, **kwargs):
        """Record star magnitude scale for interactive legends."""
        artists_before = len(self.ax.artists)
        super().star_magnitude_scale(title=title, style=style, **kwargs)
        try:
            import numpy as np
            from starplot import callables
            from starplot.models.star import Star

            size_fn = kwargs.get("size_fn", callables.size_by_magnitude)
            label_fn = kwargs.get("label_fn", lambda magnitude: str(magnitude))
            start = kwargs.get("start", -1)
            stop = kwargs.get("stop", 9)
            step = kwargs.get("step", 1)
            marker_style = self.style.star.marker
            marker_kwargs = marker_style.matplot_kwargs()
            magnitudes = list(np.arange(start, stop, step))
            self._interactive_magnitude_scale = {
                "title": title,
                "labels": [str(label_fn(magnitude)) for magnitude in magnitudes],
                # Line2D markersize is a diameter in points.  This exactly
                # mirrors LegendPlotterMixin.star_magnitude_scale().
                "sizes": [
                    float(
                        math.sqrt(
                            size_fn(
                                Star(
                                    pk=1,
                                    ra=0,
                                    dec=0,
                                    magnitude=magnitude,
                                    geometry=None,
                                )
                            )
                        )
                        * self.scale
                    )
                    for magnitude in magnitudes
                ],
                "color": _rgba_to_hex(
                    marker_kwargs.get("markerfacecolor", marker_kwargs.get("color", "#000000"))
                ),
                "edge_color": _rgba_to_hex(
                    marker_kwargs.get("markeredgecolor", marker_kwargs.get("color", "#000000"))
                ),
            }

            # star_magnitude_scale creates a Legend artist, not collections.
            # Extract the legend and its handles/texts.
            from starplot.interactive.commands import DrawingCommand, CoordinateSpace
            new_artists = self.ax.artists[artists_before:]
            for artist in new_artists:
                # Legend objects have get_texts()
                if not hasattr(artist, 'get_texts'):
                    continue
                # Record a placeholder command so the gid exists
                cmd = DrawingCommand(
                    kind="text",
                    data={
                        "text": title,
                        "x": 0.98,
                        "y": 0.98,
                        "offset_points": (0.0, 0.0),
                    },
                    style={
                        "font_size": style.label_font_size if hasattr(style, 'label_font_size') else 11,
                        "font_color": style.label_font_color.as_hex() if hasattr(style, 'label_font_color') and hasattr(style.label_font_color, 'as_hex') else "#ffffff",
                        "font_weight": "normal",
                        "font_name": "Inter",
                        "ha": "right",
                        "va": "top",
                        "alpha": 1.0,
                        "rotation": 0.0,
                        "xref": "paper",
                        "yref": "paper",
                    },
                    gid="star-magnitude-scale",
                    zorder=int(getattr(style, "zorder", 0) or 0),
                    space=CoordinateSpace.PAPER,
                )
                self._recorder.commands.append(cmd)
                break
        except _RECORDING_ERRORS as e:
            LOGGER.warning("Failed to record star magnitude scale: %s", e)

    # ------------------------------------------------------------------
    # Method 9: Optic info table
    # ------------------------------------------------------------------

    def info(self, style=None):
        """Record plot info for interactive parity.

        Handles both OpticPlot (info table) and ZenithPlot (info text).
        """
        texts_before = len(self.ax.texts)
        tables_before = len(self.ax.tables)
        result = super().info(style=style)

        from starplot.plots.optic import OpticPlot
        from starplot.plots.zenith import ZenithPlot

        # ZenithPlot: record the info text as an AXES-space annotation
        if isinstance(self, ZenithPlot):
            try:
                new_texts = self.ax.texts[texts_before:]
                resolved_style = style or self.style.info_text
                for txt in new_texts:
                    pos = txt.get_position()
                    from starplot.interactive.commands import DrawingCommand, CoordinateSpace
                    cmd = DrawingCommand(
                        kind="text",
                        data={
                            "text": txt.get_text(),
                            "x": float(pos[0]),
                            "y": float(pos[1]),
                            "offset_points": (0.0, 0.0),
                        },
                        style={
                            "font_size": txt.get_fontsize(),
                            "font_color": _rgba_to_hex(txt.get_color()),
                            "font_weight": txt.get_fontweight(),
                            "font_name": txt.get_fontname() or "Inter",
                            "ha": txt.get_ha(),
                            "va": txt.get_va(),
                            "alpha": float(txt.get_alpha() or 1.0),
                            "rotation": float(txt.get_rotation() or 0.0),
                        },
                        gid="zenith-info",
                        zorder=int(getattr(resolved_style, "zorder", 0) or 0),
                        space=CoordinateSpace.AXES,
                    )
                    self._recorder.commands.append(cmd)
            except _RECORDING_ERRORS as e:
                LOGGER.warning("Failed to record zenith info: %s", e)
            return result

        if not isinstance(self, OpticPlot):
            return result

        try:
            from starplot.utils import azimuth_to_string

            resolved_style = style or self.style.info_text
            dt_str = (
                self.observer.dt.strftime("%m/%d/%Y @ %H:%M:%S")
                + " "
                + self.observer.dt.tzname()
            )

            columns = [
                "Target (Alt/Az)",
                "Target (RA/DEC)",
                "Observer Lat, Lon",
                "Observer Date/Time",
                f"Optic - {self.optic.label}",
            ]
            values = [
                f"{self.pos_alt.degrees:.0f}\N{DEGREE SIGN} / {self.pos_az.degrees:.0f}\N{DEGREE SIGN} ({azimuth_to_string(self.pos_az.degrees)})",
                f"{(self.ra / 15):.2f}h / {self.dec:.2f}\N{DEGREE SIGN}",
                f"{self.observer.lat:.2f}\N{DEGREE SIGN}, {self.observer.lon:.2f}\N{DEGREE SIGN}",
                dt_str,
                str(self.optic),
            ]
            widths = [0.15, 0.15, 0.2, 0.2, 0.3]

            font_color = resolved_style.font_color.as_hex()
            font_name = resolved_style.font_name or resolved_style.font_family or "Inter"
            background_color = self.style.figure_background_color.as_hex()
            line_color = self.style.border_line_color.as_hex()
            new_tables = list(self.ax.tables)[tables_before:]
            if new_tables:
                cells = list(new_tables[-1].get_celld().values())
                if cells:
                    background_color = _rgba_to_hex(cells[0].get_facecolor())
                    line_color = _rgba_to_hex(cells[0].get_edgecolor())
                    font_color = _rgba_to_hex(cells[0].get_text().get_color())

            self._recorder.record_info_table(
                columns=columns,
                values=values,
                widths=widths,
                style_dict={
                    "font_size": resolved_style.font_size * self.scale,
                    "font_color": font_color,
                    "font_weight": resolved_style.font_weight,
                    "font_name": font_name,
                    "font_alpha": resolved_style.font_alpha,
                    "background_color": background_color,
                    "line_color": line_color,
                },
                gid="optic-info-table",
                zorder=getattr(resolved_style, "zorder", 0) + 2000,
            )
        except _RECORDING_ERRORS as e:
            LOGGER.warning("Failed to record optic info table: %s", e)

        return result

    # ------------------------------------------------------------------
    # Method 10: OpticPlot border
    # ------------------------------------------------------------------

    def _plot_border(self):
        """Record the final Matplotlib optic border geometry exactly once."""
        patches_before = len(self.ax.patches)
        super()._plot_border()

        # Only record for OpticPlot
        from starplot.plots.optic import OpticPlot
        if not isinstance(self, OpticPlot):
            return

        try:
            new_patches = self.ax.patches[patches_before:]
            outer_border = next(
                patch
                for patch in reversed(new_patches)
                if not patch.get_fill() and float(patch.get_linewidth() or 0) > 0
            )
            points = [
                (float(x), float(y))
                for x, y in self.ax.transData.inverted().transform(
                    outer_border.get_verts()
                )
            ]
            alpha = outer_border.get_alpha()
            self._recorder.record_polygon(
                points=points,
                rings=[points],
                style_dict={
                    "fill_color": "none",
                    "edge_color": _edge_color_string(outer_border.get_edgecolor()),
                    "edge_width": float(outer_border.get_linewidth() or 0),
                    "alpha": float(alpha if alpha is not None else 1.0),
                    "line_style": str(outer_border.get_linestyle()),
                },
                gid="optic-border",
                zorder=int(outer_border.get_zorder() or 0),
                clip_id=None,
            )
            recorded = getattr(self, "_recorded_external_patch_ids", set())
            recorded.add(id(outer_border))
            self._recorded_external_patch_ids = recorded
        except _RECORDING_ERRORS as e:
            LOGGER.warning("Failed to record optic border: %s", e)

    # ------------------------------------------------------------------
    # Method 11: Gradient background
    # ------------------------------------------------------------------

    def _plot_gradient_background(self, gradient_preset):
        super()._plot_gradient_background(gradient_preset)
        try:
            from starplot.styles import ZOrderEnum
            self._recorder.record_gradient(
                direction=self._gradient_direction.value,
                color_stops=gradient_preset,
                gid="gradient",
                zorder=ZOrderEnum.LAYER_1 - 1000,
            )
        except _RECORDING_ERRORS as e:
            LOGGER.warning("Failed to record gradient background: %s", e)
