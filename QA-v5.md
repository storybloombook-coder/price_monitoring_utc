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

## Patch 5.0.2 — Smartech seller mapping

- The existing 32S4K run already contained 14 Hinnavaatlus offers, including `Smartech Shop` at 157.60 EUR, but its stored `seller_key` was null. This was a seller-name mapping omission, not a missing price or blocked request.
- Added the exact `Smartech Shop` alias. Existing `Smartech` and `Smartech.ee` aliases and country restrictions remain. No fuzzy removal of words such as Shop/Outlet is used.
- Seller keys are derived again when presenting a run. Already saved/cached offers now populate the Smartech column without making new requests or rewriting the price, time, original seller name or historical check record. The same data supplies the Excel export.
- All 80 automated tests passed: case/whitespace aliases, rejected similar/foreign-country names, 32S4K seller-card parsing, preserved unknown availability, old results and cached runs, exact price/time preservation, unchanged stored record, numeric Smartech Excel cell.
- No Kaina24 collection changes are part of this patch. Its previously diagnosed adapter regression remains a separate issue.

## Patch 5.0.3 — working Kaina24 adapter

- Compared the old bundled adapter and successful v4 task records with current HTML. Restored its fixed User-Agent/Accept request profile and explicit UTF-8 decoding, keeping the v5 async queue, 3-second pacing, bounded responses, cancellation and protection cooldown. No header rotation, CAPTCHA solving, retailer calls or legacy EXE launches.
- Added dedicated search-card and comparison-table parsing. Seller evidence comes from logo labels; prices only from cash-price nodes. Comparison rows replace search snapshots, featured/mobile duplicates are removed, and the collapsed sold-out archive and related models are excluded. Per-row schema availability is read without borrowing aggregate stock or guessing from delivery time. Explicit ordinary prices replace loyalty prices; ambiguous conditional offers require review.
- Kaina `/ex/` tracking links are rejected before requesting them. Output links and saved model links stay on Kaina24 comparison pages. A missing saved page falls back to search. Pagination retains the first comparison link and checks advertised offer counts across pages.
- 103 automated tests passed, including 23 new Kaina regressions: real-structure seller cards/tables, exact matching, financing/delivery separation, country mapping, featured/archive exclusions, per-row stock, loyalty pricing, safe URLs, UTF-8/request headers, search reconciliation, saved-link reuse/404 fallback, protection retaining partial prices and pagination coverage. Existing v4/v5 tests remain unchanged and passing.
- Live final portable EXE, port 8153, isolated catalog, extension disconnected: **24G54 SUCCESS, 6 offers, 104.40–133.35 EUR**; **32S4K SUCCESS, 17 offers, 153.79–299.99 EUR**. Both used two requests (search + Kaina comparison), complete coverage against the declared count. Bite 104.40 and Varle 108.27 populated the 24G54 shop cells; Varle 158.90 and Smartech.ee 153.79 populated 32S4K. Rde.lt remains separate from the configured RDE.ee. Prices are observations on 2026-08-31, not fixed expectations for future runs.
- Frozen EXE file/product versions, health endpoint and page header report 5.0.3. Production catalog SHA256 before/after asset replacement was identical: `C7B86589DE7A5777723BEF5A3282D3C480917337141B1A404A7666ABB7BDB8A9`. A backup was saved under `build/recovery-503-7e7eb16a34874b689b367b585cd7cb37/`. Only v5 program assets were replaced; v4 was not stopped or modified. No ZIP generated.
- Kaina24 is working in the tested ordinary network session, not guaranteed against future protection or markup changes. Salidzini and Hinnavaatlus collection were not changed. Installed-extension capture was not exercised in this patch; it uses the same server-side HTML parser.

## Patch 5.0.4 — controls, regional sellers and safe discovery

- Marketplaces/Shops are native details lists, closed on page load, with independent green circular controls and enabled counts. Toggles do not recreate their containers. Browser QA on isolated port 8125 verified closed state after reload, readable `i` tooltip by focus/click, preserved open list after toggling, and RDE.lt disappearing while RDE.ee stays visible. Fixed the previously stale empty-table header after changing sources. Screenshot inspected; tooltip contrast corrected for the focused information button.
- Price-cache selection moved to collapsed Advanced settings. Existing stored mode remains respected; new sessions default to Balanced (4 hours). No cache functionality or per-model fresh refresh was removed.
- RDE.lt has a separate `rde_lt` source/key/column, while the existing `rde` key now displays RDE.ee. Migration preserves old switches; historical offers are reclassified by seller name without rewriting observations. Both columns are included in Excel.
- Hinnavaatlus retries a confirmed no-match search with one then two trailing characters removed (minimum three alphanumeric-model characters). Protection, unavailable network or unfamiliar HTML do not trigger this retry chain or become Not found. S45HE/S45H and S55HE/S55H are explicit regional aliases supported by TCL Italy's model pages (links in the guide). Exact matching remains strict elsewhere. Unknown shortened variants are suggestions with marketplace links in Action required, never accepted prices. Original catalog SKU remains unchanged; offers show the matched regional name.
- Senukai's published SMART NET/loyalty price is selected, labeled in table links/shop summary, and exported with a price-basis field. Other sellers retain ordinary-price rules. Pre-5.0.4 Kaina caches containing Senukai skip reuse to avoid displaying old ordinary prices as the new policy; historical runs stay unchanged.
- Unverified remains incomplete evidence, distinct from marketplace Not found and shop Not listed. Expanded tooltip explains the distinction.
- 113 tests passed; JavaScript syntax check passed. New cases cover migration/toggle preservation, historical RDE reclassification and Excel headings, loyalty metadata/cache invalidation, known aliases and saved-link reuse, bounded no-match retries, unknown-prefix suggestions with no prices, and network/protection/unknown-markup stopping conditions.
- Final frozen EXE with ordinary network access, extension disconnected, isolated data at `build/frozen-504-c6d0d4a9cc8c432ba11b229d66ebd4ec`, port 8154: S45HE SUCCESS via S45H with **32 offers**, S55HE SUCCESS via S55H with **33 offers** (3 requests each). Then a Kaina-only 55T7B run returned SUCCESS in 2 requests and selected Senukai **368.99 EUR, loyalty, IN_STOCK**, instead of its 399 EUR non-member note. Browser inspection of that EXE showed `Loyalty price` in min-price link, lowest in-stock and Senukai cell. These are observed 2026-08-31 prices/counts, not fixed future expectations.
- Production recovery snapshot: `build/recovery-504-3c95ccc741c942039dead90d87a3bfb6/catalog-full.sqlite3`, made using SQLite's backup API to include committed WAL data (the initial plain main-file copy omitted the newest run). All 113 catalog rows are identical to the initial copy; all its historical check/session records remain present. The complete snapshot includes 4 sessions and 300 checks. v4 and its running process were untouched; only v5 program assets replaced. No ZIP generated. Installed-extension behavior and Salidzini hCaptcha were not revalidated or changed.

## Rollback

The v4 source package and portable folder are unchanged. Git tag `v4.2.4` points to
the original source baseline; the old ZIP SHA256 remains
`EFF791926A6B480669A362CAD03AEF0B554023F9ECDCF1F9F45B1BCB2E627FAB`.
v5 has its own build folder, database and extension identity.
