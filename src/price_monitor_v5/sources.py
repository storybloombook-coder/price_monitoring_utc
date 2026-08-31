from dataclasses import replace
from urllib.parse import urlsplit, unquote, parse_qs
import re
from price_monitor_v4.sources import SOURCES as V4_SOURCES, MonitoringSource, search_phrase

SOURCES = tuple(replace(source, search_template={
    "kaina24": "https://www.kaina24.lt/s/{query}/",
    "salidzini": "https://www.salidzini.lv/cena?q={query}",
    "hinnavaatlus": "https://www.hinnavaatlus.ee/search/?query={query}",
}.get(source.key), name="RDE.ee" if source.key == "rde" else source.name) for source in V4_SOURCES)
SOURCES = SOURCES + (MonitoringSource("rde_lt", "RDE.lt", "shop", "Lithuania", "https://www.rde.lt/"),)
SOURCE_BY_KEY = {source.key: source for source in SOURCES}
MARKETPLACES = tuple(s for s in SOURCES if s.kind == "marketplace")
SHOPS = tuple(s for s in SOURCES if s.kind == "shop")


def marketplace_url(key: str, url: str) -> str:
    """Only marketplace pages, never outbound/affiliate redirect endpoints."""
    source = SOURCE_BY_KEY.get(key)
    value = str(url or "").strip()
    parsed = urlsplit(value)
    domain = urlsplit(source.base_url).hostname.removeprefix("www.") if source else ""
    path = unquote(parsed.path).lower()
    if (not source or source.kind != "marketplace" or parsed.scheme != "https"
            or parsed.hostname not in {domain, "www." + domain} or parsed.port not in (None, 443)
            or parsed.username or parsed.password
            or re.search(r"(?:^|/)(?:ex|out|go|click|redirect|redirector|shop|poodi|offer)(?:[/.]|$)", path)
            or re.search(r"(?:^|&)(?:url|redirect|target|to)=", parsed.query, re.I)):
        raise ValueError("Use an HTTPS comparison/search page on the selected marketplace, not a retailer or redirect link")
    return value


def search_url(key, model):
    url = SOURCE_BY_KEY[key].search_url(model)
    if key == "kaina24":
        url = url.replace("+", "-").lower()
    return marketplace_url(key, url)


def same_salidzini_search(first, second):
    """Allow normal www/encoding canonicalization, never a different SKU/filter/page."""
    a, b = (urlsplit(marketplace_url('salidzini', value)) for value in (first, second))
    return a.path.rstrip('/') == b.path.rstrip('/') == '/cena' and parse_qs(a.query) == parse_qs(b.query)
