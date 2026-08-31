"""Active-page preview/apply contracts; all tests are offline and isolated."""
import json
import uuid
import httpx
import pytest
from fastapi.testclient import TestClient
from price_monitor_v5.app import create_app
from price_monitor_v5.catalog import CatalogStore
from price_monitor_v5.config import Settings
from price_monitor_v5.browser_bridge import EXTENSION_ORIGIN
from price_monitor_v5.offers import parse_page

URL = 'https://www.salidzini.lv/cena?q=TCL+25G64'


def card(model='25G64', seller='Rde.lv', price='199', extra=''):
    return f'<div class="item_block"><span class="item_name">TCL {model}</span><span class="item_shop_name">{seller}</span><span class="item_price">{price} EUR</span>{extra}</div>'


@pytest.fixture
def setup(tmp_path):
    settings = Settings.load(tmp_path)
    store = CatalogStore(settings.catalog_database)
    item = store.create_item('source', {'model': '25G64'})
    app = create_app(settings, store, httpx.MockTransport(lambda _: pytest.fail('Page import must not fetch websites')))
    with TestClient(app) as client:
        store.begin_run('qa-one', 'deep')
        for task in store.checks('qa-one'):
            task.update(status='ACTION_REQUIRED', coverage='partial')
            store.save_check(task)
        yield client, store, item


def payload(**updates):
    return {'capture_id': str(uuid.uuid4()), 'model': '25G64', 'url': URL,
            'html': card() + card('27G64', 'Wrong.lv', '1') + card(seller='Euronics.ee', price='249'),
            'captured_at': '2026-08-31T20:00:00Z', **updates}


def preview(client, body):
    response = client.post('/browser-bridge/page-preview', json=body, headers={'origin': EXTENSION_ORIGIN})
    assert response.status_code == 200, response.text
    return response.json()


def apply(client, body, result, complete=False, selected=None):
    return client.post('/browser-bridge/page-apply', json={**body,
        **{k: result[k] for k in ['run_id', 'item_id', 'expected_signature']},
        'selected_indices': list(range(len(result['offers']))) if selected is None else selected,
        'all_pages_reviewed': complete}, headers={'origin': EXTENSION_ORIGIN})


def test_preview_is_read_only_filters_model_and_apply_is_idempotent(setup):
    client, store, item = setup
    before = store.check('qa-one', item['id'], 'salidzini')
    body = payload()
    result = preview(client, body)
    assert [o['price_eur'] for o in result['offers']] == [199, 249]
    assert result['offers'][0]['seller_key'] is None  # Rde.lv is not Rde.lt/ee.
    assert store.check('qa-one', item['id'], 'salidzini') == before
    assert client.get('/browser-bridge/status').json()['capture_revision'] == 0
    saved = apply(client, body, result, complete=True)
    assert saved.status_code == 200, saved.text
    assert saved.json()['saved'] == 2
    task = store.check('qa-one', item['id'], 'salidzini')
    assert task['status'] == 'SUCCESS' and task['collection_method'] == 'manual'
    assert task['offers'][0]['captured_at'] == body['captured_at']
    assert store.cached_check('25G64', 'salidzini', 4) is None
    again = apply(client, body, result, complete=True)
    assert again.json()['already_applied']
    assert store.check('qa-one', item['id'], 'salidzini') == task
    assert client.get('/browser-bridge/status').json()['capture_revision'] == 1
    with store.connect() as db:
        assert db.execute('SELECT count(*) FROM v5_manual_history').fetchone()[0] == 1


@pytest.mark.parametrize('change', ['price', 'clear', 'new-run', 'disable'])
def test_stale_previews_cannot_overwrite_changes(setup, change):
    client, store, item = setup
    body = payload(); result = preview(client, body)
    if change == 'price':
        task = store.check('qa-one', item['id'], 'salidzini'); task['offers'] = [{'price_eur': 777}]; store.save_check(task)
    elif change == 'clear':
        store.clear_monitoring_session('qa-one')
    elif change == 'new-run':
        store.begin_run('qa-two', 'deep')
    else:
        store.update_source('salidzini', False)
    before = store.check('qa-one', item['id'], 'salidzini')
    assert apply(client, body, result).status_code in [400, 409]
    assert store.check('qa-one', item['id'], 'salidzini') == before


@pytest.mark.parametrize('update', [
    {'security_challenge': True}, {'html': '<div class="h-captcha"></div>'},
    {'html': card('27G64')}, {'html': card(price='1 EUR 199')},
    {'url': 'https://rde.lv/product'}, {'url': 'https://www.salidzini.lv/out/1'},
    {'html': 'x' * 2_000_001}, {'model': ''},
])
def test_invalid_pages_do_not_change_results(setup, update):
    client, store, item = setup
    before = store.check('qa-one', item['id'], 'salidzini')
    assert client.post('/browser-bridge/page-preview', json=payload(**update)).status_code == 400
    assert store.check('qa-one', item['id'], 'salidzini') == before


def test_offset_pages_merge_and_recapture_replaces_only_that_page(setup):
    client, store, item = setup
    first = payload(html=card() + '<a href="/cena?q=TCL+25G64&offset=38">2</a>')
    result = preview(client, first)
    assert result['next_pages'] == [URL + '&offset=38']
    assert apply(client, first, result, complete=True).status_code == 400
    assert apply(client, first, result).status_code == 200
    assert store.check('qa-one', item['id'], 'salidzini')['status'] == 'ACTION_REQUIRED'
    second = payload(url=URL + '&offset=38', html=card(seller='Other.lv', price='205'))
    assert apply(client, second, preview(client, second), complete=True).status_code == 200
    repeat = payload(url=URL + '&offset=38', html=card(seller='Other.lv', price='210'))
    assert apply(client, repeat, preview(client, repeat), complete=True).status_code == 200
    task = store.check('qa-one', item['id'], 'salidzini')
    assert [o['price_eur'] for o in task['offers']] == [199, 210]
    assert task['coverage'] == 'complete'


def test_filtered_capture_cannot_claim_full_coverage(setup):
    client, _, _ = setup
    body = payload(); result = preview(client, body)
    assert apply(client, body, result, complete=True, selected=[0]).status_code == 400
    assert apply(client, body, result, selected=[0]).json()['saved'] == 1


def test_clear_during_cancellation_does_not_restore_prices(setup, monkeypatch):
    client, store, item = setup
    body = payload(); result = preview(client, body)

    async def clear_during_cancel(*args):
        store.clear_monitoring_session('qa-one')

    monkeypatch.setattr(client.app.state.monitor, 'cancel_pair', clear_during_cancel)
    assert apply(client, body, result).status_code == 400
    assert not store.check('qa-one', item['id'], 'salidzini').get('offers')
    assert client.get('/browser-bridge/status').json()['capture_revision'] == 0


def test_foreign_origin_and_invalid_selection_rejected(setup):
    client, _, _ = setup
    body = payload(); result = preview(client, body)
    assert client.post('/browser-bridge/page-preview', json=body, headers={'origin': 'https://evil.test'}).status_code == 403
    for selected in [[], [-1], [999], [True]]:
        assert apply(client, body, result, selected=selected).status_code == 400


def test_pagination_does_not_switch_query_or_follow_previous():
    html = card() + '<a href="/cena?q=TCL+25G64&offset=0">1</a><a href="/cena?q=TCL+27G64&offset=76">next search</a>'
    assert parse_page('salidzini', '25G64', html, URL + '&offset=38')['links'] == []
