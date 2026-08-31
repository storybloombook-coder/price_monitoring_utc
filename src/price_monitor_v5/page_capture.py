"""User-initiated, previewed page imports. No network or CAPTCHA automation."""
import hashlib
import json
import uuid
from urllib.parse import urlsplit, parse_qs

from fastapi import Body, HTTPException
from .catalog import canonicalize, utc_now
from .offers import parse_page, compact
from .sources import marketplace_url


def signature(task):
    return hashlib.sha256(json.dumps(task, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def parse_capture(payload):
    url = marketplace_url('salidzini', payload.get('url'))
    if urlsplit(url).path.rstrip('/') != '/cena':
        raise ValueError('Open a Salidzini search results page, not a retailer link')
    model = canonicalize(str(payload.get('model') or ''))
    if not model or len(model) > 100:
        raise ValueError('Enter the original monitoring SKU')
    html = payload.get('html')
    if not isinstance(html, str) or len(html.encode('utf-8')) > 2_000_000:
        raise ValueError('Capture is empty or too large (maximum 2 MB)')
    if payload.get('security_challenge') or any(marker in html.lower() for marker in
            ('class="h-captcha"', "class='h-captcha'", 'challenge-platform', 'cf-chl-', 'verify you are human')):
        raise ValueError('Complete the CAPTCHA in the same tab, then send the page again')
    parsed = parse_page('salidzini', model, html, url)
    if not parsed['offers']:
        raise ValueError('No reliable offers for this SKU were extracted. Check the model and page, or use manual price entry')
    return model, url, parsed


def register_page_capture(app, catalog, monitor, lock):
    def target(model):
        session = catalog.latest_monitoring_session()
        if not session or session.get('cleared_at'):
            raise ValueError('Start a monitoring run in PriceMonitor, then refresh this preview')
        matches = [t for t in catalog.checks(session['run_id']) if t['marketplace_key'] == 'salidzini'
                   and compact(t['source_model']) == compact(model)]
        if len(matches) != 1:
            raise ValueError('This SKU has no Salidzini check in the latest run. Enable Salidzini and start a run')
        if not any(s['key'] == 'salidzini' and s['effective_enabled'] for s in catalog.list_sources()):
            raise ValueError('Salidzini is disabled in PriceMonitor')
        return matches[0]

    @app.post('/browser-bridge/page-preview')
    async def preview(payload: dict = Body(...)):
        model, url, parsed = parse_capture(payload)
        task = target(model)
        return {'model': task['source_model'], 'url': url, 'offers': parsed['offers'],
                'next_pages': parsed['links'], 'rejected': parsed['rejected'],
                'incomplete': bool(payload.get('incomplete')), 'previewed_at': utc_now(),
                'run_id': task['run_id'], 'item_id': task['item_id'], 'expected_signature': signature(task)}

    @app.post('/browser-bridge/page-apply')
    async def apply(payload: dict = Body(...)):
        try:
            capture_id = str(uuid.UUID(str(payload.get('capture_id'))))
        except (ValueError, TypeError, AttributeError):
            raise ValueError('Invalid capture identifier')
        # The receipt and check update are committed together; retransmission
        # after a lost response must never duplicate or reapply old observations.
        async with lock:
            with catalog.connect() as db:
                receipt = db.execute('SELECT result FROM v5_capture_receipts WHERE id=?', (capture_id,)).fetchone()
            if receipt:
                return {**json.loads(receipt[0]), 'already_applied': True}
            model, url, parsed = parse_capture(payload)
            task = target(model)
            if (payload.get('run_id') != task['run_id'] or payload.get('item_id') != task['item_id']
                    or payload.get('expected_signature') != signature(task)):
                raise HTTPException(409, 'The result or run changed. Refresh the preview before saving')
            selected = payload.get('selected_indices')
            if (not isinstance(selected, list) or not selected or
                    any(type(i) is not int or i < 0 or i >= len(parsed['offers']) for i in selected)):
                raise ValueError('Select at least one offer')
            complete = payload.get('all_pages_reviewed') is True
            if complete and (parsed['links'] or parsed['rejected'] or payload.get('incomplete') or
                             len(set(selected)) != len(parsed['offers'])):
                raise ValueError('Incomplete or filtered capture: save as partial and review the remaining offers/pages')
            await monitor.cancel_pair(task['run_id'], task['item_id'], 'salidzini')
            # Clear/disable can run while cancellation yields to the event loop.
            # Revalidate the target before the synchronous transaction below.
            current = target(model)
            if signature(current) != signature(task):
                raise HTTPException(409, 'The check finished during review. Refresh the preview')
            now = utc_now()
            captured_at = str(payload.get('captured_at') or now)[:60]
            fresh = [{**parsed['offers'][i], 'manual': True, 'captured_at': captured_at,
                      'capture_method': 'active-tab'} for i in sorted(set(selected))]
            # Recapturing page 2 replaces page 2 only, preserving pages 1 and 3.
            def same_page(value):
                a, b = urlsplit(value), urlsplit(url)
                return a.path == b.path and parse_qs(a.query) == parse_qs(b.query)
            previous = [o for o in task.get('offers', []) if not same_page(o.get('url', ''))]
            offers = previous + fresh
            decision = {'status': 'SUCCESS', 'capture_id': capture_id, 'product_url': url,
                        'offer_count': len(fresh), 'captured_at': captured_at, 'decided_at': now,
                        'all_offers_reviewed': complete, 'capture_method': 'active-tab'}
            task.update(offers=offers, status='SUCCESS' if complete else 'ACTION_REQUIRED',
                        coverage='complete' if complete else 'partial', collection_method='manual',
                        cached=False, retry_after=None, error_code=None, finished_at=now,
                        manual_resolution=decision,
                        error=None if complete else 'Captured prices saved. Review remaining Salidzini pages/offers')
            result = {'saved': len(fresh), 'run_id': task['run_id'], 'model': task['source_model'],
                      'status': task['status'], 'capture_id': capture_id}
            with catalog._lock, catalog.connect() as db:
                db.execute('UPDATE marketplace_checks SET status=?,data=? WHERE run_id=? AND item_id=? AND marketplace_key=?',
                           (task['status'], json.dumps(task), task['run_id'], task['item_id'], 'salidzini'))
                db.execute('INSERT INTO v5_manual_history(run_id,item_id,marketplace_key,decision,decided_at) VALUES(?,?,?,?,?)',
                           (task['run_id'], task['item_id'], 'salidzini', json.dumps(decision), now))
                db.execute('INSERT INTO v5_capture_receipts(id,result) VALUES(?,?)', (capture_id, json.dumps(result)))
            return result
