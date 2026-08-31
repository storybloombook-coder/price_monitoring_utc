"""Bounded Kaina24 HTML fixture download for local parser QA; no retailer visits."""
import argparse
import json
from pathlib import Path
import time
import httpx
from price_monitor_v5.offers import Document
from price_monitor_v5.sources import marketplace_url


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("urls", nargs="+")
    args = parser.parse_args()
    target = Path("build/kaina-v5-503")
    target.mkdir(parents=True, exist_ok=True)
    for index, url in enumerate(args.urls[:3]):
        url = marketplace_url("kaina24", url)
        if index:
            time.sleep(3)
        response = httpx.get(url, timeout=20, follow_redirects=False,
                            headers={"User-Agent": "PriceMonitor/0.1 (local price monitoring)"})
        print(json.dumps({"url": url, "status": response.status_code}), flush=True)
        if response.status_code != 200:
            break
        html = response.content.decode("utf-8", errors="replace")
        if any(s in html.lower() for s in ("cf-chl-", "challenge-platform", 'class="h-captcha"')):
            break
        name = "-".join(url.split("/")[3:]).strip("-").replace("?", "_")
        (target / f"{name}.html").write_text(html, encoding="utf-8")
        root = Document(html).root
        rows = [n for n in root.nodes() if n.has("seller-item-table")]
        for row in rows[:1]:
            print(json.dumps([{"tag": n.tag, "attrs": n.attrs, "text": n.text()[:180]}
                              for n in row.nodes() if n.tag in {"img", "h3"} or n.attrs.get("class")], ensure_ascii=True), flush=True)


if __name__ == "__main__":
    main()
