import asyncio
import time
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import urljoin, urlsplit
import httpx
from .catalog import utc_now
from .sources import marketplace_url, search_url, MARKETPLACES
from .offers import parse_page, normalize_offer


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
        try:
            async with self.locks[key]:
                if self.blocked(key) and not capture:
                    raise ReviewRequired("Automatic requests are cooling down. Manual offer entry and browser capture are available now.")
                task.update(status="RUNNING",error=None,error_code=None,offers=[],cached=False)
                self.store.save_check(task)
                # A bounded check always returns to review; never endless Checking.
                async with asyncio.timeout(90 if capture else 65):
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
            if self.blocked(key):
                task["retry_after"] = self.cooldowns[key]
        finally:
            if self.jobs.get(ident) is asyncio.current_task():
                self.jobs.pop(ident, None)
                if not asyncio.current_task().cancelling():
                    task["finished_at"] = utc_now()
                    self.store.save_check(task)

    async def collect(self, task, client, capture):
        key, model = task["marketplace_key"], task["source_model"]
        saved = task.get("product_url")
        discovery = search_url(key,model)
        queue = [saved or discovery]
        seen = set()
        offers = []
        expected_counts = {}
        partial, empty, fallback = False, False, False
        while queue and len(seen)<12:
            url = marketplace_url(key,queue.pop(0))
            if url in seen:
                continue
            seen.add(url)
            try:
                if capture:
                    result = await self.bridge.capture(key,model,url)
                    if result.get("security_challenge") or result.get("error"):
                        raise ReviewRequired(result.get("error") or "Complete the marketplace CAPTCHA before capturing")
                    content, final = result.get("html", ""), marketplace_url(key,result.get("url") or url)
                    partial |= bool(result.get("incomplete"))
                else:
                    content, final = await self.fetch(client,key,url)
                parsed = parse_page(key,model,content,final)
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
            offers.extend(parsed["offers"])
            task["offers"] = list(offers)
            if parsed.get("coverage_url"):
                group = parsed["coverage_url"]
                expected_counts[group] = max(expected_counts.get(group, 0), parsed.get("expected_offer_count", 0))
                partial |= bool(parsed["rejected"])
            else:
                partial |= parsed["partial"]
            queue.extend(u for u in parsed["links"] if u not in seen and u not in queue)
            if parsed["offers"] and final != discovery:
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
        for group, expected in expected_counts.items():
            # Count across pagination, not each page in isolation. Missing rows
            # remain partial even if the final page omits the aggregate count.
            captured = {(o["store"].lower(), o["price_eur"], o["availability"])
                        for o in unique.values() if urlsplit(o["url"])._replace(query="", fragment="").geturl() == group}
            partial |= len(captured) < expected
        task.update(offers=list(unique.values()),collection_method="extension" if capture else "marketplace HTML",attempts=len(seen),
                    coverage="partial" if partial or queue else "complete", retry_after=None)
        if offers:
            task["status"] = "ACTION_REQUIRED" if partial or queue else "SUCCESS"
            task["error"] = "Some offers/pages need review; displayed prices cover captured offers only" if partial or queue else None
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
