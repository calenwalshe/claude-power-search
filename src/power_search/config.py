"""Configuration — env vars, budget, preferences."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    daily_budget: float | None = None  # USD hard cap per day; None = unlimited
    prefer: str = "smart"  # "smart" (best fit), "cheapest", "quality"
    db_path: Path = field(default_factory=lambda: Path.home() / ".power-search" / "usage.db")
    enabled_providers: set[str] = field(default_factory=set)  # empty = all

    def get_key(self, env_var: str) -> str | None:
        """Get an API key from the environment. Never hardcoded."""
        return os.environ.get(env_var)

    def require_key(self, env_var: str) -> str:
        """Get an API key or raise with a clear message."""
        val = self.get_key(env_var)
        if not val:
            raise ProviderKeyError(env_var)
        return val


class ProviderKeyError(Exception):
    def __init__(self, key_name: str):
        self.key_name = key_name
        super().__init__(f"{key_name} not found in environment. Set it before using this provider.")


# Module-level singleton
_config = Config()


def configure(**kwargs) -> Config:
    """Update global config. Returns the config for chaining."""
    global _config
    for k, v in kwargs.items():
        if hasattr(_config, k):
            setattr(_config, k, v)
        else:
            raise ValueError(f"Unknown config key: {k}")
    return _config


def get_config() -> Config:
    return _config
