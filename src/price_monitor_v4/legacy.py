from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from pathlib import Path

import httpx

from .config import Settings


class LegacyService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.process: subprocess.Popen[bytes] | None = None

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.settings.legacy_port}"

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    async def start(self) -> None:
        if not self.settings.legacy_enabled:
            return
        self._prepare_development_runtime()
        if not self.settings.legacy_executable.exists():
            raise RuntimeError(f"Legacy v3 executable is missing: {self.settings.legacy_executable}")
        self._write_legacy_env()
        environment = os.environ.copy()
        environment.update(self.settings.env)
        environment.update(
            {
                "HOST": "127.0.0.1",
                "PORT": str(self.settings.legacy_port),
                "SOURCE_WORKBOOK": str(self.settings.active_workbook.resolve()),
                "DATA_DIR": str(self.settings.legacy_database.parent.resolve()),
                "DATABASE_PATH": str(self.settings.legacy_database.resolve()),
                "EXPORT_DIR": str(self.settings.exports_dir.resolve()),
                "LOG_DIR": str(self.settings.logs_dir.resolve()),
                "ENABLE_SCHEDULER": "false",
            }
        )
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self.process = subprocess.Popen(
            [str(self.settings.legacy_executable)],
            cwd=self.settings.legacy_working_dir,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation_flags,
        )
        async with httpx.AsyncClient(timeout=1.5) as client:
            for _ in range(50):
                if self.process.poll() is not None:
                    raise RuntimeError(f"Legacy v3 service exited with code {self.process.returncode}")
                try:
                    response = await client.get(f"{self.base_url}/health")
                    if response.status_code == 200:
                        return
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.2)
        self.stop()
        raise RuntimeError("Legacy v3 service did not become ready")

    def _prepare_development_runtime(self) -> None:
        if getattr(__import__("sys"), "frozen", False) or self.settings.legacy_executable.exists():
            return
        source_executable = self.settings.root / "PriceMonitor.exe"
        source_internal = self.settings.root / "_internal"
        if not source_executable.exists() or not source_internal.exists():
            return
        self.settings.legacy_working_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_executable, self.settings.legacy_executable)
        destination_internal = self.settings.legacy_working_dir / "_internal"
        if not destination_internal.exists():
            shutil.copytree(source_internal, destination_internal)

    def _write_legacy_env(self) -> None:
        inherited = self.settings.env
        values = {
            "SOURCE_WORKBOOK": str(self.settings.active_workbook.resolve()),
            "DATA_DIR": str(self.settings.legacy_database.parent.resolve()),
            "DATABASE_PATH": str(self.settings.legacy_database.resolve()),
            "EXPORT_DIR": str(self.settings.exports_dir.resolve()),
            "LOG_DIR": str(self.settings.logs_dir.resolve()),
            "SCHEDULE_TIME": inherited.get("SCHEDULE_TIME", "08:00"),
            "SCHEDULE_TIMEZONE": inherited.get("SCHEDULE_TIMEZONE", "Europe/Riga"),
            "ENABLE_SCHEDULER": "false",
            "ENABLE_LIVE_MARKETPLACES": inherited.get("ENABLE_LIVE_MARKETPLACES", "true"),
            "HTTP_TIMEOUT_SECONDS": inherited.get("HTTP_TIMEOUT_SECONDS", "20"),
            "GLOBAL_CONCURRENCY": inherited.get("GLOBAL_CONCURRENCY", "3"),
            "HOST": "127.0.0.1",
            "PORT": str(self.settings.legacy_port),
        }
        content = "\n".join(f"{key}={value}" for key, value in values.items()) + "\n"
        (self.settings.legacy_working_dir / ".env").write_text(content, encoding="utf-8")

    def stop(self) -> None:
        if not self.process or self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)


def safe_filename(value: str) -> str:
    return Path(value).name
