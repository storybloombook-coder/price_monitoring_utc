import asyncio
import time
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import urljoin, urlsplit, parse_qsl, urlencode
import httpx
from .catalog import utc_now
from .sources import marketplace_url, search_url, same_salidzini_search, MARKETPLACES
from .offers import parse_page, normalize_offer, shortened_queries, candidate_links


class ReviewRequired(ValueError):
    pass


class MarketplaceMonitor:
    """One polite queue per marketplace; stores immutable run/model snapshots."""
    def __init__(self, store, bridge, *, delay=3, transport=None):
        self.store, self.bridge, self.delay, self.transport = store, bridge, delay, transport
        self.jobs = {}
        self.locks = {s.key: asyncio.Lock() for s in MARKETPLACES}
        self.last_request = {}
        self.cooldowns = store.get_meta("v5_cooldowns", {})
        self.browser_pauses = {}

    def launch(self, run_id):
        for task in self.store.checks(run_id):
            if task["status"] == "PENDING":
                self.schedule(task)

    def schedule(self, task, capture=False):
        ident = (task["run_id"], task["item_id"], task["marketplace_key"])
        if ident in self.jobs:
            self.jobs[ident].cancel()
        self.jobs[ident] = asyncio.create_task(self.check(task, capture))

    def blocked(self, key):
        return self.cooldowns.get(key, "") > utc_now()

    def protect(self, key):
        self.cooldowns[key] = (datetime.now(UTC)+timedelta(minutes=10)).isoformat()
        with self.store.connect() as db:
            self.store._set_meta(db, "v5_cooldowns", self.cooldowns)

    async def fetch(self, client, key, url):
        for _ in range(5):
            url = marketplace_url(key, url)
            wait = self.delay - (time.monotonic()-self.last_request.get(key, 0))
            if wait > 0:
                await asyncio.sleep(wait)
            self.last_request[key] = time.monotonic()
            async with client.stream("GET", url) as response:
                if response.status_code in {301,302,303,307,308}:
                    url = marketplace_url(key, urljoin(url,response.headers.get("location", "")))
                    continue
                if response.status_code in {403,429,503}:
                    self.protect(key)
                    raise ReviewRequired("Marketplace protection paused automatic requests. Open verification, complete it yourself, then capture or enter offers manually.")
                response.raise_for_status()
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body)>8_000_000:
                        raise ReviewRequired("Marketplace page is too large; review it manually")
                content = body.decode("utf-8" if key == "kaina24" else response.encoding or "utf-8",errors="replace")
            lowered = content.lower()
            if any(marker in lowered for marker in ("cf-chl-", "challenge-platform", 'class="h-captcha"', "verify you are human", "just a moment...")):
                self.protect(key)
                raise ReviewRequired("CAPTCHA or security check: open the marketplace and complete verification, or enter offers manually")
            return content, url
        raise ReviewRequired("Too many marketplace redirects")

    async def check(self, task, capture=False):
        ident = (task["run_id"], task["item_id"], task["marketplace_key"])
        key, model = task["marketplace_key"], task["source_model"]
        automatic = key == 'salidzini' and task.get('salidzini_mode') == 'auto'
        try:
            async with self.locks[key]:
                if key == 'salidzini' and task.get('salidzini_mode') == 'manual':
                    raise ReviewRequired('Manual mode: open Salidzini, then Send to PriceMonitor, review and save. No automatic requests are sent.')
                if automatic:
                    if self.browser_pauses.get(task['run_id']):
                        raise ReviewRequired(self.browser_pauses[task['run_id']])
                    if not self.bridge.connected or not getattr(self.bridge, 'automatic_salidzini', False):
                        raise ReviewRequired('Salidzini Auto needs the connected v5.0.8+ extension. Reload/connect it, then retry; manual page capture remains available.')
                    capture = True
                if self.blocked(key) and not capture:
                    raise ReviewRequired("Automatic requests are cooling down. Manual offer entry and browser capture are available now.")
                task.update(status="RUNNING",error=None,error_code=None,offers=[],cached=False,attempts=0)
                self.store.save_check(task)
                # A bounded check always returns to review; never endless Checking.
                async with asyncio.timeout(180 if automatic else 90 if capture else 65):
                    # Preserve the working legacy Kaina request profile. One fixed
                    # profile, no header rotation or retries after protection.
                    headers = ({"User-Agent": "PriceMonitor/0.1 (local price monitoring)", "Accept": "*/*"}
                               if key == "kaina24" else
                               {"User-Agent": "PriceMonitor/5.0 (personal price comparison)", "Accept": "text/html"})
                    async with httpx.AsyncClient(timeout=18, follow_redirects=False, transport=self.transport,
                            headers=headers) as client:
                        await self.collect(task, client, capture)
        except asyncio.CancelledError:
            return
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ProxyError):
            task.update(status="ACTION_REQUIRED", coverage="partial", error_code="NETWORK_UNAVAILABLE",
                        error="Network connection failed before the marketplace could be read. Check Internet/firewall/proxy access and restart PriceMonitor from its folder. This is not a CAPTCHA or a missing product.")
        except Exception as error:
            task.update(status="ACTION_REQUIRED", coverage="partial", error=str(error) or "Check timed out; use manual review")
            if automatic:
                self.browser_pauses.setdefault(task['run_id'], 'Salidzini Auto paused after a browser/collection error. Inspect the page, then Retry automatic check; manual capture remains available.')
            if self.blocked(key) and not automatic:
                task["retry_after"] = self.cooldowns[key]
        finally:
            if self.jobs.get(ident) is asyncio.current_task():
                self.jobs.pop(ident, None)
                if not asyncio.current_task().cancelling():
                    task["finished_at"] = utc_now()
                    self.store.save_check(task)

    async def collect(self, task, client, capture):
        task.update(search_queries=[], candidate_matches=[], collection_revision=4)
        queries = [None] + shortened_queries(task["source_model"])
        for query in queries:
            task["search_queries"].append(query or task["source_model"])
            await self.collect_once(task, client, capture, query)
            if task["status"] != "NOT_FOUND":
                return
        if task["candidate_matches"]:
            task.update(status="ACTION_REQUIRED", coverage="partial", error="Shortened searches found possible model variants. Review the suggested comparison links; no candidate prices were accepted automatically.")

    async def collect_once(self, task, client, capture, query=None):
        key, model = task["marketplace_key"], task["source_model"]
        saved = task.get("product_url") if query is None else None
        if saved and key == 'salidzini' and task.get('salidzini_mode') == 'auto':
            # A manually saved page 2 must not make Auto skip page 1.
            parts = urlsplit(marketplace_url(key, saved))
            saved = parts._replace(query=urlencode([(k,v) for k,v in parse_qsl(parts.query, keep_blank_values=True)
                                                      if k not in {'offset','page'}]), fragment='').geturl()
        discovery = search_url(key,query or model)
        queue = [saved or discovery]
        seen = set()
        offers = []
        expected_counts = {}
        authoritative_pages = set()
        partial, empty, fallback = False, False, False
        salidzini_ids, salidzini_seen_ids, salidzini_totals = set(), set(), []
        while queue and len(seen)<12:
            url = marketplace_url(key,queue.pop(0))
            if url in seen:
                continue
            seen.add(url)
            try:
                if capture:
                    automatic = key == 'salidzini' and task.get('salidzini_mode') == 'auto'
                    if automatic:
                        wait = self.delay - (time.monotonic() - self.last_request.get('salidzini-browser', 0))
                        if wait > 0:
                            await asyncio.sleep(wait)
                        self.last_request['salidzini-browser'] = time.monotonic()
                        result = await self.bridge.capture(key,model,url,automatic=True)
                    else:
                        result = await self.bridge.capture(key,model,url)
                    if result.get("security_challenge") or result.get("error"):
                        if automatic:
                            self.browser_pauses[task['run_id']] = ('Salidzini browser queue paused: ' +
                                (result.get('error') or 'CAPTCHA detected') + '. Resolve the open page, then Retry automatic check; or use manual capture.')
                        raise ReviewRequired(result.get("error") or "Complete the marketplace CAPTCHA before capturing")
                    content, final = result.get("html", ""), marketplace_url(key,result.get("url") or url)
                    if automatic and not same_salidzini_search(final, url):
                        raise ReviewRequired('The browser page changed. Check the SKU/search URL and retry')
                    partial |= bool(result.get("incomplete"))
                else:
                    content, final = await self.fetch(client,key,url)
                parsed = parse_page(key,model,content,final)
                if key == 'salidzini':
                    salidzini_ids.update(parsed.get('salidzini_offer_ids', []))
                    salidzini_seen_ids.update(parsed.get('salidzini_seen_ids', []))
                    salidzini_totals.append(parsed.get('salidzini_expected_count'))
                if query and not parsed["offers"]:
                    for candidate in candidate_links(query, content, final, key):
                        if not any(c["url"] == candidate["url"] for c in task["candidate_matches"]):
                            task["candidate_matches"].append(candidate)
            except httpx.HTTPStatusError as error:
                if url == saved and error.response.status_code in {404,410} and discovery not in seen:
                    queue.append(discovery)
                    fallback = True
                    continue
                raise
            empty |= parsed["not_found"]
            if parsed.get("authoritative_url"):
                # Replace search-card snapshots for this comparison only. Do not
                # double-count them or keep stale search prices beside live rows.
                offers = [o for o in offers if o["url"] != parsed["authoritative_url"]]
                authoritative_pages.add(parsed["authoritative_url"])
            # A later search page must not reintroduce stale snapshots for a
            # comparison that has already been read in full.
            offers.extend(o for o in parsed["offers"] if parsed.get("coverage_url") or o["url"] not in authoritative_pages)
            task["offers"] = list(offers)
            if parsed.get("coverage_url"):
                group = parsed["coverage_url"]
                expected_counts[group] = max(expected_counts.get(group, 0), parsed.get("expected_offer_count", 0))
                partial |= bool(parsed["rejected"])
            else:
                partial |= parsed["partial"]
            queue.extend(u for u in parsed["links"] if u not in seen and u not in queue)
            if parsed["offers"] and final != discovery and urlsplit(final).path.rstrip("/") != urlsplit(discovery).path.rstrip("/"):
                # Persist the first comparison page, not its last pagination URL.
                remembered = parsed.get("coverage_url") or final
                task["product_url"] = remembered
                try:
                    self.store.remember_source_link(task["item_id"],key,remembered)
                except KeyError:
                    pass  # The catalog item may have been deleted during this run.
            if url == saved and not parsed["offers"] and not parsed["links"] and discovery not in seen:
                queue.append(discovery)
                fallback = True
            if not parsed["offers"] and not parsed["links"] and not parsed["not_found"] and url != saved:
                partial = True
        unique = {(o["store"].lower(),o["price_eur"],o["availability"],o["url"]):o for o in offers}
        if key == 'salidzini' and (offers or any(n is not None for n in salidzini_totals)):
            expected = max((n for n in salidzini_totals if n is not None), default=None)
            counted = salidzini_ids if offers else salidzini_seen_ids
            partial |= expected is None or len(counted) != expected or any(n is None for n in salidzini_totals) or len(set(salidzini_totals)) > 1
            task['coverage_detail'] = f'{len(salidzini_ids)} verified listings / {expected if expected is not None else "unknown"} reported; {len(seen)} page(s) read'
        for group, expected in expected_counts.items():
            # Count across pagination, not each page in isolation. Missing rows
            # remain partial even if the final page omits the aggregate count.
            captured = {(o["store"].lower(), o["price_eur"], o["availability"])
                        for o in unique.values() if urlsplit(o["url"])._replace(query="", fragment="").geturl() == group}
            partial |= len(captured) < expected
        task.update(offers=list(unique.values()),collection_method="extension" if capture else "marketplace HTML",attempts=task.get("attempts",0)+len(seen),
                    coverage="partial" if partial or queue else "complete", retry_after=None)
        if offers:
            task["status"] = "ACTION_REQUIRED" if partial or queue else "SUCCESS"
            task["error"] = (('Incomplete Salidzini coverage: ' + task['coverage_detail'] + '. Review remaining or ambiguous listings.')
                             if key == 'salidzini' else "Some offers/pages need review; displayed prices cover captured offers only") if partial or queue else None
        elif empty and not partial:
            task.update(status="NOT_FOUND",error=None)
        else:
            raise ReviewRequired("No reliable seller offers extracted. Open this marketplace, capture the comparison page or add the offers manually.")

    async def cancel_pair(self, run_id, item_id, key):
        job = self.jobs.pop((run_id,item_id,key),None)
        if job:
            job.cancel()
            await asyncio.gather(job,return_exceptions=True)

    async def stop_run(self, run_id):
        for ident in list(self.jobs):
            if ident[0] == run_id:
                await self.cancel_pair(*ident)
        for task in self.store.checks(run_id):
            if task["status"] in {"RUNNING","PENDING"}:
                task.update(status="INCOMPLETE",error="Stopped by user",finished_at=utc_now(),coverage="partial")
                self.store.save_check(task)

    async def close(self):
        for ident in list(self.jobs):
            await self.cancel_pair(*ident)

    async def retry(self, run_id, item_id, key, *, url=None, capture=True):
        task = self.store.check(run_id,item_id,key)
        session = self.store.monitoring_session(run_id)
        if session.get("cleared_at"):
            raise ValueError("Start a new monitoring run after clearing the table")
        if not any(s["key"]==key and s["effective_enabled"] for s in self.store.list_sources()):
            raise ValueError("This marketplace is disabled")
        await self.cancel_pair(run_id,item_id,key)
        if key == 'salidzini':
            task['salidzini_mode'] = self.store.salidzini_mode()
            self.browser_pauses.pop(run_id, None)
        if url:
            task["product_url"] = marketplace_url(key,url)
            self.store.remember_source_link(item_id,key,url)
        task.update(status="PENDING",error=None,cached=False)
        self.store.save_check(task)
        self.schedule(task,capture)

    async def resolve(self, run_id, item_id, key, payload):
        task = self.store.check(run_id,item_id,key)
        if payload.get("expected_checked_at") and payload["expected_checked_at"] != task.get("finished_at"):
            raise ValueError("This result changed. Reopen the offer editor before saving")
        if self.store.monitoring_session(run_id).get("cleared_at"):
            raise ValueError("This table was cleared")
        status = str(payload.get("status") or "").upper()
        if status not in {"SUCCESS","NOT_FOUND"}:
            raise ValueError("Choose SUCCESS or NOT_FOUND")
        url = marketplace_url(key, payload.get("product_url") or task.get("product_url") or task["search_url"])
        if status == "NOT_FOUND":
            offers = []
        else:
            offer = normalize_offer(key,task["source_model"], {**payload,"url":url},url,manual=True)
            old_index = payload.get("offer_index")
            offers = list(task.get("offers",[]))
            if old_index is not None:
                index = int(old_index)
                if index < 0 or index >= len(offers):
                    raise ValueError("Offer changed; reopen the correction form")
                offers[index] = offer
            else:
                offers.append(offer)
        await self.cancel_pair(run_id,item_id,key)
        complete = status == "NOT_FOUND" or bool(payload.get("all_offers_reviewed"))
        decision = {**payload,"product_url":url}
        self.store.record_decision(task,decision)
        task.update(status=status,offers=offers,coverage="complete" if complete else "partial",collection_method="manual",cached=False,
                    manual_resolution=decision,error=None,retry_after=None,finished_at=utc_now())
        self.store.save_check(task)
        return task
