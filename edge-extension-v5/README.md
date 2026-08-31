# PriceMonitor v5 Marketplace Bridge · 5.0.8

## Salidzini Auto

Reload this extension after updating. Select **Auto** next to Salidzini in the
app, then Start monitoring. One owned tab is reused for pages and models; no
popup confirmation is required for fully verified automatic results. The app
checks exact models, listing counts and pagination. CAPTCHA pauses the queue
for manual action; it is never solved automatically. Hard stop cancels pending
jobs and late replies cannot write prices. No retailer pages are collected.

**Manual** mode sends no automatic requests. Use the panel below; partial saves
retain Action required. Mark all pages reviewed and choose **Save prices and
finish check** only after the whole search is reviewed. Manual snapshots from
5.0.6/5.0.7 remain compatible and survive extension reload.

The 5.0.7 app fixes current Salidzini cards. Existing 5.0.6 extension snapshots
remain compatible: click **Refresh preview**, then review and save. No recapture
or CAPTCHA is needed if the queued snapshot contains the loaded results.
Geedo recommendations are excluded from Salidzini prices.

After updating the portable app, reload this unpacked extension in Edge/Chrome.

## Salidzini: capture the page you have already opened

Start a monitoring run with Salidzini enabled. Open its search page, complete
the CAPTCHA yourself, then click this extension on that same tab. Check the
original monitoring SKU and click **Send to PriceMonitor**. The page is read
without reloading or opening another tab; there is no manual-verification timer.

Review the seller/title/price rows and click **Save selected prices**. Nothing
is applied before your confirmation. Send each results page separately; mark
**All pages and offers reviewed** only after reviewing the entire search.
Incomplete collections remain Action required with captured prices visible.

Snapshots and your selections survive closing the popup. Offline snapshots
are queued on this computer (up to 5 pages, 2 MB each, within the total queue
limit), retrying every 30 seconds. A confirmed save retries with the same ID,
preventing duplicate updates after lost acknowledgements. If a run/result
changes, refresh and review again. Changing the app address does not redirect
queued data to another instance. Discard removes a local snapshot; it cannot
undo a save already accepted by the app.

Page HTML is removed from the queue after saving/discarding. No cookies or
passwords are transferred. Captured page text may include visible personal
information, so capture only the intended marketplace results pages.

Optional extension for Edge/Chrome. v5 also works without it, using marketplace
HTML and manual seller entry.

1. Launch the v5 PriceMonitor.exe.
2. Open edge://extensions (or chrome://extensions), enable Developer mode.
3. Load unpacked and select this folder.
4. Set the app URL to http://127.0.0.1:8050 and connect.

Only Kaina24, Salidzini and Hinnavaatlus are supported. Complete CAPTCHAs yourself
on the marketplace, then use Capture again. Never submit retailer links.
Capture retains seller rows from marketplace HTML. It does not solve CAPTCHAs
or query retailers. A tab-scoped rule prevents capture tabs from navigating to
other domains.

The v5 extension has its own identity and can coexist with the v4 bridge.
The local server and extension must be running on the same computer.
