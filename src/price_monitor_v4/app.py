from __future__ import annotations

import shutil
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi import Body, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response

from . import __version__
from .catalog import CatalogStore
from .config import Settings
from .legacy import LegacyService, safe_filename


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
            legacy_service.stop()

    app = FastAPI(title="Price Monitor v4", version=__version__, lifespan=lifespan)
    app.state.settings = app_settings
    app.state.catalog = catalog
    app.state.legacy = legacy_service
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
            "catalog": catalog.stats(),
        }

    @app.get("/catalog/summary")
    async def catalog_summary() -> dict[str, Any]:
        return catalog.stats()

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

    @app.get("/marketplaces")
    async def marketplaces() -> Response:
        return await proxy("GET", "/marketplaces")

    @app.post("/runs")
    async def start_run(payload: dict[str, Any] = Body(default={})) -> Response:
        catalog.prepare_legacy(app_settings.original_database, app_settings.legacy_database, app_settings.active_workbook)
        return await proxy("POST", "/runs", __import__("json").dumps(payload).encode())

    @app.get("/runs/latest")
    async def latest_run() -> Response:
        return await proxy("GET", "/runs/latest")

    @app.get("/runs/{run_id}")
    async def run_status(run_id: str) -> Response:
        return await proxy("GET", f"/runs/{run_id}")

    @app.get("/history")
    async def history(limit: int = 100) -> Response:
        return await proxy("GET", f"/history?limit={limit}")

    @app.get("/logs")
    async def logs(limit: int = 50) -> Response:
        return await proxy("GET", f"/logs?limit={limit}")

    @app.get("/exports")
    async def exports(limit: int = 10) -> Response:
        return await proxy("GET", f"/exports?limit={limit}")

    @app.get("/exports/latest")
    async def latest_export() -> Response:
        return await proxy("GET", "/exports/latest")

    @app.get("/exports/file/{filename}")
    async def export_file(filename: str) -> Response:
        return await proxy("GET", f"/exports/file/{safe_filename(filename)}")

    return app
