"""Load and instantiate services from config/services.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .base import BaseService
from .gutenberg import GutenbergService
from .wikipedia import WikipediaService
from .internet_archive import InternetArchiveService


SERVICE_MAP = {
    "bulk_catalog": GutenbergService,
    "dump": WikipediaService,
    "ia_search": InternetArchiveService,
}


def load_config(config_path: Path | str | None = None) -> dict[str, Any]:
    if config_path is None:
        # walk up from this file
        candidates = [
            Path("config/services.yaml"),
            Path(__file__).resolve().parents[3] / "config" / "services.yaml",
        ]
        for c in candidates:
            if c.exists():
                config_path = c
                break
        else:
            raise FileNotFoundError("config/services.yaml not found")
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_services(
    root: Path | None = None,
    config_path: Path | str | None = None,
    only_enabled: bool = True,
) -> list[BaseService]:
    root = root or Path.cwd()
    cfg = load_config(config_path)
    services_cfg = cfg.get("services", {})
    result: list[BaseService] = []
    for name, scfg in services_cfg.items():
        if only_enabled and not scfg.get("enabled", False):
            continue
        stype = scfg.get("type")
        cls = SERVICE_MAP.get(stype)
        if cls is None:
            print(f"[warn] unknown service type '{stype}' for {name} – skipped")
            continue
        result.append(cls(name, scfg, root))
    return result
