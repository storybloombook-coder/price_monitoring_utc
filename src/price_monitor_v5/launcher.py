from __future__ import annotations

import threading
import time
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import urllib.error
import urllib.request
import webbrowser

import uvicorn

from . import __version__
from .app import create_app
from .config import Settings

LOG = logging.getLogger("price_monitor.launcher")


def application_is_ready(url: str) -> bool:
    try:
        # A local health check must not go through a system HTTP proxy.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f"{url}/health", timeout=1) as response:
            data = json.loads(response.read(8192))
            return response.status == 200 and data.get("application") == "Price Monitor v5" and data.get("status") == "ok"
    except (OSError, ValueError, urllib.error.URLError):
        return False


def open_application_page(url: str) -> bool:
    try:
        if webbrowser.open(url, new=2):
            LOG.info("Opened application page: %s", url)
            return True
    except Exception:
        LOG.exception("Default browser launch failed")
    if os.name == "nt":
        try:
            os.startfile(url)
            LOG.info("Opened application page using Windows URL handler: %s", url)
            return True
        except OSError:
            LOG.exception("Windows URL handler failed")
    LOG.error("Could not open browser. Open %s manually", url)
    return False


def open_browser_when_ready(url: str, page_url: str | None = None) -> None:
    for _ in range(80):
        if application_is_ready(url):
            open_application_page(page_url or url)
            return
        time.sleep(0.25)
    LOG.error("Application did not become ready: %s", url)


def main() -> None:
    settings = Settings.load()
    url = f"http://{settings.host}:{settings.port}"
    # A versioned page URL forces Chromium to request the current HTML instead
    # of merely focusing a same-address tab that still contains an older UI.
    page_url = f"{url}/?v={__version__}"
    log_dir = settings.catalog_database.parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_dir / "launcher.log", maxBytes=256_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    LOG.addHandler(handler)
    LOG.setLevel(logging.INFO)
    # Resolve an existing instance before uvicorn can exit on an occupied port.
    if application_is_ready(url):
        LOG.info("Reusing existing v5 instance at %s", url)
        if settings.open_browser:
            open_application_page(page_url)
        return
    if settings.open_browser:
        threading.Thread(target=open_browser_when_ready, args=(url,page_url), daemon=True, name="open-browser").start()
    LOG.info("Starting v5 at %s (open_browser=%s)", url, settings.open_browser)
    try:
        uvicorn.run(create_app(settings=settings), host=settings.host, port=settings.port, log_level="info")
    except SystemExit:
        # A simultaneous second launch may have won the port after the first check.
        if application_is_ready(url) and settings.open_browser:
            open_application_page(page_url)
        else:
            LOG.exception("Server failed to start")
            raise


if __name__ == "__main__":
    main()
