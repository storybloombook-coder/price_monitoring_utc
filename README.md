# Price Monitor 3.0.0 (portable)

Portable Windows application for daily TCL marketplace price monitoring. The application preserves the source workbook, stores run history in SQLite, and creates versioned Excel exports.

## Run

1. Download and unpack the portable archive.
2. Copy `.env.example` to `.env` and adjust the settings if needed.
3. Put `UTC price 2026 line up.xlsx` beside `PriceMonitor.exe`, or set `SOURCE_WORKBOOK` in `.env` to an absolute path.
4. Run `PriceMonitor.exe`.
5. Open <http://127.0.0.1:8000/> in a browser. API documentation is available at <http://127.0.0.1:8000/docs>.

Python does not need to be installed. Keep `PriceMonitor.exe` and the complete `_internal` directory together.

## Configuration

The default configuration is documented in `.env.example`. Runtime data is stored beside the executable:

- `var/price_monitor.sqlite3` — local database;
- `var/exports/` — generated Excel reports;
- `var/logs/` — application logs;
- `var/stock/latest.xlsx` — latest stock data.

These runtime files, the local `.env`, and the source workbook are intentionally excluded from version control and from the clean portable build.

## Safety boundary

Live marketplace collection is disabled in the example configuration (`ENABLE_LIVE_MARKETPLACES=false`). Kaina24, Salidzini, and Hinnavaatlus adapters should be enabled only after their access rules and parsers have been validated.

## Workflow

1. `POST /runs` starts a background run; overlapping runs are rejected.
2. The workbook loader reads the `TV`, `SB`, and `Monitors` sheets and their `Model` column.
3. Every product and marketplace task is stored locally with its durable status and errors.
4. The exporter creates a timestamped workbook in `var/exports/`, adds price/run/offer history, and leaves the source workbook unchanged.
5. `/runs/{run_id}`, `/history`, `/logs`, and `/exports/latest` expose local results.

## Build provenance

This repository contains the supplied portable PyInstaller build of Price Monitor 3.0.0. The original Python source files and the referenced `build-exe.bat` build script were not present in the supplied folder, so the executable cannot be reproducibly recompiled from this repository alone.
