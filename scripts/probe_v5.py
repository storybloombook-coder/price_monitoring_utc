"""One bounded read per supplied marketplace URL; never follows retailer redirects."""
import asyncio
import json
from pathlib import Path
import sys
import httpx
from price_monitor_v5.offers import parse_page, Document
from price_monitor_v5.sources import marketplace_url


async def main():
    target = Path("build/v5-live")
    target.mkdir(parents=True,exist_ok=True)
    async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
        for key, url in [
            ("hinnavaatlus","https://www.hinnavaatlus.ee/6366101/tcl-25-lcd-25g64/"),
            ("salidzini","https://www.salidzini.lv/cena?q=TCL+25G64"),
        ]:
            try:
                response = await client.get(marketplace_url(key,url))
                response.encoding = "utf-8"
                content = response.text
                (target / f"{key}.html").write_text(content,encoding="utf-8")
                result = parse_page(key,"25G64",content,url) if response.status_code==200 else {}
                print(json.dumps({"source":key,"http":response.status_code,"result":result},ensure_ascii=True))
                if key=="hinnavaatlus":
                    root = Document(content).root
                    for node in root.nodes():
                        if node.tag=="tr" and node.has("offer"):
                            print(json.dumps({"stock_nodes":[{"class":n.attrs.get("class"),"text":n.text()} for n in node.nodes() if "stock" in str(n.attrs.get("class"))]},ensure_ascii=True))
            except Exception as e:
                print(json.dumps({"source":key,"error":str(e)}))


if __name__ == "__main__":
    asyncio.run(main())
