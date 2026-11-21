"""Base service interface for modular document sources."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class BaseService(ABC):
    def __init__(self, name: str, config: dict[str, Any], root: Path):
        self.name = name
        self.config = config
        self.root = root
        self.output_dir = root / config.get("output_dir", f"data/{name}")

    @abstractmethod
    def acquire(self, force: bool = False) -> int:
        """Download / collect documents. Returns number of items acquired."""
        ...

    def ensure_output_dir(self) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        return self.output_dir
