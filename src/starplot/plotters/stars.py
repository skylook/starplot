from typing import Callable, Mapping

import rtree
import numpy as np
from skyfield.api import Star as SkyfieldStar, wgs84

from starplot import callables
from starplot.data import stars
from starplot.data.stars import StarCatalog
from starplot.models.star import Star, from_tuple
from starplot.styles import ObjectStyle, use_style
from starplot.profile import profile


class StarPlotterMixin:
    def _load_stars(self, catalog, filters=None):
        extent = self._extent_mask()

        # Add magnitude filter if provided in kwargs
        if 'mag' in self.__dict__:
            mag = self.__dict__['mag']
            if filters is None:
                filters = []
            filters.append(lambda df: df['magnitude'] <= mag)

        return stars.load(
            extent=extent,
            catalog=catalog,
            filters=filters,
        )

    def _scatter_stars(self, ras, decs, sizes, alphas, colors, style=None, **kwargs):
        style = style or self.style.star
        edge_colors = kwargs.pop("edgecolors", None)

        if not edge_colors:
            if style.marker.edge_color:
                edge_colors = style.marker.edge_color.as_hex()
            else:
                edge_colors = "none"

        style_kwargs = {
            's': sizes,
            'color': colors,
            'marker': kwargs.pop("symbol", None) or style.marker.symbol_matplot,
            'zorder': kwargs.pop("zorder", None) or style.marker.zorder,
            'edgecolor': edge_colors,
            'alpha': alphas,
            'label': "stars"
        }

        # Add any remaining kwargs
        style_kwargs.update(kwargs)
        style_kwargs.update(self._plot_kwargs())

        # Create scatter plot using backend
        if isinstance(ras, (list, tuple, np.ndarray)):
            plotted = None
            for i in range(len(ras)):
                plotted = self.marker(
                    ra=ras[i],
                    dec=decs[i],
                    style=style,
                    skip_bounds_check=True,  # We've already checked bounds
                    **{k: (v[i] if isinstance(v, (list, tuple, np.ndarray)) else v) for k, v in style_kwargs.items()}
                )
        else:
            plotted = self.marker(
                ra=ras,
                dec=decs,
                style=style,
                skip_bounds_check=True,  # We've already checked bounds
                **style_kwargs
            )

        return plotted

    def _star_labels(
        self,
        star_objects: list[Star],
        star_sizes: list[float],
        label_row_ids: list,
        style: ObjectStyle,
        labels: Mapping[str, str],
        bayer_labels: bool,
        flamsteed_labels: bool,
        label_fn: Callable[[Star], str],
    ):
        _bayer = []
        _flamsteed = []

        # Plot all star common names first
        for i, s in enumerate(star_objects):
            if s._row_id not in label_row_ids:
                continue

            if (
                s.hip
                and s.hip in self._labeled_stars
                or s.tyc
                and s.tyc in self._labeled_stars
            ):
                continue
            elif s.hip:
                self._labeled_stars.append(s.hip)
            elif s.tyc:
                self._labeled_stars.append(s.tyc)

            if label_fn is not None:
                label = label_fn(s)
            elif s.hip in labels:
                label = labels.get(s.hip)
            else:
                label = s.name

            bayer_desig = s.bayer
            flamsteed_num = s.flamsteed

            if label:
                self.text(
                    label,
                    s.ra,
                    s.dec,
                    style=style.label.offset_from_marker(
                        marker_symbol=style.marker.symbol,
                        marker_size=star_sizes[i],
                        scale=self.scale,
                    ),
                    hide_on_collision=self.hide_colliding_labels,
                    gid="stars-label-name",
                )

            if bayer_labels and bayer_desig:
                _bayer.append((bayer_desig, s.ra, s.dec, star_sizes[i]))

            if flamsteed_labels and flamsteed_num and not bayer_desig:
                _flamsteed.append((flamsteed_num, s.ra, s.dec, star_sizes[i]))

        # Plot bayer/flamsteed
        for bayer_desig, ra, dec, star_size in _bayer:
            self.text(
                bayer_desig,
                ra,
                dec,
                style=self.style.bayer_labels.offset_from_marker(
                    marker_symbol=style.marker.symbol,
                    marker_size=star_size,
                    scale=self.scale,
                ),
                hide_on_collision=self.hide_colliding_labels,
                gid="stars-label-bayer",
            )

        for flamsteed_num, ra, dec, star_size in _flamsteed:
            self.text(
                flamsteed_num,
                ra,
                dec,
                style=self.style.flamsteed_labels.offset_from_marker(
                    marker_symbol=style.marker.symbol,
                    marker_size=star_size,
                    scale=self.scale,
                ),
                hide_on_collision=self.hide_colliding_labels,
                gid="stars-label-flamsteed",
            )

    def _prepare_star_coords(self, df, limit_by_altaz=False):
        df["x"], df["y"] = (
            df["ra"],
            df["dec"],
        )
        return df

    @profile
    @use_style(ObjectStyle, "star")
    def stars(
        self,
        where: list = None,
        where_labels: list = None,
        catalog: StarCatalog = StarCatalog.BIG_SKY_MAG11,
        style: ObjectStyle = None,
        size_fn: Callable[[Star], float] = callables.size_by_magnitude,
        alpha_fn: Callable[[Star], float] = None,
        color_fn: Callable[[Star], str] = None,
        label_fn: Callable[[Star], str] = None,
        labels: Mapping[int, str] = None,
        legend_label: str = "Star",
        bayer_labels: bool = False,
        flamsteed_labels: bool = False,
        *args,
        **kwargs,
    ):
        # Store mag parameter in instance for _load_stars to use
        if 'mag' in kwargs:
            self.__dict__['mag'] = kwargs['mag']

        # fallback to style if callables are None
        color_hex = (
            style.marker.color.as_hex()
        )  # calculate color hex once here to avoid repeated calls in color_fn()
        size_fn = size_fn or (lambda d: style.marker.size)
        alpha_fn = alpha_fn or (lambda d: style.marker.alpha)
        color_fn = color_fn or (lambda d: color_hex)

        where = where or []
        where_labels = where_labels or []
        stars_to_index = []
        labels = labels or {}

        star_results = self._load_stars(catalog, filters=where)

        star_results_labeled = star_results
        for f in where_labels:
            star_results_labeled = star_results_labeled.filter(f)

        label_row_ids = star_results_labeled.to_pandas()["rowid"].tolist()

        stars_df = star_results.to_pandas()

        if getattr(self, "projection", None) == "zenith":
            # filter stars for zenith plots to only include those above horizon
            self.location = self.earth + wgs84.latlon(self.lat, self.lon)
            stars_apparent = (
                self.location.at(self.timescale)
                .observe(SkyfieldStar.from_dataframe(stars_df))
                .apparent()
            )
            # we only need altitude
            stars_alt, _, _ = stars_apparent.altaz()
            stars_df["alt"] = stars_alt.degrees
            stars_df = stars_df[stars_df["alt"] > 0]
        else:
            nearby_stars = SkyfieldStar.from_dataframe(stars_df)
            astrometric = self.earth.at(self.timescale).observe(nearby_stars)
            stars_ra, stars_dec, _ = astrometric.radec()
            stars_df["ra"], stars_df["dec"] = (
                stars_ra.hours * 15,
                stars_dec.degrees,
            )

        stars_df = self._prepare_star_coords(stars_df)
        starz = []
        rtree_id = 1

        for star in stars_df.itertuples():
            if hasattr(self.ax, 'transData'):
                # For Matplotlib backend
                data_xy = self._proj.transform_point(star.x, star.y, self._crs)
                display_x, display_y = self.ax.transData.transform(data_xy)
            else:
                # For HoloViews backend
                # We don't need to transform coordinates as HoloViews handles this internally
                display_x, display_y = star.x, star.y

            if (
                display_x < 0
                or display_y < 0
                or np.isnan(display_x)
                or np.isnan(display_y)
                or self._is_clipped([(display_x, display_y)])
            ):
                continue

            obj = from_tuple(star)
            size = size_fn(obj) * self.scale**2
            alpha = alpha_fn(obj)
            color = color_fn(obj) or style.marker.color.as_hex()

            if obj.magnitude < 5:
                rtree_id += 1
                # radius = ((size**0.5 / 2) / self.scale) #/ 3.14
                radius = size**0.5 / 5
                bbox = np.array(
                    (
                        display_x - radius,
                        display_y - radius,
                        display_x + radius,
                        display_y + radius,
                    )
                )
                if self._stars_rtree.get_size() > 0:
                    self._stars_rtree.insert(
                        0,
                        bbox,
                        None,
                    )
                else:
                    # if the index has no stars yet, then wait until end to load for better performance
                    stars_to_index.append((rtree_id, bbox, None))

            starz.append((star.x, star.y, size, alpha, color, obj))

        starz.sort(key=lambda s: s[2], reverse=True)  # sort by descending size

        if not starz:
            self.logger.debug(f"Star count = {len(starz)}")
            return

        x, y, sizes, alphas, colors, star_objects = zip(*starz)

        self._objects.stars.extend(star_objects)

        self.logger.debug(f"Star count = {len(star_objects)}")

        # Plot Stars
        self._scatter_stars(
            x,
            y,
            sizes,
            alphas,
            colors,
            style=style,
            zorder=style.marker.zorder,
            edgecolors=style.marker.edge_color.as_hex()
            if style.marker.edge_color
            else "none",
        )

        self._add_legend_handle_marker(legend_label, style.marker)

        if stars_to_index:
            self._stars_rtree = rtree.index.Index(stars_to_index)

        self._star_labels(
            star_objects,
            sizes,
            label_row_ids,
            style,
            labels,
            bayer_labels,
            flamsteed_labels,
            label_fn,
        )
