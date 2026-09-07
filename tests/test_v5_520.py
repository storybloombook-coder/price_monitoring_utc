from fastapi.testclient import TestClient

from price_monitor_v5.app import create_app
from price_monitor_v5.catalog import CatalogStore, utc_now
from price_monitor_v5.config import Settings


def test_model_refresh_retries_only_marketplaces_without_a_price(tmp_path):
    store = CatalogStore(tmp_path / "catalog.db")
    item = store.create_item("source", {"model": "25G64"})
    store.begin_run("one", "deep")
    kaina = store.check("one", item["id"], "kaina24")
    kaina.update(status="SUCCESS", coverage="complete", finished_at=utc_now(), offers=[{
        "store":"Varle.lt", "seller_key":"varle", "title":"TCL 25G64",
        "price_eur":199.0, "availability":"IN_STOCK", "marketplace_key":"kaina24",
        "url":"https://www.kaina24.lt/p/tcl-25g64/", "manual":False,
    }])
    store.save_check(kaina)
    for key in ("salidzini", "hinnavaatlus"):
        task = store.check("one", item["id"], key)
        task.update(status="NOT_FOUND" if key == "salidzini" else "ACTION_REQUIRED",
                    coverage="complete" if key == "salidzini" else "partial", finished_at=utc_now())
        store.save_check(task)
    app = create_app(Settings.load(tmp_path), store)
    called = []
    async def retry(run_id, item_id, key, **kwargs):
        called.append(key)
    app.state.monitor.retry = retry
    with TestClient(app) as client:
        response = client.post(f'/runs/one/models/{item["id"]}/retry')
        assert response.status_code == 200
        assert response.json()["checks_started"] == 2
        assert set(called) == {"salidzini", "hinnavaatlus"}


def test_salidzini_retry_queues_whole_current_pass_for_auto_batches(tmp_path):
    store = CatalogStore(tmp_path / "catalog.db")
    items = [store.create_item("source", {"model": f"32S{i}K"}) for i in range(7)]
    store.begin_run("one", "deep")
    for item in items:
        task = store.check("one", item["id"], "salidzini")
        task.update(status="ACTION_REQUIRED", coverage="partial", error="Page loading timed out", finished_at=utc_now())
        store.save_check(task)
    app = create_app(Settings.load(tmp_path), store)
    called = []
    async def retry(run_id, item_id, key, **kwargs):
        called.append((item_id, key))
    app.state.monitor.retry = retry
    with TestClient(app) as client:
        response = client.post('/runs/one/retry-unresolved', json={
            "marketplace_key":"salidzini", "limit":5, "include_not_found":False,
        })
        assert response.status_code == 200
        assert response.json()["checks_started"] == 7
        assert response.json()["automatic_batches"] is True
        assert len(called) == 7
