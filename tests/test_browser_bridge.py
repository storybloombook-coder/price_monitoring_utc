import asyncio
import base64
import hashlib
import json
from pathlib import Path

from price_monitor_v4.browser_bridge import BrowserBridge, EXTENSION_ID


def test_browser_bridge_capture_round_trip() -> None:
    async def run() -> None:
        bridge = BrowserBridge(timeout_seconds=2)
        bridge.heartbeat()
        capture = asyncio.create_task(bridge.capture("varle", "55T7B", "https://www.varle.lt/search/?q=55T7B"))
        job = await bridge.next_job(1)
        assert job is not None
        assert job["model"] == "55T7B"
        assert bridge.submit(job["id"], {
            "html": "<html><body>55T7B 368.99 EUR</body></html>",
            "url": "https://www.varle.lt/product/55t7b",
            "security_challenge": False,
        })
        result = await capture
        assert "368.99 EUR" in result["html"]
        assert bridge.status()["pending_jobs"] == 0

    asyncio.run(run())


def test_manifest_key_matches_fixed_extension_id() -> None:
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "edge-extension" / "manifest.json").read_text(encoding="utf-8"))
    public_key = base64.b64decode(manifest["key"])
    digest = hashlib.sha256(public_key).digest()[:16]
    extension_id = "".join(chr(97 + nibble) for byte in digest for nibble in (byte >> 4, byte & 15))
    assert extension_id == EXTENSION_ID
