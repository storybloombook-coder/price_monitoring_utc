"""Kaina24's legacy seller-card adapter, adapted to marketplace-only v5.

Read cash prices from their dedicated nodes, never delivery/installment text.
Comparison pages are authoritative; related-product cards are not offers.
"""
import re
from urllib.parse import urljoin, urlsplit, urldefrag, parse_qs

from .offers import compact, matched_model, normalize_offer, availability, price
from .sources import marketplace_url


def comparison_link(value, page_url):
    try:
        url = marketplace_url("kaina24", urldefrag(urljoin(page_url, value))[0])
        return url if urlsplit(url).path.startswith("/p/") else None
    except ValueError:
        return None


def seller_name(row, product):
    scope = row.first("col-1") if product else row.first("shop")
    if scope:
        for node in scope.nodes():
            if node.tag == "img" and node.attrs.get("alt"):
                return node.attrs["alt"].strip()
            if node.tag == "a" and node.attrs.get("title"):
                return node.attrs["title"].strip()
        if scope.text():
            return scope.text()
    return next((n.text() for n in row.nodes() if n.attrs.get("itemprop") == "seller"), "")


def cash_price(row, seller=""):
    money = row.first("price")
    if not money:
        return None
    text = " ".join(row.text().split())
    value = " ".join(money.text().split())
    # Kaina sometimes advertises a club price with the ordinary price in a note.
    conditional = (re.search(r"klubo nariams|lojalumo|su kortele", text, re.I)
                   or ("*" in value and re.search(r"su kodu|kupon", text, re.I)))
    senukai_card = compact(seller) in {"SENUKAI", "SENUKAILT"} and bool(re.search(r"smart\s*net|lojalumo|su kortele", text, re.I))
    if conditional and not senukai_card:
        ordinary = re.search(r"ne lojalumo programos nariams taikoma kaina\s*([\d\s.,]+)\s*(?:€|EUR)", text, re.I)
        return price(ordinary[1]) if ordinary else None
    # Reject multiple prices or financing text inside a changed price node.
    if not re.fullmatch(r"[\d\s.,]+\s*(?:€|EUR)?\s*\*?", value, re.I):
        return None
    return price(value)


def stock_state(row):
    status = row.first("status-block", "availability")
    explicit = availability(status.text()) if status else "UNKNOWN"
    if explicit != "UNKNOWN":
        return explicit
    states = set()
    mapping = {"instock": "IN_STOCK", "outofstock": "OUT_OF_STOCK",
               "soldout": "OUT_OF_STOCK", "discontinued": "OUT_OF_STOCK",
               "preorder": "PRE_ORDER", "presale": "PRE_ORDER"}
    # Scope strictly to this seller row, not the page's aggregate InStock tag.
    for node in row.nodes():
        if node.attrs.get("itemprop") == "availability":
            value = node.attrs.get("href") or node.attrs.get("content") or node.text()
            state = mapping.get(value.rstrip("/").rsplit("/", 1)[-1].lower())
            if state:
                states.add(state)
    return next(iter(states)) if len(states) == 1 else "UNKNOWN"


def parse_kaina(model, root, page_url):
    """Return None for unfamiliar markup, retaining the conservative fallback."""
    nodes = list(root.nodes())
    product = urlsplit(page_url).path.startswith("/p/")
    title = next((n.text() for n in nodes if n.tag == "h1"), "")
    rows = [n for n in nodes if n.has("seller-item-table" if product else "product-item-h-wrap")]
    if not rows:
        return None
    if product and not matched_model("kaina24", model, title):
        return dict(offers=[], links=[], not_found=False, rejected=0, title=title, partial=True)

    offers, links, rejected = [], [], 0
    for row in rows:
        # The collapsed "sold out" history uses the same table class. Those
        # archived prices are not current seller offers (and not in offerCount).
        if product and row.parent and row.parent.has("disabled-item"):
            continue
        name = row.first("name")
        if not name:
            rejected += 1
            continue
        evidence = name.text()
        if not matched_model("kaina24", model, evidence):
            continue
        target = page_url
        if not product:
            compare = next((comparison_link(n.attrs.get("href", ""), page_url)
                            for n in row.nodes() if n.tag == "a" and n.has("product-item__compare")), None)
            if compare:
                target = compare
                if compare not in links:
                    links.append(compare)
        try:
            seller = seller_name(row, product)
            loyalty = compact(seller) in {"SENUKAI", "SENUKAILT"} and bool(re.search(r"smart\s*net|lojalumo|su kortele", row.text(), re.I))
            offers.append(normalize_offer("kaina24", model, {
                "store": seller, "price_eur": cash_price(row, seller),
                "price_basis": "loyalty" if loyalty else "regular",
                "title": evidence, "availability": stock_state(row), "url": target,
            }, page_url))
        except (ValueError, TypeError):
            rejected += 1

    for node in nodes:
        if node.tag != "a" or not node.attrs.get("href"):
            continue
        # Search summaries may link to a complete comparison even with no seller
        # card. Never follow recommendations from an already matched product page.
        if not product and matched_model("kaina24", model, node.text() + " " + (node.attrs.get("title") or "")):
            compare = comparison_link(node.attrs["href"], page_url)
            if compare and compare not in links:
                links.append(compare)
        try:
            url = marketplace_url("kaina24", urldefrag(urljoin(page_url, node.attrs["href"]))[0])
        except ValueError:
            continue
        if urlsplit(url).path.rstrip("/") != urlsplit(page_url).path.rstrip("/"):
            continue
        try:
            following = int(parse_qs(urlsplit(url).query).get("page", ["0"])[0])
            current = int(parse_qs(urlsplit(page_url).query).get("page", ["1"])[0])
        except ValueError:
            continue
        if (following > current or "next" in (node.attrs.get("rel") or "").split()) and url != page_url and url not in links:
            links.append(url)

    unique = {(compact(o["store"]), o["price_eur"], o["availability"], o["url"]): o for o in offers}
    offers = list(unique.values())
    known = {(compact(o["store"]), o["price_eur"], o["url"]) for o in offers if o["availability"] != "UNKNOWN"}
    # Featured placements repeat the ordinary seller row without stock metadata.
    offers = [o for o in offers if o["availability"] != "UNKNOWN" or
              (compact(o["store"]), o["price_eur"], o["url"]) not in known]
    # A seller count greater than the extracted rows signals missing/lazy offers.
    counts = [n for n in nodes if n.attrs.get("itemprop") == "offerCount"] if product else []
    expected = next((int(value) for n in counts if (value := n.attrs.get("content") or n.text()).strip().isdigit()), 0)
    partial = bool(rejected or (expected > len(offers) and not links))
    return dict(offers=offers, links=links, not_found=not product and not offers and not links and not rejected, rejected=rejected,
                title=title, partial=partial,
                expected_offer_count=expected,
                coverage_url=urlsplit(page_url)._replace(query="", fragment="").geturl() if product else None,
                authoritative_url=page_url if product and offers and not rejected else None)
