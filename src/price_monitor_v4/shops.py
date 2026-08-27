from __future__ import annotations

import asyncio
import json
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from .catalog import CatalogStore, canonicalize
from .sources import SOURCE_BY_KEY


MONEY_RE = re.compile(r"(?<!\d)(\d{1,5}(?:[\s.,]\d{3})*(?:[.,]\d{2})?)\s*(?:€|EUR)\b", re.IGNORECASE)


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
        if urlparse(url).netloc != host:
            continue
        haystack = canonicalize(f"{link['text']} {url}").replace(" ", "")
        if expected and expected in haystack:
            score = 2 if expected in canonicalize(link["text"]).replace(" ", "") else 1
            scored.append((score, url))
    return max(scored, default=(0, None))[1]


class ShopMonitor:
    def __init__(self, store: CatalogStore, timeout_seconds: float = 20) -> None:
        self.store = store
        self.timeout_seconds = timeout_seconds
        self._tasks: dict[str, asyncio.Task[None]] = {}

    def start(self, run_id: str) -> None:
        models = [item for item in self.store.list_items("source", "active") if not item["paused"]]
        shops = [item for item in self.store.list_sources() if item["kind"] == "shop" and item["effective_enabled"]]
        self.store.start_shop_run(run_id, models, shops)
        if models and shops:
            self._tasks[run_id] = asyncio.create_task(self._run(run_id, models, shops))

    async def _run(self, run_id: str, models: list[dict[str, Any]], shops: list[dict[str, Any]]) -> None:
        semaphore = asyncio.Semaphore(4)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9,lt;q=0.8,et;q=0.7",
        }
        async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=True, headers=headers) as client:
            async def one(model: dict[str, Any], shop: dict[str, Any]) -> None:
                async with semaphore:
                    await self._check_one(client, run_id, model, shop)
            await asyncio.gather(*(one(model, shop) for model in models for shop in shops))
        self._tasks.pop(run_id, None)

    async def _check_one(
        self, client: httpx.AsyncClient, run_id: str, model: dict[str, Any], shop: dict[str, Any]
    ) -> None:
        source = SOURCE_BY_KEY[shop["key"]]
        manual_url = (model.get("shop_links") or {}).get(shop["key"])
        search_url = source.search_url(model["model"])
        target_url = manual_url or search_url
        if not target_url:
            self.store.finish_shop_observation(run_id, model["id"], shop["key"], "NOT_FOUND", search_url=search_url)
            return
        try:
            response = await client.get(target_url)
            response.raise_for_status()
            product_url = target_url
            parsed = parse_product(response.text, str(response.url), model["model"])
            if not manual_url and parsed is None:
                product_url = find_product_url(response.text, str(response.url), model["model"]) or ""
                if product_url:
                    response = await client.get(product_url)
                    response.raise_for_status()
                    parsed = parse_product(response.text, str(response.url), model["model"])
            if parsed:
                self.store.finish_shop_observation(
                    run_id, model["id"], shop["key"], "SUCCESS", search_url=search_url, **parsed
                )
            else:
                self.store.finish_shop_observation(
                    run_id, model["id"], shop["key"], "NOT_FOUND", product_url=product_url or None,
                    search_url=search_url, error="No matching product price was found"
                )
        except (httpx.HTTPError, ValueError) as error:
            self.store.finish_shop_observation(
                run_id, model["id"], shop["key"], "FAILED", product_url=manual_url,
                search_url=search_url, error=str(error)[:500]
            )

    def stop(self) -> None:
        for task in self._tasks.values():
            task.cancel()
        self._tasks.clear()
