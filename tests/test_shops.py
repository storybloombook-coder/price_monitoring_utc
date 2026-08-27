import asyncio

import httpx

from price_monitor_v4.shops import ActionRequiredError, ShopMonitor, find_product_url, incomplete_catalog_render, parse_product, security_challenge


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
    assert "normal browser" in kwargs["error"]
