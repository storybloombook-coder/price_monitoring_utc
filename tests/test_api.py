from pathlib import Path

from fastapi.testclient import TestClient

from price_monitor_v4.app import create_app
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
