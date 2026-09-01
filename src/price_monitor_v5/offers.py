"""Evidence-based marketplace parsing. No retailer fetches or price guessing."""
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, unquote, parse_qs
import json
import math
import re
import unicodedata
from .sources import marketplace_url, SHOPS, SOURCE_BY_KEY


def compact(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def exact_model(model, text):
    if re.search(r"\b(remote control|replacement remote|wall mount|nuotolinio valdymo pult|kaugjuhtimispult)\b", str(text), re.I):
        return False
    tokens = re.findall(r"[A-Z0-9]+", unquote(str(text or "")).upper())
    expected = compact(re.sub(r"^TCL[\s_-]*", "", str(model), flags=re.I))
    for i in range(len(tokens)):
        for width in range(1, 4):
            if "".join(tokens[i:i+width]) == expected:
                following = tokens[i+width:i+width+1]
                if following and following[0] in {"PRO", "PLUS", "MAX"} and not expected.endswith(following[0]):
                    continue
                return True
    return False


ALIASES = {
    "senukai": {"SENUKAI", "SENUKAILT"}, "bite": {"BITE", "BITELT"},
    "varle": {"VARLE", "VARLELT"}, "elesen": {"ELESEN", "ELESENLT"},
    "elisa": {"ELISA", "ELISAEE", "ELISAEESTI"},
    "euronics": {"EURONICS", "EURONICSEE", "EURONICSEESTI"},
    "rde": {"RDE", "RDEEE", "RDEELECTRONICS", "RDELECTRONICS", "RDELECTRONICSLEE"},
    "rde_lt": {"RDELT"},
    "smartech": {"SMARTECH", "SMARTECHEE", "SMARTECHSHOP"},
}


def seller_key(name, marketplace_key=None):
    token = compact(name)
    if token == "RDE" and marketplace_key == "kaina24":
        return "rde_lt"
    matched = next((key for key, names in ALIASES.items() if token in names), None)
    if matched and marketplace_key:
        shop = SOURCE_BY_KEY[matched]
        domain = compact(urlsplit(shop.base_url).hostname.removeprefix("www."))
        if token != domain and shop.country != SOURCE_BY_KEY[marketplace_key].country:
            return None  # Same brand in another country is not the configured shop.
    return matched


# Explicit regional names, not a general suffix-stripping match rule. TCL's
# Italian pages use HE headings and H identifiers for these two soundbars:
# https://www.tcl.com/it/it/soundbar/s55h
# https://www.tcl.com/it/it/support-soundbar/model/s45h
MODEL_ALIASES = {"S45HE": "S45H", "S55HE": "S55H"}


def matched_model(key, model, text):
    if exact_model(model, text):
        return model
    alias = MODEL_ALIASES.get(compact(re.sub(r"^TCL[\s_-]*", "", model, flags=re.I)))
    return alias if alias and exact_model(alias, text) else None


def shortened_queries(model):
    original = re.sub(r"^TCL[\s_-]*", "", model.strip(), flags=re.I)
    return [value for width in (1, 2) if len(value := original[:-width].strip()) >= 3
            and re.search(r"[A-Za-z]", value) and re.search(r"\d", value)]


LEGACY_OFFER_CLASSES = {"shop-row", "seller-row", "offer", "product-offer", "cena-item", "item_block"}


def salidzini_cards(root):
    nodes = list(root.nodes())
    # Current DOM has two nested containers: parse each card exactly once.
    return ([n for n in nodes if n.has('item_box_main')] or
            [n for n in nodes if n.has('item_box_sub')] or
            [n for n in nodes if any(n.has(c) for c in LEGACY_OFFER_CLASSES)])


def salidzini_card_kind(row, page_url):
    if not (row.has('item_box_main') or row.has('item_box_sub')):
        return 'offer'  # Legacy snapshots remain readable.
    link = row.first('item_link')
    target = urlsplit(urljoin(page_url, link.attrs.get('href', '') if link else ''))
    if target.hostname in {'geedo.lv', 'www.geedo.lv'}:
        return 'recommendation'
    # Inspect the redirect address as evidence only; never fetch/follow it.
    if (link and link.tag == 'a' and target.scheme == 'https' and
            target.hostname in {'salidzini.lv', 'www.salidzini.lv'} and
            target.port in (None, 443) and not target.username and not target.password and
            target.path == '/click.php' and
            re.fullmatch(r'\d+', parse_qs(target.query).get('itemid', [''])[0])):
        return 'offer'
    return 'unknown'


def salidzini_availability(row):
    # Tooltip text is the actual stock evidence; delivery days/cost are not stock.
    titles = ' '.join(n.attrs.get('title', '') for n in row.nodes())
    count = re.search(r'noliktavā\s*:\s*(\d+)(?:\+)?\b', titles, re.I)
    if count:
        return 'IN_STOCK' if int(count[1]) > 0 else 'OUT_OF_STOCK'
    return availability(row.text() + ' ' + titles)


def candidate_links(query, content, page_url, key="hinnavaatlus"):
    """Suggestions only: truncated model prefixes never authorize a price."""
    matches, seen = [], set()
    root = Document(content).root
    if key == "hinnavaatlus":
        entries = [(n, n) for n in root.nodes() if n.tag == "a" and n.has("product-name")]
    else:
        classes = {"product-item-h-wrap"} if key == "kaina24" else LEGACY_OFFER_CLASSES
        rows = ([n for n in salidzini_cards(root) if salidzini_card_kind(n, page_url) == 'offer']
                if key == 'salidzini' else [n for n in root.nodes() if any(n.has(cls) for cls in classes)])
        entries = [(n.first("name" if key == "kaina24" else "product-title", "item_name", "product-name", "title"), n)
                   for n in rows]
    for node, scope in entries:
        if not node:
            continue
        if not any(token.startswith(compact(query)) for token in re.findall(r"[A-Z0-9]+", node.text().upper())):
            continue
        url = None
        for anchor in scope.nodes():
            if anchor.tag != "a" or not anchor.attrs.get("href"):
                continue
            try:
                target = marketplace_url(key, urljoin(page_url, anchor.attrs["href"]))
            except ValueError:
                continue
            path = urlsplit(target).path
            if ((key == "hinnavaatlus" and re.match(r"/\d+/", path)) or
                    (key == "kaina24" and path.startswith("/p/")) or
                    (key == "salidzini" and anchor in list(node.nodes()))):
                url = target
                break
        # Search cards can point only to a retailer. Keep the marketplace search
        # as the evidence link; never follow an outbound redirect for a candidate.
        url = url or (marketplace_url(key, page_url) if key != "hinnavaatlus" else None)
        signature = (node.text(), url)
        if url and signature not in seen:
            seen.add(signature)
            matches.append({"title": node.text()[:600], "url": url, "query": query})
    return matches[:20]


def price(value):
    clean = re.sub(r"[^\d,.]", "", str(value or ""))
    if "," in clean and "." in clean:
        decimal = "," if clean.rfind(",") > clean.rfind(".") else "."
        clean = clean.replace("." if decimal == "," else ",", "").replace(",", ".")
    else:
        clean = clean.replace(",", ".")
    try:
        result = float(clean)
        return round(result, 2) if math.isfinite(result) and 0 < result < 1_000_000 else None
    except ValueError:
        return None


def availability(text):
    s = str(text).lower()
    if re.search(r"out.?of.?stock|išparduota|pole saadaval|nav pieejams|otsas", s):
        return "OUT_OF_STOCK"
    if re.search(r"pre.?order|išankst|ettetell|priekšpasūt", s):
        return "PRE_ORDER"
    if re.search(r"in.?stock|laos\b|turime|yra sandėlyje|ir noliktavā|on-site", s):
        return "IN_STOCK"
    return "UNKNOWN"


class Node:
    def __init__(self, tag="root", attrs=(), parent=None):
        self.tag, self.attrs, self.parent = tag, dict(attrs), parent
        self.children = []

    def nodes(self):
        yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.nodes()

    def text(self):
        if self.tag in {"script", "style", "svg"}:
            return ""
        return " ".join(c.text() if isinstance(c, Node) else c for c in self.children).strip()

    def has(self, cls):
        return cls in (self.attrs.get("class") or "").split()

    def first(self, *classes):
        return next((n for n in self.nodes() if any(n.has(c) for c in classes)), None)


class Document(HTMLParser):
    def __init__(self, content):
        super().__init__(convert_charrefs=True)
        self.root = self.current = Node()
        self.feed(content)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs, self.current)
        self.current.children.append(node)
        if tag not in {"img", "input", "meta", "link", "br", "hr", "source", "wbr", "area", "base", "embed"}:
            self.current = node

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        node = self.current
        while node.parent:
            if node.tag == tag:
                self.current = node.parent
                return
            node = node.parent

    def handle_data(self, data):
        self.current.children.append(data)


def normalize_offer(key, model, raw, page_url, *, manual=False):
    value = price(raw.get("price_eur"))
    seller = str(raw.get("store") or raw.get("seller_name") or "").strip()[:120]
    title = str(raw.get("title") or model).strip()[:600]
    match = matched_model(key, model, title)
    if not value or not seller or (not manual and not match):
        raise ValueError("A seller, positive price and exact model evidence are required")
    state = str(raw.get("availability") or "UNKNOWN")
    if state not in {"IN_STOCK", "PRE_ORDER", "UNKNOWN", "OUT_OF_STOCK"}:
        raise ValueError("Invalid availability")
    evidence = {"matched_model": match} if match and compact(match) != compact(model) else {}
    basis = raw.get("price_basis")
    if basis in {"loyalty", "regular"}:
        evidence["price_basis"] = basis
    return {**evidence, "store": seller, "seller_key": seller_key(seller,key), "title": title,
            "price_eur": value, "availability": state, "marketplace_key": key,
            "url": marketplace_url(key, raw.get("url") or page_url), "manual": manual}


def parse_page(key, model, content, page_url):
    marketplace_url(key, page_url)
    doc = Document(content).root
    if key == "kaina24":
        from .kaina24 import parse_kaina
        parsed = parse_kaina(model, doc, page_url)
        if parsed is not None:
            return parsed
    nodes = list(doc.nodes())
    title = next((n.text() for n in nodes if n.tag == "h1"), "")
    is_product = (key == "hinnavaatlus" and bool(re.match(r"/\d+/", urlsplit(page_url).path))) or (key == "kaina24" and "/p/" in page_url)
    product_match = is_product and bool(matched_model(key, model, title))
    offers, links, rejected, ambiguous = [], [], 0, 0
    salidzini_ids = set()
    salidzini_seen_ids = set()
    heading = next((n for n in nodes if n.tag == 'h1'), None)
    count_match = re.search(r'\b(\d+)\s+preces?\b', heading.parent.text(), re.I) if key == 'salidzini' and heading else None
    salidzini_expected = int(count_match[1]) if count_match else None
    if key == "hinnavaatlus":
        rows = [n for n in nodes if n.tag == "tr" and n.has("offer")]
        for row in rows if product_match else []:
            seller, money = row.first("name"), row.first("offer-price")
            stock = row.first("in-stock", "stock", "availability")
            if seller and money:
                offers.append({"store": seller.text(), "price_eur": price(money.text()),
                               "title": title, "availability": availability((stock.text() + " " + str(stock.attrs)) if stock else "")})
            else:
                rejected += 1
    # Kaina24/Salidzini expose seller rows in server HTML or in a rendered capture.
    known_search_rows = False
    if key in {"kaina24", "salidzini"}:
        rows = (salidzini_cards(doc) if key == 'salidzini' else
                [n for n in nodes if any(n.has(cls) for cls in LEGACY_OFFER_CLASSES)])
        for row in rows:
            if key == 'salidzini':
                kind = salidzini_card_kind(row, page_url)
                if kind != 'offer':
                    rejected += int(kind == 'unknown')
                    continue
                if row.has('item_box_main') or row.has('item_box_sub'):
                    salidzini_seen_ids.add(parse_qs(urlsplit(row.first('item_link').attrs['href']).query)['itemid'][0])
            name = row.first("product-title", "item_name", "product-name", "title")
            evidence = title if product_match else name.text() if name else ""
            known_search_rows |= bool(evidence)
            seller = row.first("shop-name", "seller-name", "shop_name", "store-name", "item_shop_name")
            money = row.first("price", "item_price", "offer-price")
            if matched_model(key, model, evidence):
                if seller and money:
                    cash = money.text()
                    # A cash offer may explicitly state Latvian zero-rate VAT
                    # after the price. Keep rejecting delivery, installments or
                    # any second amount, but do not discard "111,83 € PVN 0%".
                    if key == 'salidzini' and not re.fullmatch(r'\s*(?:€|EUR)?\s*\d+(?:[ .]\d{3})*(?:[.,]\d{1,2})?\s*(?:€|EUR)?(?:\s*PVN\s*0\s*%)?\s*', cash, re.I):
                        rejected += 1
                        # This is an exact SKU with an unreadable price, not an
                        # unrelated listing. It must remain reviewable.
                        ambiguous += 1
                        continue
                    raw = {"store": seller.text(), "price_eur": price(cash), "title": evidence,
                           "availability": salidzini_availability(row) if key == 'salidzini' else availability(row.text())}
                    if key == 'salidzini' and (link := row.first('item_link')):
                        raw['listing_id'] = parse_qs(urlsplit(link.attrs.get('href', '')).query).get('itemid', [None])[0]
                    offers.append(raw)
                else:
                    rejected += 1
                    ambiguous += 1
    # Explicit capture rows produced by the bundled v5 extension.
    for script in [n for n in nodes if n.tag == "script" and n.attrs.get("id") == "price-monitor-v5-offers"]:
        try:
            offers.extend(json.loads("".join(c for c in script.children if isinstance(c, str))))
        except (ValueError, TypeError):
            rejected += 1
            # Raw offers get here only after their card passed the SKU check.
            # Missing seller/price data is therefore incomplete evidence.
            ambiguous += 1
    for node in nodes:
        if node.tag != "a" or not node.attrs.get("href"):
            continue
        url = urljoin(page_url, node.attrs["href"])
        try:
            marketplace_url(key, url)
        except ValueError:
            continue
        path = urlsplit(url).path
        if matched_model(key, model, node.text()) and ((key == "hinnavaatlus" and re.match(r"/\d+/", path)) or (key == "kaina24" and path.startswith("/p/"))):
            if url not in links and url != page_url:
                links.append(url)
        # Follow pagination on the same comparison/search page, not categories,
        # advertisements or outbound offer tracking links.
        same_path = path.rstrip("/") == urlsplit(page_url).path.rstrip("/")
        next_page = "next" in (node.attrs.get("rel") or "").split()
        try:
            page_number = int(parse_qs(urlsplit(url).query).get("page",["0"])[0])
            current_page = int(parse_qs(urlsplit(page_url).query).get("page",["1"])[0])
        except ValueError:
            page_number = current_page = 0
        if key != 'salidzini' and same_path and (next_page or page_number > current_page) and url not in links:
            links.append(url)
        if key == "salidzini" and same_path:
            for parameter, default in [('offset', '0'), ('page', '1')]:
                following, current = parse_qs(urlsplit(url).query), parse_qs(urlsplit(page_url).query)
                try:
                    next_index, current_index = int(following.pop(parameter, [default])[0]), int(current.pop(parameter, [default])[0])
                except ValueError:
                    continue
                # Keep SKU and every filter unchanged, including on rel=next.
                if following == current and next_index > current_index and url not in links:
                    links.append(url)
    normalized, seen = [], set()
    for raw in offers:
        try:
            offer = normalize_offer(key, model, raw, page_url)
            if key == 'salidzini' and re.fullmatch(r'\d+', str(raw.get('listing_id') or '')):
                salidzini_ids.add(raw['listing_id'])
            signature = (compact(offer["store"]), offer["price_eur"], offer["availability"], offer["url"])
            if signature not in seen:
                seen.add(signature)
                normalized.append(offer)
        except (ValueError, TypeError):
            rejected += 1
    text = " ".join(doc.text().lower().split())
    empty = bool(re.search(r"0 toodet|tooteid ei leitud|prekių nerasta|pagal įvestą paieškos frazę nieko neradome|0 rezultāti|nekas netika atrasts|preces? nav atrastas?|nav atrasta neviena prece|meklēšanas rezultāti nav atrasti|nav meklēšanas rezultātu|0 rezultāti", text))
    empty |= key == 'salidzini' and salidzini_expected == 0
    # Recognized result cards for other models allow a shorter query. Broken
    # rows, unknown markup or incomplete pages must still go to manual review.
    if not is_product and known_search_rows and not normalized and not links and not rejected:
        empty = True
    if key == "hinnavaatlus" and urlsplit(page_url).path.rstrip("/") == "/search":
        known_results = title.lower().startswith("otsing:") and any(n.has("product-name") for n in nodes)
        empty |= known_results and not any(re.match(r"/\d+/", urlsplit(u).path) for u in links)
    # Unfamiliar markup or zero extracted offers is NOT proof of absence.
    return {"offers": normalized, "links": links, "not_found": empty and not normalized,
            "rejected": rejected, "ambiguous": ambiguous, "title": title,
            "salidzini_expected_count": salidzini_expected, "salidzini_offer_ids": sorted(salidzini_ids),
            "salidzini_seen_ids": sorted(salidzini_seen_ids),
            # Rejected cards are an intentional exact-SKU safeguard. Their
            # presence must not by itself turn a fully inspected page into a
            # manual-review result.
            "partial": bool(ambiguous or (normalized and key != "hinnavaatlus" and not (key == 'salidzini' and salidzini_expected is not None)))}
