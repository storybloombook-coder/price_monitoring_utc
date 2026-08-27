from __future__ import annotations

import shutil
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi import Body, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response

from . import __version__
from .browser_bridge import BrowserBridge, EXTENSION_ORIGIN
from .catalog import CatalogStore
from .config import Settings
from .legacy import LegacyService, safe_filename
from .shops import ShopMonitor
from .exporter import write_monitoring_export


def timestamped_upload(directory: Path, category: str, original_name: str) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    suffix = Path(original_name).suffix.lower()
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{category}-{stamp}{suffix}"


def create_app(
    settings: Settings | None = None,
    store: CatalogStore | None = None,
    legacy: LegacyService | None = None,
) -> FastAPI:
    app_settings = settings or Settings.load()
    catalog = store or CatalogStore(app_settings.catalog_database)
    legacy_service = legacy or LegacyService(app_settings)
    browser_bridge = BrowserBridge(float(app_settings.env.get("BROWSER_BRIDGE_TIMEOUT_SECONDS", "150")))
    shop_monitor = ShopMonitor(
        catalog, float(app_settings.env.get("HTTP_TIMEOUT_SECONDS", "20")), browser_bridge
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        source_workbook = app_settings.root / app_settings.env.get(
            "SOURCE_WORKBOOK", "UTC price 2026 line up.xlsx"
        )
        catalog.seed_from_v3(app_settings.original_database, source_workbook)
        catalog.prepare_legacy(
            app_settings.original_database,
            app_settings.legacy_database,
            app_settings.active_workbook,
        )
        if app_settings.legacy_enabled:
            await legacy_service.start()
        try:
            yield
        finally:
            shop_monitor.stop()
            browser_bridge.stop()
            legacy_service.stop()

    app = FastAPI(title="Price Monitor v4", version=__version__, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[EXTENSION_ORIGIN],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["content-type"],
    )
    app.state.settings = app_settings
    app.state.catalog = catalog
    app.state.legacy = legacy_service
    app.state.shop_monitor = shop_monitor
    app.state.browser_bridge = browser_bridge
    static_dir = Path(__file__).resolve().parent / "static"

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    @app.get("/assets/{filename}", include_in_schema=False)
    async def asset(filename: str) -> FileResponse:
        requested = safe_filename(filename)
        path = static_dir / requested
        if not path.exists() or path.suffix not in {".css", ".js", ".svg", ".png"}:
            raise HTTPException(404, "Asset not found")
        media = {".css": "text/css", ".js": "application/javascript", ".svg": "image/svg+xml"}.get(path.suffix)
        return FileResponse(path, media_type=media)

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "application": "Price Monitor v4",
            "version": __version__,
            "source_workbook": str(app_settings.active_workbook),
            "legacy_service": "running" if legacy_service.running else ("disabled" if not app_settings.legacy_enabled else "stopped"),
            "browser_bridge": browser_bridge.status(),
            "catalog": catalog.stats(),
        }

    def require_extension(request: Request) -> None:
        if request.headers.get("origin") != EXTENSION_ORIGIN:
            raise HTTPException(403, "Only the bundled PriceMonitor Edge extension can use this endpoint")

    @app.get("/browser-bridge/status")
    async def browser_bridge_status() -> dict[str, Any]:
        return browser_bridge.status()

    @app.post("/browser-bridge/heartbeat")
    async def browser_bridge_heartbeat(request: Request) -> dict[str, Any]:
        require_extension(request)
        browser_bridge.heartbeat()
        return browser_bridge.status()

    @app.get("/browser-bridge/jobs/next")
    async def next_browser_job(request: Request, wait_seconds: float = Query(25, ge=0, le=25)) -> Response:
        require_extension(request)
        job = await browser_bridge.next_job(wait_seconds)
        return JSONResponse(job) if job else Response(status_code=204)

    @app.post("/browser-bridge/jobs/{job_id}/result")
    async def finish_browser_job(job_id: str, request: Request, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        require_extension(request)
        html = str(payload.get("html") or "")
        if len(html) > 8_000_000:
            raise HTTPException(413, "Captured page is too large")
        if not browser_bridge.submit(job_id, {
            "html": html,
            "url": str(payload.get("url") or ""),
            "security_challenge": bool(payload.get("security_challenge")),
            "incomplete": bool(payload.get("incomplete")),
            "error": str(payload.get("error") or "")[:500],
        }):
            raise HTTPException(404, "Browser job not found or already finished")
        return {"accepted": True}

    @app.get("/catalog/summary")
    async def catalog_summary() -> dict[str, Any]:
        return catalog.stats()

    @app.get("/sources")
    async def sources() -> list[dict[str, Any]]:
        return catalog.list_sources()

    @app.patch("/sources/{key}")
    async def update_source(key: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        try:
            return catalog.update_source(key, bool(payload.get("enabled")))
        except KeyError as error:
            raise HTTPException(404, "Monitoring source not found") from error

    @app.patch("/sources/master/{kind}")
    async def update_source_master(kind: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        try:
            return catalog.update_source_master(kind, bool(payload.get("enabled")))
        except ValueError as error:
            raise HTTPException(400, str(error)) from error

    @app.get("/catalog/items")
    async def catalog_items(
        kind: str = Query(pattern="^(source|stock)$"),
        scope: str = Query("active", pattern="^(active|trash|all)$"),
        q: str = "",
    ) -> list[dict[str, Any]]:
        try:
            return catalog.list_items(kind, scope, q)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error

    @app.post("/catalog/items/{kind}", status_code=201)
    async def create_catalog_item(kind: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        try:
            return catalog.create_item(kind, payload)
        except ValueError as error:
            raise HTTPException(409, str(error)) from error

    @app.patch("/catalog/items/{item_id}")
    async def update_catalog_item(item_id: int, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        try:
            return catalog.update_item(item_id, payload)
        except KeyError as error:
            raise HTTPException(404, "Item not found") from error
        except ValueError as error:
            raise HTTPException(409, str(error)) from error

    @app.delete("/catalog/items/{item_id}")
    async def trash_catalog_item(item_id: int) -> dict[str, Any]:
        try:
            return catalog.trash_item(item_id)
        except KeyError as error:
            raise HTTPException(404, "Item not found") from error

    @app.post("/catalog/items/{item_id}/restore")
    async def restore_catalog_item(item_id: int) -> dict[str, Any]:
        try:
            return catalog.restore_item(item_id)
        except KeyError as error:
            raise HTTPException(404, "Item not found") from error

    @app.delete("/catalog/items/{item_id}/permanent", status_code=204)
    async def delete_catalog_item_permanently(item_id: int) -> Response:
        try:
            catalog.delete_item_permanently(item_id)
            return Response(status_code=204)
        except KeyError as error:
            raise HTTPException(404, "Only items in trash can be deleted permanently") from error

    @app.post("/catalog/items/{item_id}/monitor")
    async def promote_stock_item(item_id: int) -> dict[str, Any]:
        try:
            return catalog.promote_stock_item(item_id)
        except KeyError as error:
            raise HTTPException(404, "Active stock item not found") from error
        except ValueError as error:
            raise HTTPException(409, str(error)) from error

    @app.get("/workbook")
    async def workbook_info() -> dict[str, Any]:
        items = catalog.list_items("source", "active")
        meta = catalog.get_meta("source_upload", {})
        return {
            "exists": bool(items),
            "source_workbook": meta.get("filename", "v4 catalog"),
            "models_found": len(items),
            "models": [
                {"id": item["id"], "model": item["model"], "source_sheets": item["source_sheets"], "paused": item["paused"]}
                for item in items
            ],
            "uploaded_at": meta.get("uploaded_at"),
        }

    @app.post("/workbook/upload")
    async def upload_workbook(file: UploadFile = File(...)) -> dict[str, Any]:
        if Path(file.filename or "").suffix.lower() not in {".xlsx", ".xlsm"}:
            raise HTTPException(400, "Only .xlsx and .xlsm files are supported")
        destination = timestamped_upload(app_settings.uploads_dir, "source", file.filename or "source.xlsx")
        try:
            with destination.open("wb") as output:
                shutil.copyfileobj(file.file, output)
            result = catalog.import_source_workbook(destination, file.filename or destination.name)
            catalog.prepare_legacy(app_settings.original_database, app_settings.legacy_database, app_settings.active_workbook)
            return {"original_filename": file.filename, "models_found": result["imported"], **result}
        except ValueError as error:
            destination.unlink(missing_ok=True)
            raise HTTPException(400, str(error)) from error

    @app.get("/stock")
    async def stock_info() -> dict[str, Any]:
        items = catalog.list_items("stock", "active")
        meta = catalog.get_meta("stock_upload", {})
        return {
            "count": len(items),
            "matched": sum(1 for item in items if item["matched"]),
            "warehouses": sorted({item["warehouse"] for item in items if item["warehouse"]}),
            "source_filename": meta.get("filename", "v4 catalog"),
            "uploaded_at": meta.get("uploaded_at"),
            "items": items,
        }

    @app.post("/stock/upload")
    async def upload_stock(file: UploadFile = File(...)) -> dict[str, Any]:
        if Path(file.filename or "").suffix.lower() not in {".xlsx", ".xlsm"}:
            raise HTTPException(400, "Only .xlsx and .xlsm files are supported")
        destination = timestamped_upload(app_settings.uploads_dir, "stock", file.filename or "stock.xlsx")
        try:
            with destination.open("wb") as output:
                shutil.copyfileobj(file.file, output)
            result = catalog.import_stock_workbook(destination, file.filename or destination.name)
            catalog.prepare_legacy(app_settings.original_database, app_settings.legacy_database, app_settings.active_workbook)
            return {"original_filename": file.filename, **result}
        except ValueError as error:
            destination.unlink(missing_ok=True)
            raise HTTPException(400, str(error)) from error

    def example_path(name: str) -> Path:
        if getattr(__import__("sys"), "frozen", False):
            return app_settings.root / "legacy" / "_internal" / "price_monitor" / "static" / "examples" / name
        return app_settings.root / "_internal" / "price_monitor" / "static" / "examples" / name

    @app.get("/examples/workbook")
    async def example_workbook() -> FileResponse:
        return FileResponse(example_path("example-workbook.xlsx"), filename="example-workbook.xlsx")

    @app.get("/examples/stock")
    async def example_stock() -> FileResponse:
        return FileResponse(example_path("example-stock.xlsx"), filename="example-stock.xlsx")

    async def proxy(method: str, path: str, body: bytes | None = None) -> Response:
        if not legacy_service.running:
            raise HTTPException(503, "The v3 marketplace service is unavailable")
        headers = {"content-type": "application/json"} if body is not None else None
        async with httpx.AsyncClient(timeout=60) as client:
            try:
                response = await client.request(method, f"{legacy_service.base_url}{path}", content=body, headers=headers)
            except httpx.HTTPError as error:
                raise HTTPException(502, f"Legacy service error: {error}") from error
        content_type = response.headers.get("content-type", "application/octet-stream")
        disposition = response.headers.get("content-disposition")
        response_headers = {"content-disposition": disposition} if disposition else None
        return Response(response.content, status_code=response.status_code, media_type=content_type, headers=response_headers)

    async def legacy_json(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if not legacy_service.running:
            raise HTTPException(503, "The marketplace service is unavailable")
        async with httpx.AsyncClient(timeout=60) as client:
            try:
                response = await client.request(method, f"{legacy_service.base_url}{path}", json=payload)
                response.raise_for_status()
                return response.json()
            except (httpx.HTTPError, ValueError) as error:
                raise HTTPException(502, f"Marketplace service error: {error}") from error

    def marketplace_allowed(name: str, allowed: list[str]) -> bool:
        normalized = name.lower().replace(".", "")
        return any(key.replace(".", "") in normalized for key in allowed)

    async def merged_run(run_id: str) -> dict[str, Any]:
        session = catalog.monitoring_session(run_id)
        if not session:
            return await legacy_json("GET", f"/runs/{run_id}")
        if session["legacy_started"]:
            run = await legacy_json("GET", f"/runs/{run_id}")
            run["tasks"] = [
                task for task in run.get("tasks", [])
                if marketplace_allowed(str(task.get("marketplace", "")), session["marketplace_keys"])
            ]
        else:
            run = {
                "id": run_id,
                "run_id": run_id,
                "trigger": "manual",
                "status": "COMPLETE",
                "tasks": [],
                "started_at": session["created_at"],
            }
        shop = catalog.shop_run(run_id)
        run["shop_results"] = shop["results"]
        if shop["status"] == "RUNNING" or run.get("status") == "RUNNING":
            run["status"] = "RUNNING"
        elif run.get("status") not in {"FAILED", "INCOMPLETE"}:
            run["status"] = "COMPLETE"
        if run["status"] != "RUNNING":
            export_path = app_settings.exports_dir / f"PriceMonitor-v4-{safe_filename(run_id)}.xlsx"
            if not export_path.exists():
                write_monitoring_export(export_path, run, catalog.list_items("source", "active"))
            run["export_path"] = str(export_path)
        return run

    @app.get("/marketplaces")
    async def marketplaces() -> list[dict[str, Any]]:
        return [source for source in catalog.list_sources() if source["kind"] == "marketplace"]

    @app.post("/runs")
    async def start_run(payload: dict[str, Any] = Body(default={})) -> JSONResponse:
        catalog.prepare_legacy(app_settings.original_database, app_settings.legacy_database, app_settings.active_workbook)
        sources = catalog.list_sources()
        marketplaces = [source["key"] for source in sources if source["kind"] == "marketplace" and source["effective_enabled"]]
        if marketplaces:
            legacy_run = await legacy_json("POST", "/runs", payload)
            run_id = str(legacy_run.get("run_id") or legacy_run.get("id"))
            if not run_id or run_id == "None":
                raise HTTPException(502, "Marketplace service returned no run ID")
            legacy_started = True
        else:
            run_id = f"v4-{uuid.uuid4()}"
            legacy_started = False
        catalog.register_monitoring_session(run_id, legacy_started, marketplaces)
        shop_monitor.start(run_id)
        return JSONResponse({"run_id": run_id, "status": "RUNNING"})

    @app.get("/runs/latest")
    async def latest_run() -> JSONResponse:
        session = catalog.latest_monitoring_session()
        if session:
            return JSONResponse(await merged_run(session["run_id"]))
        return JSONResponse(await legacy_json("GET", "/runs/latest"))

    @app.get("/runs/{run_id}")
    async def run_status(run_id: str) -> JSONResponse:
        return JSONResponse(await merged_run(run_id))

    @app.get("/history")
    async def history(limit: int = 100) -> Response:
        return await proxy("GET", f"/history?limit={limit}")

    @app.get("/logs")
    async def logs(limit: int = 50) -> Response:
        return await proxy("GET", f"/logs?limit={limit}")

    @app.get("/exports")
    async def exports(limit: int = 10) -> list[dict[str, Any]]:
        app_settings.exports_dir.mkdir(parents=True, exist_ok=True)
        files = sorted(app_settings.exports_dir.glob("*.xlsx"), key=lambda path: path.stat().st_mtime, reverse=True)
        return [
            {"filename": path.name, "size_bytes": path.stat().st_size, "modified_at": datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()}
            for path in files[: max(0, min(limit, 100))]
        ]

    @app.get("/exports/latest")
    async def latest_export() -> FileResponse:
        items = await exports(1)
        if not items:
            raise HTTPException(404, "No exports found")
        return FileResponse(app_settings.exports_dir / items[0]["filename"], filename=items[0]["filename"])

    @app.get("/exports/file/{filename}")
    async def export_file(filename: str) -> FileResponse:
        path = app_settings.exports_dir / safe_filename(filename)
        if not path.exists() or path.suffix.lower() != ".xlsx":
            raise HTTPException(404, "Export not found")
        return FileResponse(path, filename=path.name)

    return app
