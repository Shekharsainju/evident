"""HTML to PDF and PNG with Playwright's Chromium (P2: Playwright instead of Gotenberg)."""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright


def html_to_pdf(html: str, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page()
            page.set_content(html, wait_until="load")
            page.pdf(path=str(out), format="A4", print_background=True, prefer_css_page_size=True)
        finally:
            browser.close()
    return out


def html_to_png(html: str, out: Path, width: int = 1200) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": width, "height": 800})
            page.set_content(html, wait_until="load")
            page.screenshot(path=str(out), full_page=True)
        finally:
            browser.close()
    return out
