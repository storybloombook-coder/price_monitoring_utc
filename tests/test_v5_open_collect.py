import asyncio
import httpx
import pytest
from fastapi.testclient import TestClient
from price_monitor_v5.app import create_app
from price_monitor_v5.catalog import CatalogStore
from price_monitor_v5.config import Settings
from price_monitor_v5.browser_bridge import BrowserBridge, EXTENSION_ORIGIN
from price_monitor_v5.monitor import MarketplaceMonitor
from test_v5_auto import REAL_COUNTED, REAL_CARDS, URL
from test_v5_salidzini import modern_card
from test_v5 import PRODUCT, PRODUCT_URL
from test_kaina24_v5 import product, seller_row


def setup(tmp_path, key='salidzini', model='115RM9L'):
    store=CatalogStore(tmp_path/'db')
    store.set_salidzini_mode('manual')
    item=store.create_item('source',{'model':model})
    for other in ['kaina24','salidzini','hinnavaatlus']:
        store.update_source(other,other==key)
    store.begin_run('one','deep')
    bridge=BrowserBridge();bridge.heartbeat(True,True)
    monitor=MarketplaceMonitor(store,bridge,delay=0,transport=httpx.MockTransport(lambda _:pytest.fail('Only browser pages may be collected')))
    return store,item,bridge,monitor


async def reply(bridge, html):
    job=await bridge.next_job(1)
    assert job and job['verification_id']
    assert bridge.verification(job['verification_id'])['state']=='pending'
    assert bridge.submit(job['id'],{'html':html,'url':job['url']})
    return job


def test_manual_mode_one_click_finishes_only_after_saved_result(tmp_path):
    async def scenario():
        store,item,bridge,monitor=setup(tmp_path)
        token=await monitor.retry('one',item['id'],'salidzini',open_collect=True)
        saved=store.save_check
        def checked_save(task):
            assert bridge.verification(token)['state']=='pending'
            saved(task)
        store.save_check=checked_save
        await reply(bridge,REAL_COUNTED)
        await asyncio.gather(*monitor.jobs.values())
        assert bridge.verification(token)['state']=='complete'
        task=store.check('one',item['id'],'salidzini')
        assert task['status']=='SUCCESS' and len(task['offers'])==3
        assert store.salidzini_mode()=='manual'
    asyncio.run(scenario())


@pytest.mark.parametrize('key,model,url,html',[
    ('hinnavaatlus','25G64',PRODUCT_URL,PRODUCT),
    ('kaina24','24G54','https://www.kaina24.lt/p/tcl-24g54/',product(seller_row('Varle.lt','199'))),
])
def test_all_marketplaces_use_same_confirmed_save_contract(tmp_path,key,model,url,html):
    async def scenario():
        store,item,bridge,monitor=setup(tmp_path,key,model)
        token=await monitor.retry('one',item['id'],key,url=url,open_collect=True)
        await reply(bridge,html)
        await asyncio.gather(*monitor.jobs.values())
        assert bridge.verification(token)['state']=='complete'
        assert store.check('one',item['id'],key)['offers']
    asyncio.run(scenario())


def test_partial_capture_publishes_prices_and_authorizes_closure_with_coverage_notice(tmp_path):
    async def scenario():
        store,item,bridge,monitor=setup(tmp_path)
        token=await monitor.retry('one',item['id'],'salidzini',open_collect=True)
        await reply(bridge,REAL_CARDS)
        await asyncio.gather(*monitor.jobs.values())
        assert bridge.verification(token)['state']=='complete'
        task=store.check('one',item['id'],'salidzini')
        assert task['offers'] and task['status']=='SUCCESS' and task['coverage']=='partial'
    asyncio.run(scenario())


def test_all_visible_offers_with_small_reported_count_gap_closes_tab(tmp_path):
    async def scenario():
        store,item,bridge,monitor=setup(tmp_path)
        token=await monitor.retry('one',item['id'],'salidzini',open_collect=True)
        await reply(bridge,REAL_COUNTED.replace('3 preces','4 preces'))
        await asyncio.gather(*monitor.jobs.values())
        task=store.check('one',item['id'],'salidzini')
        assert task['status']=='SUCCESS' and task['coverage']=='reported_gap'
        assert bridge.verification(token)['state']=='complete'
    asyncio.run(scenario())


def test_pagination_receipt_waits_for_last_page(tmp_path):
    async def scenario():
        store,item,bridge,monitor=setup(tmp_path)
        token=await monitor.retry('one',item['id'],'salidzini',open_collect=True)
        header='<div><h1>TCL 115RM9L</h1>2 preces</div>'
        await reply(bridge,header+modern_card()+f'<a href="{URL}&offset=1">2</a>')
        job=await bridge.next_job(1)
        assert job['verification_id']==token and job['url'].endswith('offset=1')
        assert bridge.verification(token)['state']=='pending'
        bridge.submit(job['id'],{'url':job['url'],'html':header+modern_card(href='/click.php?itemid=124')})
        await asyncio.gather(*monitor.jobs.values())
        assert bridge.verification(token)['state']=='complete'
    asyncio.run(scenario())


def test_confirmed_absence_checks_fallback_queries_before_closing(tmp_path):
    async def scenario():
        store,item,bridge,monitor=setup(tmp_path)
        token=await monitor.retry('one',item['id'],'salidzini',open_collect=True)
        for _ in range(3): await reply(bridge,'<div><h1>Search</h1>0 preces</div>')
        await asyncio.gather(*monitor.jobs.values())
        assert bridge.verification(token)['state']=='complete' and bridge.verification(token)['status']=='NOT_FOUND'
    asyncio.run(scenario())


@pytest.mark.parametrize('replacement',['stop','retry','manual'])
def test_cancelled_session_and_late_reply_cannot_close_tab(tmp_path,replacement):
    async def scenario():
        store,item,bridge,monitor=setup(tmp_path)
        token=await monitor.retry('one',item['id'],'salidzini',open_collect=True)
        job=await bridge.next_job(1)
        if replacement=='stop': await monitor.stop_run('one')
        elif replacement=='retry': await monitor.retry('one',item['id'],'salidzini')
        else: await monitor.resolve('one',item['id'],'salidzini',{'status':'NOT_FOUND'})
        assert bridge.verification(token)['state']=='cancelled'
        assert not bridge.submit(job['id'],{'url':URL,'html':REAL_COUNTED})
        await monitor.close()
    asyncio.run(scenario())


def test_database_failure_never_grants_close_receipt(tmp_path):
    async def scenario():
        store,item,bridge,monitor=setup(tmp_path)
        token=await monitor.retry('one',item['id'],'salidzini',open_collect=True)
        job=await bridge.next_job(1)
        store.save_check=lambda _: (_ for _ in ()).throw(RuntimeError('disk unavailable'))
        bridge.submit(job['id'],{'url':URL,'html':REAL_COUNTED})
        tasks=list(monitor.jobs.values())
        assert any(isinstance(r,RuntimeError) for r in await asyncio.gather(*tasks,return_exceptions=True))
        assert bridge.verification(token)['state']=='review'
    asyncio.run(scenario())


def test_new_extension_required_before_changing_existing_result(tmp_path):
    async def scenario():
        store,item,bridge,monitor=setup(tmp_path)
        before=store.check('one',item['id'],'salidzini')
        bridge.heartbeat(True,False)
        with pytest.raises(ValueError,match='v5.0.9'): await monitor.retry('one',item['id'],'salidzini',open_collect=True)
        assert store.check('one',item['id'],'salidzini')==before and not monitor.jobs
    asyncio.run(scenario())


def test_initial_save_failure_does_not_leave_a_stuck_verification(tmp_path):
    async def scenario():
        store,item,bridge,monitor=setup(tmp_path)
        store.save_check=lambda _: (_ for _ in ()).throw(RuntimeError('disk unavailable'))
        with pytest.raises(RuntimeError):await monitor.retry('one',item['id'],'salidzini',open_collect=True)
        assert not monitor.jobs and not monitor.verification_jobs
    asyncio.run(scenario())


def test_second_model_waits_for_first_interactive_check(tmp_path):
    async def scenario():
        store,item,bridge,monitor=setup(tmp_path)
        second=store.create_item('source',{'model':'25G64'});store.begin_run('two','deep')
        token=await monitor.retry('one',item['id'],'salidzini',open_collect=True)
        with pytest.raises(ValueError,match='Another Open'):
            await monitor.retry('two',second['id'],'salidzini',open_collect=True)
        assert bridge.verification(token)['state']=='pending'
        await monitor.close()
    asyncio.run(scenario())


def test_changed_comparison_page_cannot_confirm_absence(tmp_path):
    async def scenario():
        store,item,bridge,monitor=setup(tmp_path,'hinnavaatlus','25G64')
        token=await monitor.retry('one',item['id'],'hinnavaatlus',open_collect=True)
        job=await bridge.next_job(1)
        bridge.submit(job['id'],{'url':'https://www.hinnavaatlus.ee/search/?query=unrelated','html':'0 toodet'})
        await asyncio.gather(*monitor.jobs.values())
        assert bridge.verification(token)['state']=='review'
    asyncio.run(scenario())


def test_open_collect_http_flow_and_receipt_origin_guard(tmp_path):
    with TestClient(create_app(Settings.load(tmp_path))) as client:
        catalog=client.app.state.catalog
        item=catalog.create_item('source',{'model':'115RM9L'})
        catalog.begin_run('one','deep')
        headers={'origin':EXTENSION_ORIGIN}
        client.post('/browser-bridge/heartbeat?auto_salidzini=true&open_collect=true',headers=headers)
        base=f"/runs/one/marketplaces/{item['id']}/salidzini"
        assert client.post(base+'/open-collect',headers={'origin':'https://evil.test'}).status_code==403
        result=client.post(base+'/open-collect');assert result.status_code==200
        token=result.json()['verification_id']
        path='/browser-bridge/verifications/'+token
        assert client.get(path).status_code==403
        assert client.get(path,headers=headers).json()['state']=='pending'
        job=client.get('/browser-bridge/jobs/next?wait_seconds=1',headers=headers).json()
        client.post('/browser-bridge/jobs/'+job['id']+'/result',headers=headers,json={'url':job['url'],'html':REAL_COUNTED})
        for _ in range(20):
            receipt=client.get(path,headers=headers).json()
            if receipt['state']!='pending':break
        assert receipt['state']=='complete'
