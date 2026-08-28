from __future__ import annotations

import asyncio
import json
import os
import random
import re
import shutil
import subprocess
import tempfile
import time
from html.parser import HTMLParser
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urljoin, urlparse

import httpx
from websockets.asyncio.client import connect as websocket_connect

try:
    from playwright.async_api import BrowserContext, Playwright, async_playwright
except ImportError:  # The source tree remains usable before optional browser dependencies are installed.
    BrowserContext = Any
    Playwright = Any
    async_playwright = None

from .browser_bridge import BrowserBridge, BrowserBridgeTimeout, BrowserBridgeUnavailable
from .catalog import CatalogStore, canonicalize
from .sources import SOURCE_BY_KEY


MONEY_RE = re.compile(
    r"(?<!\d)(\d{1,5}(?:[\s.,]\d{3})*(?:[.,]\d{2})?)\s*(?:€|EUR)(?!\w)", re.IGNORECASE
)
CANDIDATE_RE = re.compile(
    r'<script[^>]+id=["\']price-monitor-candidates["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)


class ActionRequiredError(ValueError):
    """The shop requires a visible, human-controlled browser session."""

    def __init__(
        self,
        message: str,
        retry_after_seconds: float | None = None,
        *,
        pause_source: bool = True,
    ) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds
        self.pause_source = pause_source


class ProtectionBlockedError(ActionRequiredError):
    """A retailer protection page blocked this collection path."""


class RenderRequiredError(ValueError):
    """The direct response needs a JavaScript-capable browser."""


class CollectionMethodUnavailable(ValueError):
    """The selected collection method cannot run on this computer."""


def retry_after_seconds(value: str | None, default: float) -> float:
    if not value:
        return default
    text = value.strip()
    try:
        return max(1.0, min(float(text), 86_400.0))
    except ValueError:
        pass
    try:
        parsed = parsedate_to_datetime(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return max(1.0, min((parsed - datetime.now(UTC)).total_seconds(), 86_400.0))
    except (TypeError, ValueError, OverflowError):
        return default


class ProductDocument(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[dict[str, str]] = []
        self.meta: dict[str, str] = {}
        self.json_blocks: list[str] = []
        self.itemprops: dict[str, str] = {}
        self._link: dict[str, str] | None = None
        self._json: list[str] | None = None
        self._title: list[str] | None = None
        self.title = ""
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): value or "" for key, value in attrs}
        if tag == "a" and values.get("href"):
            self._link = {"href": values["href"], "text": ""}
        if tag == "meta":
            key = values.get("property") or values.get("name") or values.get("itemprop")
            if key and values.get("content"):
                self.meta[key.lower()] = values["content"].strip()
        if tag == "script" and "ld+json" in values.get("type", "").lower():
            self._json = []
        if tag == "title":
            self._title = []
        itemprop = values.get("itemprop", "").lower()
        if itemprop and values.get("content"):
            self.itemprops[itemprop] = values["content"].strip()

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._link is not None:
            self._link["text"] = re.sub(r"\s+", " ", self._link["text"]).strip()
            self.links.append(self._link)
            self._link = None
        if tag == "script" and self._json is not None:
            self.json_blocks.append("".join(self._json).strip())
            self._json = None
        if tag == "title" and self._title is not None:
            self.title = re.sub(r"\s+", " ", " ".join(self._title)).strip()
            self._title = None

    def handle_data(self, data: str) -> None:
        if self._link is not None:
            self._link["text"] += " " + data
        if self._json is not None:
            self._json.append(data)
        if self._title is not None:
            self._title.append(data)
        if data.strip():
            self._text.append(data.strip())

    @property
    def text(self) -> str:
        return re.sub(r"\s+", " ", " ".join(self._text))


def iter_json(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from iter_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_json(child)


def normalize_price(value: Any) -> float | None:
    if value in (None, ""):
        return None
    cleaned = re.sub(r"[^0-9,.]", "", str(value)).replace(",", ".")
    if cleaned.count(".") > 1:
        cleaned = cleaned.replace(".", "", cleaned.count(".") - 1)
    try:
        result = float(cleaned)
        return result if result >= 0 else None
    except ValueError:
        return None


def availability_label(value: Any, text: str = "") -> str:
    combined = f"{value or ''} {text}".lower()
    unavailable = ("outofstock", "out of stock", "išparduota", "pole saadaval", "nav pieejams")
    preorder = ("preorder", "pre-order", "išankst", "ettetell")
    if any(token in combined for token in unavailable):
        return "OUT_OF_STOCK"
    if any(token in combined for token in preorder):
        return "PRE_ORDER"
    if value or any(token in combined for token in ("instock", "in stock", "available", "turime", "saadaval")):
        return "IN_STOCK"
    return "UNKNOWN"


def is_search_listing_url(value: str) -> bool:
    """Return True for retailer search/listing URLs that are not product evidence."""
    parsed = urlparse(value or "")
    path = unquote(parsed.path).lower()
    return any(token in path for token in (
        "/search", "/otsing", "/rezultatus", "/paieska", "/paieška", "/word/",
    ))


def exact_model_match(expected: str, *values: Any) -> bool:
    return bool(expected and any(
        expected in canonicalize(str(value or "")).replace(" ", "") for value in values
    ))


def parse_product(html: str, url: str, model: str) -> dict[str, Any] | None:
    document = ProductDocument()
    document.feed(html)
    candidates: list[dict[str, Any]] = []
    for block in document.json_blocks:
        try:
            data = json.loads(block)
        except (json.JSONDecodeError, TypeError):
            continue
        for item in iter_json(data):
            item_type = item.get("@type")
            types = item_type if isinstance(item_type, list) else [item_type]
            if "Product" in types:
                candidates.append(item)
    expected = canonicalize(model).replace(" ", "")
    product = next(
        (
            item for item in candidates
            if exact_model_match(
                expected,
                item.get("name"), item.get("sku"), item.get("mpn"),
                item.get("model"), item.get("productID"),
            )
        ),
        None,
    )
    if product:
        offers = product.get("offers") or {}
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        if isinstance(offers, dict):
            price = normalize_price(offers.get("price") or offers.get("lowPrice") or offers.get("highPrice"))
            if price is not None:
                return {
                    "title": str(product.get("name") or document.meta.get("og:title") or model),
                    "price_eur": price,
                    "availability": availability_label(offers.get("availability"), document.text[:5000]),
                    "product_url": urljoin(url, str(offers.get("url") or product.get("url") or url)),
                }
    candidate_match = CANDIDATE_RE.search(html or "")
    try:
        rendered_candidates = json.loads(candidate_match.group(1)) if candidate_match else []
    except (TypeError, ValueError, json.JSONDecodeError):
        rendered_candidates = []
    for candidate in rendered_candidates if isinstance(rendered_candidates, list) else []:
        if not isinstance(candidate, dict):
            continue
        text = str(candidate.get("text") or "")
        if not exact_model_match(expected, text):
            continue
        exact_links: list[str] = []
        for link in candidate.get("links") or []:
            if not isinstance(link, dict) or not link.get("url"):
                continue
            link_url = urljoin(url, str(link["url"]))
            if exact_model_match(expected, link.get("text"), unquote(urlparse(link_url).path)):
                exact_links.append(link_url)
        # A search page may contain the query and an unrelated promotional price in
        # the same container. It is only product evidence when the container also
        # has an exact-model product link.
        if is_search_listing_url(url) and not exact_links:
            continue
        # Elisa exposes the monthly instalment before the actual product total.
        total_match = re.search(
            r"(?:toote\s+hind|total\s+price)\s*[:\-]?\s*" + MONEY_RE.pattern,
            text, re.IGNORECASE,
        )
        price_match = total_match or MONEY_RE.search(text)
        price = normalize_price(price_match.group(price_match.lastindex or 1)) if price_match else None
        if price is not None:
            return {
                "title": next(
                    (str(link.get("text") or "") for link in candidate.get("links") or []
                     if isinstance(link, dict) and exact_model_match(expected, link.get("text"))),
                    document.meta.get("og:title") or document.title or model,
                ),
                "price_eur": price,
                "availability": availability_label(None, text),
                "product_url": exact_links[0] if exact_links else url,
            }

    page_title = document.meta.get("og:title") or document.meta.get("twitter:title") or document.title
    strong_product_page = not is_search_listing_url(url) and exact_model_match(
        expected, page_title, unquote(urlparse(url).path)
    )
    if not strong_product_page:
        return None
    price = normalize_price(
        document.meta.get("product:price:amount")
        or document.meta.get("og:price:amount")
        or document.itemprops.get("price")
    )
    if price is None:
        match = MONEY_RE.search(document.text)
        price = normalize_price(match.group(1)) if match else None
    if price is None:
        return None
    return {
        "title": page_title or model,
        "price_eur": price,
        "availability": availability_label(
            document.meta.get("product:availability") or document.itemprops.get("availability"),
            document.text[:5000],
        ),
        "product_url": url,
    }


def find_product_url(html: str, base_url: str, model: str) -> str | None:
    document = ProductDocument()
    document.feed(html)
    expected = canonicalize(model).replace(" ", "")
    host = urlparse(base_url).netloc
    scored: list[tuple[int, str]] = []
    for link in document.links:
        url = urljoin(base_url, link["href"])
        parsed = urlparse(url)
        if parsed.netloc != host or parsed.fragment or is_search_listing_url(url):
            continue
        # Do not score the search query itself: every link on ?q=55T7B would
        # otherwise look like a model match (including "#content").
        path = unquote(parsed.path)
        haystack = canonicalize(f"{link['text']} {path}").replace(" ", "")
        if expected and expected in haystack:
            score = 3 if expected in canonicalize(link["text"]).replace(" ", "") else 2
            if any(token in path.lower() for token in ("/p/", "/product", "/televizoriai/")):
                score += 1
            scored.append((score, url))
    candidate_match = CANDIDATE_RE.search(html or "")
    try:
        rendered_candidates = json.loads(candidate_match.group(1)) if candidate_match else []
    except (TypeError, ValueError, json.JSONDecodeError):
        rendered_candidates = []
    for candidate in rendered_candidates if isinstance(rendered_candidates, list) else []:
        if not isinstance(candidate, dict):
            continue
        candidate_text = str(candidate.get("text") or "")
        if expected not in canonicalize(candidate_text).replace(" ", ""):
            continue
        for link in candidate.get("links") or []:
            if not isinstance(link, dict) or not link.get("url"):
                continue
            url = urljoin(base_url, str(link["url"]))
            parsed = urlparse(url)
            if parsed.netloc != host or parsed.fragment or is_search_listing_url(url):
                continue
            link_text = canonicalize(str(link.get("text") or "")).replace(" ", "")
            path = unquote(parsed.path)
            haystack = canonicalize(f"{link_text} {path}").replace(" ", "")
            if expected in haystack:
                scored.append((6 if expected in link_text else 5, url))
    return max(scored, default=(0, None))[1]


def security_challenge(html: str) -> bool:
    lowered = html.lower()
    return any(token in lowered for token in (
        "performing security verification", "cf-chl-", "just a moment...", "verify you are human",
        "attention required!", "sorry, you have been blocked"
    ))


def incomplete_catalog_render(html: str) -> bool:
    lowered = html.lower()
    return "muiskeleton" in lowered and not re.search(r'href=["\'][^"\']*/p/[^"\']+["\']', lowered)


def edge_executable() -> Path | None:
    candidates = [
        Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/Edge/Application/msedge.exe",
    ]
    return next((path for path in candidates if path.is_file()), None)


class EdgeRenderer:
    """Small CDP client that reuses one local headless Edge process per run."""

    def __init__(self, timeout_seconds: float) -> None:
        self.timeout_seconds = timeout_seconds
        self.profile = Path(tempfile.mkdtemp(prefix="price-monitor-edge-"))
        self.process: asyncio.subprocess.Process | None = None
        self.port: int | None = None

    async def start(self) -> bool:
        if self.process and self.process.returncode is None and self.port:
            return True
        executable = edge_executable()
        if not executable:
            return False
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self.process = await asyncio.create_subprocess_exec(
            str(executable), "--disable-gpu", "--no-first-run", "--disable-extensions",
            "--window-position=-32000,-32000", "--window-size=800,600",
            "--disable-backgrounding-occluded-windows", "--disable-renderer-backgrounding",
            "--remote-debugging-port=0", f"--user-data-dir={self.profile}", "about:blank",
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            creationflags=creation_flags,
        )
        port_file = self.profile / "DevToolsActivePort"
        for _ in range(80):
            if port_file.exists():
                lines = port_file.read_text(encoding="utf-8", errors="replace").splitlines()
                if lines:
                    self.port = int(lines[0])
                    return True
            if self.process.returncode is not None:
                break
            await asyncio.sleep(0.1)
        return False

    async def fetch(self, url: str) -> str | None:
        if not await self.start() or not self.port:
            return None
        api_root = f"http://127.0.0.1:{self.port}"
        target_id: str | None = None
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                target_response = await client.put(f"{api_root}/json/new?{quote(url, safe='')}")
                target_response.raise_for_status()
                target = target_response.json()
            target_id = str(target["id"])
            socket_url = str(target["webSocketDebuggerUrl"])
            async with websocket_connect(socket_url, max_size=None, open_timeout=5, close_timeout=2) as socket:
                # The shops render their catalog client-side after the initial load.
                await asyncio.sleep(6)
                command_id = 1
                await socket.send(json.dumps({
                    "id": command_id,
                    "method": "Runtime.evaluate",
                    "params": {"expression": "document.documentElement.outerHTML", "returnByValue": True},
                }))
                while True:
                    message = json.loads(await asyncio.wait_for(socket.recv(), timeout=max(10.0, self.timeout_seconds)))
                    if message.get("id") == command_id:
                        return message.get("result", {}).get("result", {}).get("value")
        except (httpx.HTTPError, OSError, TimeoutError, ValueError, KeyError):
            return None
        finally:
            if target_id and self.port:
                try:
                    async with httpx.AsyncClient(timeout=3) as client:
                        await client.get(f"{api_root}/json/close/{target_id}")
                except httpx.HTTPError:
                    pass

    async def close(self) -> None:
        if self.process and self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=5)
            except TimeoutError:
                self.process.kill()
                await self.process.wait()
        shutil.rmtree(self.profile, ignore_errors=True)


class PlaywrightRenderer:
    """Persistent Edge profile used by the selectable Playwright strategy."""

    def __init__(self, profile: Path, timeout_seconds: float) -> None:
        self.profile = profile
        self.timeout_seconds = timeout_seconds
        self.playwright: Playwright | None = None
        self.context: BrowserContext | None = None

    async def start(self) -> bool:
        if self.context:
            return True
        if async_playwright is None or not edge_executable():
            return False
        self.profile.mkdir(parents=True, exist_ok=True)
        try:
            self.playwright = await async_playwright().start()
            self.context = await self.playwright.chromium.launch_persistent_context(
                str(self.profile),
                channel="msedge",
                headless=True,
                viewport={"width": 1280, "height": 900},
                locale="en-US",
                args=["--disable-backgrounding-occluded-windows", "--disable-renderer-backgrounding"],
            )
            return True
        except Exception:
            if self.playwright:
                await self.playwright.stop()
            self.playwright = None
            self.context = None
            return False

    async def fetch(self, url: str) -> tuple[str, str] | None:
        if not await self.start() or not self.context:
            return None
        page = await self.context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=int(self.timeout_seconds * 1000))
            try:
                await page.wait_for_load_state("networkidle", timeout=min(8000, int(self.timeout_seconds * 1000)))
            except Exception:
                pass
            return await page.content(), page.url
        except Exception:
            return None
        finally:
            await page.close()

    async def close(self) -> None:
        if self.context:
            await self.context.close()
        if self.playwright:
            await self.playwright.stop()
        self.context = None
        self.playwright = None


async def fetch_rendered_html(url: str, timeout_seconds: float) -> str | None:
    renderer = EdgeRenderer(timeout_seconds)
    try:
        return await renderer.fetch(url)
    finally:
        await renderer.close()


class ShopMonitor:
    def __init__(
        self,
        store: CatalogStore,
        timeout_seconds: float = 20,
        browser_bridge: BrowserBridge | None = None,
        *,
        request_delay_min_seconds: float = 8,
        request_delay_max_seconds: float = 15,
        cooldown_seconds: float = 3600,
        cache_ttl_seconds: float = 14_400,
    ) -> None:
        self.store = store
        self.timeout_seconds = timeout_seconds
        self.browser_bridge = browser_bridge
        self.request_delay_min_seconds = max(0, request_delay_min_seconds)
        self.request_delay_max_seconds = max(self.request_delay_min_seconds, request_delay_max_seconds)
        self.cooldown_seconds = max(1, cooldown_seconds)
        self.cache_ttl_seconds = max(0, cache_ttl_seconds)
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._browser_semaphore = asyncio.Semaphore(1)
        self._extension_semaphore = asyncio.Semaphore(1)
        self._browser_blocked: set[str] = set()
        self._extension_blocked: set[str] = set()

    def start(self, run_id: str) -> None:
        self._browser_blocked.clear()
        self._extension_blocked.clear()
        models = [item for item in self.store.list_items("source", "active") if not item["paused"]]
        shops = [item for item in self.store.list_sources() if item["kind"] == "shop" and item["effective_enabled"]]
        self.store.start_shop_run(run_id, models, shops, self.cache_ttl_seconds)
        if models and shops:
            self._tasks[run_id] = asyncio.create_task(self._run(run_id, models, shops))

    async def _run(self, run_id: str, models: list[dict[str, Any]], shops: list[dict[str, Any]]) -> None:
        renderer = EdgeRenderer(self.timeout_seconds)
        database = Path(getattr(self.store, "database", Path(tempfile.gettempdir()) / "price-monitor.sqlite3"))
        playwright_renderer = PlaywrightRenderer(database.parent / "playwright-edge-profile", self.timeout_seconds)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9,lt;q=0.8,et;q=0.7",
        }
        async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=True, headers=headers) as client:
            async def one_shop(shop: dict[str, Any]) -> None:
                ordered_models = sorted(
                    models,
                    key=lambda model: not bool((model.get("shop_links") or {}).get(shop["key"])),
                )
                sent_request = False
                for model in ordered_models:
                    if not self.store.shop_observation_pending(run_id, model["id"], shop["key"]):
                        continue
                    if sent_request and shop.get("collection_method") != "manual":
                        await asyncio.sleep(random.uniform(
                            self.request_delay_min_seconds, self.request_delay_max_seconds
                        ))
                    await self._check_one(client, renderer, run_id, model, shop, playwright_renderer)
                    sent_request = True
            try:
                # Shops may progress independently, but a single domain is always sequential.
                await asyncio.gather(*(one_shop(shop) for shop in shops))
            finally:
                await renderer.close()
                await playwright_renderer.close()
        self._tasks.pop(run_id, None)

    async def _check_one(
        self,
        client: httpx.AsyncClient,
        renderer: EdgeRenderer,
        run_id: str,
        model: dict[str, Any],
        shop: dict[str, Any],
        playwright_renderer: PlaywrightRenderer | None = None,
        method_override: str | None = None,
        link_only: bool = False,
    ) -> None:
        attempts: list[dict[str, Any]] = []
        selected_method = method_override or str(shop.get("collection_method") or "auto")
        used_method: str | None = None
        source = SOURCE_BY_KEY[shop["key"]]
        manual_url = (model.get("shop_links") or {}).get(shop["key"])
        search_url = source.search_url(model["model"])
        target_url = manual_url or search_url
        if not target_url:
            self.store.finish_shop_observation(
                run_id, model["id"], shop["key"], "NOT_FOUND", search_url=search_url,
                collection_method=selected_method, attempts=attempts,
            )
            return

        async def attempted(method: str, operation) -> tuple[str, str]:
            nonlocal used_method
            started = time.monotonic()
            try:
                result = await operation()
                attempts.append({
                    "method": method,
                    "result": "SUCCESS",
                    "duration_ms": round((time.monotonic() - started) * 1000),
                })
                used_method = method
                return result
            except Exception as error:
                attempts.append({
                    "method": method,
                    "result": "BLOCKED" if isinstance(error, ActionRequiredError) else "FAILED",
                    "duration_ms": round((time.monotonic() - started) * 1000),
                    "error": str(error)[:300],
                })
                raise

        try:
            async def fetch_from_extension(url: str) -> tuple[str, str]:
                if not self.browser_bridge or not self.browser_bridge.connected:
                    raise BrowserBridgeUnavailable("The PriceMonitor Edge extension is not connected")
                if shop["key"] in self._extension_blocked:
                    raise ActionRequiredError("Browser verification for this shop was already blocked during this run")
                try:
                    async with self._extension_semaphore:
                        if shop["key"] in self._extension_blocked:
                            raise ActionRequiredError("Browser verification for this shop was already blocked during this run")
                        capture = await self.browser_bridge.capture(shop["key"], model["model"], url)
                except (BrowserBridgeUnavailable, BrowserBridgeTimeout) as error:
                    self._extension_blocked.add(shop["key"])
                    raise ActionRequiredError(str(error)) from error
                rendered = str(capture.get("html") or "")
                if capture.get("security_challenge") or capture.get("incomplete") or not rendered or security_challenge(rendered):
                    self._extension_blocked.add(shop["key"])
                    raise ProtectionBlockedError(
                        "Complete the visible security verification in Edge, then start monitoring again"
                    )
                return rendered, str(capture.get("url") or url)

            async def fetch_from_local_edge(url: str) -> tuple[str, str]:
                async with self._browser_semaphore:
                    if shop["key"] in self._browser_blocked:
                        raise ProtectionBlockedError("Background Edge was already blocked for this shop during this run")
                    rendered = await renderer.fetch(url)
                    if not rendered or security_challenge(rendered) or incomplete_catalog_render(rendered):
                        self._browser_blocked.add(shop["key"])
                        raise ProtectionBlockedError("Background Edge was blocked or could not render the retailer page")
                return rendered, url

            async def fetch_from_playwright(url: str) -> tuple[str, str]:
                if not playwright_renderer:
                    raise CollectionMethodUnavailable("Playwright Edge is unavailable")
                async with self._browser_semaphore:
                    rendered = await playwright_renderer.fetch(url)
                if not rendered:
                    raise CollectionMethodUnavailable("Playwright Edge could not open the retailer page")
                html, resolved = rendered
                if security_challenge(html) or incomplete_catalog_render(html):
                    raise ProtectionBlockedError("Playwright Edge was blocked or could not render the retailer page")
                return html, resolved

            async def fetch_direct(url: str) -> tuple[str, str]:
                response = await client.get(url)
                if response.status_code == 429:
                    delay = retry_after_seconds(response.headers.get("retry-after"), self.cooldown_seconds)
                    raise ProtectionBlockedError(
                        "The shop rate-limited this IP. Requests are paused to avoid a longer block.", delay
                    )
                if response.status_code == 403:
                    raise ProtectionBlockedError("The direct request was rejected by retailer protection")
                response.raise_for_status()
                html = response.text
                if response.headers.get("cf-mitigated", "").lower() == "challenge" or security_challenge(html):
                    raise ProtectionBlockedError("The direct request reached a retailer security challenge")
                if incomplete_catalog_render(html):
                    raise RenderRequiredError("The retailer page requires JavaScript rendering")
                return html, str(response.url)

            methods = {
                "direct": fetch_direct,
                "background": fetch_from_local_edge,
                "playwright": fetch_from_playwright,
                "extension": fetch_from_extension,
            }

            async def fetch(url: str) -> tuple[str, str]:
                # Manual discovery does not generate blind searches. Once the user has
                # supplied a verified SKU URL, that URL becomes a safe automatic fast path.
                # If it has moved, the same retry may perform the normal search fallback.
                effective_method = "auto" if selected_method == "manual" and manual_url else selected_method
                if effective_method == "manual":
                    raise ActionRequiredError("Manual collection is selected; open the retailer link and verify the price")
                if effective_method != "auto":
                    operation = methods.get(effective_method)
                    if not operation:
                        raise CollectionMethodUnavailable(f"Unknown collection method: {effective_method}")
                    return await attempted(effective_method, lambda: operation(url))

                try:
                    return await attempted("direct", lambda: fetch_direct(url))
                except ProtectionBlockedError as direct_error:
                    if direct_error.retry_after_seconds:
                        raise
                    if self.browser_bridge and self.browser_bridge.connected:
                        return await attempted("extension", lambda: fetch_from_extension(url))
                    raise ActionRequiredError(
                        "Retailer protection blocked direct collection and the Edge extension is not connected"
                    ) from direct_error
                except (RenderRequiredError, httpx.HTTPError, CollectionMethodUnavailable):
                    preferred = str(shop.get("last_success_method") or "")
                    browser_order = [preferred] if preferred in {"playwright", "background"} else []
                    browser_order.extend(method for method in ("playwright", "background") if method not in browser_order)
                    last_error: Exception | None = None
                    for method in browser_order:
                        try:
                            return await attempted(method, lambda method=method: methods[method](url))
                        except (ProtectionBlockedError, CollectionMethodUnavailable, OSError) as error:
                            last_error = error
                    if self.browser_bridge and self.browser_bridge.connected:
                        return await attempted("extension", lambda: fetch_from_extension(url))
                    raise ActionRequiredError(
                        "Browser rendering did not complete and the Edge extension is not connected"
                    ) from last_error

            parsed = None
            product_url = ""
            if manual_url:
                try:
                    html, resolved_url = await fetch(manual_url)
                    product_url = resolved_url
                    parsed = parse_product(html, resolved_url, model["model"])
                    if not parsed:
                        discovered_url = find_product_url(html, resolved_url, model["model"])
                        if discovered_url and discovered_url != resolved_url:
                            product_html, product_resolved_url = await fetch(discovered_url)
                            product_url = product_resolved_url
                            parsed = parse_product(product_html, product_resolved_url, model["model"])
                except (httpx.HTTPError, CollectionMethodUnavailable, RenderRequiredError) as error:
                    if link_only:
                        raise ActionRequiredError(
                            "The saved link needs browser verification; open it and use Capture again",
                            pause_source=False,
                        ) from error
                    # A saved URL is a fast path, not a permanent dead end. Search again
                    # when the retailer has moved or removed the old product page.
                    parsed = None
            if not parsed and not link_only and search_url and search_url != manual_url:
                search_html, search_resolved_url = await fetch(search_url)
                product_url = find_product_url(search_html, search_resolved_url, model["model"]) or ""
                if product_url:
                    product_html, product_resolved_url = await fetch(product_url)
                    parsed = parse_product(product_html, product_resolved_url, model["model"])
            if parsed:
                if hasattr(self.store, "remember_source_method"):
                    self.store.remember_source_method(shop["key"], used_method or selected_method)
                if parsed.get("product_url") and hasattr(self.store, "remember_source_link"):
                    self.store.remember_source_link(model["id"], shop["key"], str(parsed["product_url"]))
                self.store.finish_shop_observation(
                    run_id, model["id"], shop["key"], "SUCCESS", search_url=search_url,
                    collection_method=used_method or selected_method, attempts=attempts, **parsed
                )
            elif link_only:
                raise ActionRequiredError(
                    "The saved page opened, but no exact-model price was found; verify it in the browser",
                    pause_source=False,
                )
            else:
                self.store.finish_shop_observation(
                    run_id, model["id"], shop["key"], "NOT_FOUND", product_url=product_url or None,
                    search_url=search_url, error="No matching product price was found",
                    collection_method=used_method or selected_method, attempts=attempts,
                )
        except ActionRequiredError as error:
            cooldown_until = None
            if error.pause_source and (selected_method != "manual" or manual_url):
                cooldown_until = self.store.pause_shop_for_protection(
                    run_id,
                    shop["key"],
                    error.retry_after_seconds or self.cooldown_seconds,
                    str(error),
                )
            self.store.finish_shop_observation(
                run_id, model["id"], shop["key"], "ACTION_REQUIRED", product_url=manual_url,
                search_url=search_url, error=str(error)[:500], retry_after=cooldown_until,
                collection_method=used_method or selected_method, attempts=attempts,
            )
        except (httpx.HTTPError, ValueError, OSError) as error:
            self.store.finish_shop_observation(
                run_id, model["id"], shop["key"], "FAILED", product_url=manual_url,
                search_url=search_url, error=str(error)[:500],
                collection_method=used_method or selected_method, attempts=attempts,
            )
        except Exception as error:
            # A retry must always leave PENDING, even when an unexpected collector
            # bug occurs. Otherwise the UI can remain on Checking indefinitely.
            self.store.finish_shop_observation(
                run_id, model["id"], shop["key"], "FAILED", product_url=manual_url,
                search_url=search_url, error=f"Unexpected collector error: {error}"[:500],
                collection_method=used_method or selected_method, attempts=attempts,
            )

    def retry(
        self,
        run_id: str,
        item_id: int,
        shop_key: str,
        *,
        method_override: str | None = None,
        link_only: bool = False,
    ) -> None:
        model = self.store.get_item(item_id)
        shop = next(
            (item for item in self.store.list_sources() if item["key"] == shop_key and item["kind"] == "shop"),
            None,
        )
        if model["kind"] != "source" or not shop:
            raise KeyError((item_id, shop_key))
        task_key = f"retry:{run_id}:{item_id}:{shop_key}"
        if task_key in self._tasks:
            raise ValueError("This shop check is already running")
        self.store.ensure_shop_observation(run_id, item_id, shop_key)
        self.store.retry_shop_observation(run_id, item_id, shop_key)
        self._extension_blocked.discard(shop_key)
        self._browser_blocked.discard(shop_key)

        async def run_retry() -> None:
            renderer = EdgeRenderer(self.timeout_seconds)
            database = Path(getattr(self.store, "database", Path(tempfile.gettempdir()) / "price-monitor.sqlite3"))
            playwright_renderer = PlaywrightRenderer(database.parent / "playwright-edge-profile", self.timeout_seconds)
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9,lt;q=0.8,et;q=0.7",
            }
            try:
                async with httpx.AsyncClient(
                    timeout=self.timeout_seconds, follow_redirects=True, headers=headers
                ) as client:
                    await self._check_one(
                        client, renderer, run_id, model, shop, playwright_renderer,
                        method_override=method_override,
                        link_only=link_only,
                    )
            finally:
                await renderer.close()
                await playwright_renderer.close()
                self._tasks.pop(task_key, None)

        self._tasks[task_key] = asyncio.create_task(run_retry())

    def retry_model(self, run_id: str, item_id: int) -> int:
        model = self.store.get_item(item_id)
        if model["kind"] != "source" or model.get("deleted_at") or model.get("paused"):
            raise KeyError(item_id)
        shops = [
            source for source in self.store.list_sources()
            if source["kind"] == "shop" and source["effective_enabled"]
        ]
        started = 0
        for shop in shops:
            try:
                self.retry(run_id, item_id, shop["key"])
                started += 1
            except ValueError:
                continue
        return started

    async def test_method(self, item_id: int, shop_key: str, method: str) -> dict[str, Any]:
        """Run one isolated SKU/method diagnostic without changing monitoring history."""
        allowed = {"auto", "direct", "background", "playwright", "extension", "manual"}
        if method not in allowed:
            raise ValueError(f"Unsupported shop collection method: {method}")
        model = self.store.get_item(item_id)
        shop = next(
            (item for item in self.store.list_sources() if item["key"] == shop_key and item["kind"] == "shop"),
            None,
        )
        if model["kind"] != "source" or not shop:
            raise KeyError((item_id, shop_key))

        class ProbeStore:
            def __init__(self, database: Path) -> None:
                self.database = database
                self.result: dict[str, Any] = {}

            def finish_shop_observation(self, _run_id, _item_id, _shop_key, status, **kwargs) -> None:
                self.result = {"status": status, **kwargs}

            def pause_shop_for_protection(self, _run_id, _shop_key, cooldown_seconds, reason) -> str:
                self.result["protection"] = {"cooldown_seconds": cooldown_seconds, "reason": reason}
                return datetime.now(UTC).isoformat()

            def remember_source_method(self, _key, _method) -> None:
                return None

        probe_store = ProbeStore(Path(getattr(self.store, "database")))
        probe = ShopMonitor(
            probe_store,
            self.timeout_seconds,
            self.browser_bridge,
            request_delay_min_seconds=0,
            request_delay_max_seconds=0,
            cooldown_seconds=self.cooldown_seconds,
            cache_ttl_seconds=0,
        )
        renderer = EdgeRenderer(self.timeout_seconds)
        playwright_renderer = PlaywrightRenderer(
            probe_store.database.parent / "playwright-edge-profile", self.timeout_seconds
        )
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9,lt;q=0.8,et;q=0.7",
        }
        started = time.monotonic()
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds, follow_redirects=True, headers=headers
            ) as client:
                await probe._check_one(
                    client, renderer, "method-test", model, shop, playwright_renderer, method_override=method
                )
        finally:
            await renderer.close()
            await playwright_renderer.close()
        return {
            "shop_key": shop_key,
            "model": model["model"],
            "requested_method": method,
            "duration_ms": round((time.monotonic() - started) * 1000),
            **probe_store.result,
        }

    async def cancel_run(self, run_id: str) -> int:
        task_keys = [
            key for key in self._tasks
            if key == run_id or key.startswith(f"retry:{run_id}:")
        ]
        tasks = [self._tasks.pop(key) for key in task_keys]
        for task in tasks:
            task.cancel()
        self.store.cancel_shop_run(run_id)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        return len(tasks)

    def stop(self) -> None:
        for task in self._tasks.values():
            task.cancel()
        self._tasks.clear()
