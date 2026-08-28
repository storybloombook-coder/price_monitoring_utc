# PriceMonitor Browser Bridge

1. Start `PriceMonitor.exe`.
2. Open `edge://extensions` in Microsoft Edge.
3. Enable **Developer mode**.
4. Choose **Load unpacked** and select this `edge-extension` folder.
5. Open the **PriceMonitor Browser Bridge** extension and confirm that it says **Connected to PriceMonitor**.

Keep Edge open during monitoring. If a retailer requests a security verification, complete it in the visible tab opened by the extension. Successfully captured tabs close automatically by default.

The bridge maintains a local WebSocket connection to PriceMonitor, sends a keepalive every 20 seconds, and reconnects automatically after worker sleep or a temporary application restart. The 30-second alarm is retained only as a recovery watchdog. A temporary **Reconnecting** state is normal; active jobs are stored locally and resume when the worker wakes.

The extension communicates only with the local PriceMonitor address and the retailer domains listed in `manifest.json`.
