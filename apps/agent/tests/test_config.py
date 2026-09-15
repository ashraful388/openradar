"""Tests for the config migration shim and the new fields."""
from __future__ import annotations
import json
from pathlib import Path

import pytest

from openradar import config


def test_load_legacy_run_frequency_every_10_hours(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENRADAR_DATA", str(tmp_path))
    p = Path(tmp_path) / "config.json"
    p.write_text(json.dumps({
        "agent": {"run_frequency": "every_10_hours"},
        "free_detection": {},
        "flagships": {},
        "sources": {},
        "ui": {},
        "verifier": {},
        "notifications": {},
    }))
    cfg = config.load()
    assert cfg["agent"]["run_interval_hours"] == 10
    assert "run_frequency" not in cfg["agent"]
    assert cfg["agent"].get("manual_mode") in (False, None)


def test_load_legacy_run_frequency_every_6_hours(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENRADAR_DATA", str(tmp_path))
    p = Path(tmp_path) / "config.json"
    p.write_text(json.dumps({"agent": {"run_frequency": "every_6_hours"}}))
    cfg = config.load()
    assert cfg["agent"]["run_interval_hours"] == 6


def test_load_legacy_run_frequency_every_24_hours(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENRADAR_DATA", str(tmp_path))
    p = Path(tmp_path) / "config.json"
    p.write_text(json.dumps({"agent": {"run_frequency": "every_24_hours"}}))
    cfg = config.load()
    assert cfg["agent"]["run_interval_hours"] == 24


def test_load_legacy_run_frequency_manual(tmp_path, monkeypatch):
    """The old 'manual' value means manual_mode=True, with the default
    interval retained for the Run now button."""
    monkeypatch.setenv("OPENRADAR_DATA", str(tmp_path))
    p = Path(tmp_path) / "config.json"
    p.write_text(json.dumps({"agent": {"run_frequency": "manual"}}))
    cfg = config.load()
    assert cfg["agent"]["manual_mode"] is True
    assert cfg["agent"]["run_interval_hours"] == 10  # default retained


def test_load_clamps_out_of_range_interval(tmp_path, monkeypatch):
    """A value of 0 or 50 (out of the 1-24 range) is clamped to the
    default 10, not silently accepted."""
    monkeypatch.setenv("OPENRADAR_DATA", str(tmp_path))
    p = Path(tmp_path) / "config.json"
    p.write_text(json.dumps({"agent": {"run_interval_hours": 0}}))
    cfg = config.load()
    assert cfg["agent"]["run_interval_hours"] == 10

    p.write_text(json.dumps({"agent": {"run_interval_hours": 50}}))
    cfg = config.load()
    assert cfg["agent"]["run_interval_hours"] == 10


def test_load_accepts_24(tmp_path, monkeypatch):
    """24 is the upper bound; the clamp accepts it."""
    monkeypatch.setenv("OPENRADAR_DATA", str(tmp_path))
    p = Path(tmp_path) / "config.json"
    p.write_text(json.dumps({"agent": {"run_interval_hours": 24}}))
    cfg = config.load()
    assert cfg["agent"]["run_interval_hours"] == 24


def test_load_keeps_existing_run_interval_hours(tmp_path, monkeypatch):
    """If a newer config already has the new field, don't overwrite it
    with a translation of the legacy value."""
    monkeypatch.setenv("OPENRADAR_DATA", str(tmp_path))
    p = Path(tmp_path) / "config.json"
    p.write_text(json.dumps({"agent": {
        "run_frequency": "every_6_hours",
        "run_interval_hours": 17,  # explicit override
    }}))
    cfg = config.load()
    assert cfg["agent"]["run_interval_hours"] == 17


def test_load_default_has_no_run_frequency(tmp_path, monkeypatch):
    """A fresh config has the new shape, not the legacy one."""
    monkeypatch.setenv("OPENRADAR_DATA", str(tmp_path))
    cfg = config.load()
    assert "run_frequency" not in cfg["agent"]
    assert cfg["agent"]["run_interval_hours"] == 10
    assert cfg["agent"]["llm_orchestration_enabled"] is False
    assert cfg["agent"]["manual_mode"] is False
