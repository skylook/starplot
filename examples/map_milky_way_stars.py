import os

from PIL import Image, ImageFilter

from starplot import MapPlot, Mollweide, _
from starplot.data.catalogs import BIG_SKY
from starplot.styles import PlotStyle, extensions
from starplot.callables import size_by_magnitude_factory, color_by_bv

style = PlotStyle().extend(
    extensions.GRAYSCALE_DARK,
    extensions.MAP,
)

_sizer = size_by_magnitude_factory(6, 0.02, 7)

p = MapPlot(
    projection=Mollweide(),
    style=style,
    resolution=4800,
)
p.stars(
    where=[_.magnitude < 11],
    where_labels=[False],
    size_fn=_sizer,
    alpha_fn=lambda s: 0.95 if s.magnitude < 9 else 0.6,
    color_fn=color_by_bv,
    catalog=BIG_SKY,
    style__marker__edge_color="#fff",
)
p.export("map_milky_way_stars.png", padding=0.1, transparent=True)

# Keep the published example's contrast pass, but compare the raw Matplotlib
# render with the raw interactive render in the visual-parity harness.
if "STARPLOT_COMPARISON_TRANSPORTS" not in os.environ:
    with Image.open("map_milky_way_stars.png") as img:
        filtered = img.filter(ImageFilter.MedianFilter(size=5))
        filtered.save("map_milky_way_stars.png")
