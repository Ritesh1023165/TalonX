"""
tests/test_backtest_reproducibility.py
-------------------------------------------
talonx_backtest.reproducibility: git commit / strategy version /
backtester version / config hash metadata (spec section 7) -- the same
configuration must always hash the same, git_commit must never be
fabricated (falls back to the literal "UNKNOWN"), and the strategy
fingerprint must actually change when strategy source changes.
"""
from __future__ import annotations

import dataclasses
import os
import subprocess as subprocess_module
from pathlib import Path
from unittest.mock import MagicMock

from talonx_backtest.data import load_ohlcv_directory
from talonx_backtest.engine import BacktestConfig
from talonx_backtest.execution import ExecutionConfig
from talonx_backtest.reproducibility import (
    _STRATEGY_FILES,
    build_metadata,
    config_hash,
    get_backtester_version,
    get_dataset_hash,
    get_git_commit,
    get_strategy_version,
    get_working_tree_dirty,
)
from talonx_quant.config import QuantConfig


def test_git_commit_is_a_real_sha_or_the_literal_unknown():
    commit = get_git_commit()
    assert commit == "UNKNOWN" or (len(commit) == 40 and all(c in "0123456789abcdef" for c in commit))


def test_git_commit_never_raises_when_git_is_unavailable(monkeypatch):
    import subprocess as subprocess_module

    def _boom(*args, **kwargs):
        raise FileNotFoundError("git not found")

    monkeypatch.setattr(subprocess_module, "run", _boom)
    assert get_git_commit() == "UNKNOWN"


def test_strategy_version_is_a_stable_12_char_fingerprint():
    v1 = get_strategy_version()
    v2 = get_strategy_version()
    assert v1 == v2
    assert len(v1) == 12


def test_backtester_version_is_present():
    assert get_backtester_version() != ""


def test_same_config_produces_the_same_hash():
    c1 = config_hash(BacktestConfig())
    c2 = config_hash(BacktestConfig())
    assert c1 == c2


def test_different_execution_config_changes_the_hash():
    baseline = config_hash(BacktestConfig())
    changed = config_hash(BacktestConfig(execution=ExecutionConfig(entry_slippage_bps=5.0)))
    assert baseline != changed


def test_different_quant_config_changes_the_hash():
    baseline = config_hash(BacktestConfig())
    changed_qc = dataclasses.replace(QuantConfig(), cooldown_seconds=999.0)
    changed = config_hash(BacktestConfig(quant_config=changed_qc))
    assert baseline != changed


def test_eod_flatten_flag_is_part_of_the_hash():
    enabled = config_hash(BacktestConfig(eod_flatten_enabled=True))
    disabled = config_hash(BacktestConfig(eod_flatten_enabled=False))
    assert enabled != disabled


def test_build_metadata_returns_all_seven_fields():
    meta = build_metadata(BacktestConfig())
    d = meta.to_dict()
    assert set(d.keys()) == {
        "git_commit", "working_tree_dirty", "backtester_version",
        "strategy_version", "config_hash", "dataset_hash", "run_timestamp",
    }
    # working_tree_dirty/dataset_hash are legitimate False/None values,
    # not "blank" -- check presence/non-None on the others instead of
    # bare truthiness. dataset_hash is honestly None here since no
    # dataset_path was given to build_metadata().
    for key in ("git_commit", "backtester_version", "strategy_version", "config_hash", "run_timestamp"):
        assert d[key], f"{key} should not be blank"
    assert d["working_tree_dirty"] in (True, False, None)
    assert d["dataset_hash"] is None


# ------------------------------------------------------------------
# 2026-08-17 Task 5.1: consumer.py added to the strategy fingerprint
# (finding G2), working_tree_dirty added to ReproducibilityMetadata
# (finding G1).
# ------------------------------------------------------------------

def test_consumer_py_is_included_in_the_strategy_fingerprint_files():
    # The engine imports load-bearing gating/scoring logic from
    # consumer.py (_GATE_NAMES, _fails_min_volatility, _opportunity_score,
    # _partition, _trend_gate_applicable) -- strategy_version must cover
    # it, not just strategy.py/indicators.py/config.py/session.py.
    assert any(p.name == "consumer.py" for p in _STRATEGY_FILES)
    # the four previously-covered files must still be present too --
    # additive, not a replacement.
    for name in ("strategy.py", "indicators.py", "config.py", "session.py"):
        assert any(p.name == name for p in _STRATEGY_FILES)


def test_strategy_version_changes_when_a_fingerprinted_file_changes(monkeypatch, tmp_path):
    # Isolates the GENERAL mechanism with temp files rather than touching
    # the real consumer.py -- proves get_strategy_version() genuinely
    # reacts to a change in one of its _STRATEGY_FILES, the same
    # mechanism that now covers consumer.py too.
    from talonx_backtest import reproducibility

    fake_file = tmp_path / "fake_consumer.py"
    fake_file.write_text("original content", encoding="utf-8")
    monkeypatch.setattr(reproducibility, "_STRATEGY_FILES", (fake_file,))

    before = get_strategy_version()
    fake_file.write_text("changed content", encoding="utf-8")
    after = get_strategy_version()

    assert before != after
    assert len(before) == len(after) == 12


def test_working_tree_dirty_is_false_for_a_clean_tree(monkeypatch):
    clean_result = MagicMock(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(subprocess_module, "run", lambda *a, **k: clean_result)
    assert get_working_tree_dirty() is False


def test_working_tree_dirty_is_true_for_a_dirty_tree(monkeypatch):
    dirty_result = MagicMock(returncode=0, stdout=" M talonx_backtest/reproducibility.py\n", stderr="")
    monkeypatch.setattr(subprocess_module, "run", lambda *a, **k: dirty_result)
    assert get_working_tree_dirty() is True


def test_working_tree_dirty_is_none_when_git_is_unavailable(monkeypatch):
    def _boom(*args, **kwargs):
        raise FileNotFoundError("git not found")

    monkeypatch.setattr(subprocess_module, "run", _boom)
    assert get_working_tree_dirty() is None


def test_working_tree_dirty_is_none_on_nonzero_git_exit(monkeypatch):
    not_a_repo = MagicMock(returncode=128, stdout="", stderr="fatal: not a git repository")
    monkeypatch.setattr(subprocess_module, "run", lambda *a, **k: not_a_repo)
    assert get_working_tree_dirty() is None


def test_working_tree_dirty_is_serialized_into_the_metadata_dict():
    meta = build_metadata(BacktestConfig())
    d = meta.to_dict()
    assert "working_tree_dirty" in d
    assert d["working_tree_dirty"] == meta.working_tree_dirty


def test_existing_reproducibility_fields_are_unaffected_by_the_new_field():
    # The five pre-existing fields must keep behaving exactly as before
    # -- same types, same non-blank guarantee -- with working_tree_dirty
    # present alongside them, not replacing or altering any of them.
    meta = build_metadata(BacktestConfig())
    assert isinstance(meta.git_commit, str) and meta.git_commit
    assert isinstance(meta.backtester_version, str) and meta.backtester_version
    assert isinstance(meta.strategy_version, str) and len(meta.strategy_version) == 12
    assert isinstance(meta.config_hash, str) and meta.config_hash
    assert isinstance(meta.run_timestamp, str) and meta.run_timestamp
    assert meta.working_tree_dirty in (True, False, None)


# ------------------------------------------------------------------
# 2026-08-17 Task 5.2: dataset_hash -- a deterministic fingerprint of
# the exact CSV file(s) a backtest run actually consumed (finding
# surfaced in the Task 5 audit: git_commit/strategy_version/config_hash
# together still can't answer "what market-data bytes were used").
# All tests use tmp_path -- never the real repository's market data.
# ------------------------------------------------------------------

def _write_csv(path: Path, content: str = "timestamp,open,high,low,close,volume\n") -> None:
    path.write_text(content, encoding="utf-8")


def test_same_dataset_in_two_different_directories_produces_the_same_hash(tmp_path):
    # TEST 1
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    for d in (dir_a, dir_b):
        _write_csv(d / "AAPL.csv", "timestamp,open,high,low,close,volume\n2026-01-01,1,2,0,1,100\n")
        _write_csv(d / "MSFT.csv", "timestamp,open,high,low,close,volume\n2026-01-01,3,4,2,3,200\n")

    assert get_dataset_hash(dir_a) == get_dataset_hash(dir_b)


def test_changing_one_csvs_content_changes_the_hash(tmp_path):
    # TEST 2
    d = tmp_path / "data"
    d.mkdir()
    _write_csv(d / "AAPL.csv", "timestamp,open,high,low,close,volume\n2026-01-01,1,2,0,1,100\n")
    before = get_dataset_hash(d)

    _write_csv(d / "AAPL.csv", "timestamp,open,high,low,close,volume\n2026-01-01,1,2,0,1,999\n")  # one value changed
    after = get_dataset_hash(d)

    assert before != after


def test_adding_a_csv_changes_the_hash(tmp_path):
    # TEST 3
    d = tmp_path / "data"
    d.mkdir()
    _write_csv(d / "AAPL.csv")
    before = get_dataset_hash(d)

    _write_csv(d / "MSFT.csv")
    after = get_dataset_hash(d)

    assert before != after


def test_removing_a_csv_changes_the_hash(tmp_path):
    # TEST 4
    d = tmp_path / "data"
    d.mkdir()
    _write_csv(d / "AAPL.csv")
    _write_csv(d / "MSFT.csv")
    before = get_dataset_hash(d)

    (d / "MSFT.csv").unlink()
    after = get_dataset_hash(d)

    assert before != after


def test_renaming_a_csv_changes_the_hash(tmp_path):
    # TEST 5
    d = tmp_path / "data"
    d.mkdir()
    _write_csv(d / "AAPL.csv", "same content\n")
    before = get_dataset_hash(d)

    (d / "AAPL.csv").rename(d / "AAPL_renamed.csv")
    after = get_dataset_hash(d)

    assert before != after


def test_creation_order_does_not_affect_the_hash(tmp_path):
    # TEST 6 -- two directories with IDENTICAL content written in
    # different orders (so raw filesystem enumeration order can differ)
    # must still produce the same hash; get_dataset_hash sorts by
    # relative_id itself rather than trusting iteration order.
    dir_a = tmp_path / "created_c_then_a_then_b"
    dir_a.mkdir()
    _write_csv(dir_a / "C.csv", "c-content\n")
    _write_csv(dir_a / "A.csv", "a-content\n")
    _write_csv(dir_a / "B.csv", "b-content\n")

    dir_b = tmp_path / "created_a_then_b_then_c"
    dir_b.mkdir()
    _write_csv(dir_b / "A.csv", "a-content\n")
    _write_csv(dir_b / "B.csv", "b-content\n")
    _write_csv(dir_b / "C.csv", "c-content\n")

    assert get_dataset_hash(dir_a) == get_dataset_hash(dir_b)


def test_modification_time_does_not_affect_the_hash(tmp_path):
    # TEST 7
    d = tmp_path / "data"
    d.mkdir()
    _write_csv(d / "AAPL.csv", "fixed content\n")
    before = get_dataset_hash(d)

    # Set mtime to something wildly different (10 years in the past) --
    # content is untouched.
    far_past = 1_000_000
    os.utime(d / "AAPL.csv", (far_past, far_past))
    after = get_dataset_hash(d)

    assert before == after


def test_large_file_hashing_streams_in_chunks_rather_than_a_single_full_read(tmp_path, monkeypatch):
    # TEST 8 -- forces a tiny chunk size so a modest file requires many
    # read() calls, and counts them directly to prove streaming actually
    # happens rather than one big f.read() -- more convincing than just
    # checking the final hash value is correct.
    from talonx_backtest import reproducibility

    d = tmp_path / "data"
    d.mkdir()
    payload = ("x" * 1000 + "\n") * 50  # ~51KB
    (d / "AAPL.csv").write_text(payload, encoding="utf-8")

    monkeypatch.setattr(reproducibility, "_DATASET_HASH_CHUNK_SIZE", 1024)  # 1KB chunks -> ~51 reads

    read_calls = {"n": 0}
    real_open = open

    def counting_open(*args, **kwargs):
        f = real_open(*args, **kwargs)
        real_read = f.read

        def counting_read(*a, **k):
            read_calls["n"] += 1
            return real_read(*a, **k)

        f.read = counting_read
        return f

    monkeypatch.setattr("builtins.open", counting_open)
    result = get_dataset_hash(d)

    assert result is not None
    assert read_calls["n"] > 10  # many small reads, not one whole-file read


def test_dataset_hash_is_present_in_build_metadata(tmp_path):
    # TEST 9
    d = tmp_path / "data"
    d.mkdir()
    _write_csv(d / "AAPL.csv")

    meta = build_metadata(BacktestConfig(), dataset_path=d)
    assert meta.dataset_hash is not None
    assert len(meta.dataset_hash) == 12
    assert "dataset_hash" in meta.to_dict()


def test_dataset_hash_is_none_when_no_dataset_path_given():
    meta = build_metadata(BacktestConfig())
    assert meta.dataset_hash is None


def test_dataset_hash_is_none_for_a_nonexistent_path(tmp_path):
    assert get_dataset_hash(tmp_path / "does_not_exist") is None


def test_dataset_hash_is_none_for_a_directory_with_no_matching_csvs(tmp_path):
    d = tmp_path / "empty"
    d.mkdir()
    (d / "readme.txt").write_text("not a csv", encoding="utf-8")
    assert get_dataset_hash(d) is None


def test_all_other_reproducibility_fields_unchanged_by_dataset_hash_addition(tmp_path):
    # TEST 10 -- adding dataset_hash must not alter git_commit/
    # working_tree_dirty/backtester_version/strategy_version/config_hash/
    # run_timestamp's own values relative to a call with no dataset_path.
    d = tmp_path / "data"
    d.mkdir()
    _write_csv(d / "AAPL.csv")

    without_dataset = build_metadata(BacktestConfig())
    with_dataset = build_metadata(BacktestConfig(), dataset_path=d)

    assert without_dataset.git_commit == with_dataset.git_commit
    assert without_dataset.working_tree_dirty == with_dataset.working_tree_dirty
    assert without_dataset.backtester_version == with_dataset.backtester_version
    assert without_dataset.strategy_version == with_dataset.strategy_version
    assert without_dataset.config_hash == with_dataset.config_hash
    # only dataset_hash (and run_timestamp, which always varies by call time) differs
    assert without_dataset.dataset_hash is None
    assert with_dataset.dataset_hash is not None


def test_dataset_hash_matches_load_ohlcv_directorys_own_file_selection_rule(tmp_path):
    # TEST 11 -- the fingerprint must correspond to exactly what the
    # actual backtest loader (data.load_ohlcv_directory) reads: a
    # non-CSV file must be ignored by both, and a --symbols filter must
    # exclude the same files from both.
    d = tmp_path / "data"
    d.mkdir()
    _write_csv(d / "AAPL.csv", "timestamp,open,high,low,close,volume\n2026-01-05 14:30:00,1,1,1,1,100\n")
    _write_csv(d / "MSFT.csv", "timestamp,open,high,low,close,volume\n2026-01-05 14:30:00,1,1,1,1,100\n")

    # A non-CSV file present in the directory: the loader ignores it
    # entirely (not a recognized extension) -- the fingerprint must too.
    (d / "notes.txt").write_text("not part of the dataset", encoding="utf-8")
    hash_without_symbols = get_dataset_hash(d)

    # Confirm the loader itself actually reads both symbols when unfiltered.
    loaded_all = load_ohlcv_directory(d, tz="UTC")
    assert set(loaded_all["symbol"].unique()) == {"AAPL", "MSFT"}

    # Adding another non-CSV file must not change the hash (loader would
    # still ignore it) -- confirms .txt files aren't part of "the dataset".
    (d / "another_note.md").write_text("also not part of the dataset", encoding="utf-8")
    assert get_dataset_hash(d) == hash_without_symbols

    # Now apply the SAME --symbols filter to both the real loader and the
    # fingerprint -- both must agree on "AAPL only".
    loaded_aapl_only = load_ohlcv_directory(d, symbols=["AAPL"], tz="UTC")
    assert set(loaded_aapl_only["symbol"].unique()) == {"AAPL"}

    hash_aapl_only = get_dataset_hash(d, symbols=["AAPL"])
    hash_aapl_only_via_full_dataset_minus_msft = get_dataset_hash(d)
    (d / "MSFT.csv").unlink()
    hash_after_removing_msft = get_dataset_hash(d)

    # Filtering to AAPL-only must produce the SAME hash as a directory
    # that only ever physically contained AAPL.csv -- proving the
    # symbol filter really does select the same file set the loader uses.
    assert hash_aapl_only == hash_after_removing_msft
    assert hash_aapl_only != hash_aapl_only_via_full_dataset_minus_msft
