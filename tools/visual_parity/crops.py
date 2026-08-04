#!/usr/bin/env python3
"""Shared crop/diff utilities for visual parity review."""

from __future__ import annotations

import math
import re
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops

try:
    from scipy import ndimage as _ndimage
except ImportError:  # pragma: no cover - semantic crops are optional
    _ndimage = None


# (name, normalized box as (x0, y0, x1, y1), description)
# Coordinates use PIL's top-left origin: y=0 is the top of the image.
CROP_BOXES = [
    ("center", (0.30, 0.30, 0.70, 0.70), "center region"),
    ("top-left", (0.00, 0.00, 0.30, 0.30), "top-left"),
    ("top-right", (0.70, 0.00, 1.00, 0.30), "top-right"),
    ("bottom-left", (0.00, 0.70, 0.30, 1.00), "bottom-left"),
    ("bottom-right", (0.70, 0.70, 1.00, 1.00), "bottom-right"),
    ("middle-left", (0.00, 0.35, 0.25, 0.65), "middle-left"),
    ("middle-right", (0.75, 0.35, 1.00, 0.65), "middle-right"),
    ("upper-center", (0.35, 0.00, 0.65, 0.25), "upper-center"),
]


def crop_box(width: int, height: int, box: tuple[float, float, float, float]) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = box
    return (
        int(round(x0 * width)),
        int(round(y0 * height)),
        int(round(x1 * width)),
        int(round(y1 * height)),
    )


def composite_on_color(img: Image.Image, color: tuple[int, int, int]) -> Image.Image:
    """Composite an RGBA image onto a solid RGB background. Opaque or
    grayscale images are converted to RGB unchanged."""
    # Palette and LA images may carry transparency; normalize to RGBA first
    # so the alpha channel is composited rather than dropped.
    if img.mode in ("P", "PA", "LA"):
        img = img.convert("RGBA")
    if img.mode == "RGBA":
        bg = Image.new("RGBA", img.size, (*color, 255))
        return Image.alpha_composite(bg, img).convert("RGB")
    return img.convert("RGB")


def diff_stats(orig: Image.Image, inline: Image.Image) -> dict[str, float]:
    """Return diff metrics when both images are the same size."""
    orig_g = composite_on_color(orig, (255, 255, 255)).convert("L")
    inline_g = composite_on_color(inline, (255, 255, 255)).convert("L")
    diff = ImageChops.difference(orig_g, inline_g)
    arr = np.asarray(diff, dtype=np.float32)
    mae = float(arr.mean())
    rmse = float(math.sqrt((arr * arr).mean()))
    nonzero_gt5 = float(np.count_nonzero(arr > 5)) / arr.size * 100.0
    nonzero_gt20 = float(np.count_nonzero(arr > 20)) / arr.size * 100.0
    max_diff = float(arr.max())
    return {
        "mae": round(mae, 2),
        "rmse": round(rmse, 2),
        "nonzero_gt5": round(nonzero_gt5, 2),
        "nonzero_gt20": round(nonzero_gt20, 2),
        "max_diff": round(max_diff, 2),
    }


def _semantic_crop_boxes(
    img: Image.Image,
    count: int = 8,
) -> list[tuple[str, tuple[float, float, float, float], str]]:
    """Detect semantic regions (bright stars, clusters, lines/edges) and return crop boxes.

    Selection proceeds round-robin across feature sources so all salient region
    types are represented, then continues with the next-best candidates until
    ``count`` crops are found.  Geometric boxes are used as a fallback when
    scipy is unavailable or no salient features are found.
    """
    if _ndimage is None:
        return CROP_BOXES[:count]

    # Stars are bright on a dark sky, so detect against black.
    gray = np.asarray(composite_on_color(img, (0, 0, 0)).convert("L"), dtype=np.float32)
    height, width = gray.shape
    min_dim = min(width, height)
    crop_px = max(300, min_dim // 4)
    half_x = crop_px / (2 * width)
    half_y = crop_px / (2 * height)

    def to_box(cy: int, cx: int) -> tuple[float, float, float, float]:
        x = cx / width
        y = cy / height
        return (
            max(0.0, x - half_x),
            max(0.0, y - half_y),
            min(1.0, x + half_x),
            min(1.0, y + half_y),
        )

    # 1. Bright stars: local maxima above a high intensity threshold.
    bright_max = _ndimage.maximum_filter(gray, size=15, mode="constant")
    bright_threshold = max(np.percentile(gray, 95), gray.mean() + 1.5 * gray.std())
    bright_mask = (gray == bright_max) & (gray > bright_threshold)
    bright_coords = np.argwhere(bright_mask)
    bright_scores = gray[bright_mask]

    # 2. Dense clusters: large connected components above the mean.
    binary = gray > (gray.mean() + 0.5 * gray.std())
    labeled, num_labels = _ndimage.label(binary)
    if num_labels:
        areas = _ndimage.sum(binary, labeled, index=range(1, num_labels + 1))
        centers = _ndimage.center_of_mass(gray, labeled, index=range(1, num_labels + 1))
        valid = areas > 100
        centers = np.asarray(centers)[valid]
        cluster_points = centers[:, :2].astype(int)
        cluster_scores = areas[valid].astype(np.float32)
    else:
        cluster_points = np.empty((0, 2), dtype=int)
        cluster_scores = np.empty(0, dtype=np.float32)

    # 3. Lines / arrows / edges: high Sobel-gradient local maxima.
    grad_x = _ndimage.sobel(gray, axis=1)
    grad_y = _ndimage.sobel(gray, axis=0)
    gradient = np.hypot(grad_x, grad_y)
    edge_max = _ndimage.maximum_filter(gradient, size=15, mode="constant")
    edge_threshold = max(np.percentile(gradient, 95), gradient.mean() + 2 * gradient.std())
    edge_mask = (gradient == edge_max) & (gradient > edge_threshold)
    edge_coords = np.argwhere(edge_mask)
    edge_scores = gradient[edge_mask]

    sources = (
        ("bright-star", bright_coords, bright_scores),
        ("cluster", cluster_points, cluster_scores),
        ("lines/arrows", edge_coords, edge_scores),
    )

    min_distance = min_dim * 0.15
    existing: list[tuple[int, int]] = []
    results: list[tuple[str, tuple[float, float, float, float], str]] = []
    source_counts = [0] * len(sources)
    source_orders = [np.argsort(scores)[::-1] for _, _, scores in sources]
    source_pointers = [0] * len(sources)

    while len(results) < count:
        added_this_round = False
        for i, (label, coords, _scores) in enumerate(sources):
            order = source_orders[i]
            pointer = source_pointers[i]
            while pointer < len(order):
                index = order[pointer]
                pointer += 1
                cy, cx = coords[index]
                if any(
                    math.hypot(cx - ex, cy - ey) < min_distance for ey, ex in existing
                ):
                    continue
                existing.append((cy, cx))
                source_counts[i] += 1
                name = f"{label.replace('/', '-')}-{source_counts[i]}"
                results.append((name, to_box(cy, cx), label))
                added_this_round = True
                break
            source_pointers[i] = pointer
            if len(results) >= count:
                break
        if not added_this_round:
            break

    # If semantic detection produced too few crops, pad with the geometric boxes.
    if len(results) < count:
        results.extend(CROP_BOXES[: max(0, count - len(results))])

    return results[:count]


def _path_for_report(path: Path, root_dir: Path | None) -> str:
    if root_dir is not None:
        return str(path.relative_to(root_dir))
    return str(path)


def build_pair_review(
    left_path: Path,
    right_path: Path,
    output_dir: Path,
    pair_name: str,
    *,
    root_dir: Path | None = None,
    semantic: bool = True,
    reference: str = "left",
) -> dict:
    """Generate full-image stats and local semantic crops for a pair of images.

    The ``reference`` argument controls which image dictates the comparison size:
    ``"left"`` resizes the right image to the left size, ``"right"`` resizes the
    left image to the right size. Combined and diff crops are written to
    ``output_dir`` and a report dict is returned.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    with Image.open(left_path) as left_raw, Image.open(right_path) as right_raw:
        left = left_raw.convert("RGBA")
        right = right_raw.convert("RGBA")

        if reference == "left" and left.size != right.size:
            right = right.resize(left.size, Image.Resampling.LANCZOS)
        elif reference == "right" and left.size != right.size:
            left = left.resize(right.size, Image.Resampling.LANCZOS)

        full_stats = diff_stats(left, right)

        slug = re.sub(r"[^\w]+", "_", pair_name).strip("_")
        crop_entries = []
        crop_boxes = _semantic_crop_boxes(left) if semantic else CROP_BOXES
        for crop_name, box, desc in crop_boxes:
            crop_left = left.crop(crop_box(*left.size, box))
            crop_right = right.crop(crop_box(*right.size, box))
            stats = diff_stats(crop_left, crop_right)

            # Composite onto white so the comparison has a fixed, consistent
            # background regardless of the viewer's page color.
            combined = Image.new("RGB", (crop_left.width * 2, crop_left.height), (255, 255, 255))
            combined.paste(composite_on_color(crop_left, (255, 255, 255)), (0, 0))
            combined.paste(composite_on_color(crop_right, (255, 255, 255)), (crop_left.width, 0))
            combined_path = output_dir / f"{slug}_{crop_name}.png"
            combined.save(combined_path)

            diff_img = ImageChops.difference(
                composite_on_color(crop_left, (255, 255, 255)).convert("L"),
                composite_on_color(crop_right, (255, 255, 255)).convert("L"),
            )
            diff_vis = diff_img.point(lambda v: min(255, v * 4))
            diff_path = output_dir / f"{slug}_{crop_name}_diff.png"
            diff_vis.save(diff_path)

            crop_entries.append({
                "name": crop_name,
                "desc": desc,
                "combined": _path_for_report(combined_path, root_dir),
                "diff": _path_for_report(diff_path, root_dir),
                "stats": stats,
            })

        return {
            "pair_name": pair_name,
            "full_stats": full_stats,
            "left_size": left.size,
            "right_size": right.size,
            "crops": crop_entries,
        }
