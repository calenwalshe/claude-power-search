"""Tests for configuration."""

import os
import pytest

from power_search.config import Config, ProviderKeyError, configure, get_config


def test_get_key_from_env(monkeypatch):
    monkeypatch.setenv("TEST_KEY", "test-value")
    cfg = Config()
    assert cfg.get_key("TEST_KEY") == "test-value"


def test_get_key_missing():
    cfg = Config()
    assert cfg.get_key("NONEXISTENT_KEY_12345") is None


def test_require_key_raises():
    cfg = Config()
    with pytest.raises(ProviderKeyError, match="MISSING_KEY"):
        cfg.require_key("MISSING_KEY")


def test_configure_updates_preference():
    configure(prefer="cheapest")
    assert get_config().prefer == "cheapest"
    configure(prefer="smart")  # reset


def test_configure_rejects_unknown():
    with pytest.raises(ValueError, match="Unknown config key"):
        configure(fake_option=True)
