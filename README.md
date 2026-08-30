# Price Monitor 4.2.3

Local-first Windows application for TCL marketplace and direct-shop price monitoring. Version 4 adds an editable catalog, per-source controls, compact model-level results, and direct retailer checks while preserving Excel import and local SQLite history.

## Run

1. Open the v4 portable folder.
2. Copy `.env.example` to `.env` and adjust the settings if needed.
3. Run `PriceMonitor.exe`.
4. The application opens <http://127.0.0.1:8000/> automatically. API documentation is available at <http://127.0.0.1:8000/docs>.

Python does not need to be installed. Keep the complete portable directory together, including `_internal` and `legacy`.

### Edge extension for protected shops

The portable folder includes `edge-extension`, which lets PriceMonitor use a normal Edge tab when a retailer blocks direct collection:

1. Start `PriceMonitor.exe`.
2. Open `edge://extensions` in Edge and enable **Developer mode**.
3. Choose **Load unpacked** and select the portable folder's `edge-extension` directory.
4. Open **PriceMonitor Browser Bridge** and confirm **Connected to PriceMonitor**.

Keep Edge open during monitoring. When a retailer displays a human verification, complete it in the visible tab. The extension has a fixed identity and communicates only with the local PriceMonitor server and the configured retailer domains.

The extension keeps its local WebSocket in a dedicated offscreen worker rather than the short-lived Manifest V3 service worker. It sends a 20-second keepalive, reconnects automatically with backoff, preserves active tab jobs in extension storage, and keeps HTTP polling as a recovery watchdog. Visible verification has up to 135 seconds to finish. The portable builder updates extension files in place instead of deleting the loaded unpacked directory; after an extension-code update, use **Reload** once on `edge://extensions` so Edge activates the new worker.

## Editable catalog

After Setup, open **Position management**. The panel has two synchronized lists:

- **Source / Monitoring models** — models included in monitoring checks;
- **Stock / Warehouse stock** — inventory, warehouse, quantity, unit cost, and linked model.

Both lists support manual creation, editing, search, pause/resume, soft deletion to trash, and restoration. Paused and trashed items are excluded from new monitoring runs. Excel upload remains available for bulk import; manually edited items are preserved as manual records.

## Monitoring sources and results

Marketplaces and shops have individual switches plus master switches for each group. Shops are grouped by Lithuania, Latvia, and Estonia. A model can use automatic shop search or an optional direct product URL saved in its editor.

Each direct shop has an independent collection method selector:

- **Auto · gentle fallback** starts with a lightweight direct request, uses Playwright/background Edge only when JavaScript rendering is needed, and goes straight to the normal-browser extension when retailer protection is detected.
- **Direct request**, **Background Edge**, **Playwright Edge**, and **Browser extension** pin a check to one path for diagnostics or site-specific operation.
- **Manual only** sends no automated retailer request and reports the check for human review.

The **Test** button beside a shop runs exactly one selected method against one monitoring model. It reports the status, price, duration, method attempts, and protection errors without starting a full monitoring run. Successful automatic checks remember the last working browser strategy for that shop. Kaina24 and Hinnavaatlus still use the bundled legacy marketplace engine. Salidzini uses an assisted Edge collector: it searches the exact model, reads rendered offer cards and selects the lowest exact-model price. A direct Salidzini product URL can optionally be saved per model.

The monitoring table keeps one row per model. A matching stock record does not create another network check: active monitoring models are the only task source, while stock quantity and unit cost are merged into the same canonical SKU row. Duplicate active monitoring models are rejected. Marketplace and shop discovery queries use `TCL <model>` without duplicating an existing TCL prefix, while exact SKU matching remains mandatory. Marketplace and shop cells expand to show individual offers, availability, links, timestamps, and errors. All table filters accept multiple values. Columns can be shown or hidden from the **Columns** menu; column visibility is retained in the browser. Use **Hard stop** to cancel a stuck run while preserving completed results.

After a run finishes, **Export table to Excel** downloads that exact opened run, including historical runs. The summary and offer-detail worksheets use an A4 landscape print setup fitted to one page horizontally.

If the Edge extension is connected, protected pages are automatically delegated to a visible normal-browser tab. Without the extension, or when a human verification times out, the check is reported as **Action required** instead of a generic failure. Expand the retailer cell and choose **Open verification** to inspect the price manually.

Opening a retailer page does not silently change stored monitoring data. The **Action required** dialog provides explicit follow-up actions: **Capture again** after completing browser verification, **Mark not found** after confirming that the model is absent, or **Save manual price** for a confirmed in-stock offer. Manual results immediately update the table and invalidate the previous export so it can be regenerated.

Salidzini opens the manual-review workflow immediately for fresh uncached checks. The operator can confirm absence/price or explicitly ask the extension to capture the verified page. Successful assisted results are cached for 4 hours to balance freshness with repeated manual work.

Status badges include hover/focus explanations throughout the catalog, stock table, and monitoring results. Expanded marketplace and shop result cells remain open while the running monitor refreshes the table.

### Polite monitoring

Direct-shop collection uses one sequential request stream per retailer with an 8–15 second delay. Fresh successful observations are reused for four hours and clearly marked **Cached**. A `429`, Cloudflare challenge, or blocked browser verification pauses the retailer for at least one hour (or the server's `Retry-After` value); remaining checks are marked **Cooldown** with the next retry time. The review window then offers two safe choices: wait until that timestamp and retry automatically, or enter a manual price/not-found result immediately. Other retailer domains can continue independently. Marketplace concurrency defaults to one.

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

The default build command updates the stable portable directory `dist/PriceMonitor-v4.0.0-windows-x64-portable` in place (the application itself reports version 4.2.3). Keeping this directory stable preserves local data and the unpacked Edge extension path. It does not create a ZIP file. Use `./build-v4.ps1 -Archive` only when an archive is explicitly needed.

The Python source for the v4 catalog, API, launcher, and interface is reproducible from this repository. Marketplace collection is temporarily delegated to the supplied v3 executable in an isolated internal service because the original v3 adapter source was not present in the supplied folder.
