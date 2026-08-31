"""Reduced real Kaina24 markup; offline regression, no retailer requests."""
import asyncio
import httpx
import pytest

from price_monitor_v5.offers import parse_page
from price_monitor_v5.sources import marketplace_url
from price_monitor_v5.catalog import CatalogStore
from price_monitor_v5.browser_bridge import BrowserBridge
from price_monitor_v5.monitor import MarketplaceMonitor

URL = "https://www.kaina24.lt/p/tcl-24g54/"
SEARCH_URL = "https://www.kaina24.lt/s/tcl-24g54/"


def card(seller="Bite.lt", amount="104.40", model="24G54", compare=True, note=""):
    return f'''<div class="product-item-h-wrap extended"><div class="product-item-h">
      {f'<a class="product-item__compare" href="{URL}"></a>' if compare else ''}
      <p class="name"><a href="/ex/123">TCL <b>{model}</b> monitorius</a></p>
      <p class="price"><a href="/ex/123">{amount} €</a></p>
      <div class="item-delivery">4 d.d. Pristatymo kaina: 4.99 €</div>
      <div class="item-delivery">12 mėn. lizingas nuo 8.88 eur/mėn</div>
      <p class="shop"><a title="{seller}"><img alt="{seller}"></a></p>
      <div class="item-details-on-hover">{note}</div>
      </div></div>'''


def seller_row(seller="Bite.lt", amount="104.40", model="24G54", state="InStock", note=""):
    return f'''<div class="item-table-wrap" itemprop="offers" itemtype="http://schema.org/Offer">
      <table class="seller-item-table"><tr>
      <td class="col-1"><img alt="{seller}" data-src="/logo.svg"></td>
      <td class="col-4"><h3 class="name">Monitorius TCL {model}</h3><p class="description">{note}</p></td>
      <td class="col-5"><div class="status-block"></div></td>
      <td class="col-6"><a href="/ex/123"><div class="price"><span itemprop="price">{amount}</span> €</div></a>
      <div class="delivery">4 d.d. Pristatymo kaina: 4.99 €</div></td>
      <td class="col-7"><div class="tablet-show"><div class="price">{amount} €</div></div>
      <a class="info-link" href="/ex/123"><span itemprop="seller">{seller}
      {f'<link itemprop="availability" href="http://schema.org/{state}">' if state else ''}
      <link itemprop="url" href="https://www.bite.lt/product"></span></a></td>
      </tr></table></div>'''


def product(*rows, count=None):
    return '<h1>Monitorius TCL 24G54 kaina</h1><div itemtype="http://schema.org/AggregateOffer"><link itemprop="availability" href="http://schema.org/InStock">' + (
        f'<span itemprop="offerCount">{count}</span>' if count is not None else ''
    ) + '</div>' + ''.join(rows)


def parse(html, url=URL):
    return parse_page("kaina24", "24G54", html, url)


def test_legacy_search_cards_use_seller_cash_price_not_financing_or_summary():
    html = '<a href="/p/tcl-24g54/" title="TCL 24G54">nuo 99 €</a>' + card() + card("Rde.lt", "106.56")
    result = parse(html, SEARCH_URL)
    assert [o["price_eur"] for o in result["offers"]] == [104.40, 106.56]
    assert [o["seller_key"] for o in result["offers"]] == ["bite", None]
    assert all(o["availability"] == "UNKNOWN" and o["url"] == URL for o in result["offers"])
    assert result["links"] == [URL] and not result["partial"]


def test_product_rows_ignore_mobile_duplicates_recommendations_and_other_models():
    html = product(seller_row(), seller_row("Varle.lt", "108.27"), seller_row("Other", "99", "27G64"), count=2)
    html += card("Recommendation", "1") + '<a href="/p/recommended-24g54/">TCL 24G54</a>'
    result = parse(html)
    assert len(result["offers"]) == 2 and not result["partial"]
    assert result["links"] == [] and result["authoritative_url"] == URL
    assert result["offers"][1]["seller_key"] == "varle"
    assert not parse_page("kaina24", "27G64", html, URL)["offers"]


@pytest.mark.parametrize("model", ["24G54 Pro", "27G54", "124G54", "24G54 remote control"])
def test_wrong_models_do_not_leak_from_search_or_product_title(model):
    assert not parse(card(model=model), SEARCH_URL)["offers"]
    assert not parse(product(seller_row(model=model)))["offers"]


@pytest.mark.parametrize("state,expected", [(None, "UNKNOWN"), ("InStock", "IN_STOCK"), ("PreOrder", "PRE_ORDER"), ("OutOfStock", "OUT_OF_STOCK")])
def test_stock_is_per_seller_never_aggregate_or_delivery_eta(state, expected):
    result = parse(product(seller_row(state=state), count=1))
    assert result["offers"][0]["availability"] == expected


def test_partial_missing_rows_price_and_no_stock_guess():
    assert parse(product(seller_row(), count=5))["partial"]
    result = parse(product(seller_row(amount="104.40 € 8.88"), count=1))
    assert result["partial"] and not result["offers"]
    assert not parse('<h1>TCL 24G54</h1><p>Changed markup</p>')["not_found"]


def test_club_price_uses_explicit_regular_price_optional_coupon_does_not_replace_cash():
    note = "Kaina taikoma ERMI KLUBO nariams. Ne lojalumo programos nariams taikoma kaina 199 €"
    assert parse(card(amount="159", note=note), SEARCH_URL)["offers"][0]["price_eur"] == 199
    assert parse(product(seller_row(amount="159", note=note)))["offers"][0]["price_eur"] == 199
    assert parse(card(note="Kaina taikoma KLUBO nariams"), SEARCH_URL)["partial"]
    assert parse(card(amount="299.99", note="5 Eur nuolaida su kodu Telikas"), SEARCH_URL)["offers"][0]["price_eur"] == 299.99


@pytest.mark.parametrize("path", ["/ex/123", "/EX/123", "/%65%78/123", "/ex.php?id=123"])
def test_outbound_kaina_tracking_links_rejected(path):
    with pytest.raises(ValueError):
        marketplace_url("kaina24", "https://www.kaina24.lt" + path)


def test_search_product_reconciliation_saved_link_and_request_profile(tmp_path):
    async def scenario():
        store = CatalogStore(tmp_path / "test.db")
        item = store.create_item("source", {"model": "24G54"})
        requests = []
        def handler(request):
            requests.append(str(request.url))
            assert request.headers["accept"] == "*/*"
            assert request.headers["user-agent"] == "PriceMonitor/0.1 (local price monitoring)"
            if request.url.path.startswith("/s/"):
                html = card(amount="100") + card("Standalone.lt", "120", compare=False)
            else:
                assert str(request.url) == URL
                html = product(seller_row(amount="104.40"), seller_row("Varle.lt", "108.27"), count=2)
            # Legacy adapter forced UTF-8 even when the server declared otherwise.
            return httpx.Response(200, content=html.encode(), headers={"content-type": "text/html; charset=iso-8859-1"})
        monitor = MarketplaceMonitor(store, BrowserBridge(), delay=0, transport=httpx.MockTransport(handler))
        store.begin_run("one", "deep")
        monitor.schedule(store.check("one", item["id"], "kaina24"))
        await asyncio.gather(*list(monitor.jobs.values()))
        result = next(t for t in store.run("one")["tasks"] if t["marketplace_key"] == "kaina24")
        assert result["status"] == "SUCCESS" and result["coverage"] == "complete"
        assert [o["price_eur"] for o in result["offers"]] == [120, 104.40, 108.27]
        assert result["cheapest_in_stock"]["price_eur"] == 104.40
        assert result["highest_in_stock"]["price_eur"] == 108.27
        assert result["product_url"] == URL
        assert store.get_item(item["id"])["marketplace_links"]["kaina24"] == URL
        assert requests == [SEARCH_URL, URL]
        store.begin_run("two", "deep")
        monitor.schedule(store.check("two", item["id"], "kaina24"))
        await asyncio.gather(*list(monitor.jobs.values()))
        assert requests == [SEARCH_URL, URL, URL]
    asyncio.run(scenario())


def test_protected_comparison_keeps_search_evidence_and_no_more_requests(tmp_path):
    async def scenario():
        store = CatalogStore(tmp_path / "test.db")
        item = store.create_item("source", {"model": "24G54"})
        requests = []
        def handler(request):
            requests.append(str(request.url))
            return httpx.Response(200, text=card()) if request.url.path.startswith("/s/") else httpx.Response(403)
        monitor = MarketplaceMonitor(store, BrowserBridge(), delay=0, transport=httpx.MockTransport(handler))
        store.begin_run("one", "deep")
        monitor.schedule(store.check("one", item["id"], "kaina24"))
        await asyncio.gather(*list(monitor.jobs.values()))
        result = store.check("one", item["id"], "kaina24")
        assert result["status"] == "ACTION_REQUIRED" and result["coverage"] == "partial"
        assert result["offers"][0]["price_eur"] == 104.4
        assert result["offers"][0]["availability"] == "UNKNOWN"
        assert monitor.blocked("kaina24") and requests == [SEARCH_URL, URL]
    asyncio.run(scenario())


def test_saved_missing_product_falls_back_to_search(tmp_path):
    async def scenario():
        store = CatalogStore(tmp_path / "test.db")
        old = "https://www.kaina24.lt/p/old-24g54/"
        item = store.create_item("source", {"model": "24G54", "marketplace_links": {"kaina24": old}})
        requests = []
        def handler(request):
            requests.append(str(request.url))
            if str(request.url) == old:
                return httpx.Response(404)
            return httpx.Response(200, text=card() if request.url.path.startswith("/s/") else product(seller_row()))
        monitor = MarketplaceMonitor(store, BrowserBridge(), delay=0, transport=httpx.MockTransport(handler))
        store.begin_run("fallback", "deep")
        monitor.schedule(store.check("fallback", item["id"], "kaina24"))
        await asyncio.gather(*list(monitor.jobs.values()))
        assert store.check("fallback", item["id"], "kaina24")["status"] == "SUCCESS"
        assert requests == [old, SEARCH_URL, URL]
    asyncio.run(scenario())


def test_pagination_stays_on_marketplace_comparison():
    html = product(seller_row(), count=3) + '<a rel="next" href="?page=2">Next</a><a rel="next" href="/ex/123">TCL 24G54</a>'
    result = parse(html)
    assert result["links"] == [URL + "?page=2"]
    assert not result["partial"]


def test_featured_placements_and_archived_sold_out_prices_are_not_current_duplicates():
    archived = seller_row("Old shop", "1").replace('class="item-table-wrap"', 'class="disabled-item item-table-wrap"')
    html = product(seller_row(state=None), seller_row(), archived, count=1)
    result = parse(html)
    assert len(result["offers"]) == 1 and not result["partial"]
    assert result["offers"][0]["availability"] == "IN_STOCK"


@pytest.mark.parametrize("expected,status", [(2, "SUCCESS"), (3, "ACTION_REQUIRED")])
def test_count_coverage_across_pagination(tmp_path, expected, status):
    async def scenario():
        store = CatalogStore(tmp_path / "test.db")
        item = store.create_item("source", {"model": "24G54", "marketplace_links": {"kaina24": URL}})
        def handler(request):
            html = (product(seller_row(), count=expected) + '<a rel="next" href="?page=2">Next</a>'
                    if not request.url.query else product(seller_row("Varle.lt", "108.27")))
            return httpx.Response(200, text=html)
        monitor = MarketplaceMonitor(store, BrowserBridge(), delay=0, transport=httpx.MockTransport(handler))
        store.begin_run("pages", "deep")
        monitor.schedule(store.check("pages", item["id"], "kaina24"))
        await asyncio.gather(*list(monitor.jobs.values()))
        result = store.check("pages", item["id"], "kaina24")
        assert result["status"] == status
        assert len(result["offers"]) == 2
        assert result["product_url"] == URL
    asyncio.run(scenario())
