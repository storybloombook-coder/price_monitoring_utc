from __future__ import annotations

import asyncio
import json
import re
import time
from html import unescape
from typing import Any

from .browser_bridge import BrowserBridge, BrowserBridgeTimeout, BrowserBridgeUnavailable
from .catalog import CatalogStore
from .sources import SOURCE_BY_KEY


MODEL_CLEAN_RE = re.compile(r"[^A-Z0-9]+")
PRICE_RE = re.compile(
    r"(?<!\d)(\d{1,4}(?:[ .]\d{3})*(?:[,.]\d{1,2})?|\d+[,.]\d{1,2})\s*(?:€|EUR)(?!\w)",
    re.IGNORECASE,
)
CANDIDATE_RE = re.compile(
    r'<script[^>]+id=["\']price-monitor-candidates["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)


def compact(value: str) -> str:
    return MODEL_CLEAN_RE.sub("", str(value or "").upper())


def parse_price(value: str) -> float:
    cleaned = value.replace(" ", "")
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    return float(cleaned)


def parse_salidzini_capture(html: str, model: str) -> list[dict[str, Any]]:
    """Extract exact-model Salidzini offers from the extension's compact page snapshot."""
    match = CANDIDATE_RE.search(html or "")
    if not match:
        return []
    try:
        candidates = json.loads(unescape(match.group(1)))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    expected = compact(model)
    if not expected:
        return []
    offers: list[dict[str, Any]] = []
    seen: set[tuple[float, str]] = set()
    for candidate in candidates if isinstance(candidates, list) else []:
        text = str(candidate.get("text") or "") if isinstance(candidate, dict) else ""
        normalized = compact(text)
        if expected not in normalized:
            continue
        price_matches = list(PRICE_RE.finditer(text))
        if not price_matches:
            continue
        # A comparison card may contain delivery prices too. The value closest to the exact
        # model token is the safest default; the final result is the lowest exact-model card.
        raw_model_position = max(0, text.upper().find(str(model).upper().strip()))
        price_match = min(price_matches, key=lambda item: abs(item.start() - raw_model_position))
        try:
            price = parse_price(price_match.group(1))
        except ValueError:
            continue
        if price <= 0 or price > 1_000_000:
            continue
        links = candidate.get("links") if isinstance(candidate, dict) else []
        links = links if isinstance(links, list) else []
        product_link = next(
            (
                link for link in links
                if isinstance(link, dict) and expected in compact(f"{link.get('text', '')} {link.get('url', '')}")
            ),
            next((link for link in links if isinstance(link, dict) and link.get("url")), {}),
        )
        url = str(product_link.get("url") or "")
        key = (price, url)
        if key in seen:
            continue
        seen.add(key)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        title = next((line for line in lines if expected in compact(line)), model)
        seller = next(
            (str(link.get("text") or "").strip() for link in links if isinstance(link, dict)
             and str(link.get("text") or "").strip() and expected not in compact(str(link.get("text") or ""))),
            "Salidzini",
        )
        offers.append({
            "title": title[:500],
            "seller_name": seller[:200],
            "price_eur": price,
            "availability": "IN_STOCK",
            "product_url": url or None,
        })
    return sorted(offers, key=lambda offer: offer["price_eur"])


class AssistedMarketplaceMonitor:
    """Runs extension-assisted collectors for marketplaces not covered reliably by v3."""

    supported_keys = {"salidzini"}

    def __init__(
        self,
        store: CatalogStore,
        browser_bridge: BrowserBridge,
        *,
        cache_ttl_seconds: float = 14_400,
        negative_cache_ttl_seconds: float = 21_600,
        request_delay_seconds: float = 3,
    ) -> None:
        self.store = store
        self.browser_bridge = browser_bridge
        self.cache_ttl_seconds = max(0, cache_ttl_seconds)
        self.negative_cache_ttl_seconds = max(0, negative_cache_ttl_seconds)
        self.request_delay_seconds = max(0, request_delay_seconds)
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._blocked: set[str] = set()

    def start(self, run_id: str, mode: str = "balanced") -> None:
        if mode not in {"quick", "balanced", "deep"}:
            raise ValueError(f"Unsupported monitoring mode: {mode}")
        self._blocked.clear()
        models = [item for item in self.store.list_items("source", "active") if not item["paused"]]
        marketplaces = [
            item for item in self.store.list_sources()
            if item["kind"] == "marketplace" and item["effective_enabled"]
            and item["key"] in self.supported_keys
        ]
        success_cache_ttl = 0 if mode == "deep" else (
            max(self.cache_ttl_seconds, 43_200) if mode == "quick" else self.cache_ttl_seconds
        )
        negative_cache_ttl = 0 if mode == "deep" else self.negative_cache_ttl_seconds
        self.store.start_assisted_marketplace_run(
            run_id,
            models,
            marketplaces,
            success_cache_ttl,
            negative_cache_ttl,
        )
        # Salidzini commonly starts with hCaptcha. Do not hide the manual workflow
        # behind the full extension timeout: fresh uncached checks are immediately
        # ready for a manual price/not-found decision. Capture again remains an
        # explicit browser-assisted option.
        for marketplace in marketplaces:
            for model in models:
                self._mark_manual_required(run_id, model, marketplace)

    def _mark_manual_required(
        self, run_id: str, model: dict[str, Any], marketplace: dict[str, Any]
    ) -> bool:
        key = marketplace["key"]
        if not self.store.assisted_marketplace_observation_pending(run_id, model["id"], key):
            return False
        source = SOURCE_BY_KEY[key]
        manual_url = (model.get("marketplace_links") or {}).get(key)
        self.store.finish_assisted_marketplace_observation(
            run_id, model["id"], key, "ACTION_REQUIRED",
            product_url=manual_url,
            search_url=source.search_url(model["model"]),
            error="Manual verification is ready; enter the price and seller, mark not found, or use Capture again",
            collection_method="manual",
            attempts=[],
        )
        return True

    async def _run(
        self, run_id: str, models: list[dict[str, Any]], marketplaces: list[dict[str, Any]]
    ) -> None:
        try:
            for marketplace in marketplaces:
                first = True
                for model in models:
                    if not self.store.assisted_marketplace_observation_pending(
                        run_id, model["id"], marketplace["key"]
                    ):
                        continue
                    if not first and marketplace["key"] not in self._blocked:
                        await asyncio.sleep(self.request_delay_seconds)
                    await self._check_one(run_id, model, marketplace)
                    first = False
        finally:
            self._tasks.pop(run_id, None)

    async def _check_one(
        self, run_id: str, model: dict[str, Any], marketplace: dict[str, Any]
    ) -> None:
        key = marketplace["key"]
        source = SOURCE_BY_KEY[key]
        manual_url = (model.get("marketplace_links") or {}).get(key)
        search_url = source.search_url(model["model"])
        target_url = manual_url or search_url
        started = time.monotonic()
        attempts: list[dict[str, Any]] = []
        if not target_url:
            self.store.finish_assisted_marketplace_observation(
                run_id, model["id"], key, "NOT_FOUND", search_url=search_url,
                error="No search or product URL is configured", attempts=attempts,
            )
            return
        if key in self._blocked:
            self.store.finish_assisted_marketplace_observation(
                run_id, model["id"], key, "ACTION_REQUIRED", product_url=manual_url,
                search_url=search_url,
                error="This marketplace already requested browser verification during this run",
                attempts=attempts,
            )
            return
        try:
            capture = await self.browser_bridge.capture(key, model["model"], target_url)
            if capture.get("security_challenge") or capture.get("incomplete") or not capture.get("html"):
                raise BrowserBridgeTimeout(
                    str(capture.get("error") or "Complete the visible browser verification, then capture again")
                )
            offers = parse_salidzini_capture(str(capture.get("html") or ""), model["model"])
            attempts.append({
                "method": "extension", "result": "SUCCESS",
                "duration_ms": round((time.monotonic() - started) * 1000),
            })
            if offers:
                best = offers[0]
                remembered_url = str(best.get("product_url") or capture.get("url") or target_url)
                if remembered_url:
                    self.store.remember_source_link(model["id"], key, remembered_url)
                self.store.finish_assisted_marketplace_observation(
                    run_id, model["id"], key, "SUCCESS", search_url=search_url,
                    collection_method="extension", attempts=attempts, **best,
                )
            else:
                self.store.finish_assisted_marketplace_observation(
                    run_id, model["id"], key, "NOT_FOUND",
                    product_url=str(capture.get("url") or manual_url or "") or None,
                    search_url=search_url, error="No exact-model offer was found on the rendered page",
                    collection_method="extension", attempts=attempts,
                )
        except (BrowserBridgeUnavailable, BrowserBridgeTimeout) as error:
            self._blocked.add(key)
            attempts.append({
                "method": "extension", "result": "BLOCKED",
                "duration_ms": round((time.monotonic() - started) * 1000), "error": str(error)[:300],
            })
            self.store.finish_assisted_marketplace_observation(
                run_id, model["id"], key, "ACTION_REQUIRED", product_url=manual_url,
                search_url=search_url, error=str(error)[:500], attempts=attempts,
            )

    def retry(self, run_id: str, item_id: int, marketplace_key: str) -> None:
        if marketplace_key not in self.supported_keys:
            raise KeyError((item_id, marketplace_key))
        model = self.store.get_item(item_id)
        marketplace = next(
            (item for item in self.store.list_sources() if item["key"] == marketplace_key), None
        )
        if model["kind"] != "source" or not marketplace:
            raise KeyError((item_id, marketplace_key))
        task_key = f"retry:{run_id}:{item_id}:{marketplace_key}"
        if task_key in self._tasks:
            raise ValueError("This marketplace check is already running")
        self.store.ensure_assisted_marketplace_observation(run_id, item_id, marketplace_key)
        self.store.retry_assisted_marketplace_observation(run_id, item_id, marketplace_key)
        self._blocked.discard(marketplace_key)

        async def run_retry() -> None:
            try:
                await self._check_one(run_id, model, marketplace)
            finally:
                self._tasks.pop(task_key, None)

        self._tasks[task_key] = asyncio.create_task(run_retry())

    def retry_model(self, run_id: str, item_id: int) -> int:
        model = self.store.get_item(item_id)
        if model["kind"] != "source" or model.get("deleted_at") or model.get("paused"):
            raise KeyError(item_id)
        marketplaces = [
            source for source in self.store.list_sources()
            if source["kind"] == "marketplace" and source["effective_enabled"]
            and source["key"] in self.supported_keys
        ]
        started = 0
        for marketplace in marketplaces:
            task_key = f"retry:{run_id}:{item_id}:{marketplace['key']}"
            if task_key in self._tasks:
                continue
            self.store.ensure_assisted_marketplace_observation(run_id, item_id, marketplace["key"])
            self.store.retry_assisted_marketplace_observation(run_id, item_id, marketplace["key"])
            if self._mark_manual_required(run_id, model, marketplace):
                started += 1
        return started

    async def cancel_run(self, run_id: str) -> int:
        task_keys = [key for key in self._tasks if key == run_id or key.startswith(f"retry:{run_id}:")]
        tasks = [self._tasks.pop(key) for key in task_keys]
        for task in tasks:
            task.cancel()
        self.store.cancel_assisted_marketplace_run(run_id)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        return len(tasks)

    def stop(self) -> None:
        for task in self._tasks.values():
            task.cancel()
        self._tasks.clear()
