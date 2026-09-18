"""Tests for headless browser synthetic monitor."""
import asyncio
import pytest

from app.monitoring.synthetic_monitor import _find_browser_binary, probe_synthetic


def test_find_browser_binary():
    # Should detect Edge or Chrome if present on the test machine
    binary = _find_browser_binary()
    assert binary is None or ("edge.exe" in binary.lower() or "chrome" in binary.lower())


def test_probe_synthetic_local_preview():
    # Test probing local preview server
    res = asyncio.run(probe_synthetic("http://localhost:4173/", expected_content="Aptitude Formulas", timeout_sec=10))
    # Even if offline, it returns a structured dict
    assert "ok" in res
    assert "status" in res
    assert "reason" in res
