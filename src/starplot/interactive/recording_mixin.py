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

from starplot.interactive.recorder import DrawingRecorder
from starplot.interactive.commands import CoordinateSpace
from starplot.coordinates import CoordinateSystem
from starplot.styles import ObjectStyle, PathStyle, LineStyle, LabelStyle, LegendStyle, ArrowStyle
from starplot.styles.helpers import use_style

LOGGER = logging.getLogger("starplot.interactive")


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


class RecordingMixin:
    """Mixin that records drawing commands alongside matplotlib rendering."""

    def __init__(self, *args, **kwargs):
        self._recorder = DrawingRecorder()
        super().__init__(*args, **kwargs)
        # Metadata is recorded lazily in to_plotly() so __init__ does not
        # produce matplotlib side effects (e.g., drawing).

    # ------------------------------------------------------------------
    # Coordinate projection helper
    # ------------------------------------------------------------------

    def _project_coords(self, ra, dec):
        """Transform RA/DEC to the plot's projected coordinate space.

        For MapPlot/ZenithPlot (Cartopy-based): applies the Cartopy projection
        via self._proj.transform_point(), matching how ax.scatter/plot works
        internally with transform=self._crs.

        For HorizonPlot/OpticPlot: delegates to _prepare_coords which handles
        AZ/ALT or camera coordinate conversion.

        Returns (x, y) in the plot's native coordinate system.
        """
        if hasattr(self, '_proj') and hasattr(self, '_crs'):
            try:
                if self._coordinate_system == CoordinateSystem.AZ_ALT:
                    # Inputs are RA/DEC; convert to AZ/ALT then project
                    az, alt = self._prepare_coords(ra, dec)
                    x, y = self._proj.transform_point(az, alt, self._crs)
                else:
                    x, y = self._proj.transform_point(ra, dec, self._crs)
                if math.isfinite(x) and math.isfinite(y):
                    return float(x), float(y)
                return float('nan'), float('nan')
            except Exception as e:
                LOGGER.debug("Projection failed for (%s, %s): %s", ra, dec, e)
                return float('nan'), float('nan')
        else:
            # Fallback for plot types without a projection
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
        except Exception as e:
            LOGGER.debug("Could not extract axis limits: %s", e)

        # Force a draw so axes position and window extent are final
        try:
            self.fig.draw_without_rendering()
        except Exception as e:
            LOGGER.debug("Could not draw without rendering: %s", e)

        # Record axes bbox and pixel dimensions
        try:
            ax_pos = self.ax.get_position()
            proj_info["axes_bbox"] = (
                float(ax_pos.x0), float(ax_pos.y0),
                float(ax_pos.width), float(ax_pos.height),
            )
            extent = self.ax.get_window_extent()
            proj_info["axes_pixels"] = (
                float(extent.width), float(extent.height),
            )
        except Exception as e:
            LOGGER.debug("Could not extract axes geometry: %s", e)
            proj_info["axes_bbox"] = (0.0, 0.0, 1.0, 1.0)
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
        except Exception as e:
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
        try:
            self._recorder.style_info["source_axes_width"] = float(
                self.ax.get_window_extent().width
            )
        except Exception as e:
            LOGGER.debug("Could not extract axes width: %s", e)

    def _record_final_clip_geometry(self):
        """Extract the final clip polygon from Matplotlib's background patch.

        Transforms the patch path through the patch transform and then through
        the inverse data transform to get final DATA-space coordinates.
        Returns a ClipGeometry with kind "rect" or "polygon".
        """
        from starplot.interactive.commands import ClipGeometry

        patch = getattr(self, "_background_clip_path", None)
        if patch is None:
            return ClipGeometry(kind="none")

        try:
            path_obj = patch.get_path()
            # Interpolate curved paths (Circle uses CURVE3/CURVE4 codes)
            # to get enough vertices for an accurate polygon approximation.
            codes = path_obj.codes
            has_curves = codes is not None and any(c in (3, 4) for c in codes)
            if has_curves and len(path_obj.vertices) < 64:
                path_obj = path_obj.interpolated(8)

            # Transform: path coords → display → data
            trans = patch.get_transform() + self.ax.transData.inverted()
            raw_verts = trans.transform(path_obj.vertices)

            # Filter finite vertices
            finite = [
                (float(x), float(y))
                for x, y in raw_verts
                if math.isfinite(x) and math.isfinite(y)
            ]
            if len(finite) < 3:
                return ClipGeometry(kind="none")

            # Remove duplicate closing point if present
            if len(finite) > 1 and finite[0] == finite[-1]:
                finite = finite[:-1]

            # Classify: rect if exactly 4 unique vertices, otherwise polygon
            unique = set(finite)
            if len(unique) == 4:
                kind = "rect"
            else:
                kind = "polygon"

            return ClipGeometry(kind=kind, points=tuple(finite))
        except Exception as e:
            LOGGER.warning("Failed to extract clip geometry: %s", e)
            return ClipGeometry(kind="none")

    # ------------------------------------------------------------------
    # Method 1: Stars scatter
    # ------------------------------------------------------------------

    def _scatter_stars(self, ras, decs, sizes, alphas, colors, style=None, **kwargs):
        legend_label = kwargs.pop("legend_label", "Star")
        result = super()._scatter_stars(ras, decs, sizes, alphas, colors, style, **kwargs)

        ras_list = list(ras)
        n = len(ras_list)

        # Pull metadata from recently added star objects
        recent_stars = self._objects.stars[-n:] if n > 0 else []
        metadata = []
        for s in recent_stars:
            label = ""
            try:
                label = s.get_label(s) if callable(getattr(s, "get_label", None)) else ""
            except Exception as e:
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

        # Project to the plot's native coordinate space so Plotly can render
        # directly as Cartesian coordinates without a separate projection step.
        # For OpticPlot/HorizonPlot, ras/decs are already az/alt in self._crs,
        # whereas _project_coords would re-convert them as RA/Dec, so use the
        # same Cartopy transform path that matplotlib's ax.scatter uses.
        decs_list = list(decs)
        projected = []
        for ra, dec in zip(ras_list, decs_list):
            try:
                x, y = self._proj.transform_point(ra, dec, self._crs)
            except Exception:
                x, y = float("nan"), float("nan")
            if math.isfinite(x) and math.isfinite(y):
                projected.append((x, y))
            else:
                projected.append((float("nan"), float("nan")))
        xs = [p[0] for p in projected]
        ys = [p[1] for p in projected]

        resolved_style = style or self.style.star
        symbol = kwargs.get("symbol", getattr(resolved_style.marker, "symbol", "circle"))
        symbol = getattr(symbol, "value", symbol)
        style_dict = {
            "symbol": str(symbol),
            "edge_color": kwargs.get("edgecolors", "none"),
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
            zorder=int(kwargs.get("zorder") or resolved_style.marker.zorder),
        )
        return result

    # ------------------------------------------------------------------
    # Method 2: Polygons (milky way, DSO shapes, circles, ellipses, etc.)
    # ------------------------------------------------------------------

    def _polygon(self, points, style, **kwargs):
        projected_points = [self._project_coords(ra, dec) for ra, dec in points]
        super()._polygon(points, style, **kwargs)
        try:
            style_dict = {
                "fill_color": style.fill_color.as_hex() if getattr(style, "fill_color", None) else None,
                "edge_color": style.edge_color.as_hex() if getattr(style, "edge_color", None) else None,
                "edge_width": getattr(style, "edge_width", 0),
                "alpha": getattr(style, "alpha", 1.0),
                "line_style": str(getattr(style, "line_style", "solid")),
                "zorder": int(getattr(style, "zorder", 0) or 0),
                "legend_label": kwargs.get("legend_label"),
            }
        except Exception as e:
            LOGGER.debug("Could not extract polygon style: %s", e)
            style_dict = {"legend_label": kwargs.get("legend_label")}
        self._recorder.record_polygon(
            points=[(float(x), float(y)) for x, y in projected_points],
            style_dict=style_dict,
            gid=kwargs.get("gid", "polygon"),
            zorder=int(getattr(style, "zorder", 0) or 0),
        )

    # ------------------------------------------------------------------
    # Method 3: Text labels (only records labels that survive collision detection)
    # ------------------------------------------------------------------

    def _text(self, x, y, text, **kwargs):
        result = super()._text(x, y, text, **kwargs)
        if result is not None:
            # _text_point() has already called _prepare_coords(). For Horizon
            # and Optic plots this means x/y are AZ/ALT, so passing them back
            # through _project_coords() would incorrectly treat them as RA/Dec.
            px, py = self._proj.transform_point(x, y, self._crs)

            from starplot.interactive.commands import DrawingCommand, CoordinateSpace
            cmd = DrawingCommand(
                kind="text",
                data={"text": str(text), "x": px, "y": py},
                style={
                    "font_size": kwargs.get("fontsize", 12),
                    "font_color": kwargs.get("color", "#ffffff"),
                    "font_weight": kwargs.get("weight", "normal"),
                    "font_name": kwargs.get("fontname", "Inter"),
                    "ha": kwargs.get("ha", "center"),
                    "va": kwargs.get("va", "center"),
                    "alpha": kwargs.get("alpha", 1.0),
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
        super().line(style=style, coordinates=coordinates, geometry=geometry, **kwargs)
        try:
            coords_iter = geometry.coords if geometry is not None else coordinates
            processed = [self._project_coords(*p) for p in coords_iter]
            if processed:
                xs, ys = zip(*processed)
                self._recorder.record_line(
                    x=list(xs),
                    y=list(ys),
                    style_dict={
                        "color": style.color.as_hex() if hasattr(style, "color") else "#777777",
                        "width": getattr(style, "width", 1),
                        "line_style": str(getattr(style, "style", "solid")),
                        "alpha": getattr(style, "alpha", 1.0),
                    },
                    gid=kwargs.get("gid", "line"),
                    zorder=int(getattr(style, "zorder", 0) or 0),
                )
        except Exception as e:
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
        """Record a scatter command for every marker call."""
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

        x, y = self._project_coords(ra, dec)
        if not (math.isfinite(x) and math.isfinite(y)):
            return

        style_kwargs = style.marker.matplot_scatter_kwargs(self.scale)
        style_dict = {
            "symbol": str(getattr(style.marker.symbol, "value", style.marker.symbol)),
            "edge_color": style_kwargs.get("edgecolors", "none"),
            "edge_width": style_kwargs.get("linewidths", 0) or 0,
            "fill": str(getattr(style.marker.fill, "value", style.marker.fill)),
            "legend_label": legend_label,
        }

        self._recorder.record_scatter(
            x=[x],
            y=[y],
            sizes=[style_kwargs.get("s", 22)],
            colors=[style_kwargs.get("c", "#000000")],
            alphas=[style_kwargs.get("alpha", 1.0)],
            metadata=[{"type": "marker", "name": label or ""}],
            style_dict=style_dict,
            gid=kwargs.get("gid_marker") or "marker",
            zorder=int(style_kwargs.get("zorder") or style.marker.zorder),
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
                    points = [self._project_coords(ra_val, d) for d in decs]
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
                    points = [self._project_coords(r, dec_val) for r in ras]
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
        except Exception as e:
            LOGGER.warning("Failed to record gridlines: %s", e)

    # ------------------------------------------------------------------
    # Method 5: Constellation lines (re-extract line data after super() renders)
    # ------------------------------------------------------------------

    def constellations(self, style=None, where=None, sql=None, catalog=None, **kwargs):
        # Let matplotlib render fully first
        kw = {k: v for k, v in {"style": style, "where": where, "sql": sql, "catalog": catalog}.items() if v is not None}
        super().constellations(**kw, **kwargs)

        # Re-extract line data from the constellation objects that were just plotted
        cons = self._objects.constellations
        if not cons:
            return

        try:
            constars = self._prepare_constellation_stars(cons)
        except Exception as e:
            LOGGER.warning("Failed to prepare constellation stars: %s", e)
            return

        constellation_lines = []
        constellation_metadata = []

        for c in cons:
            for s1_hip, s2_hip in c.star_hip_lines:
                if not constars.get(s1_hip) or not constars.get(s2_hip):
                    continue
                s1_ra, s1_dec = constars[s1_hip]
                s2_ra, s2_dec = constars[s2_hip]
                # _prepare_constellation_stars() already returns AZ/ALT for
                # HorizonPlot and OpticPlot. Re-running _project_coords()
                # would incorrectly interpret that pair as RA/Dec.
                if self._coordinate_system == CoordinateSystem.AZ_ALT:
                    x1, y1 = self._proj.transform_point(s1_ra, s1_dec, self._geodetic)
                    x2, y2 = self._proj.transform_point(s2_ra, s2_dec, self._geodetic)
                else:
                    x1, y1 = self._project_coords(s1_ra, s1_dec)
                    x2, y2 = self._project_coords(s2_ra, s2_dec)
                # Skip segments that project to infinity (e.g. wrap-around seams)
                if not (math.isfinite(x1) and math.isfinite(y1) and
                        math.isfinite(x2) and math.isfinite(y2)):
                    continue
                constellation_lines.append([(x1, y1), (x2, y2)])
                constellation_metadata.append({
                    "name": getattr(c, "name", ""),
                    "iau_id": getattr(c, "iau_id", ""),
                    "type": "constellation",
                })

        if constellation_lines:
            resolved_style = style or self.style.constellation_lines
            self._recorder.record_line_collection(
                lines=constellation_lines,
                style_dict={
                    "color": resolved_style.color.as_hex(),
                    "width": resolved_style.width,
                    "alpha": resolved_style.alpha,
                },
                metadata=constellation_metadata,
                gid="constellations-line",
                zorder=resolved_style.zorder,
            )

    # ------------------------------------------------------------------
    # Method 5.5: Constellation borders
    # ------------------------------------------------------------------

    @use_style(LineStyle, "constellation_borders")
    def constellation_borders(self, style=None, catalog=None, **kwargs):
        """Record constellation borders as a line collection."""
        from starplot.data.catalogs import CONSTELLATION_BORDERS
        catalog = catalog or CONSTELLATION_BORDERS
        super().constellation_borders(style=style, catalog=catalog, **kwargs)

        try:
            from starplot.data import db
            from starplot.data.catalogs import CONSTELLATION_BORDERS
            from starplot.coordinates import CoordinateSystem
            from ibis import _

            con = db.connect()
            borders = CONSTELLATION_BORDERS._load(
                connection=con, table_name="constellation_borders"
            )
            borders = borders.mutate(geometry=_.geometry.cast("geometry"))

            extent = self._extent_mask()
            borders_df = borders.filter(_.geometry.intersects(extent)).to_pandas()

            if borders_df.empty:
                return

            border_lines = []
            geometries = [line.geometry for line in borders_df.itertuples()]

            for ls in geometries:
                if ls.length < 360:
                    ls = ls.segmentize(1)
                xy = [c for c in ls.coords]

                if self._coordinate_system == CoordinateSystem.RA_DEC:
                    coords = [self._project_coords(*p) for p in xy]
                elif self._coordinate_system == CoordinateSystem.AZ_ALT:
                    coords = [self._proj.transform_point(*p, self._crs) for p in xy]
                else:
                    continue

                segments = _split_points(coords)
                border_lines.extend(segments)

            if border_lines:
                self._recorder.record_line_collection(
                    lines=border_lines,
                    style_dict={
                        "color": style.color.as_hex(),
                        "width": style.width,
                        "alpha": style.alpha,
                        "line_style": str(style.style),
                    },
                    metadata=[{"type": "constellation-border"} for _ in border_lines],
                    gid="constellations-border",
                    zorder=int(style.zorder or 0),
                )
        except Exception as e:
            LOGGER.warning("Failed to record constellation borders: %s", e)

    # ------------------------------------------------------------------
    # Method 6: Ecliptic line
    # ------------------------------------------------------------------

    def ecliptic(self, style=None, label="ECLIPTIC", collision_handler=None):
        super().ecliptic(style=style, label=label, collision_handler=collision_handler)
        try:
            from starplot.data import ecliptic as ecliptic_data
            resolved_style = style or self.style.ecliptic
            xs, ys = [], []
            for ra_h, dec in ecliptic_data.RA_DECS:
                x, y = self._project_coords(ra_h * 15, dec)
                xs.append(x)
                ys.append(y)
            if xs:
                self._recorder.record_line(
                    x=xs, y=ys,
                    style_dict={
                        "color": resolved_style.line.color.as_hex(),
                        "width": resolved_style.line.width,
                        "line_style": str(resolved_style.line.style),
                        "alpha": resolved_style.line.alpha,
                    },
                    gid="ecliptic-line",
                    zorder=resolved_style.line.zorder,
                )
        except Exception as e:
            LOGGER.warning("Failed to record ecliptic line: %s", e)

    # ------------------------------------------------------------------
    # Method 7: Celestial equator
    # ------------------------------------------------------------------

    def celestial_equator(self, style=None, label=None, collision_handler=None):
        super().celestial_equator(style=style, label=label, collision_handler=collision_handler)
        try:
            resolved_style = style or self.style.celestial_equator
            # Celestial equator is dec=0 across all RA values
            xs = list(range(0, 361, 2))
            ys = [0.0] * len(xs)
            processed = [self._project_coords(ra, 0) for ra in xs]
            px, py = zip(*processed)
            self._recorder.record_line(
                x=list(px), y=list(py),
                style_dict={
                    "color": resolved_style.line.color.as_hex(),
                    "width": resolved_style.line.width,
                    "line_style": str(resolved_style.line.style),
                    "alpha": resolved_style.line.alpha,
                },
                gid="celestial-equator-line",
                zorder=resolved_style.line.zorder,
            )
        except Exception as e:
            LOGGER.warning("Failed to record celestial equator: %s", e)

    # ------------------------------------------------------------------
    # Method 8: Horizon (MapPlot great circle, HorizonPlot bar, ZenithPlot circle)
    # ------------------------------------------------------------------

    @use_style(PathStyle, "horizon")
    def horizon(self, style=None, labels=None, **kwargs):
        """Record horizon elements for MapPlot, HorizonPlot, and ZenithPlot."""
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
            from starplot import geod

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

            elif isinstance(self, MapPlot):
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

                points = geod.ellipse(
                    center=(ra.hours * 15, dec.degrees),
                    height_degrees=180,
                    width_degrees=180,
                    num_pts=100,
                )
                projected = [self._project_coords(ra, dec) for ra, dec in points]
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
                        x, y = self._project_coords(ra.hours * 15, dec.degrees)
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
                xlim = self.ax.get_xlim()
                ylim = self.ax.get_ylim()
                center_x = (xlim[0] + xlim[1]) / 2
                center_y = (ylim[0] + ylim[1]) / 2
                radius = (xlim[1] - xlim[0]) / 2 * 0.454 / 0.5

                import numpy as np
                theta = np.linspace(0, 2 * np.pi, 100)
                circle_x = center_x + radius * np.cos(theta)
                circle_y = center_y + radius * np.sin(theta)

                self._recorder.record_line(
                    x=list(circle_x),
                    y=list(circle_y),
                    style_dict={
                        "color": resolved_style.line.color.as_hex(),
                        "width": resolved_style.line.width,
                        "line_style": str(resolved_style.line.style),
                        "alpha": resolved_style.line.alpha,
                    },
                    gid="horizon-circle",
                    zorder=int(resolved_style.line.zorder or 0),
                )

                if labels is None:
                    labels = ["N", "E", "S", "W"]
                if labels:
                    labels = [translate(label, self.language) for label in labels]
                    label_ax_coords = [
                        (0.5, 0.95),
                        (0.045, 0.5),
                        (0.5, 0.045),
                        (0.954, 0.5),
                    ]
                    for label, (ax_x, ax_y) in zip(labels, label_ax_coords):
                        data_x = xlim[0] + (xlim[1] - xlim[0]) * ax_x
                        data_y = ylim[0] + (ylim[1] - ylim[0]) * ax_y
                        self._recorder.record_text(
                            text=str(label),
                            x=data_x,
                            y=data_y,
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
        except Exception as e:
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
        """Record the arrow polygon in axes (paper) coordinates."""
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
            self._recorder.record_polygon(
                points=points,
                style_dict={
                    "fill_color": style.fill_color.as_hex() if style.fill_color else None,
                    "edge_color": style.edge_color.as_hex() if style.edge_color else None,
                    "edge_width": getattr(style, "edge_width", 0),
                    "alpha": getattr(style, "alpha", 1.0),
                    "line_style": str(getattr(style, "line_style", "solid")),
                    "xref": "paper",
                    "yref": "paper",
                },
                gid="arrow",
                zorder=int(getattr(style, "zorder", 0) or 0),
            )
        except Exception as e:
            LOGGER.debug("Could not record arrow: %s", e)

    # ------------------------------------------------------------------
    # Method 8.5: Title
    # ------------------------------------------------------------------

    @use_style(LabelStyle, "title")
    def title(self, text: str, style: LabelStyle = None, **kwargs):
        """Record the plot title as a paper-coordinate text annotation."""
        super().title(text=text, style=style, **kwargs)

        try:
            self._recorder.record_text(
                text=str(text),
                x=0.5,
                y=0.98,
                style_dict={
                    "font_size": style.font_size,
                    "font_color": style.font_color.as_hex(),
                    "font_alpha": style.font_alpha,
                    "font_weight": style.font_weight,
                    "font_style": style.font_style,
                    "font_name": style.font_name,
                    "xref": "paper",
                    "yref": "paper",
                    "ha": "center",
                    "va": "top",
                },
                gid="title",
                zorder=int(style.zorder or 0),
                space=CoordinateSpace.PAPER,
            )
        except Exception as e:
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
        super().star_magnitude_scale(title=title, style=style, **kwargs)
        # TODO: record scatter commands for each magnitude step

    # ------------------------------------------------------------------
    # Method 9: Optic info table
    # ------------------------------------------------------------------

    def info(self, style=None):
        """Record OpticPlot's bottom info table for interactive parity."""
        result = super().info(style=style)

        from starplot.plots.optic import OpticPlot
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
                    "background_color": self.style.figure_background_color.as_hex(),
                    "line_color": self.style.border_line_color.as_hex(),
                },
                gid="optic-info-table",
                zorder=getattr(resolved_style, "zorder", 0) + 2000,
            )
        except Exception as e:
            LOGGER.warning("Failed to record optic info table: %s", e)

        return result

    # ------------------------------------------------------------------
    # Method 10: OpticPlot border (circular field of view)
    # ------------------------------------------------------------------

    def _plot_border(self):
        """Override _plot_border for OpticPlot to record circular border."""
        super()._plot_border()
        
        # Only record for OpticPlot
        from starplot.plots.optic import OpticPlot
        if not isinstance(self, OpticPlot):
            return
        
        try:
            # Match OpticPlot._plot_border() outer ring:
            # optic.patch(..., padding=0.05, linewidth=25 * self.scale,
            #            edgecolor=self.style.border_bg_color)
            color = self.style.border_bg_color.as_hex()
            width = 25 * self.scale
            alpha = 1.0

            # Optic.patch() is a circle for scope/binocular optics.
            # Keep fallback for non-circular optics.
            import numpy as np
            radius = getattr(self.optic, "radius", self.optic.xlim) + 0.05
            theta = np.linspace(0, 2 * np.pi, 100)
            circle_x = radius * np.cos(theta)
            circle_y = radius * np.sin(theta)
            
            self._recorder.record_line(
                x=list(circle_x),
                y=list(circle_y),
                style_dict={
                    "color": color,
                    "width": width,
                    "line_style": "solid",
                    "alpha": alpha,
                },
                gid="optic-border",
                zorder=1000,
            )
        except Exception as e:
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
        except Exception as e:
            LOGGER.warning("Failed to record gradient background: %s", e)
