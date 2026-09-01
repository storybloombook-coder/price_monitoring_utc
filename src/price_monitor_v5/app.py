import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from fastapi import FastAPI, Body, File, UploadFile, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from . import __version__
from .config import Settings
from .catalog import CatalogStore, utc_now
from .browser_bridge import BrowserBridge, EXTENSION_ORIGIN
from .monitor import MarketplaceMonitor
from .sources import marketplace_url
from .exporter import write_monitoring_export
from .page_capture import register_page_capture


def create_app(settings=None, store=None, transport=None):
    settings = settings or Settings.load()
    catalog = store or CatalogStore(settings.catalog_database)
    bridge = BrowserBridge(timeout_seconds=75)
    monitor = MarketplaceMonitor(catalog,bridge,transport=transport)
    start_lock = asyncio.Lock()

    @asynccontextmanager
    async def lifespan(app):
        # Recover interrupted checks explicitly, never silently resume old traffic.
        with catalog.connect() as db:
            pending = db.execute("SELECT DISTINCT run_id FROM marketplace_checks WHERE status IN ('PENDING','RUNNING')").fetchall()
        for row in pending:
            await monitor.stop_run(row[0])
            catalog.stop_monitoring_session(row[0])
        yield
        await monitor.close()
        bridge.stop()

    app = FastAPI(title="Price Monitor v5",version=__version__,lifespan=lifespan)
    app.add_middleware(CORSMiddleware,allow_origins=[EXTENSION_ORIGIN],allow_methods=["GET","POST","OPTIONS"],allow_headers=["content-type"])
    app.state.catalog, app.state.monitor, app.state.browser_bridge = catalog, monitor, bridge
    register_page_capture(app, catalog, monitor, start_lock)

    @app.middleware("http")
    async def local_writes(request: Request, call_next):
        origin = request.headers.get("origin")
        if request.method not in {"GET","HEAD","OPTIONS"} and origin:
            own = {str(request.base_url).rstrip("/"),EXTENSION_ORIGIN}
            if origin not in own:
                return JSONResponse({"detail":"Foreign-origin writes are not allowed"},status_code=403)
        return await call_next(request)

    @app.exception_handler(KeyError)
    async def missing(request,error):
        return JSONResponse({"detail":str(error)},status_code=404)

    @app.exception_handler(ValueError)
    async def invalid(request,error):
        return JSONResponse({"detail":str(error)},status_code=400)

    @app.get("/")
    async def index():
        return FileResponse(Path(__file__).parent / "static/index.html",headers={"Cache-Control":"no-store"})

    @app.get("/assets/{filename}")
    async def asset(filename: str):
        if Path(filename).name != filename or Path(filename).suffix not in {".js",".css",".svg"}:
            raise HTTPException(404)
        return FileResponse(Path(__file__).parent / "static" / filename)

    @app.get("/health")
    async def health():
        return {"status":"ok","application":"Price Monitor v5","version":__version__,"legacy_service":"disabled · marketplace-only v5",
                "browser_bridge":bridge.status(),"polite_monitoring":{"delay_seconds":[3,3],
                    "salidzini_browser_delay_seconds":monitor.salidzini_delay,
                    "salidzini_page_timeout_seconds":30,"salidzini_circuit_breaker_failures":2,
                    "cache_ttl_seconds":14400,"negative_cache_ttl_seconds":0,
                    "cooldown_seconds":600,"browser_concurrency":1}}

    @app.get("/browser-bridge/status")
    async def bridge_status():
        with catalog.connect() as db:
            revision = db.execute('SELECT COUNT(*) FROM v5_capture_receipts').fetchone()[0]
        return {**bridge.status(), 'capture_revision': revision}

    def extension(request):
        if request.headers.get("origin") != EXTENSION_ORIGIN:
            raise HTTPException(403,"Bundled extension only")

    @app.post("/browser-bridge/heartbeat")
    async def heartbeat(request: Request, auto_salidzini: bool=False, open_collect: bool=False):
        extension(request)
        bridge.heartbeat(auto_salidzini, open_collect)
        return bridge.status()

    @app.get("/browser-bridge/jobs/next")
    async def next_job(request: Request, wait_seconds: float=25):
        extension(request)
        job = await bridge.next_job(wait_seconds)
        return JSONResponse(job) if job else Response(status_code=204)

    def submit(job_id, payload):
        if len(str(payload.get("html", ""))) > 8_000_000:
            raise ValueError("Captured page exceeds 8 MB")
        return bridge.submit(job_id,payload)

    @app.post("/browser-bridge/jobs/{job_id}/result")
    async def result(job_id: str, request: Request, payload: dict=Body(...)):
        extension(request)
        if not submit(job_id,payload):
            raise HTTPException(404,"Job already completed or stopped")
        return {"accepted":True}

    @app.get('/browser-bridge/verifications/{token}')
    async def verification_result(token: str, request: Request):
        extension(request)
        return bridge.verification(token)

    @app.websocket("/browser-bridge/ws")
    async def socket(ws: WebSocket):
        if ws.headers.get("origin") != EXTENSION_ORIGIN:
            await ws.close(code=1008)
            return
        await ws.accept()
        bridge.heartbeat(ws.query_params.get('auto_salidzini') == '1', ws.query_params.get('open_collect') == '1')
        bridge.websocket_connected()
        receiver = asyncio.create_task(ws.receive_json())
        sender = asyncio.create_task(bridge.next_job(25))
        try:
            await ws.send_json({"type":"ready","status":bridge.status()})
            while True:
                done,_ = await asyncio.wait({receiver,sender},timeout=20,return_when=asyncio.FIRST_COMPLETED)
                if not done:
                    await ws.send_json({"type":"ping"})
                if receiver in done:
                    message = receiver.result()
                    bridge.heartbeat()
                    if message.get("type") == "result":
                        submit(str(message.get("job_id")),message.get("payload") or {})
                    else:
                        await ws.send_json({"type":"ack"})
                    receiver = asyncio.create_task(ws.receive_json())
                if sender in done:
                    job = sender.result()
                    if job:
                        await ws.send_json({"type":"job","job":job})
                    sender = asyncio.create_task(bridge.next_job(25))
        except (WebSocketDisconnect,RuntimeError,ValueError):
            pass
        finally:
            receiver.cancel(); sender.cancel()
            await asyncio.gather(receiver,sender,return_exceptions=True)
            bridge.websocket_disconnected()

    @app.get("/sources")
    async def sources():
        return catalog.list_sources()

    @app.get('/salidzini/settings')
    async def salidzini_settings():
        return {'mode': catalog.salidzini_mode()}

    @app.post('/salidzini/settings')
    async def update_salidzini_settings(payload: dict=Body(...)):
        async with start_lock:
            if any(ident[2] == 'salidzini' for ident in monitor.jobs):
                raise HTTPException(409, 'Stop the active Salidzini checks before changing mode')
            catalog.set_salidzini_mode(payload.get('mode'))
        return {'mode': catalog.salidzini_mode()}

    @app.patch("/sources/master/{kind}")
    async def master(kind: str,payload: dict=Body(...)):
        return catalog.update_source_master(kind,bool(payload.get("enabled")))

    @app.patch("/sources/{key}")
    async def source(key: str,payload: dict=Body(...)):
        if "collection_method" in payload:
            raise ValueError("v5 collects only marketplace pages; shop method selection is disabled")
        return catalog.update_source(key,bool(payload.get("enabled")))

    @app.get("/catalog/summary")
    async def summary():
        return catalog.stats()

    @app.get("/catalog/items")
    async def items(kind: str,scope: str="active",q: str=""):
        return catalog.list_items(kind,scope,q)

    @app.post("/catalog/items/{kind}",status_code=201)
    async def create(kind: str,payload: dict=Body(...)):
        return catalog.create_item(kind,payload)

    @app.post("/catalog/clear/{kind}")
    async def clear_catalog(kind: str,payload: dict=Body(...)):
        if payload.get("confirm") is not True:
            raise ValueError("Confirm moving all rows in this table to Trash")
        async with start_lock:
            if monitor.jobs:
                raise HTTPException(409,"Stop the current checks before clearing a catalog table")
            return catalog.clear_catalog(kind)

    @app.patch("/catalog/items/{item_id}")
    async def update(item_id: int,payload: dict=Body(...)):
        return catalog.update_item(item_id,payload)

    @app.delete("/catalog/items/{item_id}")
    async def trash(item_id: int):
        return catalog.trash_item(item_id)

    @app.post("/catalog/items/{item_id}/restore")
    async def restore(item_id: int):
        return catalog.restore_item(item_id)

    @app.post("/catalog/items/{item_id}/monitor")
    async def promote(item_id: int):
        return catalog.promote_stock_item(item_id)

    @app.delete("/catalog/items/{item_id}/permanent",status_code=204)
    async def permanent(item_id: int):
        catalog.delete_item_permanently(item_id)
        return Response(status_code=204)

    @app.get("/workbook")
    async def workbook():
        values = catalog.list_items("source")
        return {"models_found":len(values),"source_workbook":"v5 catalog · stock auto-enrolled"}

    @app.get("/stock")
    async def stock():
        values = catalog.list_items("stock")
        return {"count":len(values),"matched":sum(i["matched"] for i in values)}

    async def upload(file,kind):
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in {".xlsx",".xlsm"}:
            raise ValueError("Only XLSX and XLSM are supported")
        data = await file.read(20_000_001)
        if len(data)>20_000_000:
            raise ValueError("Workbook exceeds 20 MB")
        settings.uploads_dir.mkdir(parents=True,exist_ok=True)
        path = settings.uploads_dir / f"{kind}-{uuid.uuid4()}{suffix}"
        path.write_bytes(data)
        method = catalog.import_source_workbook if kind=="source" else catalog.import_stock_workbook
        return await asyncio.to_thread(method,path,file.filename)

    @app.post("/stock/upload")
    async def upload_stock(file: UploadFile=File(...)):
        return await upload(file,"stock")

    @app.post("/workbook/upload")
    async def upload_models(file: UploadFile=File(...)):
        return await upload(file,"source")

    @app.get("/examples/{kind}")
    async def example(kind: str):
        if kind not in {"workbook","stock"}:
            raise HTTPException(404)
        return FileResponse(Path(__file__).parent / "static/examples" / f"example-{kind}.xlsx")

    @app.post("/runs")
    async def start(payload: dict=Body(default={})):
        async with start_lock:
            if monitor.jobs:
                raise HTTPException(409,"Stop the active run first")
            run_id = f"v5-{uuid.uuid4()}"
            await asyncio.to_thread(catalog.begin_run,run_id,str(payload.get("mode") or "balanced"))
            monitor.launch(run_id)
        return {"run_id":run_id,"status":"RUNNING"}

    def run_payload(run_id: str):
        result = catalog.run(run_id)
        result.setdefault("execution", {})["current_activity"] = monitor.activity(run_id)
        result["execution"]["queue_progress"] = monitor.progress(run_id)
        return result

    @app.get("/runs/latest")
    async def latest():
        session = catalog.latest_monitoring_session()
        if not session:
            raise HTTPException(404,"No runs yet")
        return run_payload(session["run_id"])

    @app.get("/monitoring-history")
    async def history(limit: int=20):
        return catalog.list_monitoring_sessions(limit)

    @app.get("/runs/{run_id}")
    async def run(run_id: str):
        return run_payload(run_id)

    @app.post("/runs/{run_id}/stop")
    async def stop(run_id: str):
        await monitor.stop_run(run_id)
        catalog.stop_monitoring_session(run_id)
        return catalog.run(run_id)

    @app.post("/runs/{run_id}/clear")
    async def clear(run_id: str):
        await stop(run_id)
        catalog.clear_monitoring_session(run_id)
        return catalog.run(run_id)

    @app.post("/runs/{run_id}/marketplaces/{item_id}/{key}/retry")
    async def retry(run_id: str,item_id: int,key: str):
        task = catalog.check(run_id,item_id,key)
        catalog.resume_monitoring_session(run_id)
        monitor.begin_batch(run_id,[task],f"Retry {task['source_model']}")
        await monitor.retry(run_id,item_id,key,capture=bridge.connected)
        return {"status":"PENDING"}

    @app.post('/runs/{run_id}/marketplaces/{item_id}/{key}/open-collect')
    async def open_collect(run_id: str, item_id: int, key: str):
        async with start_lock:
            task = catalog.check(run_id,item_id,key)
            catalog.resume_monitoring_session(run_id)
            monitor.begin_batch(run_id,[task],f"Open & collect {task['source_model']}")
            token = await monitor.retry(run_id,item_id,key,open_collect=True)
        return {'status':'PENDING', 'verification_id':token}

    @app.post("/runs/{run_id}/marketplaces/{item_id}/{key}/link")
    async def link(run_id: str,item_id: int,key: str,payload: dict=Body(...)):
        task = catalog.check(run_id,item_id,key)
        catalog.resume_monitoring_session(run_id)
        monitor.begin_batch(run_id,[task],f"Parse link for {task['source_model']}")
        await monitor.retry(run_id,item_id,key,url=marketplace_url(key,payload.get("url")),capture=bridge.connected)
        return {"status":"PENDING"}

    @app.post("/runs/{run_id}/marketplaces/{item_id}/{key}/resolve")
    async def resolve(run_id: str,item_id: int,key: str,payload: dict=Body(...)):
        return await monitor.resolve(run_id,item_id,key,payload)

    @app.delete("/runs/{run_id}/marketplaces/{item_id}/{key}/offers/{index}")
    async def remove_offer(run_id: str,item_id: int,key: str,index: int):
        task = catalog.check(run_id,item_id,key)
        if not 0 <= index < len(task.get("offers",[])):
            raise HTTPException(404,"Offer not found")
        await monitor.cancel_pair(run_id,item_id,key)
        removed = task["offers"].pop(index)
        catalog.record_decision(task,{"status":"REMOVED","removed_offer":removed})
        task.update(status="SUCCESS" if task["offers"] else "ACTION_REQUIRED",collection_method="manual",coverage="partial",finished_at=utc_now())
        catalog.save_check(task)
        return task

    @app.post("/runs/{run_id}/models/{item_id}/retry")
    async def retry_model(run_id: str,item_id: int):
        enabled = {s["key"] for s in catalog.list_sources() if s["effective_enabled"]}
        tasks = [task for task in catalog.checks(run_id)
                 if task["item_id"]==item_id and task["marketplace_key"] in enabled]
        if tasks:
            catalog.resume_monitoring_session(run_id)
            monitor.begin_batch(run_id,tasks,f"Retry model {tasks[0]['source_model']}")
        count = 0
        for task in tasks:
            await monitor.retry(run_id,item_id,task["marketplace_key"],capture=False)
            count += 1
        return {"checks_started":count,"status":"PENDING"}

    @app.post("/runs/{run_id}/retry-unresolved")
    async def retry_unresolved(run_id: str, payload: dict=Body(default={})):
        include_not_found = bool(payload.get("include_not_found"))
        source_key = str(payload.get("marketplace_key") or "all")
        if source_key not in {"all", "kaina24", "salidzini", "hinnavaatlus"}:
            raise ValueError("Choose a valid marketplace retry filter")
        try:
            limit = int(payload.get("limit") or 10)
        except (TypeError, ValueError):
            raise ValueError("Retry batch size must be 5, 10, 25 or all")
        if limit not in {5, 10, 25, 10000}:
            raise ValueError("Retry batch size must be 5, 10, 25 or all")
        if any(ident[0] == run_id for ident in monitor.jobs):
            raise HTTPException(409,"A retry batch is already running")
        enabled = {s["key"] for s in catalog.list_sources() if s["effective_enabled"]}
        statuses = {"ACTION_REQUIRED", "FAILED", "INCOMPLETE"}
        if include_not_found:
            statuses.add("NOT_FOUND")
        tasks = [task for task in catalog.checks(run_id)
                 if task["marketplace_key"] in enabled and task.get("status") in statuses
                 and source_key in {"all",task["marketplace_key"]}]
        priority = {"ACTION_REQUIRED": 0, "FAILED": 1, "INCOMPLETE": 2, "NOT_FOUND": 3}
        tasks.sort(key=lambda task:(priority.get(task.get("status"),9),task["source_model"],task["marketplace_key"]))
        tasks = tasks[:limit]
        if tasks:
            catalog.resume_monitoring_session(run_id)
            monitor.begin_batch(run_id,tasks,"Retry unresolved" if source_key == "all" else f"Retry {tasks[0]['marketplace']}")
        count = 0
        for task in tasks:
            await monitor.retry(run_id, task["item_id"], task["marketplace_key"], capture=False)
            count += 1
        return {"checks_started": count, "status": "PENDING" if count else "UNCHANGED"}

    @app.get("/runs/{run_id}/export")
    async def export(run_id: str):
        run = catalog.run(run_id)
        if run["status"]=="RUNNING":
            raise HTTPException(409,"Wait for the run or stop it before export")
        if Path(run_id).name != run_id:
            raise HTTPException(400)
        path = settings.exports_dir / f"PriceMonitor-v5-{run_id}.xlsx"
        await asyncio.to_thread(write_monitoring_export,path,run)
        return FileResponse(path,filename=path.name)

    @app.get("/exports")
    async def exports(limit: int=6):
        return [{"filename":p.name,"size_bytes":p.stat().st_size} for p in sorted(settings.exports_dir.glob("*.xlsx"),key=lambda p:p.stat().st_mtime,reverse=True)[:max(0,min(limit,100))]]

    @app.get("/exports/file/{filename}")
    async def export_file(filename: str):
        if Path(filename).name!=filename or not filename.endswith(".xlsx"):
            raise HTTPException(404)
        return FileResponse(settings.exports_dir / filename,filename=filename)

    @app.get("/logs")
    async def logs():
        return [{"level":"INFO","message":"v5: only Kaina24, Salidzini and Hinnavaatlus are queried. Shop columns are derived from marketplace offers."}]

    return app
