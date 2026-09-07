import asyncio

from price_monitor_v5.browser_bridge import BrowserBridge
from price_monitor_v5.catalog import CatalogStore
from price_monitor_v5.monitor import MarketplaceMonitor
from price_monitor_v5.offers import plausible_shortened_candidate, matched_model, candidate_model


def test_shortened_candidates_are_narrow_and_q75_alias_is_explicit():
    assert not plausible_shortened_candidate("25G54", "TCL gaming monitor 25G64")
    assert plausible_shortened_candidate("S55HE", "TCL soundbar S55H")
    assert matched_model("hinnavaatlus", "Q75HE", "Teler TCL Q75H") == "Q75H"
    assert candidate_model("Z100-", "TCL Z100") == "Z100"


def test_old_quick_review_card_without_model_resolves_instead_of_looping(tmp_path):
    async def scenario():
        store = CatalogStore(tmp_path / "candidate.db")
        monitor = MarketplaceMonitor(store, BrowserBridge(), delay=0)
        item = store.create_item("source", {"model":"Z100-SW"})
        store.begin_run("candidate", "deep")
        task = store.check("candidate", item["id"], "kaina24")
        task.update(status="ACTION_REQUIRED", candidate_matches=[{
            "title":"TCL Z100", "url":"https://www.kaina24.lt/p/tcl-z100/",
            "query":"Z100-", "model":None,
        }])
        store.save_check(task)
        called = {}
        async def retry(run_id, item_id, key, **kwargs):
            called.update(run_id=run_id,item_id=item_id,key=key,**kwargs)
        monitor.retry = retry
        await monitor.accept_candidate("candidate",item["id"],"kaina24",{
            "candidate_index":0,"remember_alias":True,
        })
        saved = store.check("candidate",item["id"],"kaina24")
        assert saved["accepted_model"] == "Z100"
        assert store.model_aliases()["Z100SW"] == "Z100"
        assert called["url"] == "https://www.kaina24.lt/p/tcl-z100/"
    asyncio.run(scenario())


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


def test_waiting_old_browser_cannot_steal_job_after_switch():
    async def scenario():
        bridge = BrowserBridge(timeout_seconds=.5)
        bridge.heartbeat(True, True, "chrome-1", "Chrome")
        bridge.heartbeat(True, True, "edge-1", "Edge")
        stale_waiter = asyncio.create_task(bridge.next_job(.3, "chrome-1", "Chrome"))
        await asyncio.sleep(.01)
        bridge.set_active_client("edge-1")
        capture = asyncio.create_task(bridge.capture("salidzini", "25G64", "https://www.salidzini.lv/cena?q=25G64"))
        assert await stale_waiter is None
        job = await bridge.next_job(.2, "edge-1", "Edge")
        assert job["assigned_client_id"] == "edge-1"
        assert bridge.submit(job["id"], {"html":"ok"}, "edge-1")
        result = await capture
        assert result["browser_client_id"] == "edge-1"
        assert result["browser_name"] == "Edge"
    asyncio.run(scenario())


def test_late_standby_submission_cannot_reactivate_browser():
    bridge = BrowserBridge()
    bridge.heartbeat(True, True, "chrome-1", "Chrome")
    bridge.heartbeat(True, True, "edge-1", "Edge")
    bridge.set_active_client("edge-1")
    assert not bridge.submit("already-finished", {"html":"stale"}, "chrome-1")
    assert bridge.status()["active_client_id"] == "edge-1"


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
