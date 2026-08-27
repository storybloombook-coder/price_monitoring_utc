# PriceMonitor Browser Bridge

1. Start `PriceMonitor.exe`.
2. Open `edge://extensions` in Microsoft Edge.
3. Enable **Developer mode**.
4. Choose **Load unpacked** and select this `edge-extension` folder.
5. Open the **PriceMonitor Browser Bridge** extension and confirm that it says **Connected to PriceMonitor**.

Keep Edge open during monitoring. If a retailer requests a security verification, complete it in the visible tab opened by the extension. Successfully captured tabs close automatically by default.

The extension communicates only with the local PriceMonitor address and the retailer domains listed in `manifest.json`.
