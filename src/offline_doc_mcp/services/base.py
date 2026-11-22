"""Base service interface for modular document sources."""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from .http import RobotsAwareHTTP


class BaseService(ABC):
    def __init__(self, name: str, config: dict[str, Any], root: Path):
        self.name = name
        self.config = config
        self.root = root
        self.output_dir = root / config.get("output_dir", f"data/{name}")
        self.http = RobotsAwareHTTP(
            config.get("user_agent", "RefactoredSpoonBot/0.2 (+https://github.com/ljrseals-dev/refactored-spoon)"),
            contact=os.environ.get("OFFLINE_DOC_CONTACT") or config.get("contact"),
            timeout=float(config.get("timeout_seconds", 30)),
            min_delay=float(config.get("request_delay_seconds", 1)),
            max_retries=int(config.get("max_retries", 3)),
        )

    @abstractmethod
    def acquire(self, force: bool = False) -> int:
        """Download / collect permitted documents. Returns documents acquired."""
        ...

    def ensure_output_dir(self) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        return self.output_dir

    def close(self) -> None:
        self.http.close()
