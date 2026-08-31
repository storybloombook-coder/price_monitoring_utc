from dataclasses import dataclass
from pathlib import Path
import os
from price_monitor_v4.config import application_root, read_env, as_bool


@dataclass(frozen=True)
class Settings:
    root: Path
    host: str
    port: int
    open_browser: bool
    catalog_database: Path
    uploads_dir: Path
    exports_dir: Path
    env: dict

    @classmethod
    def load(cls, root=None):
        root = (root or application_root()).resolve()
        env = read_env(root / ".env")
        value = lambda key, default: os.environ.get(key, env.get(key, default))
        data = root / value("V5_DATA_DIR", "var/v5")
        return cls(root, value("V5_HOST", "127.0.0.1"), int(value("V5_PORT", "8050")),
                   as_bool(value("OPEN_BROWSER", "true"), True), data / "catalog.sqlite3",
                   data / "uploads", data / "exports", env)
