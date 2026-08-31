"""Default bounded fallback on every marketplace, with strict price evidence."""
import asyncio
import httpx
import pytest

from price_monitor_v5.browser_bridge import BrowserBridge
from price_monitor_v5.catalog import CatalogStore, utc_now
from price_monitor_v5.monitor import MarketplaceMonitor
from price_monitor_v5.offers import parse_page, matched_model, shortened_queries, candidate_links
from price_monitor_v5.sources import search_url
from test_kaina24_v5 import card, product, seller_row

KEYS = ['kaina24', 'salidzini', 'hinnavaatlus']


def search_card(key, model):
    if key == 'kaina24':
        return card(model=model, compare=False)
    if key == 'salidzini':
        return f'<div class="item_block"><a class="item_name" href="/out/123">TCL {model}</a><div class="item_shop_name">Varle.lt</div><div class="item_price">98.59 €</div></div>'
    return f'<h1>Otsing: TCL</h1><a class="product-name" href="/123456/{model.lower()}/">TCL {model}</a>'


@pytest.mark.parametrize('key', KEYS)
@pytest.mark.parametrize('capture', [False, True])
@pytest.mark.parametrize('case', ['empty', 'candidate', 'blocked', 'unknown', 'network', 'exact'])
def test_default_searches_all_marketplaces_and_methods(tmp_path, key, capture, case):
    async def scenario():
        store = CatalogStore(tmp_path / 'db')
        item = store.create_item('source', {'model': '55C7KE'})
        urls = []

        def content(url):
            urls.append(url)
            if case == 'network':
                raise httpx.ConnectError('offline')
            if case == 'unknown':
                return 'unrecognized HTML'
            if case == 'candidate' and len(urls) > 1:
                return search_card(key, '55C7K')
            if case == 'exact':
                if key == 'hinnavaatlus' and '/123456/' in url:
                    return '<h1>TCL 55C7KE</h1><tr class="offer"><td class="name">RDE.EE</td><td class="offer-price">199 €</td></tr>'
                return search_card(key, '55C7KE')
            return 'prekių nerasta' if key == 'kaina24' else 'nekas netika atrasts' if key == 'salidzini' else '0 toodet'

        def handler(request):
            html = content(str(request.url))
            return httpx.Response(403 if case == 'blocked' else 200, text=html)

        class Bridge:
            async def capture(self, source, model, url):
                return {'html': content(url), 'url': url, 'security_challenge': case == 'blocked'}

        monitor = MarketplaceMonitor(store, Bridge(), delay=0, transport=httpx.MockTransport(handler))
        store.begin_run('one', 'deep')
        monitor.schedule(store.check('one', item['id'], key), capture=capture)
        await asyncio.gather(*list(monitor.jobs.values()))
        task = store.check('one', item['id'], key)
        if case == 'empty':
            assert task['status'] == 'NOT_FOUND'
        elif case == 'exact':
            assert task['offers'] and task['search_queries'] == ['55C7KE']
        else:
            assert task['status'] == 'ACTION_REQUIRED' and not task['offers']
        if case in {'empty', 'candidate'}:
            assert urls == [search_url(key, model) for model in ['55C7KE', '55C7K', '55C7']]
            assert task['search_queries'] == ['55C7KE', '55C7K', '55C7']
            if case == 'candidate':
                assert task['candidate_matches']
                assert all('/out/' not in c['url'] and '/ex/' not in c['url'] for c in task['candidate_matches'])
        elif case != 'exact':
            assert len(urls) == 1
    asyncio.run(scenario())


@pytest.mark.parametrize('key', KEYS)
@pytest.mark.parametrize('model,alias', [('S45HE', 'S45H'), ('S55HE', 'S55H')])
def test_known_aliases_are_global_but_other_variants_are_not(key, model, alias):
    assert matched_model(key, model, f'TCL S {alias} soundbar') == alias
    for title in [f'TCL {alias} Pro', f'TCL {alias} Plus', f'TCL {alias} remote control', 'TCL S60H']:
        assert matched_model(key, model, title) is None
    assert matched_model(key, '65C8L', 'TCL 65C8') is None
    url = search_url(key, model)
    html = search_card(key, alias)
    if key == 'hinnavaatlus':
        url = 'https://www.hinnavaatlus.ee/123456/soundbar/'
        html = f'<h1>TCL {alias}</h1><tr class="offer"><td class="name">RDE.EE</td><td class="offer-price">99 €</td></tr>'
    result = parse_page(key, model, html, url)
    assert result['offers'][0]['matched_model'] == alias


def test_kaina_s55he_varle_second_page_and_comparison(tmp_path):
    async def scenario():
        store = CatalogStore(tmp_path / 'db')
        item = store.create_item('source', {'model': 'S55HE'})
        first = search_url('kaina24', 'S55HE')
        second = first + '?page=2'
        comparison = 'https://www.kaina24.lt/p/tcl-s55h/'
        urls = []
        def handler(request):
            url = str(request.url)
            urls.append(url)
            if url == first:
                html = card('Rde.lt', '100', 'S55HE', compare=False) + f'<a href="{second}">2</a>'
            elif url == second:
                html = card('Varle.lt', '98.59', 'S S55H', compare=False) + f'<a href="{comparison}">TCL S55H</a>'
            else:
                assert url == comparison
                html = product(seller_row('Varle.lt', '98.59', 'S55H'), count=1).replace('Monitorius TCL 24G54 kaina', 'Namų kinas TCL S55H kaina')
            return httpx.Response(200, text=html)
        monitor = MarketplaceMonitor(store, BrowserBridge(), delay=0, transport=httpx.MockTransport(handler))
        store.begin_run('one', 'deep')
        monitor.schedule(store.check('one', item['id'], 'kaina24'))
        await asyncio.gather(*list(monitor.jobs.values()))
        task = store.check('one', item['id'], 'kaina24')
        assert urls == [first, second, comparison]
        varle = next(s for s in store.run('one')['shop_results'] if s['shop_key'] == 'varle')
        assert varle['price_eur'] == 98.59
        assert task['source_model'] == 'S55HE'
        assert any(o.get('matched_model') == 'S55H' and o['store'] == 'Varle.lt' for o in task['offers'])
    asyncio.run(scenario())


def test_missing_price_is_review_not_a_reason_for_shortening():
    html = '<div class="item_block"><a class="item_name">TCL S55HE</a></div>'
    parsed = parse_page('salidzini', 'S55HE', html, search_url('salidzini', 'S55HE'))
    assert parsed['partial'] and not parsed['not_found']


def test_actual_kaina_empty_message():
    html = '<h1>Tcl-s55hexx kaina</h1><p>Pagal įvestą paieškos frazę nieko neradome. Patikslinkite paieškos frazę arba peržiūrėkite visą prekių katalogą</p>'
    parsed = parse_page('kaina24', 'S55HEXX', html, search_url('kaina24', 'S55HEXX'))
    assert parsed['not_found'] and not parsed['partial']


def test_kaina_later_search_page_does_not_restore_stale_alias_price(tmp_path):
    async def scenario():
        store = CatalogStore(tmp_path / 'db')
        item = store.create_item('source', {'model': 'S55HE'})
        first = search_url('kaina24', 'S55HE')
        second = first + '?page=2'
        comparison = 'https://www.kaina24.lt/p/tcl-s55h/'
        def handler(request):
            if str(request.url) == first:
                html = f'<a href="{comparison}">TCL S55HE</a>' + card(model='S55HE', compare=False) + f'<a href="{second}">2</a>'
            elif str(request.url) == second:
                html = card('Varle.lt', '1', 'S55H').replace('/p/tcl-24g54/', '/p/tcl-s55h/')
            else:
                html = product(seller_row('Varle.lt', '98.59', 'S55H'), count=1).replace('Monitorius TCL 24G54 kaina', 'Namų kinas TCL S55H kaina')
            return httpx.Response(200, text=html)
        monitor = MarketplaceMonitor(store, BrowserBridge(), delay=0, transport=httpx.MockTransport(handler))
        store.begin_run('one', 'deep')
        monitor.schedule(store.check('one', item['id'], 'kaina24'))
        await asyncio.gather(*list(monitor.jobs.values()))
        task = store.check('one', item['id'], 'kaina24')
        assert [o['price_eur'] for o in task['offers'] if o['seller_key'] == 'varle'] == [98.59]
        assert task['product_url'] == comparison
        assert store.get_item(item['id'])['marketplace_links']['kaina24'] == comparison
    asyncio.run(scenario())


def test_shortening_has_limits_and_does_not_change_source_model():
    assert shortened_queries('TCL S55HE') == ['S55H', 'S55']
    assert shortened_queries('65C8L') == ['65C8', '65C']
    assert shortened_queries('A12') == []
    assert shortened_queries('1234') == []


def test_old_alias_cache_is_not_reused(tmp_path):
    store = CatalogStore(tmp_path / 'db')
    item = store.create_item('source', {'model': 'S55HE'})
    store.begin_run('one', 'deep')
    task = store.check('one', item['id'], 'kaina24')
    task.update(status='SUCCESS', coverage='complete', finished_at=utc_now(), collection_method='marketplace HTML', collection_revision=2)
    store.save_check(task)
    assert store.cached_check('S55HE', 'kaina24', 4) is None
    task['collection_revision'] = 3
    store.save_check(task)
    assert store.cached_check('S55HE', 'kaina24', 4)
