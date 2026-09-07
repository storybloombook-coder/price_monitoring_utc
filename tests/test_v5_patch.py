import asyncio
import json
from types import SimpleNamespace

import httpx
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from price_monitor_v5 import launcher
from price_monitor_v5.app import create_app
from price_monitor_v5.browser_bridge import BrowserBridge
from price_monitor_v5.catalog import CatalogStore
from price_monitor_v5.config import Settings
from price_monitor_v5.exporter import write_monitoring_export
from price_monitor_v5.monitor import MarketplaceMonitor
from price_monitor_v5.offers import parse_page


def test_second_launch_opens_existing_instance_without_starting_server(monkeypatch, tmp_path):
    settings = SimpleNamespace(host="127.0.0.1", port=8050, open_browser=True, catalog_database=tmp_path / "catalog.db")
    monkeypatch.setattr(launcher.Settings, "load", lambda: settings)
    monkeypatch.setattr(launcher, "application_is_ready", lambda _: True)
    opened = []
    monkeypatch.setattr(launcher, "open_application_page", lambda url: opened.append(url))
    monkeypatch.setattr(launcher.uvicorn, "run", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("Must reuse server")))
    launcher.main()
    assert opened == ["http://127.0.0.1:8050/?v=5.0.19"]


def test_browser_waits_for_health(monkeypatch):
    responses = iter([False, False, True])
    opened, sleeps = [], []
    monkeypatch.setattr(launcher, "application_is_ready", lambda _: next(responses))
    monkeypatch.setattr(launcher.time, "sleep", sleeps.append)
    monkeypatch.setattr(launcher, "open_application_page", opened.append)
    launcher.open_browser_when_ready("http://127.0.0.1:8050")
    assert len(sleeps) == 2 and len(opened) == 1


def test_browser_windows_fallback(monkeypatch):
    monkeypatch.setattr(launcher.webbrowser, "open", lambda *_a, **_k: False)
    monkeypatch.setattr(launcher.os, "name", "nt")
    opened = []
    monkeypatch.setattr(launcher.os, "startfile", opened.append, raising=False)
    assert launcher.open_application_page("http://127.0.0.1:8050")
    assert opened == ["http://127.0.0.1:8050"]


def test_health_requires_our_application(monkeypatch):
    class Response:
        status = 200
        application = "Another app"
        def read(self, _):
            return json.dumps({"application": self.application, "status": "ok"}).encode()
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass
    response = Response()
    monkeypatch.setattr(launcher.urllib.request, "build_opener", lambda *_: SimpleNamespace(open=lambda *_a, **_k: response))
    assert not launcher.application_is_ready("http://127.0.0.1:8050")
    response.application = "Price Monitor v5"
    assert launcher.application_is_ready("http://127.0.0.1:8050")


def test_clear_stock_preserves_monitoring_and_history(tmp_path):
    store = CatalogStore(tmp_path / "catalog.db")
    stock = store.create_item("stock", {"model": "25G64", "nomenclature": "TCL 25G64", "quantity": 0})
    store.begin_run("before", "deep")
    old_tasks = store.checks("before")
    assert store.clear_catalog("stock")["moved_to_trash"] == 1
    assert store.list_items("stock") == []
    assert len(store.list_items("source")) == 1
    assert store.checks("before") == old_tasks
    store.restore_item(stock["id"])
    assert len(store.list_items("stock")) == 1


def test_clear_models_preserves_stock_pauses_and_restoration(tmp_path):
    store = CatalogStore(tmp_path / "catalog.db")
    stock = store.create_item("stock", {"model": "25G64", "nomenclature": "TCL 25G64", "quantity": 2})
    paused = store.create_item("source", {"model": "75C6K", "paused": True})
    assert store.clear_catalog("source")["moved_to_trash"] == 2
    assert store.list_items("source") == []
    assert len(store.list_items("stock")) == 1
    store.update_item(stock["id"], {"quantity": 3})
    assert store.list_items("source") == []  # Stock edits must not undo a deliberate clear.
    store.restore_item(paused["id"])
    assert store.get_item(paused["id"])["paused"]
    assert store.clear_catalog("source")["moved_to_trash"] == 1
    assert store.clear_catalog("source")["moved_to_trash"] == 0


def test_catalog_clear_api_confirmation_and_running_guard(tmp_path):
    app = create_app(Settings.load(tmp_path))
    with TestClient(app) as client:
        client.post("/catalog/items/source", json={"model": "25G64"})
        assert client.post("/catalog/clear/source", json={}).status_code == 400
        assert client.post("/catalog/clear/invalid", json={"confirm": True}).status_code == 400
        app.state.monitor.jobs["test"] = object()
        assert client.post("/catalog/clear/source", json={"confirm": True}).status_code == 409
        app.state.monitor.jobs.clear()
        assert len(client.get("/catalog/items?kind=source").json()) == 1
        assert client.post("/catalog/clear/source", json={"confirm": True}).json()["moved_to_trash"] == 1
        assert len(client.get("/catalog/items?kind=source&scope=trash").json()) == 1


def test_retry_unresolved_is_filtered_bounded_and_resumes_stopped_run(tmp_path):
    store = CatalogStore(tmp_path / "catalog.db")
    for index in range(6):
        store.create_item("source", {"model": f"32S4K{index}"})
    store.begin_run("retry-batch", "deep")
    for task in store.checks("retry-batch"):
        task.update(status="ACTION_REQUIRED", error="review")
        store.save_check(task)
    store.stop_monitoring_session("retry-batch")
    app = create_app(Settings.load(tmp_path), store)
    scheduled = []
    app.state.monitor.schedule = lambda task, capture=False: scheduled.append((task["marketplace_key"], task["item_id"], capture))
    with TestClient(app) as client:
        response = client.post("/runs/retry-batch/retry-unresolved", json={
            "marketplace_key": "salidzini", "limit": 5, "include_not_found": False,
        })
        assert response.status_code == 200 and response.json()["checks_started"] == 5
        assert len(scheduled) == 5 and {item[0] for item in scheduled} == {"salidzini"}
        assert response.json()["retry_round"] == 1
        progress = client.get("/runs/retry-batch").json()["execution"]["queue_progress"]
        assert progress["marketplaces"][0]["total"] == 5
        assert progress["marketplaces"][0]["queued"] == 5
        # Simulate the first five checks remaining unresolved. Only the one SKU
        # still untouched in pass 1 may enter the next batch; the endpoint must
        # not fill that batch by returning to the beginning of pass 2.
        for task in store.checks("retry-batch"):
            if task["marketplace_key"] == "salidzini" and task.get("retry_count") == 1:
                task.update(status="ACTION_REQUIRED", error="still unavailable")
                store.save_check(task)
        response = client.post("/runs/retry-batch/retry-unresolved", json={
            "marketplace_key": "salidzini", "limit": 5, "include_not_found": False,
        })
        assert response.status_code == 200 and response.json()["checks_started"] == 1
        assert response.json()["retry_round"] == 1
        assert len(scheduled) == 6
        assert store.monitoring_session("retry-batch")["stopped_at"] is None
        progress = client.get("/runs/retry-batch").json()["execution"]["queue_progress"]
        assert progress["marketplaces"][0]["total"] == 1
        assert progress["marketplaces"][0]["queued"] == 1
        assert client.post("/runs/retry-batch/retry-unresolved", json={"limit": 7}).status_code == 400


def test_index_is_not_cached_between_versions(tmp_path):
    with TestClient(create_app(Settings.load(tmp_path))) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert "v5.0.19" in response.text
        policy = client.get("/health").json()["polite_monitoring"]
        assert policy["salidzini_browser_delay_seconds"] == 12
        assert policy["salidzini_page_timeout_seconds"] == 30
        assert policy["salidzini_circuit_breaker_failures"] == 2


def test_network_failure_is_not_reported_as_captcha_or_not_found(tmp_path):
    async def scenario():
        store = CatalogStore(tmp_path / "catalog.db")
        store.create_item("source", {"model": "25G64"})
        def handler(request):
            raise httpx.ConnectError("All connection attempts failed", request=request)
        monitor = MarketplaceMonitor(store, BrowserBridge(), delay=0, transport=httpx.MockTransport(handler))
        store.begin_run("network", "deep")
        monitor.launch("network")
        await asyncio.gather(*list(monitor.jobs.values()))
        checks = store.checks("network")
        assert len(checks) == 3
        assert all(t["status"] == "ACTION_REQUIRED" and t["error_code"] == "NETWORK_UNAVAILABLE" for t in checks if t['marketplace_key'] != 'salidzini')
        assert 'extension' in next(t['error'] for t in checks if t['marketplace_key'] == 'salidzini')
        assert not monitor.cooldowns
    asyncio.run(scenario())


def test_live_markup_unknown_stock_keeps_visible_price_and_link(tmp_path):
    # Reduced actual Hinnavaatlus 25G64 markup: the generic `in-stock` component
    # contains delivery text even when availability is not confirmed as in stock.
    url = "https://www.hinnavaatlus.ee/6366101/tcl-25-lcd-25g64/"
    html = '''<h1>Monitor TCL 25" LCD 25G64</h1><table>
    <tr class="offer"><td><a class="name">Elisa Eesti</a></td>
    <td class="stock svelte-9rnd92 body-small"><div class="in-stock svelte-k47yze"><div class="in-stock-message">0-1tp</div></div></td>
    <td><button class="offer-price">199,00 €</button><button class="offer-per-month">5,53 €/kuus</button></td></tr></table>'''
    parsed = parse_page("hinnavaatlus", "25G64", html, url)
    assert parsed["offers"][0]["availability"] == "UNKNOWN"
    store = CatalogStore(tmp_path / "catalog.db")
    store.create_item("source", {"model": "25G64"})
    store.begin_run("observed", "deep")
    task = next(t for t in store.checks("observed") if t["marketplace_key"] == "hinnavaatlus")
    task.update(offers=parsed["offers"], status="SUCCESS", coverage="complete")
    store.save_check(task)
    run = store.run("observed")
    result = next(t for t in run["tasks"] if t["marketplace_key"] == "hinnavaatlus")
    assert result["cheapest_in_stock"] is None
    assert result["lowest_reported"]["price_eur"] == 199
    assert result["highest_reported"]["url"] == url
    path = tmp_path / "export.xlsx"
    write_monitoring_export(path, run)
    workbook = load_workbook(path)
    assert "199.00 EUR" in workbook.active["B2"].value
    assert "reported price" in workbook.active["B2"].value
    assert workbook.active["D2"].value is None
