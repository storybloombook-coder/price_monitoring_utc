from price_monitor_v4 import launcher


class ReadyResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def test_opens_application_page_when_server_is_ready(monkeypatch) -> None:
    opened: list[tuple[str, int]] = []
    monkeypatch.setattr(launcher.urllib.request, "urlopen", lambda *_args, **_kwargs: ReadyResponse())
    monkeypatch.setattr(launcher.webbrowser, "open", lambda url, new=0: opened.append((url, new)))

    launcher.open_browser_when_ready("http://127.0.0.1:8000")

    assert opened == [("http://127.0.0.1:8000", 2)]
