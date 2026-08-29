import json
from pathlib import Path

from price_monitor_v4.assisted_marketplaces import AssistedMarketplaceMonitor, parse_salidzini_capture
from price_monitor_v4.browser_bridge import BrowserBridge
from price_monitor_v4.catalog import CatalogStore


def snapshot(candidates: list[dict]) -> str:
    return (
        '<html><head><script id="price-monitor-candidates" type="application/json">'
        + json.dumps(candidates)
        + "</script></head></html>"
    )


def test_salidzini_parser_uses_lowest_exact_model_offer() -> None:
    html = snapshot([
        {
            "text": "Shop A\nTCL monitor 25G64\n199,00 €\nDelivery 2,50 €",
            "links": [{"text": "TCL 25G64", "url": "https://shop-a.example/25g64"}],
        },
        {
            "text": "Shop B\nTCL 25G64 Gaming Monitor\n176.40 EUR",
            "links": [{"text": "TCL 25G64", "url": "https://shop-b.example/25g64"}],
        },
        {
            "text": "Shop C\nTCL 27G64\n150,00 €",
            "links": [{"text": "TCL 27G64", "url": "https://shop-c.example/27g64"}],
        },
    ])
    offers = parse_salidzini_capture(html, "25G64")
    assert [offer["price_eur"] for offer in offers] == [176.4, 199.0]
    assert offers[0]["product_url"] == "https://shop-b.example/25g64"


def test_assisted_marketplace_manual_result_and_link_are_persisted(tmp_path: Path) -> None:
    store = CatalogStore(tmp_path / "catalog.sqlite3")
    source = store.create_item(
        "source",
        {
            "model": "25G64",
            "marketplace_links": {"salidzini": "https://www.salidzini.lv/example"},
        },
    )
    assert store.get_item(source["id"])["marketplace_links"]["salidzini"].endswith("/example")
    salidzini = next(item for item in store.list_sources() if item["key"] == "salidzini")
    store.register_monitoring_session("run-assisted", False, ["salidzini"])
    store.start_assisted_marketplace_run("run-assisted", [source], [salidzini])
    store.finish_assisted_marketplace_observation(
        "run-assisted", source["id"], "salidzini", "ACTION_REQUIRED",
        search_url="https://www.salidzini.lv/cena?q=25G64", error="Verification required",
    )
    store.resolve_assisted_marketplace_observation(
        "run-assisted", source["id"], "salidzini", "SUCCESS", price_eur=176.4,
        seller_name="RD Electronics",
    )
    result = store.assisted_marketplace_run("run-assisted")["results"][0]
    assert result["status"] == "SUCCESS"
    assert result["cheapest_in_stock"]["price_eur"] == 176.4
    assert result["collection_method"] == "manual"
    assert result["assisted"] is True
    assert result["cheapest_in_stock"]["store"] == "RD Electronics"


def test_salidzini_initial_run_requests_manual_input_immediately(tmp_path: Path) -> None:
    store = CatalogStore(tmp_path / "catalog.sqlite3")
    source = store.create_item("source", {"model": "25G64"})
    store.register_monitoring_session("manual-first", False, ["salidzini"])
    monitor = AssistedMarketplaceMonitor(store, BrowserBridge(timeout_seconds=150))

    monitor.start("manual-first")

    result = store.assisted_marketplace_run("manual-first")
    assert result["status"] == "COMPLETE"
    assert result["results"][0]["status"] == "ACTION_REQUIRED"
    assert "Manual verification is ready" in result["results"][0]["error"]
    assert monitor._tasks == {}
