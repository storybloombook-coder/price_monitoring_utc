from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import tempfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urljoin, urlparse

import httpx
from websockets.asyncio.client import connect as websocket_connect

from .browser_bridge import BrowserBridge, BrowserBridgeTimeout, BrowserBridgeUnavailable
from .catalog import CatalogStore, canonicalize
from .sources import SOURCE_BY_KEY


MONEY_RE = re.compile(r"(?<!\d)(\d{1,5}(?:[\s.,]\d{3})*(?:[.,]\d{2})?)\s*(?:€|EUR)\b", re.IGNORECASE)


class ActionRequiredError(ValueError):
    """The shop requires a visible, human-controlled browser session."""


class ProductDocument(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[dict[str, str]] = []
        self.meta: dict[str, str] = {}
        self.json_blocks: list[str] = []
        self.itemprops: dict[str, str] = {}
        self._link: dict[str, str] | None = None
        self._json: list[str] | None = None
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

    def handle_data(self, data: str) -> None:
        if self._link is not None:
            self._link["text"] += " " + data
        if self._json is not None:
            self._json.append(data)
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
        (item for item in candidates if expected in canonicalize(str(item.get("name", ""))).replace(" ", "")),
        candidates[0] if candidates else None,
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
    meta_price = normalize_price(
        document.meta.get("product:price:amount")
        or document.meta.get("og:price:amount")
        or document.itemprops.get("price")
    )
    if meta_price is None:
        match = MONEY_RE.search(document.text)
        meta_price = normalize_price(match.group(1)) if match else None
    if meta_price is None:
        return None
    return {
        "title": document.meta.get("og:title") or document.meta.get("twitter:title") or model,
        "price_eur": meta_price,
        "availability": availability_label(
            document.meta.get("product:availability") or document.itemprops.get("availability"), document.text[:5000]
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
        if parsed.netloc != host or parsed.fragment:
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


async def fetch_rendered_html(url: str, timeout_seconds: float) -> str | None:
    renderer = EdgeRenderer(timeout_seconds)
    try:
        return await renderer.fetch(url)
    finally:
        await renderer.close()


class ShopMonitor:
    def __init__(
        self, store: CatalogStore, timeout_seconds: float = 20, browser_bridge: BrowserBridge | None = None
    ) -> None:
        self.store = store
        self.timeout_seconds = timeout_seconds
        self.browser_bridge = browser_bridge
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
        self.store.start_shop_run(run_id, models, shops)
        if models and shops:
            self._tasks[run_id] = asyncio.create_task(self._run(run_id, models, shops))

    async def _run(self, run_id: str, models: list[dict[str, Any]], shops: list[dict[str, Any]]) -> None:
        semaphore = asyncio.Semaphore(4)
        renderer = EdgeRenderer(self.timeout_seconds)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9,lt;q=0.8,et;q=0.7",
        }
        async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=True, headers=headers) as client:
            async def one(model: dict[str, Any], shop: dict[str, Any]) -> None:
                async with semaphore:
                    await self._check_one(client, renderer, run_id, model, shop)
            jobs = [(model, shop) for model in models for shop in shops]
            # Direct links are the fastest and most reliable checks, so process them first.
            jobs.sort(key=lambda pair: (not bool((pair[0].get("shop_links") or {}).get(pair[1]["key"])), pair[1]["sort_order"]))
            try:
                await asyncio.gather(*(one(model, shop) for model, shop in jobs))
            finally:
                await renderer.close()
        self._tasks.pop(run_id, None)

    async def _check_one(
        self, client: httpx.AsyncClient, renderer: EdgeRenderer, run_id: str, model: dict[str, Any], shop: dict[str, Any]
    ) -> None:
        source = SOURCE_BY_KEY[shop["key"]]
        manual_url = (model.get("shop_links") or {}).get(shop["key"])
        search_url = source.search_url(model["model"])
        target_url = manual_url or search_url
        if not target_url:
            self.store.finish_shop_observation(run_id, model["id"], shop["key"], "NOT_FOUND", search_url=search_url)
            return
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
                    raise ActionRequiredError(
                        "Complete the visible security verification in Edge, then start monitoring again"
                    )
                return rendered, str(capture.get("url") or url)

            async def fetch_from_local_edge(url: str) -> tuple[str, str]:
                if shop["key"] not in {"senukai", "varle"}:
                    raise ActionRequiredError(
                        "Open the shop link in your normal browser and verify this price manually; automated access was blocked"
                    )
                async with self._browser_semaphore:
                    if shop["key"] in self._browser_blocked:
                        raise ActionRequiredError(
                            "Open the shop link in your normal browser and verify this price manually; automated access was blocked"
                        )
                    rendered = await renderer.fetch(url)
                    if not rendered or security_challenge(rendered) or incomplete_catalog_render(rendered):
                        self._browser_blocked.add(shop["key"])
                        raise ActionRequiredError(
                            "Open the shop link in your normal browser and verify this price manually; automated access was blocked"
                        )
                return rendered, url

            async def fetch(url: str) -> tuple[str, str]:
                try:
                    response = await client.get(url)
                    response.raise_for_status()
                    html = response.text
                    if security_challenge(html) or incomplete_catalog_render(html):
                        if self.browser_bridge and self.browser_bridge.connected:
                            return await fetch_from_extension(str(response.url))
                        return await fetch_from_local_edge(str(response.url))
                    return html, str(response.url)
                except httpx.HTTPStatusError as error:
                    if error.response.status_code not in {403, 429}:
                        raise
                    if self.browser_bridge and self.browser_bridge.connected:
                        return await fetch_from_extension(url)
                    return await fetch_from_local_edge(url)

            html, resolved_url = await fetch(target_url)
            product_url = target_url
            if manual_url:
                parsed = parse_product(html, resolved_url, model["model"])
            else:
                product_url = find_product_url(html, resolved_url, model["model"]) or ""
                parsed = None
                if product_url:
                    product_html, product_resolved_url = await fetch(product_url)
                    parsed = parse_product(product_html, product_resolved_url, model["model"])
            if parsed:
                self.store.finish_shop_observation(
                    run_id, model["id"], shop["key"], "SUCCESS", search_url=search_url, **parsed
                )
            else:
                self.store.finish_shop_observation(
                    run_id, model["id"], shop["key"], "NOT_FOUND", product_url=product_url or None,
                    search_url=search_url, error="No matching product price was found"
                )
        except ActionRequiredError as error:
            self.store.finish_shop_observation(
                run_id, model["id"], shop["key"], "ACTION_REQUIRED", product_url=manual_url,
                search_url=search_url, error=str(error)[:500]
            )
        except (httpx.HTTPError, ValueError, OSError) as error:
            self.store.finish_shop_observation(
                run_id, model["id"], shop["key"], "FAILED", product_url=manual_url,
                search_url=search_url, error=str(error)[:500]
            )

    def retry(self, run_id: str, item_id: int, shop_key: str) -> None:
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
        self.store.retry_shop_observation(run_id, item_id, shop_key)
        self._extension_blocked.discard(shop_key)
        self._browser_blocked.discard(shop_key)

        async def run_retry() -> None:
            renderer = EdgeRenderer(self.timeout_seconds)
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9,lt;q=0.8,et;q=0.7",
            }
            try:
                async with httpx.AsyncClient(
                    timeout=self.timeout_seconds, follow_redirects=True, headers=headers
                ) as client:
                    await self._check_one(client, renderer, run_id, model, shop)
            finally:
                await renderer.close()
                self._tasks.pop(task_key, None)

        self._tasks[task_key] = asyncio.create_task(run_retry())

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
