# v5.0.0 verification — 2026-08-31

## Automated checks

59 tests passed (39 preserved v4 tests + 20 v5 tests). Coverage includes:

- Stock auto-enrollment, duplicate warehouses, zero quantity, subsequent imports,
  preserved deliberate pauses and catalog-only migration.
- Marketplace URL allowlist and rejection of redirects before a retailer request.
- Exact model matching; ordinary price versus installments; all seller observations;
  in-stock minima/maxima, preorder separation and explicit unknown availability.
- Seller aliases, including protection against mapping a same-brand shop from a
  different country to the configured retailer.
- Manual add/edit/not-found decisions, previous-decision history and cache invalidation.
- 4-hour/12-hour freshness boundaries, hard stop and protection cooldown.
- 705 queued checks across 235 models with synthetic protection responses: exactly
  three outbound requests (one per marketplace), then Action required for all checks.
  This is a queue-safety test, not a claim about real-site throughput.
- Excel sheets, numeric offer rows, marketplace hyperlinks and one-page print width.

## UI and portable executable

Browser QA used an isolated catalog with synthetic prices on localhost:8125.
Verified auto-enrollment, min/max columns, seller entry, a shop toggle hiding its
column without changing marketplace min/max, and history completion status.
The UI keeps open result details and does not replace an active manual-entry popover
while other check data changes.

Excel summary, offer-detail and check sheets were imported and rendered for visual
inspection. Dates are exported as UTC date values; headers and wrapped text remain legible.

The separate windowless x64 portable EXE starts successfully on localhost:8050,
returns version 5.0.0 and loads the migrated catalog. No v3 process is launched.
51 v4 catalog rows were copied, then 22 newly recognized stock models enrolled.
Result: 27 active monitoring models, 9 deliberately paused, 1 in trash; 36 stock rows.
v4 prices, runs, retailer links and browser profiles were not copied.

## Live-site evidence and limits

The v5 engine discovered the exact Hinnavaatlus 25G64 comparison page and parsed
two seller offers in two marketplace requests. It did not visit retailer URLs.
The page exposed delivery times but no unambiguous physical stock confirmation;
these offers correctly remain Availability unknown and are excluded from in-stock extrema.

Kaina24 returned HTTP 403 to the inspection request. Salidzini returned an hCaptcha
page. No CAPTCHA was solved or bypassed. Generic seller-row parsing is fixture-tested;
rendered parsing of these protected sites still needs verification in the user's
authenticated browser session. Partial or unfamiliar results go to manual review,
not false Not found or fabricated complete market coverage.

The v5 extension is separately identified and restricted to the three marketplaces.
Its full installed-browser recovery/capture flow has not been exercised in this QA
session; use the Russian guide for installation and initial verification.

## Patch 5.0.1 — 2026-08-31

- Inspected the user's last run: 27/27 checks failed with `All connection attempts failed`, before any marketplace HTML was received. The remaining v5 process (PID 36352) was the earlier QA launch with restricted networking and browser opening disabled. A sandbox probe reproduced Windows socket error 10013; the same Hinnavaatlus request with ordinary network access returned HTTP 200. Stopped only this idle, path-verified v5 process. v4 was not stopped or changed.
- Launcher now checks for an existing v5 health endpoint before starting a server, opens its page synchronously on relaunch, has a Windows URL-handler fallback and a rotating startup log. Connection failures have a separate network diagnostic; they are not presented as CAPTCHA or product absence.
- All 68 automated tests passed. New regression cases cover browser readiness/instance reuse/fallback, foreign-app health rejection, table-clear confirmation and running-check guard, stock/model isolation, restoring paused rows, history retention, network errors and reported prices with unknown availability in UI data/Excel. Tests ran in new `build/qa-501-*` directories, without accessing user data.
- Browser UI QA on port 8125 with an isolated synthetic catalog: both Clear table buttons are left of + Add; Cancel preserves rows; stock clear leaves both monitoring models active; source clear leaves historical results and captured prices visible; confirmation identifies the table and explains recovery through Trash. Mode description changes correctly. Unknown-availability prices are visible with a disclaimer and are not counted as Lowest in-stock.
- Real source-engine probe: 24G54 yielded four Hinnavaatlus seller offers (109.20–136.66 EUR), 25G64 yielded two (199.00–259.68 EUR). Kaina24 returned protection and Salidzini CAPTCHA; both moved to Action required, not a false success/not-found. No retailer pages were requested and no CAPTCHA was bypassed.
- Frozen EXE QA on port 8151 with a separate catalog and normal network access: version 5.0.1, first launch opened the default browser; a second launch logged reuse, opened the existing page and exited without a duplicate server. The EXE itself collected the four 24G54 Hinnavaatlus offers without the extension. Production catalog/history were not used for these test writes.
- The stable v5 portable folder keeps its existing `v5.0.0` directory name so shortcuts/data paths remain valid; the EXE, UI and package version are 5.0.1. No ZIP generated for this patch. The unchanged v5 extension remains version 5.0.0.

## Rollback

The v4 source package and portable folder are unchanged. Git tag `v4.2.4` points to
the original source baseline; the old ZIP SHA256 remains
`EFF791926A6B480669A362CAD03AEF0B554023F9ECDCF1F9F45B1BCB2E627FAB`.
v5 has its own build folder, database and extension identity.
