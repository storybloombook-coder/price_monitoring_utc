import asyncio

from price_monitor_v5.browser_bridge import BrowserBridge
from price_monitor_v5.catalog import CatalogStore
from price_monitor_v5.monitor import MarketplaceMonitor
from price_monitor_v5.offers import plausible_shortened_candidate, matched_model


def test_shortened_candidates_are_narrow_and_q75_alias_is_explicit():
    assert not plausible_shortened_candidate("25G54", "TCL gaming monitor 25G64")
    assert plausible_shortened_candidate("S55HE", "TCL soundbar S55H")
    assert matched_model("hinnavaatlus", "Q75HE", "Teler TCL Q75H") == "Q75H"


def test_two_browser_clients_have_one_active_queue_consumer():
    async def scenario():
        bridge = BrowserBridge(timeout_seconds=.2)
        bridge.heartbeat(True, True, "chrome-1", "Chrome")
        bridge.heartbeat(True, True, "edge-1", "Edge")
        assert bridge.status()["active_client_id"] == "chrome-1"
        capture = asyncio.create_task(bridge.capture("salidzini", "25G64", "https://www.salidzini.lv/cena?q=25G64"))
        assert await bridge.next_job(.01, "edge-1", "Edge") is None
        job = await bridge.next_job(.05, "chrome-1", "Chrome")
        assert job and bridge.submit(job["id"], {"html":"ok"}, "chrome-1")
        assert (await capture)["browser_client_id"] == "chrome-1"
        bridge.set_active_client("edge-1")
        assert bridge.status()["active_browser"] == "Edge"
    asyncio.run(scenario())


def test_accept_partial_can_be_undone(tmp_path):
    async def scenario():
        store = CatalogStore(tmp_path / "review.db")
        monitor = MarketplaceMonitor(store, BrowserBridge(), delay=0)
        item = store.create_item("source", {"model":"55C6K PRO"})
        store.begin_run("review", "deep")
        task = store.check("review", item["id"], "kaina24")
        task.update(status="ACTION_REQUIRED", coverage="partial", offers=[{
            "store":"Varle.lt", "seller_key":"varle", "price_eur":603.74,
            "availability":"UNKNOWN", "url":"https://www.kaina24.lt/p/tcl-55c6k-pro/",
            "marketplace_key":"kaina24", "price_basis":"regular", "manual":False,
        }])
        store.save_check(task)
        accepted = await monitor.accept_partial("review",item["id"],"kaina24")
        assert accepted["status"] == "SUCCESS" and accepted["coverage"] == "accepted_partial"
        restored = await monitor.undo("review",item["id"],"kaina24")
        assert restored["status"] == "ACTION_REQUIRED" and restored["coverage"] == "partial"
    asyncio.run(scenario())
