# Price Monitor 4.0.0

Local-first Windows application for TCL marketplace and direct-shop price monitoring. Version 4 adds an editable catalog, per-source controls, compact model-level results, and direct retailer checks while preserving Excel import and local SQLite history.

## Run

1. Open the v4 portable folder.
2. Copy `.env.example` to `.env` and adjust the settings if needed.
3. Run `PriceMonitor.exe`.
4. The application opens <http://127.0.0.1:8000/> automatically. API documentation is available at <http://127.0.0.1:8000/docs>.

Python does not need to be installed. Keep the complete portable directory together, including `_internal` and `legacy`.

## Editable catalog

After Setup, open **Position management**. The panel has two synchronized lists:

- **Source / Monitoring models** — models included in monitoring checks;
- **Stock / Warehouse stock** — inventory, warehouse, quantity, unit cost, and linked model.

Both lists support manual creation, editing, search, pause/resume, soft deletion to trash, and restoration. Paused and trashed items are excluded from new monitoring runs. Excel upload remains available for bulk import; manually edited items are preserved as manual records.

## Monitoring sources and results

Marketplaces and shops have individual switches plus master switches for each group. Shops are grouped by Lithuania, Latvia, and Estonia. A model can use automatic shop search or an optional direct product URL saved in its editor.

The monitoring table keeps one row per model. Marketplace and shop cells expand to show individual offers, availability, links, timestamps, and errors. All table filters accept multiple values. Every column can be hidden from its header and restored from the **Columns** menu; column visibility is retained in the browser.

If a retailer presents a browser security challenge, the check is reported as **Action required** instead of a generic failure. Expand the retailer cell and choose **Open verification** to inspect the price manually in the normal browser session.

## Configuration

The default configuration is documented in `.env.example`. Runtime data is stored beside the executable:

- `var/price_monitor_v4.sqlite3` — editable v4 catalog;
- `var/price_monitor_v4_legacy.sqlite3` — monitoring history and observations;
- `var/exports/` — generated Excel reports;
- `var/logs/` — application logs;
- `var/stock/latest.xlsx` — latest stock data.

These runtime files, the local `.env`, and the source workbook are intentionally excluded from version control and from the clean portable build.

## Safety boundary

Live marketplace collection is enabled by default (`ENABLE_LIVE_MARKETPLACES=true`) for Kaina24, Salidzini, and Hinnavaatlus. Individual and master switches in the application still control which sources participate in each monitoring run.

## Workflow

1. `POST /runs` starts a background run; overlapping runs are rejected.
2. The workbook loader reads the `TV`, `SB`, and `Monitors` sheets and their `Model` column.
3. Every product and marketplace task is stored locally with its durable status and errors.
4. The exporter creates a timestamped workbook in `var/exports/`, adds price/run/offer history, and leaves the source workbook unchanged.
5. `/runs/{run_id}`, `/history`, `/logs`, and `/exports/latest` expose local results.

## Development

```powershell
./run-v4.ps1
./run-v4.ps1 -Test
./build-v4.ps1
```

The default build command updates `dist/PriceMonitor-v4.0.0-windows-x64-portable` and does not create a ZIP file. Use `./build-v4.ps1 -Archive` only when an archive is explicitly needed.

The Python source for the v4 catalog, API, launcher, and interface is reproducible from this repository. Marketplace collection is temporarily delegated to the supplied v3 executable in an isolated internal service because the original v3 adapter source was not present in the supplied folder.
