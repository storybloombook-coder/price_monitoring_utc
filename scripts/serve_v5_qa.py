"""Isolated local UI fixture. Network responses are synthetic, not live prices."""
from pathlib import Path
import asyncio
import httpx
import uvicorn
from price_monitor_v5.app import create_app
from price_monitor_v5.config import Settings
from price_monitor_v5.catalog import CatalogStore

settings = Settings.load(Path("build/v5-ui-qa"))
store = CatalogStore(settings.catalog_database)
if not store.list_items("source"):
    for model in ["25G64", "75C6K"]:
        store.create_item("stock",{"nomenclature":f"TCL {model}","quantity":0,"unit_cost_eur":100})

async def handler(request):
    await asyncio.sleep(.3)
    if request.url.host != "www.hinnavaatlus.ee":
        return httpx.Response(403,text="QA challenge")
    if "75C6K" in str(request.url):
        return httpx.Response(200,text="0 toodet")
    if "/6366101/" not in request.url.path:
        return httpx.Response(200,text='<a href="/6366101/tcl-25-lcd-25g64/">TCL 25G64</a>')
    return httpx.Response(200,text='''<h1>TCL 25G64</h1><table>
        <tr class="offer"><td class="name">Elisa Eesti</td><td class="in-stock">Laos</td><td class="offer-price">199 €</td></tr>
        <tr class="offer"><td class="name">QA other seller</td><td class="in-stock">Laos</td><td class="offer-price">249 €</td></tr></table>''')

app=create_app(settings,store,httpx.MockTransport(handler))
app.state.monitor.delay=.3
uvicorn.run(app,host="127.0.0.1",port=8125)
