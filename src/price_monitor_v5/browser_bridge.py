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
    automatic: bool = False
    verification_id: str | None = None
    assigned_client: str | None = None

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "shop_key": self.shop_key,
            "model": self.model,
            "url": self.url,
            "automatic": self.automatic,
            "verification_id": self.verification_id,
            # The extension uses this to discard work that belonged to the
            # other browser after an active Chrome/Edge hand-off.
            "assigned_client_id": self.assigned_client,
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
        self.automatic_salidzini = False
        self.open_collect = False
        self._verifications = {}
        self._clients: dict[str, dict[str, Any]] = {}
        self.active_client_id: str | None = None

    def _client(self, client_id="legacy", browser_name=None):
        client_id = str(client_id or "legacy")[:96]
        record = self._clients.setdefault(client_id, {"id":client_id,"browser_name":browser_name or "Browser",
                                                       "last_seen":0.0,"websockets":0,
                                                       "automatic_salidzini":False,"open_collect":False})
        if browser_name:
            record["browser_name"] = str(browser_name)[:48]
        return record

    def client_connected(self, record):
        return record.get("websockets",0) > 0 or (record.get("last_seen",0) > 0 and
               time.monotonic() - record["last_seen"] <= self.connected_window_seconds)

    def active_client(self):
        record = self._clients.get(self.active_client_id) if self.active_client_id else None
        if record and self.client_connected(record):
            return record
        record = next((value for value in self._clients.values() if self.client_connected(value)), None)
        if record:
            self.active_client_id = record["id"]
            self.automatic_salidzini = bool(record.get("automatic_salidzini"))
            self.open_collect = bool(record.get("open_collect"))
        return record

    @property
    def connected(self) -> bool:
        return self.active_client() is not None

    def heartbeat(self, automatic_salidzini=None, open_collect=None, client_id="legacy", browser_name=None) -> None:
        self._last_seen = time.monotonic()
        record = self._client(client_id,browser_name)
        record["last_seen"] = self._last_seen
        if not self.active_client_id:
            self.active_client_id = record["id"]
        if automatic_salidzini is not None:
            record["automatic_salidzini"] = automatic_salidzini is True
            if record["id"] == self.active_client_id:
                self.automatic_salidzini = record["automatic_salidzini"]
        if open_collect is not None:
            record["open_collect"] = open_collect is True
            if record["id"] == self.active_client_id:
                self.open_collect = record["open_collect"]

    def set_active_client(self, client_id):
        record = self._clients.get(str(client_id))
        if not record or not self.client_connected(record):
            raise ValueError("The selected browser extension is not connected")
        if self._jobs:
            raise ValueError("Finish or stop the active browser capture before switching browsers")
        self.active_client_id = record["id"]
        self.automatic_salidzini = bool(record.get("automatic_salidzini"))
        self.open_collect = bool(record.get("open_collect"))
        return self.status()

    def client_name(self, client_id):
        record = self._clients.get(str(client_id))
        return record.get("browser_name") if record else None

    def activate_standby(self, *, exclude=(), allowed=None):
        """Select a healthy connected standby client without user UI races."""
        excluded = {str(value) for value in exclude if value}
        allowed = {str(value) for value in allowed} if allowed is not None else None
        for record in self._clients.values():
            if (record["id"] in excluded or not self.client_connected(record)
                    or not record.get("automatic_salidzini")
                    or (allowed is not None and record["id"] not in allowed)):
                continue
            self.active_client_id = record["id"]
            self.automatic_salidzini = bool(record.get("automatic_salidzini"))
            self.open_collect = bool(record.get("open_collect"))
            return record
        return None

    def begin_verification(self) -> str:
        now = time.monotonic()
        self._verifications = {k:v for k,v in self._verifications.items() if now-v['created_at'] < 3600}
        if len(self._verifications) >= 512:
            raise ValueError('Too many verification sessions; retry later')
        token = str(uuid.uuid4())
        self._verifications[token] = {'id':token, 'state':'pending', 'created_at':now}
        return token

    def verification(self, token):
        return dict(self._verifications[token])

    def finish_verification(self, token, state, **details):
        record = self._verifications.get(token)
        if record and record['state'] == 'pending':
            record.update(state=state, **details)

    def websocket_connected(self, client_id="legacy", browser_name="Browser") -> None:
        self._websocket_connections += 1
        record = self._client(client_id,browser_name)
        record["websockets"] += 1
        self.heartbeat(client_id=client_id,browser_name=browser_name)

    def websocket_disconnected(self, client_id="legacy") -> None:
        self._websocket_connections = max(0, self._websocket_connections - 1)
        record = self._clients.get(str(client_id))
        if record:
            record["websockets"] = max(0,record.get("websockets",0)-1)

    def status(self) -> dict[str, Any]:
        age = time.monotonic() - self._last_seen if self._last_seen else None
        active = self.active_client()
        clients = [{"id":record["id"],"browser_name":record["browser_name"],
                    "connected":self.client_connected(record),
                    "active":record["id"] == self.active_client_id,
                    "last_seen_seconds":round(time.monotonic()-record["last_seen"],1) if record["last_seen"] else None,
                    "transport":"websocket" if record.get("websockets") else "polling"}
                   for record in self._clients.values()]
        return {
            "connected": self.connected,
            "last_seen_seconds": round(age, 1) if age is not None else None,
            "pending_jobs": len(self._jobs),
            "transport": "websocket" if active and active.get("websockets") else ("polling" if self.connected else "offline"),
            "jobs": [job.public() for job in self._jobs.values()],
            "extension_id": EXTENSION_ID,
            "automatic_salidzini": self.automatic_salidzini,
            "open_collect": self.open_collect,
            "active_client_id": self.active_client_id,
            "active_browser": active.get("browser_name") if active else None,
            "clients": clients,
        }

    async def capture(self, shop_key: str, model: str, url: str, *, automatic=False, verification_id=None) -> dict[str, Any]:
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
                automatic=automatic,
                verification_id=verification_id,
            )
            self._jobs[job.id] = job
            self._queue.put_nowait(job.id)
            try:
                return await asyncio.wait_for(asyncio.shield(job.future), timeout=620 if verification_id else self.timeout_seconds)
            except TimeoutError as error:
                raise BrowserBridgeTimeout("The Edge extension did not finish browser verification in time") from error
            finally:
                self._jobs.pop(job.id, None)
                if not job.future.done():
                    job.future.cancel()

    async def next_job(self, wait_seconds: float = 25, client_id="legacy", browser_name="Browser") -> dict[str, Any] | None:
        self.heartbeat(client_id=client_id,browser_name=browser_name)
        if self.active_client_id != str(client_id):
            await asyncio.sleep(min(max(wait_seconds,0),1))
            return None
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
                # A websocket from the previously active browser may already
                # be waiting on the shared queue when the user/server switches
                # Chrome <-> Edge. It must not steal the next job.
                if self.active_client_id != str(client_id):
                    self._queue.put_nowait(job_id)
                    return None
                job.assigned_client = str(client_id)
                return job.public()

    def submit(self, job_id: str, payload: dict[str, Any], client_id="legacy") -> bool:
        job = self._jobs.get(job_id)
        if not job or job.future.done() or (job.assigned_client and job.assigned_client != str(client_id)):
            return False
        # A late result from a stale extension job must not make that browser
        # active again. Heartbeat only after ownership has been validated.
        self.heartbeat(client_id=client_id)
        payload["browser_client_id"] = str(client_id)
        payload["browser_name"] = self.client_name(client_id) or "Browser"
        job.future.set_result(payload)
        return True

    def stop(self) -> None:
        for job in self._jobs.values():
            if not job.future.done():
                job.future.cancel()
        self._jobs.clear()
        self._websocket_connections = 0
        self._clients.clear()
        self.active_client_id = None
