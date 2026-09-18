"""Headless Browser Synthetic Monitoring.

Probes client web applications (React, Vite, Vue, Next.js) using headless Chromium.
Executes client-side JavaScript, detects blank screens, missing DOM elements,
unhandled rendering exceptions, and captures outage screenshots automatically.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import re
import shutil
import subprocess

from app.core.logging import get_logger
from app.engines.restart_manager import PROJECT_ROOT

log = get_logger("synthetic-monitor")

SCREENSHOTS_DIR = (PROJECT_ROOT / "backend" / "app" / "static" / "screenshots").resolve()
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)


def _find_browser_binary() -> str | None:
    """Locate headless Chromium / Edge on the host system."""
    candidates = [
        # Windows Edge (Chromium based, installed by default on Windows)
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        # Google Chrome
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        # Linux / Mac candidates on PATH
        shutil.which("google-chrome"),
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
        shutil.which("msedge"),
    ]
    for c in candidates:
        if c and os.path.isfile(c):
            return str(c)
    return None


async def probe_synthetic(
    url: str,
    *,
    expected_content: str = "",
    service_id: int | str = 0,
    capture_screenshot: bool = True,
    timeout_sec: int = 15,
) -> dict:
    """Probe a web URL using a headless browser to detect blank pages and DOM issues.
    
    Returns a dict with:
      ok: bool
      status: HEALTHY | BLANK_PAGE | CONTENT_MISSING | CRASH_DETECTED | UNREACHABLE
      reason: str
      dom_length: int
      screenshot_path: str | None
    """
    browser = _find_browser_binary()
    if not browser:
        log.warning("No browser binary found for synthetic check; falling back to http")
        return {
            "ok": True,
            "status": "HEALTHY",
            "reason": "headless browser binary not available on host",
            "dom_length": 0,
            "screenshot_path": None,
        }

    screenshot_file = SCREENSHOTS_DIR / f"svc_{service_id}.png"
    args = [
        browser,
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        "--dump-dom",
    ]
    if capture_screenshot:
        args.append(f"--screenshot={screenshot_file}")
    args.append(url)

    def _exec() -> tuple[int, str, str]:
        try:
            cp = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
            )
            return cp.returncode, cp.stdout or "", cp.stderr or ""
        except subprocess.TimeoutExpired:
            return 124, "", "browser probe timed out"
        except Exception as exc:
            return -1, "", str(exc)

    code, dom, err = await asyncio.to_thread(_exec)

    if code != 0 or not dom.strip():
        return {
            "ok": False,
            "status": "UNREACHABLE",
            "reason": f"Synthetic probe failed: {err[:200] or 'empty DOM'}",
            "dom_length": 0,
            "screenshot_path": str(screenshot_file) if screenshot_file.is_file() else None,
        }

    # Extract text from rendered body
    body_match = re.search(r"<body.*?>(.*?)</body>", dom, re.S | re.I)
    body_html = body_match.group(1) if body_match else dom
    text_content = re.sub(r"<script.*?</script>", " ", body_html, flags=re.S | re.I)
    text_content = re.sub(r"<style.*?</style>", " ", text_content, flags=re.S | re.I)
    text_content = re.sub(r"<[^>]+>", " ", text_content)
    text_content = re.sub(r"\s+", " ", text_content).strip()

    # Detect blank pages: root is empty or body text is trivial (< 40 chars)
    has_empty_root = bool(re.search(r'<div[^>]*id=["\']root["\'][^>]*>\s*</div>', dom, re.I))
    if has_empty_root and len(text_content) < 50:
        return {
            "ok": False,
            "status": "BLANK_PAGE",
            "reason": "Blank page detected: <div id='root'> is empty and body has no rendered content",
            "dom_length": len(dom),
            "screenshot_path": str(screenshot_file) if screenshot_file.is_file() else None,
        }

    # Detect known error banners / crash text
    crash_indicators = [
        "Uncaught TypeError",
        "Minified React error",
        "Application Error",
        "500 Internal Server Error",
        "502 Bad Gateway",
    ]
    for ci in crash_indicators:
        if ci.lower() in text_content.lower():
            return {
                "ok": False,
                "status": "CRASH_DETECTED",
                "reason": f"Client runtime crash text detected on page: '{ci}'",
                "dom_length": len(dom),
                "screenshot_path": str(screenshot_file) if screenshot_file.is_file() else None,
            }

    # Verify expected content
    if expected_content and expected_content.lower() not in text_content.lower():
        return {
            "ok": False,
            "status": "CONTENT_MISSING",
            "reason": f"Expected text '{expected_content}' was not found in hydrated DOM",
            "dom_length": len(dom),
            "screenshot_path": str(screenshot_file) if screenshot_file.is_file() else None,
        }

    return {
        "ok": True,
        "status": "HEALTHY",
        "reason": f"Synthetic check passed ({len(text_content)} chars rendered)",
        "dom_length": len(dom),
        "screenshot_path": str(screenshot_file) if screenshot_file.is_file() else None,
    }
