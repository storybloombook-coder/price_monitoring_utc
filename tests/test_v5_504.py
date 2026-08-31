import asyncio
from urllib.parse import parse_qs
import httpx
import pytest
from openpyxl import load_workbook
from price_monitor_v5.catalog import CatalogStore, utc_now
from price_monitor_v5.monitor import MarketplaceMonitor
from price_monitor_v5.browser_bridge import BrowserBridge
from price_monitor_v5.offers import parse_page, exact_model, seller_key
from price_monitor_v5.exporter import write_monitoring_export
from test_kaina24_v5 import card, product, seller_row


def test_rde_split_survives_migration_and_old_offers(tmp_path):
    store = CatalogStore(tmp_path / 'db')
    store.update_source('rde', enabled=False)
    store.migrate()
    sources = {s['key']:s for s in store.list_sources()}
    assert sources['rde']['name'] == 'RDE.ee' and not sources['rde']['enabled']
    assert sources['rde_lt']['country'] == 'Lithuania'
    assert seller_key('Rde.lt','kaina24') == 'rde_lt'
    assert seller_key('RDE','kaina24') == 'rde_lt'
    assert seller_key('RDE.ee','hinnavaatlus') == 'rde'
    assert seller_key('RDE','salidzini') is None
    store.create_item('source', {'model':'24G54'})
    store.begin_run('old','deep')
    task = next(t for t in store.checks('old') if t['marketplace_key']=='kaina24')
    task.update(status='SUCCESS', coverage='complete', offers=[{'store':'Rde.lt','seller_key':None,'price_eur':100,'availability':'IN_STOCK','url':'https://www.kaina24.lt/p/tcl-24g54/'}])
    store.save_check(task)
    run = store.run('old')
    assert next(s for s in run['shop_results'] if s['shop_key']=='rde_lt')['price_eur']==100
    assert next(s for s in run['shop_results'] if s['shop_key']=='rde')['price_eur'] is None
    assert store.check('old',task['item_id'],'kaina24')['offers'][0]['seller_key'] is None
    path=tmp_path/'export.xlsx';write_monitoring_export(path,run)
    headers=[c.value for c in load_workbook(path).active[1]]
    assert 'RDE.ee' in headers and 'RDE.lt' in headers


def test_senukai_card_price_metadata_and_old_cache_invalidation(tmp_path):
    note='Kaina taikoma SMART NET nariams. Ne lojalumo programos nariams taikoma kaina 399 €'
    for body,url in [(card('Senukai.lt','368.99',note=note),'https://www.kaina24.lt/s/tcl-24g54/'),(product(seller_row('Senukai.lt','368.99',note=note)),'https://www.kaina24.lt/p/tcl-24g54/')]:
        offer=parse_page('kaina24','24G54',body,url)['offers'][0]
        assert offer['price_eur']==368.99 and offer['price_basis']=='loyalty'
    store=CatalogStore(tmp_path/'db');store.create_item('source',{'model':'24G54'});store.begin_run('old','deep')
    task=next(t for t in store.checks('old') if t['marketplace_key']=='kaina24')
    task.update(status='SUCCESS',coverage='complete',finished_at=utc_now(),collection_method='marketplace HTML',offers=[offer])
    store.save_check(task)
    assert store.cached_check('24G54','kaina24',4) is None
    task['collection_revision']=2;store.save_check(task)
    assert store.cached_check('24G54','kaina24',4)


@pytest.mark.parametrize('model,alias',[('S45HE','S45H'),('S55HE','S55H')])
def test_hinna_known_alias_and_saved_page(model,alias,tmp_path):
    async def scenario():
        store=CatalogStore(tmp_path/'db');item=store.create_item('source',{'model':model});requests=[]
        url=f'https://www.hinnavaatlus.ee/4116083/tcl-{alias.lower()}/'
        def handler(request):
            requests.append(str(request.url))
            q=parse_qs(request.url.query.decode()).get('query',[''])[0]
            if q==f'TCL {model}':return httpx.Response(200,text='0 toodet')
            if q==f'TCL {alias}':return httpx.Response(200,text=f'<h1>Otsing: {q}</h1><a class="product-name" href="{url}">TCL soundbar {alias}</a>')
            return httpx.Response(200,text=f'<h1>TCL soundbar {alias}</h1><table><tr class="offer"><td class="name">RDE.EE</td><td class="offer-price">99 €</td></tr></table>')
        monitor=MarketplaceMonitor(store,BrowserBridge(),delay=0,transport=httpx.MockTransport(handler))
        store.begin_run('one','deep');monitor.schedule(store.check('one',item['id'],'hinnavaatlus'));await asyncio.gather(*list(monitor.jobs.values()))
        task=store.check('one',item['id'],'hinnavaatlus')
        assert task['status']=='SUCCESS' and len(requests)==3
        assert task['source_model']==model and task['offers'][0]['matched_model']==alias
        assert task['search_queries']==[model,alias]
        store.begin_run('two','deep');monitor.schedule(store.check('two',item['id'],'hinnavaatlus'));await asyncio.gather(*list(monitor.jobs.values()))
        assert len(requests)==4 and requests[-1]==url
        assert store.check('two',item['id'],'hinnavaatlus')['attempts']==1
        assert not exact_model(model,alias)  # Exact matching stays strict; aliases are explicit.
    asyncio.run(scenario())


@pytest.mark.parametrize('case,expected,count',[('empty','NOT_FOUND',3),('candidate','ACTION_REQUIRED',3),('blocked','ACTION_REQUIRED',1),('unknown','ACTION_REQUIRED',1),('network','ACTION_REQUIRED',1)])
def test_bounded_shortening_never_turns_protection_or_similar_models_into_not_found(case,expected,count,tmp_path):
    async def scenario():
        store=CatalogStore(tmp_path/'db');item=store.create_item('source',{'model':'55C7KE'});requests=[]
        def handler(request):
            requests.append(str(request.url))
            if case=='network':raise httpx.ConnectError('offline',request=request)
            if case=='blocked':return httpx.Response(403)
            if case=='unknown':return httpx.Response(200,text='unknown HTML')
            if case=='candidate' and len(requests)>1:
                return httpx.Response(200,text='<h1>Otsing: TCL 55C7K</h1><a class="product-name" href="/123456/55c7k/">TCL 55C7K</a>')
            return httpx.Response(200,text='0 toodet')
        monitor=MarketplaceMonitor(store,BrowserBridge(),delay=0,transport=httpx.MockTransport(handler))
        store.begin_run('one','deep');monitor.schedule(store.check('one',item['id'],'hinnavaatlus'));await asyncio.gather(*list(monitor.jobs.values()))
        task=store.check('one',item['id'],'hinnavaatlus')
        assert task['status']==expected and len(requests)==count
        assert task['offers']==[]
        if case=='candidate':assert len(task['candidate_matches'])==1
    asyncio.run(scenario())


def test_unverified_is_not_absence(tmp_path):
    store=CatalogStore(tmp_path/'db');store.create_item('source',{'model':'24G54'});store.begin_run('one','deep')
    assert {s['status'] for s in store.run('one')['shop_results']}=={'UNVERIFIED'}
    for task in store.checks('one'):
        task.update(status='NOT_FOUND',coverage='complete');store.save_check(task)
    assert {s['status'] for s in store.run('one')['shop_results']}=={'NOT_LISTED'}
