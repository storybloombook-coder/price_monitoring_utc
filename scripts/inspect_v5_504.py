"""Four bounded marketplace-only HTML samples for the 5.0.4 regression."""
import asyncio
from pathlib import Path
import httpx
from price_monitor_v5.monitor import MarketplaceMonitor
from price_monitor_v5.catalog import CatalogStore
from price_monitor_v5.browser_bridge import BrowserBridge
from price_monitor_v5.sources import search_url


async def main():
    target = Path('build/fixtures-504')
    monitor = MarketplaceMonitor(CatalogStore(target / 'qa.sqlite3'), BrowserBridge())
    for key, model in [('hinnavaatlus','S45HE'), ('hinnavaatlus','S45H'), ('hinnavaatlus','S55H'), ('kaina24','55T7B')]:
        if monitor.blocked(key):
            continue
        headers = {'User-Agent':'PriceMonitor/0.1 (local price monitoring)', 'Accept':'*/*'} if key == 'kaina24' else {'User-Agent':'PriceMonitor/5.0 (personal price comparison)', 'Accept':'text/html'}
        try:
            async with httpx.AsyncClient(headers=headers, timeout=18) as client:
                html, url = await monitor.fetch(client, key, search_url(key, model))
            (target / f'{key}-{model}.html').write_text(html, encoding='utf-8')
            print(key, model, '200', len(html), url, flush=True)
        except Exception as e:
            print(key, model, str(e), flush=True)


if __name__ == '__main__':
    asyncio.run(main())
