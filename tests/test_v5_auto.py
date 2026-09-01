import asyncio
from pathlib import Path
import re
import httpx
import pytest
from fastapi.testclient import TestClient
from price_monitor_v5.app import create_app
from price_monitor_v5.config import Settings
from price_monitor_v5.catalog import CatalogStore
from price_monitor_v5.monitor import MarketplaceMonitor
from price_monitor_v5.browser_bridge import BrowserBridge, EXTENSION_ORIGIN
from price_monitor_v5.offers import parse_page
from test_v5_salidzini import modern_card

URL = 'https://www.salidzini.lv/cena?q=TCL+115RM9L'
REAL_CARDS = (Path(__file__).parent/'fixtures/salidzini-115rm9l-cards.html').read_text(encoding='utf-8')
REAL_COUNTED = re.sub(r'(<h1\b.*?</h1>)', r'<div>\1 <span>3 preces no 3 veikaliem</span></div>', REAL_CARDS, count=1)


class FakeBridge:
    connected = True
    automatic_salidzini = True

    def __init__(self, pages):
        self.pages, self.urls = pages, []

    async def capture(self, key, model, url, *, automatic=False):
        assert key == 'salidzini' and automatic
        self.urls.append(url)
        result = self.pages(url) if callable(self.pages) else self.pages
        return {'html': result, 'url': url} if isinstance(result,str) else result


async def collect(store, bridge, model='115RM9L', run='auto', delay=0):
    item = store.create_item('source', {'model':model})
    store.begin_run(run,'deep')
    monitor = MarketplaceMonitor(store,bridge,delay=delay,transport=httpx.MockTransport(lambda _:pytest.fail('Auto/Manual must not fetch websites over HTTP')))
    monitor.schedule(store.check(run,item['id'],'salidzini'))
    await asyncio.gather(*list(monitor.jobs.values()))
    return monitor,store.check(run,item['id'],'salidzini')


def test_auto_finishes_complete_live_dom_and_bypasses_only_http_cooldown(tmp_path):
    async def scenario():
        store=CatalogStore(tmp_path/'db'); bridge=FakeBridge(REAL_COUNTED)
        with store.connect() as db: store._set_meta(db,'v5_cooldowns',{'salidzini':'2099-01-01'})
        _, task=await collect(store,bridge)
        assert task['status']=='SUCCESS' and task['coverage']=='complete'
        assert len(task['offers'])==3 and len(bridge.urls)==1
        assert store.run('auto')['tasks'][0]['status'] != 'RUNNING'
    asyncio.run(scenario())


@pytest.mark.parametrize('mode,connected,capability', [('manual',True,True),('auto',False,True),('auto',True,False)])
def test_manual_offline_and_old_extension_never_open_pages(tmp_path,mode,connected,capability):
    async def scenario():
        store=CatalogStore(tmp_path/'db');store.set_salidzini_mode(mode)
        bridge=FakeBridge(REAL_COUNTED);bridge.connected=connected;bridge.automatic_salidzini=capability
        _,task=await collect(store,bridge)
        assert task['status']=='ACTION_REQUIRED' and not bridge.urls
        assert ('Manual mode' if mode=='manual' else 'extension') in task['error']
    asyncio.run(scenario())


def test_pagination_counts_listings_not_deduplicated_sellers(tmp_path):
    async def scenario():
        store=CatalogStore(tmp_path/'db')
        def pages(url):
            header='<div><h1>TCL 115RM9L</h1><span>2 preces no 1 veikaliem</span></div>'
            if 'offset=' not in url:
                return header+modern_card()+f'<a href="{URL}&offset=1">2</a>'
            return header+modern_card(href='/click.php?itemid=124')
        bridge=FakeBridge(pages);_,task=await collect(store,bridge)
        assert bridge.urls==[URL,URL+'&offset=1']
        assert task['status']=='SUCCESS'
        assert task['coverage_detail'].startswith('2 verified listings / 2')
    asyncio.run(scenario())


@pytest.mark.parametrize('html', [REAL_CARDS, REAL_COUNTED.replace('3 preces','6 preces'), REAL_COUNTED.replace('12999,00','bad price',1)])
def test_unproven_coverage_stays_in_review_with_prices(tmp_path,html):
    async def scenario():
        _,task=await collect(CatalogStore(tmp_path/'db'),FakeBridge(html))
        assert task['offers'] and task['status']=='ACTION_REQUIRED' and 'coverage' in task['error']
    asyncio.run(scenario())


def test_small_marketplace_heading_gap_saves_visible_offers_without_cache(tmp_path):
    async def scenario():
        store=CatalogStore(tmp_path/'db')
        _,task=await collect(store,FakeBridge(REAL_COUNTED.replace('3 preces','4 preces')))
        assert task['status']=='SUCCESS' and task['coverage']=='reported_gap'
        assert task['coverage_detail'].startswith('3 verified listings / 4 reported')
        assert store.cached_check('115RM9L','salidzini',4) is None
        run=store.run('auto')
        assert next(s for s in run['shop_results'] if s['shop_key']=='bite')['status']=='UNVERIFIED'
    asyncio.run(scenario())


def test_captcha_pauses_following_skus_without_more_browser_traffic(tmp_path):
    async def scenario():
        store=CatalogStore(tmp_path/'db'); store.create_item('source',{'model':'25G64'});store.create_item('source',{'model':'32S4K'})
        store.begin_run('one','deep');bridge=FakeBridge({'html':'','security_challenge':True,'error':'CAPTCHA'})
        monitor=MarketplaceMonitor(store,bridge,delay=0)
        for task in store.checks('one'):
            if task['marketplace_key']=='salidzini': monitor.schedule(task)
        await asyncio.gather(*list(monitor.jobs.values()))
        assert len(bridge.urls)==1 and all(t['status']=='ACTION_REQUIRED' for t in store.checks('one') if t['marketplace_key']=='salidzini')
    asyncio.run(scenario())


def test_auto_hard_stop_cancels_bridge_and_late_capture(tmp_path):
    async def scenario():
        store=CatalogStore(tmp_path/'db'); item=store.create_item('source',{'model':'115RM9L'});store.begin_run('one','deep')
        bridge=BrowserBridge();bridge.heartbeat(True);monitor=MarketplaceMonitor(store,bridge,delay=0)
        monitor.schedule(store.check('one',item['id'],'salidzini'))
        job=await bridge.next_job(1)
        assert job['automatic']
        await monitor.stop_run('one')
        assert not bridge.submit(job['id'],{'html':REAL_COUNTED,'url':URL})
        assert store.check('one',item['id'],'salidzini')['status']=='INCOMPLETE'
    asyncio.run(scenario())


def test_settings_persist_validate_and_do_not_rewrite_existing_checks(tmp_path):
    settings=Settings.load(tmp_path);store=CatalogStore(settings.catalog_database)
    with TestClient(create_app(settings,store)) as client:
        assert client.get('/salidzini/settings').json()=={'mode':'auto'}
        store.create_item('source',{'model':'115RM9L'});store.begin_run('one','deep')
        before=store.checks('one')
        assert client.post('/salidzini/settings',json={'mode':'manual'}).status_code==200
        assert client.post('/salidzini/settings',json={'mode':'invalid'}).status_code==400
        assert store.checks('one')==before and CatalogStore(settings.catalog_database).salidzini_mode()=='manual'
        assert client.post('/salidzini/settings',json={'mode':'auto'},headers={'origin':'https://evil.test'}).status_code==403
        assert client.post('/browser-bridge/heartbeat?auto_salidzini=true',headers={'origin':EXTENSION_ORIGIN}).json()['automatic_salidzini']


def test_pagination_never_changes_sku_even_with_rel_next():
    page='<div><h1>TCL 115RM9L</h1>1 prece</div>'+modern_card()+'<a rel="next" href="/cena?q=TCL+27G64&page=2">next</a>'
    assert parse_page('salidzini','115RM9L',page,URL)['links']==[]


def test_auto_shortened_queries_keep_original_model(tmp_path):
    async def scenario():
        _,task=await collect(CatalogStore(tmp_path/'db'),FakeBridge('<div><h1>Search</h1>0 preces</div>'))
        assert task['status']=='NOT_FOUND' and task['search_queries']==['115RM9L','115RM9','115RM']
    asyncio.run(scenario())


def test_incomplete_nonmatching_page_is_not_not_found(tmp_path):
    async def scenario():
        page='<div><h1>TCL 115RM9L</h1>3 preces</div>'+modern_card(title='TCL 115RM9X')
        bridge=FakeBridge(page);_,task=await collect(CatalogStore(tmp_path/'db'),bridge)
        assert task['status']=='ACTION_REQUIRED' and len(bridge.urls)==1
    asyncio.run(scenario())


def test_normal_host_and_encoding_redirect_is_not_a_different_sku(tmp_path):
    async def scenario():
        bridge=FakeBridge({'html':REAL_COUNTED,'url':'https://salidzini.lv/cena?q=TCL%20115RM9L'})
        _,task=await collect(CatalogStore(tmp_path/'db'),bridge)
        assert task['status']=='SUCCESS'
    asyncio.run(scenario())


def test_auto_starts_at_first_page_of_saved_manual_search(tmp_path):
    async def scenario():
        store=CatalogStore(tmp_path/'db');item=store.create_item('source',{'model':'115RM9L'})
        store.remember_source_link(item['id'],'salidzini',URL+'&offset=20')
        store.begin_run('one','deep');bridge=FakeBridge(REAL_COUNTED)
        monitor=MarketplaceMonitor(store,bridge,delay=0)
        monitor.schedule(store.check('one',item['id'],'salidzini'))
        await asyncio.gather(*list(monitor.jobs.values()))
        assert bridge.urls==[URL] and store.check('one',item['id'],'salidzini')['status']=='SUCCESS'
    asyncio.run(scenario())
