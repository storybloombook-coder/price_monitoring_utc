from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


def application_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    root: Path
    host: str
    port: int
    legacy_port: int
    open_browser: bool
    legacy_enabled: bool
    catalog_database: Path
    legacy_database: Path
    original_database: Path
    active_workbook: Path
    uploads_dir: Path
    exports_dir: Path
    logs_dir: Path
    legacy_executable: Path
    legacy_working_dir: Path
    env: dict[str, str]

    @classmethod
    def load(cls, root: Path | None = None) -> "Settings":
        app_root = (root or application_root()).resolve()
        file_env = read_env(app_root / ".env")

        def value(name: str, default: str) -> str:
            return os.environ.get(name, file_env.get(name, default))

        data_dir = app_root / value("DATA_DIR", "var")
        if getattr(sys, "frozen", False):
            legacy_executable = app_root / "legacy" / "PriceMonitor-v3.exe"
            legacy_working_dir = legacy_executable.parent
        else:
            legacy_working_dir = data_dir / "legacy-runtime"
            legacy_executable = legacy_working_dir / "PriceMonitor-v3.exe"

        return cls(
            root=app_root,
            host=value("HOST", "127.0.0.1"),
            port=int(value("PORT", "8000")),
            legacy_port=int(value("LEGACY_PORT", "8001")),
            open_browser=as_bool(value("OPEN_BROWSER", "true"), True),
            legacy_enabled=as_bool(value("ENABLE_LEGACY_SERVICE", "true"), True),
            catalog_database=data_dir / "price_monitor_v4.sqlite3",
            legacy_database=data_dir / "price_monitor_v4_legacy.sqlite3",
            original_database=data_dir / "price_monitor.sqlite3",
            active_workbook=data_dir / "v4-active-source.xlsx",
            uploads_dir=data_dir / "uploads",
            exports_dir=app_root / value("EXPORT_DIR", "var/exports"),
            logs_dir=app_root / value("LOG_DIR", "var/logs"),
            legacy_executable=legacy_executable,
            legacy_working_dir=legacy_working_dir,
            env={**file_env, **{key: val for key, val in os.environ.items() if key in file_env}},
        )
