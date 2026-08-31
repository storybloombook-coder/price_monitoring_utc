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
    "smartech": {"SMARTECH", "SMARTECHEE"},
}


def seller_key(name, marketplace_key=None):
    token = compact(name)
    matched = next((key for key, names in ALIASES.items() if token in names), None)
    if matched and marketplace_key:
        shop = SOURCE_BY_KEY[matched]
        domain = compact(urlsplit(shop.base_url).hostname.removeprefix("www."))
        if token != domain and shop.country != SOURCE_BY_KEY[marketplace_key].country:
            return None  # Same brand in another country is not the configured shop.
    return matched


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
    if not value or not seller or (not manual and not exact_model(model, title)):
        raise ValueError("A seller, positive price and exact model evidence are required")
    state = str(raw.get("availability") or "UNKNOWN")
    if state not in {"IN_STOCK", "PRE_ORDER", "UNKNOWN", "OUT_OF_STOCK"}:
        raise ValueError("Invalid availability")
    return {"store": seller, "seller_key": seller_key(seller,key), "title": title,
            "price_eur": value, "availability": state, "marketplace_key": key,
            "url": marketplace_url(key, raw.get("url") or page_url), "manual": manual}


def parse_page(key, model, content, page_url):
    marketplace_url(key, page_url)
    doc = Document(content).root
    nodes = list(doc.nodes())
    title = next((n.text() for n in nodes if n.tag == "h1"), "")
    is_product = (key == "hinnavaatlus" and bool(re.match(r"/\d+/", urlsplit(page_url).path))) or (key == "kaina24" and "/p/" in page_url)
    product_match = is_product and exact_model(model, title)
    offers, links, rejected = [], [], 0
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
    if key in {"kaina24", "salidzini"}:
        row_classes = {"shop-row", "seller-row", "offer", "product-offer", "cena-item", "item_block"}
        for row in [n for n in nodes if any(n.has(cls) for cls in row_classes)]:
            name = row.first("product-title", "item_name", "product-name", "title")
            evidence = title if product_match else name.text() if name else ""
            seller = row.first("shop-name", "seller-name", "shop_name", "store-name", "item_shop_name")
            money = row.first("price", "item_price", "offer-price")
            if exact_model(model, evidence) and seller and money:
                offers.append({"store": seller.text(), "price_eur": price(money.text()), "title": evidence,
                               "availability": availability(row.text())})
    # Explicit capture rows produced by the bundled v5 extension.
    for script in [n for n in nodes if n.tag == "script" and n.attrs.get("id") == "price-monitor-v5-offers"]:
        try:
            offers.extend(json.loads("".join(c for c in script.children if isinstance(c, str))))
        except (ValueError, TypeError):
            rejected += 1
    for node in nodes:
        if node.tag != "a" or not node.attrs.get("href"):
            continue
        url = urljoin(page_url, node.attrs["href"])
        try:
            marketplace_url(key, url)
        except ValueError:
            continue
        path = urlsplit(url).path
        if exact_model(model, node.text()) and ((key == "hinnavaatlus" and re.match(r"/\d+/", path)) or (key == "kaina24" and path.startswith("/p/"))):
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
        if same_path and (next_page or page_number > current_page) and url not in links:
            links.append(url)
    normalized, seen = [], set()
    for raw in offers:
        try:
            offer = normalize_offer(key, model, raw, page_url)
            signature = (compact(offer["store"]), offer["price_eur"], offer["availability"], offer["url"])
            if signature not in seen:
                seen.add(signature)
                normalized.append(offer)
        except (ValueError, TypeError):
            rejected += 1
    text = doc.text().lower()
    empty = bool(re.search(r"0 toodet|tooteid ei leitud|prekių nerasta|0 rezultāti|nekas netika atrasts", text))
    # Unfamiliar markup or zero extracted offers is NOT proof of absence.
    return {"offers": normalized, "links": links, "not_found": empty and not normalized,
            "rejected": rejected, "title": title,
            "partial": bool(rejected) or bool(normalized and key != "hinnavaatlus")}
