"""Headless-browser helpers (Playwright). Imported lazily so the rest of the project and the
tests work without a browser installed. In GitHub Actions the workflow installs Chromium."""
from . import net

LAUNCH_ARGS = ["--no-sandbox", "--disable-dev-shm-usage"]


def _sync():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise RuntimeError("Playwright is not installed (pip install playwright && playwright install chromium)") from e
    return sync_playwright


def fetch_html(url, wait_ms=3500, timeout_ms=60000):
    """Open a page in a real browser, let its JavaScript run, return the final HTML."""
    sync_playwright = _sync()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=LAUNCH_ARGS)
        try:
            page = browser.new_page(user_agent=net.UA, locale="en-US")
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            try:
                page.wait_for_load_state("networkidle", timeout=20000)
            except Exception:
                pass
            page.wait_for_timeout(wait_ms)
            return page.content()
        finally:
            browser.close()
