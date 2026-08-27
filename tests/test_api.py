from pathlib import Path

from fastapi.testclient import TestClient
from openpyxl import load_workbook

from price_monitor_v4.app import create_app
from price_monitor_v4.browser_bridge import EXTENSION_ORIGIN
from price_monitor_v4.catalog import CatalogStore
from price_monitor_v4.config import Settings


def test_catalog_api_and_v4_health(tmp_path: Path) -> None:
    settings = Settings.load(tmp_path)
    settings = Settings(
        **{
            **settings.__dict__,
            "legacy_enabled": False,
            "open_browser": False,
        }
    )
    store = CatalogStore(settings.catalog_database)
    app = create_app(settings=settings, store=store)

    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["version"] == "4.0.0"
        assert health.json()["browser_bridge"]["connected"] is False
        assert client.post("/browser-bridge/heartbeat").status_code == 403
        heartbeat = client.post("/browser-bridge/heartbeat", headers={"origin": EXTENSION_ORIGIN})
        assert heartbeat.status_code == 200
        assert heartbeat.json()["connected"] is True

        created = client.post(
            "/catalog/items/source",
            json={"model": "55P7L", "source_sheets": ["TV"]},
        )
        assert created.status_code == 201
        item_id = created.json()["id"]

        paused = client.patch(f"/catalog/items/{item_id}", json={"paused": True})
        assert paused.json()["state"] == "paused"

        trashed = client.delete(f"/catalog/items/{item_id}")
        assert trashed.json()["state"] == "trash"
        assert client.get("/catalog/items?kind=source&scope=active").json() == []

        restored = client.post(f"/catalog/items/{item_id}/restore")
        assert restored.json()["state"] == "paused"

        stock_item = client.post(
            "/catalog/items/stock", json={"nomenclature": "TCL TV", "model": "55T7B"}
        ).json()
        promoted = client.post(f"/catalog/items/{stock_item['id']}/monitor")
        assert promoted.status_code == 200
        assert promoted.json()["model"] == "55T7B"

        client.delete(f"/catalog/items/{item_id}")
        permanent = client.delete(f"/catalog/items/{item_id}/permanent")
        assert permanent.status_code == 204

        sources = client.get("/sources").json()
        assert {item["name"] for item in sources if item["kind"] == "shop"} == {
            "Senukai", "Bite", "Varle", "Elesen", "Elisa", "Euronics", "RDE", "Smartech"
        }
        client.patch("/sources/master/marketplace", json={"enabled": False})
        client.patch("/sources/master/shop", json={"enabled": False})
        started = client.post("/runs", json={})
        assert started.status_code == 200
        run = client.get(f"/runs/{started.json()['run_id']}").json()
        assert run["status"] == "COMPLETE"
        assert run["tasks"] == []
        assert run["shop_results"] == []
        export_path = Path(run["export_path"])
        assert export_path.exists()
        workbook = load_workbook(export_path, read_only=True)
        headers = [cell.value for cell in next(workbook["Monitoring summary"].iter_rows())]
        assert headers[3:12] == [
            "Lowest pre-order", "Senukai", "Bite", "Varle", "Elesen",
            "Elisa", "Euronics", "RDE", "Smartech",
        ]
