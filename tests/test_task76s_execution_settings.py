"""Task 76S Stage 2/5 -- per-ticker paper_entry_enabled settings tests.

Pure filesystem/dataclass tests -- no broker, no network, no event bus."""
from __future__ import annotations

import json

from talonx_piv.execution_settings import PaperEntrySettings, load_paper_entry_settings


def test_missing_file_defaults_every_ticker_disabled(tmp_path):
    settings = load_paper_entry_settings(tmp_path / "does_not_exist.json")
    assert settings.enabled_for("AAPL") is False
    assert settings.enabled_for("MSFT") is False


def test_explicit_true_enables_a_ticker(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"AAPL": True}), encoding="utf-8")
    settings = load_paper_entry_settings(path)
    assert settings.enabled_for("AAPL") is True
    assert settings.enabled_for("MSFT") is False  # absent -> disabled


def test_explicit_false_disables_a_ticker(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"AAPL": False}), encoding="utf-8")
    assert load_paper_entry_settings(path).enabled_for("AAPL") is False


def test_malformed_non_dict_json_defaults_all_disabled(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(["AAPL", "MSFT"]), encoding="utf-8")
    settings = load_paper_entry_settings(path)
    assert settings.enabled_for("AAPL") is False


def test_corrupt_json_defaults_all_disabled_not_an_exception(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{not valid json", encoding="utf-8")
    settings = load_paper_entry_settings(path)  # must not raise
    assert settings.enabled_for("AAPL") is False


def test_non_boolean_value_defaults_ticker_disabled(tmp_path):
    """A string "true", 1, or null must not be treated as enabled -- only
    the literal JSON boolean true does."""
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"AAPL": "true", "MSFT": 1, "NVDA": None}), encoding="utf-8")
    settings = load_paper_entry_settings(path)
    assert settings.enabled_for("AAPL") is False
    assert settings.enabled_for("MSFT") is False
    assert settings.enabled_for("NVDA") is False


def test_ticker_lookup_is_case_insensitive(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"AAPL": True}), encoding="utf-8")
    settings = load_paper_entry_settings(path)
    assert settings.enabled_for("aapl") is True


def test_no_settings_object_at_all_defaults_all_disabled():
    """PaperEntrySettings.all_disabled() -- the object PaperLifecycle
    constructs internally when no settings are supplied at all."""
    settings = PaperEntrySettings.all_disabled()
    assert settings.enabled_for("AAPL") is False


def test_for_test_helper_is_explicit_opt_in_only():
    """TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE. Enabling one ticker via the
    test-only constructor must not enable any other ticker."""
    settings = PaperEntrySettings.for_test("AAPL")
    assert settings.enabled_for("AAPL") is True
    assert settings.enabled_for("MSFT") is False
