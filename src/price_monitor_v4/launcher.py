from __future__ import annotations

import threading
import time
import urllib.error
import urllib.request
import webbrowser

import uvicorn

from .app import create_app
from .config import Settings


def open_browser_when_ready(url: str) -> None:
    for _ in range(80):
        try:
            with urllib.request.urlopen(f"{url}/health", timeout=1) as response:
                if response.status == 200:
                    webbrowser.open(url, new=2)
                    return
        except (OSError, urllib.error.URLError):
            time.sleep(0.25)


def main() -> None:
    settings = Settings.load()
    url = f"http://{settings.host}:{settings.port}"
    if settings.open_browser:
        threading.Thread(target=open_browser_when_ready, args=(url,), daemon=True).start()
    uvicorn.run(create_app(settings=settings), host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
