import asyncio

import httpx

from price_monitor_v4.browser_bridge import BrowserBridge
from price_monitor_v4.shops import ActionRequiredError, ShopMonitor, find_product_url, incomplete_catalog_render, parse_product, retry_after_seconds, security_challenge


def test_product_json_ld_and_search_link_parsing() -> None:
    product_html = """
    <html><head><script type="application/ld+json">
    {"@type":"Product","name":"TCL 55P7L television","offers":{"@type":"Offer","price":"630.00","priceCurrency":"EUR","availability":"https://schema.org/InStock"}}
    </script></head><body>Available</body></html>
    """
    result = parse_product(product_html, "https://shop.example/tcl-55p7l", "55P7L")
    assert result is not None
    assert result["price_eur"] == 630.0
    assert result["availability"] == "IN_STOCK"

    search_html = '<a href="/products/tcl-55p7l">TCL television 55P7L</a>'
    assert find_product_url(search_html, "https://shop.example/search?q=55P7L", "55P7L") == "https://shop.example/products/tcl-55p7l"

    unrelated = '<a href="#content">Skip</a><a href="/other">Other</a>'
    assert find_product_url(unrelated, "https://shop.example/search?q=55P7L", "55P7L") is None
    assert security_challenge("<title>Just a moment...</title><p>Performing security verification</p>")
    assert incomplete_catalog_render('<span class="MuiSkeleton-root"></span>')
    assert issubclass(ActionRequiredError, ValueError)


def test_security_challenge_is_reported_as_action_required() -> None:
    class Store:
        observation = None

        def pause_shop_for_protection(self, run_id, shop_key, cooldown_seconds, reason) -> str:
            self.cooldown = (run_id, shop_key, cooldown_seconds, reason)
            return "2026-08-27T23:00:00+00:00"

        def finish_shop_observation(self, *args, **kwargs) -> None:
            self.observation = (args, kwargs)

    class Renderer:
        async def fetch(self, url: str) -> str:
            return "<title>Just a moment...</title><p>Performing security verification</p>"

    async def run() -> tuple:
        store = Store()
        monitor = ShopMonitor(store)
        transport = httpx.MockTransport(lambda request: httpx.Response(403, request=request))
        async with httpx.AsyncClient(transport=transport) as client:
            await monitor._check_one(
                client,
                Renderer(),
                "run-1",
                {"id": 7, "model": "55T7B", "shop_links": {}},
                {"key": "varle"},
            )
        return store.observation

    args, kwargs = asyncio.run(run())
    assert args[3] == "ACTION_REQUIRED"
    assert "extension is not connected" in kwargs["error"]
    assert kwargs["retry_after"] == "2026-08-27T23:00:00+00:00"


def test_edge_extension_completes_protected_search_and_product() -> None:
    class Store:
        observation = None

        def finish_shop_observation(self, *args, **kwargs) -> None:
            self.observation = (args, kwargs)

    class Renderer:
        async def fetch(self, url: str) -> None:
            raise AssertionError("Local CDP fallback must not run while the extension is connected")

    async def run() -> tuple:
        bridge = BrowserBridge(timeout_seconds=2)
        bridge.heartbeat()
        store = Store()
        monitor = ShopMonitor(store, browser_bridge=bridge)
        transport = httpx.MockTransport(lambda request: httpx.Response(403, request=request))

        async def extension_worker() -> None:
            search_job = await bridge.next_job(1)
            assert search_job is not None
            bridge.submit(search_job["id"], {
                "url": search_job["url"],
                "html": '<a href="https://www.varle.lt/televizoriai/tcl-55t7b.html">TCL 55T7B</a>',
                "security_challenge": False,
            })
            product_job = await bridge.next_job(1)
            assert product_job is not None
            bridge.submit(product_job["id"], {
                "url": product_job["url"],
                "html": '<script type="application/ld+json">{"@type":"Product","name":"TCL 55T7B","offers":{"price":"368.99","availability":"https://schema.org/InStock"}}</script>',
                "security_challenge": False,
            })

        async with httpx.AsyncClient(transport=transport) as client:
            await asyncio.gather(
                monitor._check_one(
                    client,
                    Renderer(),
                    "run-2",
                    {"id": 8, "model": "55T7B", "shop_links": {}},
                    {"key": "varle"},
                ),
                extension_worker(),
            )
        return store.observation

    args, kwargs = asyncio.run(run())
    assert args[3] == "SUCCESS"
    assert kwargs["price_eur"] == 368.99


def test_rate_limit_honors_retry_after_and_does_not_open_browser() -> None:
    class Store:
        observation = None
        cooldown = None

        def pause_shop_for_protection(self, run_id, shop_key, cooldown_seconds, reason) -> str:
            self.cooldown = (run_id, shop_key, cooldown_seconds, reason)
            return "2026-08-28T00:00:00+00:00"

        def finish_shop_observation(self, *args, **kwargs) -> None:
            self.observation = (args, kwargs)

    class Renderer:
        async def fetch(self, url: str) -> None:
            raise AssertionError("429 must enter cooldown without another browser request")

        async def close(self) -> None:
            return None

    async def run() -> Store:
        store = Store()
        monitor = ShopMonitor(store, cooldown_seconds=3600)
        transport = httpx.MockTransport(
            lambda request: httpx.Response(429, headers={"Retry-After": "120"}, request=request)
        )
        async with httpx.AsyncClient(transport=transport) as client:
            await monitor._check_one(
                client, Renderer(), "run-429", {"id": 9, "model": "55T7B", "shop_links": {}}, {"key": "varle"}
            )
        return store

    store = asyncio.run(run())
    assert store.cooldown[2] == 120
    assert store.observation[0][3] == "ACTION_REQUIRED"
    assert store.observation[1]["retry_after"] == "2026-08-28T00:00:00+00:00"
    assert retry_after_seconds("45", 3600) == 45


def test_direct_only_does_not_fallback_after_protection() -> None:
    class Store:
        observation = None

        def pause_shop_for_protection(self, run_id, shop_key, cooldown_seconds, reason) -> str:
            return "2026-08-28T00:00:00+00:00"

        def finish_shop_observation(self, *args, **kwargs) -> None:
            self.observation = (args, kwargs)

    class Renderer:
        async def fetch(self, url: str) -> None:
            raise AssertionError("Direct-only mode must not open a browser")

    async def run() -> tuple:
        store = Store()
        monitor = ShopMonitor(store)
        transport = httpx.MockTransport(lambda request: httpx.Response(403, request=request))
        async with httpx.AsyncClient(transport=transport) as client:
            await monitor._check_one(
                client, Renderer(), "direct-only", {"id": 10, "model": "55T7B", "shop_links": {}},
                {"key": "varle", "collection_method": "direct"},
            )
        return store.observation

    args, kwargs = asyncio.run(run())
    assert args[3] == "ACTION_REQUIRED"
    assert kwargs["collection_method"] == "direct"
    assert [attempt["method"] for attempt in kwargs["attempts"]] == ["direct"]


def test_manual_only_sends_no_request_and_does_not_start_protection_cooldown() -> None:
    class Store:
        observation = None

        def pause_shop_for_protection(self, *args) -> str:
            raise AssertionError("Manual-only mode must not start retailer protection cooldown")

        def finish_shop_observation(self, *args, **kwargs) -> None:
            self.observation = (args, kwargs)

    class Renderer:
        async def fetch(self, url: str) -> None:
            raise AssertionError("Manual-only mode must not open a browser")

    async def run() -> tuple:
        store = Store()
        monitor = ShopMonitor(store)
        transport = httpx.MockTransport(lambda request: (_ for _ in ()).throw(AssertionError("No HTTP request expected")))
        async with httpx.AsyncClient(transport=transport) as client:
            await monitor._check_one(
                client, Renderer(), "manual-only", {"id": 11, "model": "55T7B", "shop_links": {}},
                {"key": "varle", "collection_method": "manual"},
            )
        return store.observation

    args, kwargs = asyncio.run(run())
    assert args[3] == "ACTION_REQUIRED"
    assert kwargs["retry_after"] is None
    assert kwargs["attempts"] == []


def test_shop_run_never_overlaps_requests_to_the_same_domain() -> None:
    class Store:
        def shop_observation_pending(self, run_id, item_id, shop_key) -> bool:
            return True

    async def run() -> tuple[dict[str, int], int]:
        monitor = ShopMonitor(
            Store(), request_delay_min_seconds=0, request_delay_max_seconds=0,
            cooldown_seconds=60, cache_ttl_seconds=0,
        )
        active: dict[str, int] = {"bite": 0, "elisa": 0}
        maximum: dict[str, int] = {"bite": 0, "elisa": 0}
        global_active = 0
        global_maximum = 0

        async def check(client, renderer, run_id, model, shop, playwright_renderer=None) -> None:
            nonlocal global_active, global_maximum
            key = shop["key"]
            active[key] += 1
            global_active += 1
            maximum[key] = max(maximum[key], active[key])
            global_maximum = max(global_maximum, global_active)
            await asyncio.sleep(0.01)
            active[key] -= 1
            global_active -= 1

        monitor._check_one = check
        await monitor._run(
            "paced-run",
            [{"id": 1, "model": "25G64"}, {"id": 2, "model": "55T7B"}],
            [{"key": "bite"}, {"key": "elisa"}],
        )
        return maximum, global_maximum

    maximum, global_maximum = asyncio.run(run())
    assert maximum == {"bite": 1, "elisa": 1}
    assert global_maximum == 2
