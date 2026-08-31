"""Small real-network regression. Writes ONLY an isolated QA catalog, not user data."""
import asyncio
import json
from pathlib import Path
import uuid

from price_monitor_v5.catalog import CatalogStore
from price_monitor_v5.browser_bridge import BrowserBridge
from price_monitor_v5.monitor import MarketplaceMonitor


async def main():
    store = CatalogStore(Path("build/v5-live-5.0.1") / f"{uuid.uuid4().hex}.sqlite3")
    for model in ("25G64", "24G54"):
        store.create_item("source", {"model": model})
    monitor = MarketplaceMonitor(store, BrowserBridge())
    store.begin_run("live", "deep")
    monitor.launch("live")
    await asyncio.gather(*list(monitor.jobs.values()))
    for task in store.run("live")["tasks"]:
        print(json.dumps({"model": task["source_model"], "marketplace": task["marketplace_key"], "status": task["status"], "error": task.get("error"), "offers": task["offers"]}, ensure_ascii=True), flush=True)
    await monitor.close()


if __name__ == "__main__":
    asyncio.run(main())
