"""RecordingMixin — intercepts starplot drawing primitives and records them
as backend-agnostic DrawingCommands.

Must appear before the concrete Plot class in the MRO:

    class InteractiveMapPlot(RecordingMixin, MapPlot): ...
    # MRO: InteractiveMapPlot → RecordingMixin → MapPlot → BasePlot → ...

Each overridden method calls super() first (preserving matplotlib rendering),
then records a DrawingCommand for the Plotly renderer.
"""

import math

from starplot.interactive.recorder import DrawingRecorder


class RecordingMixin:
    """Mixin that records drawing commands alongside matplotlib rendering."""

    def __init__(self, *args, **kwargs):
        self._recorder = DrawingRecorder()
        super().__init__(*args, **kwargs)
        # After super().__init__ the plot axes are ready; record plot metadata.
        self._record_plot_info()

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
                x, y = self._proj.transform_point(ra, dec, self._crs)
                if math.isfinite(x) and math.isfinite(y):
                    return float(x), float(y)
                return float('nan'), float('nan')
            except Exception:
                return float('nan'), float('nan')
        else:
            # HorizonPlot, OpticPlot — _prepare_coords handles conversion
            return self._prepare_coords(ra, dec)

    # ------------------------------------------------------------------
    # Plot metadata
    # ------------------------------------------------------------------

    def _record_plot_info(self):
        """Capture projection and style info after the plot is initialized."""
        proj_info = {
            "type": getattr(self, "projection", None).__class__.__name__
            if hasattr(self, "projection") and getattr(self, "projection") is not None
            else type(self).__name__,
            "ra_min": getattr(self, "ra_min", 0),
            "ra_max": getattr(self, "ra_max", 360),
            "dec_min": getattr(self, "dec_min", -90),
            "dec_max": getattr(self, "dec_max", 90),
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
        except Exception:
            pass

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
        except Exception:
            bg = "#ffffff"
            fig_bg = "#ffffff"

        self._recorder.style_info = {
            "background_color": bg,
            "figure_background_color": fig_bg,
            "resolution": getattr(self, "resolution", 2048),
        }

    # ------------------------------------------------------------------
    # Method 1: Stars scatter
    # ------------------------------------------------------------------

    def _scatter_stars(self, ras, decs, sizes, alphas, colors, style=None, **kwargs):
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
            except Exception:
                pass
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
        decs_list = list(decs)
        projected = [self._project_coords(ra, dec) for ra, dec in zip(ras_list, decs_list)]
        xs = [p[0] for p in projected]
        ys = [p[1] for p in projected]

        resolved_style = style or self.style.star
        self._recorder.record_scatter(
            x=xs,
            y=ys,
            sizes=list(sizes),
            colors=colors,
            alphas=alphas,
            metadata=metadata,
            gid=kwargs.get("gid", "stars"),
            zorder=kwargs.get("zorder", resolved_style.marker.zorder),
        )
        return result

    # ------------------------------------------------------------------
    # Method 2: Polygons (milky way, DSO shapes, circles, ellipses, etc.)
    # ------------------------------------------------------------------

    def _polygon(self, points, style, **kwargs):
        super()._polygon(points, style, **kwargs)
        try:
            style_dict = {
                "fill_color": style.fill_color.as_hex() if getattr(style, "fill_color", None) else None,
                "edge_color": style.edge_color.as_hex() if getattr(style, "edge_color", None) else None,
                "edge_width": getattr(style, "edge_width", 0),
                "alpha": getattr(style, "alpha", 1.0),
                "line_style": str(getattr(style, "line_style", "solid")),
                "zorder": getattr(style, "zorder", 0),
            }
        except Exception:
            style_dict = {}
        self._recorder.record_polygon(
            points=[(float(x), float(y)) for x, y in points],
            style_dict=style_dict,
            gid=kwargs.get("gid", "polygon"),
            zorder=getattr(style, "zorder", 0),
        )

    # ------------------------------------------------------------------
    # Method 3: Text labels (only records labels that survive collision detection)
    # ------------------------------------------------------------------

    def _text(self, x, y, text, **kwargs):
        result = super()._text(x, y, text, **kwargs)
        if result is not None:
            # x, y come from _prepare_coords(ra, dec) which returns raw RA/DEC
            # for MapPlot/ZenithPlot. Project to the plot's coordinate space.
            px, py = self._project_coords(x, y)

            from starplot.interactive.commands import DrawingCommand
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
                    zorder=getattr(style, "zorder", 0),
                )
        except Exception:
            pass

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
        except Exception:
            return

        constellation_lines = []
        constellation_metadata = []

        for c in cons:
            for s1_hip, s2_hip in c.star_hip_lines:
                if not constars.get(s1_hip) or not constars.get(s2_hip):
                    continue
                s1_ra, s1_dec = constars[s1_hip]
                s2_ra, s2_dec = constars[s2_hip]
                # Project both endpoints to the plot's coordinate space
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
        except Exception:
            pass

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
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Method 8: Gradient background
    # ------------------------------------------------------------------

    def _plot_gradient_background(self, gradient_preset):
        super()._plot_gradient_background(gradient_preset)
        try:
            self._recorder.record_gradient(
                direction=self._gradient_direction.value,
                color_stops=gradient_preset,
                gid="gradient",
            )
        except Exception:
            pass
