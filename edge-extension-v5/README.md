# PriceMonitor v5 Marketplace Bridge

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
