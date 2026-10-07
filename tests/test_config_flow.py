"""Tests for Luxeva Heater config-flow helpers."""

import pytest

from custom_components.luxeva_heater.config_flow import _normalize_mac


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("00:aa:11:bb:22:cc", "00:AA:11:BB:22:CC"),
        ("00-AA-11-BB-22-CC", "00:AA:11:BB:22:CC"),
        ("00AA11BB22CC", "00:AA:11:BB:22:CC"),
        (" 00 aa 11 bb 22 cc ", "00:AA:11:BB:22:CC"),
        ("00:AA:11:BB:22", None),
        ("not-a-mac", None),
        ("", None),
    ],
)
def test_normalize_mac(raw: str, expected: str | None) -> None:
    assert _normalize_mac(raw) == expected
