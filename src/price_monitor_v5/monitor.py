import asyncio
import time
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import urljoin, urlsplit, parse_qsl, urlencode
import httpx
from .catalog import utc_now
from .sources import marketplace_url, search_url, same_salidzini_search, MARKETPLACES
from .offers import parse_page, normalize_offer, shortened_queries, candidate_links, plausible_shortened_candidate, candidate_model


class ReviewRequired(ValueError):
    pass


class MarketplaceMonitor:
    """One polite queue per marketplace; stores immutable run/model snapshots."""
    def __init__(self, store, bridge, *, delay=3, transport=None):
        self.store, self.bridge, self.delay, self.transport = store, bridge, delay, transport
        # Browser automation must be materially gentler than the lightweight
        # server-side marketplace readers.  ``delay=0`` remains the explicit
        # test hook used by the isolated regression suite.
        self.salidzini_delay = 0 if delay == 0 else max(12, delay)
        self.jobs = {}
        self.locks = {s.key: asyncio.Lock() for s in MARKETPLACES}
        self.last_request = {}
        self.cooldowns = store.get_meta("v5_cooldowns", {})
        # Live queue status belongs to the running process, not to a stored run
        # snapshot. The UI uses this to explain what is happening right now.
        self.activities = {}
        self.batches = {}
        self.verification_jobs = {}
        self.salidzini_health = {}

    def launch(self, run_id):
        tasks = [task for task in self.store.checks(run_id) if task["status"] == "PENDING"]
        self.begin_batch(run_id, tasks, "Full monitoring run")
        for task in tasks:
            self.schedule(task)

    def begin_batch(self, run_id, tasks, label="Retry unresolved"):
        self.batches[run_id] = {
            "label": label,
            "started_at": utc_now(),
            "started_monotonic": time.monotonic(),
            "ids": [(task["run_id"], task["item_id"], task["marketplace_key"]) for task in tasks],
            "stopped": False,
        }
        self.activities[run_id] = {}
        # Keep a live protection cooldown across retry clicks. A new attempt is
        # allowed after it expires or after a deliberate active-browser switch.
        previous = self.salidzini_health.get(run_id, {})
        cooldown = previous.get("cooldown_until")
        if self.delay == 0 or not cooldown or cooldown <= utc_now():
            self.salidzini_health[run_id] = {
                "consecutive_unavailable": 0, "successful_pages": 0,
                "paused": False, "reason": None, "cooldown_until": None,
                "pause_until_monotonic": 0,
            }

    def salidzini_state(self, run_id):
        return self.salidzini_health.setdefault(run_id, {
            "consecutive_unavailable": 0, "successful_pages": 0,
            "paused": False, "reason": None, "cooldown_until": None,
            "pause_until_monotonic": 0,
        })

    def reset_salidzini_browser_cycle(self):
        """A deliberate active-browser switch starts a fresh isolated session."""
        for state in self.salidzini_health.values():
            state.update(consecutive_unavailable=0, successful_pages=0, paused=False,
                         reason=None, cooldown_until=None, pause_until_monotonic=0)

    def pause_salidzini(self, run_id, reason):
        state = self.salidzini_state(run_id)
        state.update(paused=True, reason=reason,
                     cooldown_until=(datetime.now(UTC)+timedelta(minutes=50)).isoformat())

    def record_salidzini_capture(self, run_id, result):
        """Pause a batch before repeated blank/protected pages create a block."""
        state = self.salidzini_state(run_id)
        if result.get("security_challenge"):
            self.pause_salidzini(run_id, "CAPTCHA or browser security challenge")
            return
        message = str(result.get("error") or "")
        unavailable = any(marker in message.lower() for marker in (
            "results did not become ready", "page loading timed out",
            "could not read the retailer page", "search page changed or redirected",
        ))
        if unavailable:
            state["consecutive_unavailable"] += 1
            if state["consecutive_unavailable"] >= 2:
                self.pause_salidzini(run_id, "two consecutive unavailable result pages")
        elif not message and int(result.get("salidzini_card_count") or 0) > 0:
            state.update(consecutive_unavailable=0, reason=None)
            state["successful_pages"] = int(state.get("successful_pages") or 0) + 1
            count = state["successful_pages"]
            if count == 5:
                state.update(reason="Safe Auto pause after 5 pages", pause_until_monotonic=time.monotonic()+45)
            elif count == 10:
                state.update(reason="Safe Auto pause after the next 5 pages", pause_until_monotonic=time.monotonic()+90)
            elif count >= 20:
                state.update(paused=True, reason="Safe 5 + 5 + 10 cycle complete; switch the active browser or wait before continuing",
                             cooldown_until=(datetime.now(UTC)+timedelta(minutes=20)).isoformat())

    def schedule(self, task, capture=False):
        ident = (task["run_id"], task["item_id"], task["marketplace_key"])
        if ident in self.jobs:
            self.jobs[ident].cancel()
        self.set_activity(task, "Queued for marketplace check")
        self.jobs[ident] = asyncio.create_task(self.check(task, capture))

    def set_activity(self, task, message):
        self.activities.setdefault(task["run_id"], {})[task["marketplace_key"]] = {
            "marketplace": task.get("marketplace") or task.get("marketplace_key", ""),
            "marketplace_key": task.get("marketplace_key", ""),
            "model": task.get("source_model") or task.get("canonical_model", ""),
            "message": message,
            "updated_at": utc_now(),
        }

    def activity(self, run_id):
        values = list(self.activities.get(run_id, {}).values())
        return max(values, key=lambda item: item.get("updated_at", ""), default=None)

    def progress(self, run_id):
        batch = self.batches.get(run_id)
        if not batch:
            return None
        elapsed = max(0.0, time.monotonic() - batch["started_monotonic"])
        snapshots = {(task["run_id"],task["item_id"],task["marketplace_key"]):task
                     for task in self.store.checks(run_id)}
        rows = []
        for key in dict.fromkeys(ident[2] for ident in batch["ids"]):
            ids = [ident for ident in batch["ids"] if ident[2] == key]
            statuses = [snapshots.get(ident, {}).get("status") for ident in ids]
            queued = statuses.count("PENDING")
            running = statuses.count("RUNNING")
            remaining = queued + running
            finished = len(ids) - remaining
            needs_review = sum(status in {"ACTION_REQUIRED","FAILED","INCOMPLETE"} for status in statuses)
            estimate = round((elapsed / finished) * remaining) if finished and remaining else 0
            event = self.activities.get(run_id, {}).get(key)
            guard = self.salidzini_health.get(run_id, {}) if key == "salidzini" else {}
            rows.append({
                "marketplace_key": key,
                "marketplace": next((source.name for source in MARKETPLACES if source.key == key), key),
                "total": len(ids), "finished": finished, "remaining": remaining,
                "queued": queued, "running": running, "needs_review": needs_review,
                "eta_seconds": estimate, "current": event,
                "protection_paused": bool(guard.get("paused")),
                "protection_reason": guard.get("reason"),
                "safe_pages": guard.get("successful_pages",0),
                "cooldown_until": guard.get("cooldown_until"),
            })
        return {"label": batch["label"], "started_at": batch["started_at"],
                "stopped": batch.get("stopped", False), "marketplaces": rows}

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
        verification = self.verification_jobs.get(ident)
        retry_timeout = False
        try:
            async with self.locks[key]:
                task.pop("automation_paused", None)
                task.pop("page_diagnostics", None)
                if verification:
                    capture = True
                if not verification and key == 'salidzini' and task.get('salidzini_mode') == 'manual':
                    raise ReviewRequired('Manual mode: no background requests. Choose Open & collect for a one-click check, or Open only → Send to PriceMonitor to review offers yourself.')
                if automatic and not verification:
                    if not self.bridge.connected or not getattr(self.bridge, 'automatic_salidzini', False):
                        raise ReviewRequired('Salidzini Auto needs the connected v5.0.8+ extension. Reload/connect it, then retry; manual page capture remains available.')
                    state = self.salidzini_state(task["run_id"])
                    pause = max(0, float(state.get("pause_until_monotonic") or 0)-time.monotonic())
                    if pause:
                        self.set_activity(task, f"Safe Salidzini pause · resuming in {round(pause)} s")
                        await asyncio.sleep(pause)
                        state["pause_until_monotonic"] = 0
                        state["reason"] = None
                    if state["paused"]:
                        task["automation_paused"] = True
                        raise ReviewRequired('Salidzini Auto paused this batch to protect the browser session after CAPTCHA or repeated unavailable pages. No request was sent for this SKU. Complete the CAPTCHA in the retained tab, then retry Salidzini in a batch of 5.')
                    capture = True
                if self.blocked(key) and not capture:
                    raise ReviewRequired("Automatic requests are cooling down. Manual offer entry and browser capture are available now.")
                task.update(status="RUNNING",error=None,error_code=None,offers=[],cached=False,attempts=0)
                self.set_activity(task, "Starting check")
                self.store.save_check(task)
                # A bounded check always returns to review; never endless Checking.
                async with asyncio.timeout(900 if verification else 180 if automatic else 90 if capture else 65):
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
            self.set_activity(task, "Network unavailable — moved to review; queue continues")
        except TimeoutError:
            if key == "hinnavaatlus" and not capture and int(task.get("timeout_retry_count") or 0) < 1:
                task["timeout_retry_count"] = 1
                task.update(status="PENDING", coverage="partial", error="First Hinnavaatlus timeout; one automatic retry is queued")
                self.set_activity(task, "Hinnavaatlus timed out — automatic retry 1/1")
                retry_timeout = True
            else:
                task.update(status="ACTION_REQUIRED", coverage="partial", error="Marketplace check timed out; use Quick Review or retry")
                self.set_activity(task, "Timed out — moved to review; queue continues")
        except Exception as error:
            task.update(status="ACTION_REQUIRED", coverage="partial", error=str(error) or "Check timed out; use manual review")
            self.set_activity(task, "Needs review — continuing with the next check")
            if self.blocked(key) and not automatic:
                task["retry_after"] = self.cooldowns[key]
        finally:
            if self.jobs.get(ident) is asyncio.current_task():
                self.jobs.pop(ident, None)
                if not asyncio.current_task().cancelling():
                    task["finished_at"] = utc_now()
                    try:
                        self.store.save_check(task)
                    except Exception:
                        if verification:
                            self.bridge.finish_verification(verification, 'review', error='Could not save the result; keep the page open')
                        raise
                    finally:
                        self.verification_jobs.pop(ident, None)
                    if verification:
                        # A reported-count gap means every rendered listing was
                        # parsed, while Salidzini's heading over-reported by at
                        # most two. There is nothing else for the browser tab to
                        # capture, so the saved result may close it just like a
                        # fully reconciled result. It is deliberately not cached.
                        # Exact offers are useful even when the marketplace's
                        # own heading/count cannot be fully reconciled.  The
                        # result carries its coverage warning in the table, so
                        # there is no manual confirmation step merely to make
                        # already-collected prices visible.
                        complete = task['status'] in {'SUCCESS','NOT_FOUND'}
                        self.bridge.finish_verification(verification, 'complete' if complete else 'review',
                                                        status=task['status'], error=task.get('error'))
                    if retry_timeout:
                        loop = asyncio.get_running_loop()
                        loop.call_later(1, lambda current=task: self.schedule(current, False))
                    elif not any(run_id == task['run_id'] for run_id, _, _ in self.jobs):
                        self.activities.pop(task['run_id'], None)
                        if task['run_id'] in self.batches:
                            self.batches[task['run_id']]["completed_at"] = utc_now()

    async def collect(self, task, client, capture):
        task.update(search_queries=[], candidate_matches=[], collection_revision=4)
        queries = [None] + shortened_queries(task["source_model"])
        for query in queries:
            task["search_queries"].append(query or task["source_model"])
            self.set_activity(task, "Checking original SKU" if query is None else f"Retrying shortened SKU: {query}")
            await self.collect_once(task, client, capture, query)
            if task["status"] != "NOT_FOUND":
                return
        if task["candidate_matches"]:
            task.update(status="ACTION_REQUIRED", coverage="partial", error="Shortened searches found possible model variants. Review the suggested comparison links; no candidate prices were accepted automatically.")

    async def collect_once(self, task, client, capture, query=None):
        key, model = task["marketplace_key"], task["source_model"]
        parse_model = task.get("accepted_model") or model
        saved = task.get("product_url") if query is None else None
        if saved and key == 'salidzini' and (task.get('salidzini_mode') == 'auto' or task.get('verification_id')):
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
        rejected_count = 0
        salidzini_ids, salidzini_seen_ids, salidzini_totals = set(), set(), []
        while queue and len(seen)<12:
            url = marketplace_url(key,queue.pop(0))
            if url in seen:
                continue
            seen.add(url)
            try:
                self.set_activity(task, f"Reading marketplace page {len(seen)}")
                if capture:
                    automatic = key == 'salidzini' and task.get('salidzini_mode') == 'auto'
                    verification = task.get('verification_id')
                    if automatic or verification:
                        if automatic:
                            state = self.salidzini_state(task["run_id"])
                            pause = max(0, float(state.get("pause_until_monotonic") or 0)-time.monotonic())
                            if pause:
                                self.set_activity(task, f"Safe Salidzini pause · resuming in {round(pause)} s")
                                await asyncio.sleep(pause)
                                state["pause_until_monotonic"] = 0
                                state["reason"] = None
                            if state.get("paused"):
                                task["automation_paused"] = True
                                raise ReviewRequired('Safe Salidzini browser cycle paused before another page was opened. Switch the active browser or wait for the displayed cooldown.')
                        pace_key = key + '-browser'
                        pace = self.salidzini_delay if automatic else self.delay
                        wait = pace - (time.monotonic() - self.last_request.get(pace_key, 0))
                        if wait > 0:
                            await asyncio.sleep(wait)
                        self.last_request[pace_key] = time.monotonic()
                        if verification:
                            result = await self.bridge.capture(key,model,url,verification_id=verification)
                        else:
                            result = await self.bridge.capture(key,model,url,automatic=True)
                    else:
                        result = await self.bridge.capture(key,model,url)
                    if automatic:
                        task["page_diagnostics"] = result.get("page_diagnostics") or {
                            "title": result.get("title"),
                            "ready_state": result.get("ready_state"),
                            "card_count": result.get("salidzini_card_count"),
                            "text_length": result.get("page_text_length"),
                        }
                        self.record_salidzini_capture(task["run_id"], result)
                    if result.get("security_challenge") or result.get("error"):
                        raise ReviewRequired(result.get("error") or "Complete the marketplace CAPTCHA before capturing")
                    content, final = result.get("html", ""), marketplace_url(key,result.get("url") or url)
                    if (automatic or verification and key == 'salidzini') and not same_salidzini_search(final, url):
                        raise ReviewRequired('The browser page changed. Check the SKU/search URL and retry')
                    if verification and key != 'salidzini':
                        expected, actual = urlsplit(url), urlsplit(final)
                        if expected.path.rstrip('/') != actual.path.rstrip('/') or sorted(parse_qsl(expected.query)) != sorted(parse_qsl(actual.query)):
                            raise ReviewRequired('The verification page changed. Check the SKU/search URL and retry')
                    partial |= bool(result.get("incomplete"))
                else:
                    content, final = await self.fetch(client,key,url)
                parsed = parse_page(key,parse_model,content,final)
                self.set_activity(task, f"Classifying offers on page {len(seen)}")
                if key == 'salidzini':
                    salidzini_ids.update(parsed.get('salidzini_offer_ids', []))
                    salidzini_seen_ids.update(parsed.get('salidzini_seen_ids', []))
                    salidzini_totals.append(parsed.get('salidzini_expected_count'))
                if query and not parsed["offers"]:
                    for candidate in candidate_links(query, content, final, key):
                        if not plausible_shortened_candidate(model, candidate["title"]):
                            continue
                        if not any(c["url"] == candidate["url"] for c in task["candidate_matches"]):
                            task["candidate_matches"].append(candidate)
            except httpx.HTTPStatusError as error:
                if url == saved and error.response.status_code in {404,410} and discovery not in seen:
                    queue.append(discovery)
                    fallback = True
                    continue
                raise
            # Confidently rejected cards are unrelated products, not an
            # incomplete parser result. They can prove absence after all pages
            # and fallback queries have been checked.
            empty |= parsed["not_found"] or bool(parsed.get("rejected") and not parsed["offers"] and not parsed["links"])
            rejected_count += int(parsed.get("rejected") or 0)
            # Exact SKU rows with a malformed price/seller are incomplete;
            # unrelated cards are merely documented as rejected.
            partial |= bool(parsed.get("ambiguous"))
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
            if not parsed["offers"] and not parsed["links"] and not parsed["not_found"] and not parsed.get("rejected") and url != saved:
                partial = True
        unique = {(o["store"].lower(),o["price_eur"],o["availability"],o["url"]):o for o in offers}
        reported_gap = False
        if key == 'salidzini' and (offers or any(n is not None for n in salidzini_totals)):
            expected = max((n for n in salidzini_totals if n is not None), default=None)
            # Completion is based on listings inspected, not only accepted
            # offers. A rejected accessory or wrong SKU has already been
            # examined and must not create needless manual work.
            counted = salidzini_seen_ids
            totals_consistent = expected is not None and not any(n is None for n in salidzini_totals) and len(set(salidzini_totals)) == 1
            gap = expected - len(salidzini_seen_ids) if expected is not None else None
            # Salidzini's visible heading can be one or two above the actual
            # rendered /click.php listing cards. If every rendered card was
            # safely parsed and at least 75% of the reported total is present,
            # retain a truthful non-cacheable Success instead of asking the
            # user to repeat a manual check that cannot reveal more rows.
            reported_gap = bool(offers and not partial and not queue and totals_consistent and
                                gap is not None and 0 < gap <= 2 and
                                len(salidzini_seen_ids) / expected >= .75)
            partial |= not reported_gap and (not totals_consistent or len(counted) != expected)
            # Some layouts omit a malformed/mismatched raw offer before the
            # normalizer can record it. The inspected-vs-accepted ID delta is
            # still authoritative for the user-facing audit trail.
            rejected_count = max(rejected_count, len(salidzini_seen_ids) - len(salidzini_ids))
            task['coverage_detail'] = (f'{len(salidzini_seen_ids)} listings inspected / '
                                       f'{expected if expected is not None else "unknown"} reported; '
                                       f'{len(unique)} exact offers saved; {rejected_count} unrelated rejected; '
                                       f'{len(seen)} page(s) read')
        for group, expected in expected_counts.items():
            # Count across pagination, not each page in isolation. Missing rows
            # remain partial even if the final page omits the aggregate count.
            captured = {(o["store"].lower(), o["price_eur"], o["availability"])
                        for o in unique.values() if urlsplit(o["url"])._replace(query="", fragment="").geturl() == group}
            partial |= len(captured) < expected
        task.update(offers=list(unique.values()),collection_method="extension" if capture else "marketplace HTML",attempts=task.get("attempts",0)+len(seen),
                    coverage="partial" if partial or queue else "reported_gap" if reported_gap else "complete", retry_after=None)
        if offers:
            # Salidzini regularly reports a heading count that differs from
            # its rendered cards. Publish its confidently matched offers
            # immediately; partial coverage remains explicit, is never cached,
            # and is surfaced through an information marker in the table.
            # Other marketplaces retain the strict review requirement.
            publish_partial = key == 'salidzini'
            task["status"] = "SUCCESS" if publish_partial or not (partial or queue) else "ACTION_REQUIRED"
            task["error"] = None if publish_partial or not (partial or queue) else "Some offers/pages need review; displayed prices cover captured offers only"
        elif empty and not partial:
            task.update(status="NOT_FOUND",error=None)
        else:
            raise ReviewRequired("No reliable seller offers extracted. Open this marketplace, capture the comparison page or add the offers manually.")

    async def cancel_pair(self, run_id, item_id, key):
        verification = self.verification_jobs.pop((run_id,item_id,key),None)
        if verification:
            self.bridge.finish_verification(verification, 'cancelled')
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
        if run_id in self.batches:
            self.batches[run_id]["stopped"] = True
            self.batches[run_id]["completed_at"] = utc_now()
        self.activities.pop(run_id, None)

    async def close(self):
        for ident in list(self.jobs):
            await self.cancel_pair(*ident)

    async def retry(self, run_id, item_id, key, *, url=None, capture=True, open_collect=False):
        task = self.store.check(run_id,item_id,key)
        session = self.store.monitoring_session(run_id)
        if session.get("cleared_at"):
            raise ValueError("Start a new monitoring run after clearing the table")
        if not any(s["key"]==key and s["effective_enabled"] for s in self.store.list_sources()):
            raise ValueError("This marketplace is disabled")
        if open_collect and (not self.bridge.connected or not self.bridge.open_collect):
            raise ValueError('Open & collect needs the connected v5.0.9+ extension. Reload it on the browser extensions page. Open only and manual entry remain available.')
        if open_collect and any(ident != (run_id,item_id,key) for ident in self.verification_jobs):
            raise ValueError('Another Open & collect check is active. Finish it or use Hard stop before opening the next one.')
        await self.cancel_pair(run_id,item_id,key)
        task.pop('verification_id',None)
        if open_collect:
            task['verification_id'] = self.bridge.begin_verification()
            self.verification_jobs[(run_id,item_id,key)] = task['verification_id']
        if key == 'salidzini':
            task['salidzini_mode'] = self.store.salidzini_mode()
        if url:
            task["product_url"] = marketplace_url(key,url)
            self.store.remember_source_link(item_id,key,url)
        task.update(status="PENDING",error=None,cached=False,
                    retry_count=int(task.get("retry_count") or 0)+1,
                    last_retry_at=utc_now())
        try:
            self.store.save_check(task)
        except Exception:
            token = self.verification_jobs.pop((run_id,item_id,key),None)
            if token:
                self.bridge.finish_verification(token,'review',error='Could not start verification; database write failed')
            raise
        self.schedule(task,capture)
        return task.get('verification_id')

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
        undo = {k:v for k,v in task.items() if k != "undo_snapshot"}
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
                    manual_resolution=decision,error=None,retry_after=None,finished_at=utc_now(),undo_snapshot=undo)
        self.store.save_check(task)
        return task

    async def accept_candidate(self, run_id, item_id, key, payload):
        task = self.store.check(run_id, item_id, key)
        candidates = task.get("candidate_matches") or []
        index = int(payload.get("candidate_index", -1))
        if index < 0 or index >= len(candidates):
            raise ValueError("Candidate changed; reopen Quick Review")
        candidate = candidates[index]
        # Older stored Quick Review cards may predate concrete candidate-model
        # extraction. Infer it from the already-reviewed title/query so the
        # button cannot remain in an unresolvable loop after an upgrade.
        alias = candidate.get("model") or candidate_model(candidate.get("query"), candidate.get("title"))
        if not alias:
            raise ValueError("This suggestion has no identifiable SKU. Mark it as Not found or open the comparison link.")
        task["undo_snapshot"] = {k:v for k,v in task.items() if k != "undo_snapshot"}
        task["accepted_model"] = alias
        task["product_url"] = marketplace_url(key, candidate["url"])
        task["quick_review_resolution"] = {"choice":"candidate", "candidate":candidate, "decided_at":utc_now()}
        if payload.get("remember_alias"):
            self.store.remember_model_alias(task["source_model"], alias)
        self.store.remember_source_link(item_id, key, task["product_url"])
        self.store.save_check(task)
        return await self.retry(run_id, item_id, key, url=task["product_url"], capture=False)

    async def accept_partial(self, run_id, item_id, key):
        task = self.store.check(run_id, item_id, key)
        if not task.get("offers"):
            raise ValueError("There are no collected offers to accept")
        await self.cancel_pair(run_id, item_id, key)
        undo = {k:v for k,v in task.items() if k != "undo_snapshot"}
        decision = {"status":"SUCCESS", "choice":"accept_partial", "decided_at":utc_now()}
        self.store.record_decision(task, decision)
        task.update(status="SUCCESS", coverage="accepted_partial", collection_method="review",
                    manual_resolution=decision, error=None, retry_after=None,
                    finished_at=utc_now(), undo_snapshot=undo)
        self.store.save_check(task)
        return task

    async def undo(self, run_id, item_id, key):
        task = self.store.check(run_id, item_id, key)
        snapshot = task.get("undo_snapshot")
        if not snapshot:
            raise ValueError("No review decision is available to undo")
        await self.cancel_pair(run_id, item_id, key)
        snapshot["finished_at"] = utc_now()
        self.store.save_check(snapshot)
        return snapshot
