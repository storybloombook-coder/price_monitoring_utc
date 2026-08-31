"""Bounded live Kaina24 engine QA; writes only a new isolated test catalog."""
import asyncio
import json
from pathlib import Path
import uuid

from price_monitor_v5.catalog import CatalogStore
from price_monitor_v5.browser_bridge import BrowserBridge
from price_monitor_v5.monitor import MarketplaceMonitor


class InspectMonitor(MarketplaceMonitor):
    async def fetch(self, client, key, url):
        print(json.dumps({"request": url}), flush=True)
        return await super().fetch(client, key, url)


async def main():
    store = CatalogStore(Path("build/kaina-v5-503") / f"live-{uuid.uuid4().hex}.sqlite3")
    for key in ("salidzini", "hinnavaatlus"):
        store.update_source(key, enabled=False)
    for model in ("24G54", "32S4K"):
        store.create_item("source", {"model": model})
    monitor = InspectMonitor(store, BrowserBridge())
    store.begin_run("live", "deep")
    monitor.launch("live")
    await asyncio.gather(*list(monitor.jobs.values()))
    for task in store.run("live")["tasks"]:
        print(json.dumps({key: task.get(key) for key in (
            "source_model", "status", "coverage", "attempts", "product_url", "error", "offers")}, ensure_ascii=True), flush=True)
    await monitor.close()


if __name__ == "__main__":
    asyncio.run(main())
