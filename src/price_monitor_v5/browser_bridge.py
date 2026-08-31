from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from typing import Any


EXTENSION_ID = "diimecjiomlbokhepgeplonclgfhcifk"
EXTENSION_ORIGIN = f"chrome-extension://{EXTENSION_ID}"


class BrowserBridgeUnavailable(RuntimeError):
    pass


class BrowserBridgeTimeout(RuntimeError):
    pass


@dataclass
class CaptureJob:
    id: str
    shop_key: str
    model: str
    url: str
    created_at: float
    future: asyncio.Future[dict[str, Any]]

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "shop_key": self.shop_key,
            "model": self.model,
            "url": self.url,
        }


class BrowserBridge:
    """In-memory queue connecting shop checks to the local Edge extension."""

    def __init__(self, timeout_seconds: float = 150, connected_window_seconds: float = 45) -> None:
        self.timeout_seconds = timeout_seconds
        self.connected_window_seconds = connected_window_seconds
        self._last_seen = 0.0
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._jobs: dict[str, CaptureJob] = {}
        self._websocket_connections = 0
        self._capture_lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        return self._websocket_connections > 0 or (
            self._last_seen > 0 and time.monotonic() - self._last_seen <= self.connected_window_seconds
        )

    def heartbeat(self) -> None:
        self._last_seen = time.monotonic()

    def websocket_connected(self) -> None:
        self._websocket_connections += 1
        self.heartbeat()

    def websocket_disconnected(self) -> None:
        self._websocket_connections = max(0, self._websocket_connections - 1)

    def status(self) -> dict[str, Any]:
        age = time.monotonic() - self._last_seen if self._last_seen else None
        return {
            "connected": self.connected,
            "last_seen_seconds": round(age, 1) if age is not None else None,
            "pending_jobs": len(self._jobs),
            "transport": "websocket" if self._websocket_connections else ("polling" if self.connected else "offline"),
            "jobs": [job.public() for job in self._jobs.values()],
            "extension_id": EXTENSION_ID,
        }

    async def capture(self, shop_key: str, model: str, url: str) -> dict[str, Any]:
        async with self._capture_lock:
            if not self.connected:
                raise BrowserBridgeUnavailable("The PriceMonitor Edge extension is not connected")
            loop = asyncio.get_running_loop()
            job = CaptureJob(
                id=str(uuid.uuid4()),
                shop_key=shop_key,
                model=model,
                url=url,
                created_at=time.monotonic(),
                future=loop.create_future(),
            )
            self._jobs[job.id] = job
            self._queue.put_nowait(job.id)
            try:
                return await asyncio.wait_for(asyncio.shield(job.future), timeout=self.timeout_seconds)
            except TimeoutError as error:
                raise BrowserBridgeTimeout("The Edge extension did not finish browser verification in time") from error
            finally:
                self._jobs.pop(job.id, None)

    async def next_job(self, wait_seconds: float = 25) -> dict[str, Any] | None:
        self.heartbeat()
        deadline = time.monotonic() + max(0, min(wait_seconds, 25))
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            try:
                job_id = await asyncio.wait_for(self._queue.get(), timeout=remaining)
            except TimeoutError:
                return None
            job = self._jobs.get(job_id)
            if job and not job.future.done():
                return job.public()

    def submit(self, job_id: str, payload: dict[str, Any]) -> bool:
        self.heartbeat()
        job = self._jobs.get(job_id)
        if not job or job.future.done():
            return False
        job.future.set_result(payload)
        return True

    def stop(self) -> None:
        for job in self._jobs.values():
            if not job.future.done():
                job.future.cancel()
        self._jobs.clear()
        self._websocket_connections = 0
