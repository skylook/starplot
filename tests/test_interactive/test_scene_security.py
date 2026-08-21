"""Security/resource-limit contracts at the Python transport boundary."""

from __future__ import annotations

import json

import pytest

from starplot.interactive.scene_validation import (
    LoaderLimits,
    validate_data_url,
    validate_manifest_bytes,
)


def test_loader_limits_reject_oversized_and_deep_untrusted_manifest_values():
    with pytest.raises(ValueError, match="byte limit"):
        validate_manifest_bytes(b"{}", LoaderLimits(max_manifest_bytes=1))
    with pytest.raises(ValueError, match="geometry depth"):
        validate_manifest_bytes(
            json.dumps([[[[[]]]]]).encode(),
            LoaderLimits(max_geometry_depth=2),
        )
    with pytest.raises(ValueError, match="string exceeding"):
        validate_manifest_bytes(
            json.dumps({"value": "unsafe"}).encode(),
            LoaderLimits(max_string_bytes=3),
        )


def test_data_urls_are_http_same_origin_by_default_and_never_script_urls():
    assert validate_data_url(
        "layers/stars.arrow", manifest_url="https://chart.test/scene/manifest.json"
    ) == "https://chart.test/scene/layers/stars.arrow"
    with pytest.raises(ValueError, match="not allowed"):
        validate_data_url(
            "https://cdn.test/stars.arrow",
            manifest_url="https://chart.test/manifest.json",
        )
    assert validate_data_url(
        "https://cdn.test/stars.arrow",
        manifest_url="https://chart.test/manifest.json",
        allowed_origins=("https://cdn.test",),
    ) == "https://cdn.test/stars.arrow"
    with pytest.raises(ValueError, match="HTTP"):
        validate_data_url(
            "javascript:alert(1)", manifest_url="https://chart.test/manifest.json"
        )
