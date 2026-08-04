"""Unit tests for visual parity crop/diff utilities."""

from PIL import Image

import tools.visual_parity.crops as crops


def test_crop_box_rounds_normalized_coordinates():
    assert crops.crop_box(1000, 800, (0.25, 0.25, 0.75, 0.75)) == (
        250, 200, 750, 600,
    )


def test_composite_on_color_preserves_opaque_rgb():
    img = Image.new("RGB", (2, 2), color=(10, 20, 30))
    assert crops.composite_on_color(img, (255, 255, 255)).mode == "RGB"


def test_composite_on_color_composites_rgba_onto_background():
    img = Image.new("RGBA", (2, 2), color=(255, 0, 0, 128))
    result = crops.composite_on_color(img, (0, 0, 0))
    assert result.mode == "RGB"
    # Half-transparent red over black should be dark red.
    pixel = result.getpixel((0, 0))
    assert pixel[0] > 0
    assert pixel[0] < 255
    assert pixel[1] == 0
    assert pixel[2] == 0


def test_composite_on_color_handles_palette_png_with_transparency():
    """Palette-mode PNGs with a tRNS index must composite, not drop alpha."""
    img = Image.new("P", (2, 2), color=0)
    palette = [255, 0, 0] + [0, 255, 0] + [0] * (256 * 3 - 6)
    img.putpalette(palette)
    # Index 0 (red) is transparent; the whole image is transparent.
    img.info["transparency"] = 0

    result = crops.composite_on_color(img, (255, 255, 255))
    assert result.mode == "RGB"
    assert result.getpixel((0, 0)) == (255, 255, 255)
    assert result.getpixel((1, 1)) == (255, 255, 255)


def test_diff_stats_zero_for_identical_images():
    img = Image.new("RGBA", (10, 10), color=(128, 128, 128, 255))
    stats = crops.diff_stats(img, img)
    assert stats["mae"] == 0.0
    assert stats["rmse"] == 0.0
    assert stats["nonzero_gt20"] == 0.0
    assert stats["max_diff"] == 0.0


def test_semantic_crop_boxes_returns_requested_count():
    img = Image.new("RGBA", (100, 100), color=(0, 0, 0, 255))
    boxes = crops._semantic_crop_boxes(img, count=4)
    assert len(boxes) == 4
    for name, box, desc in boxes:
        assert len(box) == 4
        assert 0.0 <= box[0] <= box[2] <= 1.0
        assert 0.0 <= box[1] <= box[3] <= 1.0
