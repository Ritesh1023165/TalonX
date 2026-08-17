"""
talonx_backtest.reproducibility
------------------------------------
Metadata every backtest result should carry so it can actually be
reproduced later: the exact code involved, the full effective
configuration, and when it ran. Never fabricates a value it can't
determine -- an unavailable git commit is recorded as the literal
string "UNKNOWN", not omitted or guessed.

This project defines no formal semantic version for either the
strategy or the backtester, so both "version" fields here are content
fingerprints (sha256, first 12 hex chars) rather than invented version
numbers:
  - strategy_version: fingerprint of talonx_quant's own strategy/
    indicator/config/session source files -- changes IF AND ONLY IF the
    frozen strategy's own code changes.
  - backtester_version: talonx_backtest.__version__ if this package
    ever adopts one; falls back to "UNKNOWN" rather than inventing one.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_STRATEGY_FILES = (
    _REPO_ROOT / "talonx_quant" / "strategy.py",
    _REPO_ROOT / "talonx_quant" / "indicators.py",
    _REPO_ROOT / "talonx_quant" / "config.py",
    _REPO_ROOT / "talonx_quant" / "session.py",
    # 2026-08-17 Task 5 audit (finding G2): engine.py imports _GATE_NAMES/
    # _fails_min_volatility/_opportunity_score/_partition/
    # _trend_gate_applicable directly from consumer.py -- load-bearing for
    # every backtest's gating and opportunity scoring, and one of the four
    # files every task in this project treats as frozen. Omitting it here
    # meant strategy_version could stay identical across two runs that
    # actually used different consumer.py gate/scoring logic.
    _REPO_ROOT / "talonx_quant" / "consumer.py",
)


def get_git_commit() -> str:
    """The current HEAD commit SHA, or the literal string "UNKNOWN" if
    git isn't available, this isn't a git checkout, or the command
    otherwise fails -- never guessed, never silently omitted."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=_REPO_ROOT, capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return "UNKNOWN"
    if result.returncode != 0:
        return "UNKNOWN"
    sha = result.stdout.strip()
    return sha if sha else "UNKNOWN"


def get_working_tree_dirty() -> bool | None:
    """True if `git status --porcelain` reports any pending change
    (staged, unstaged, or untracked), False if the tree is clean, or
    None if this can't actually be determined (git unavailable, not a
    git checkout, or the command otherwise fails) -- same "never
    guessed, never silently omitted" posture as get_git_commit() above,
    just in bool|None form since there's no natural "UNKNOWN" string
    equivalent for a boolean. A None here must NOT be read as "clean" by
    any caller: a result built with git_commit=<some SHA> while the tree
    was actually dirty (uncommitted source changes beyond that commit)
    is NOT fully reproducible from the commit alone (2026-08-17 Task 5
    audit, finding G1 -- Tasks 3 and 4 were both run this way)."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=_REPO_ROOT, capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return bool(result.stdout.strip())


def get_strategy_version() -> str:
    """sha256 (first 12 hex chars) of the frozen strategy's own source
    files. A missing file contributes a distinct, deterministic marker
    to the hash rather than silently being skipped, so a broken
    checkout doesn't masquerade as a valid fingerprint."""
    digest = hashlib.sha256()
    for path in _STRATEGY_FILES:
        try:
            digest.update(path.read_bytes())
        except OSError:
            digest.update(b"MISSING:" + str(path).encode())
    return digest.hexdigest()[:12]


def get_backtester_version() -> str:
    import talonx_backtest
    return getattr(talonx_backtest, "__version__", "UNKNOWN")


_DATASET_HASH_CHUNK_SIZE = 1024 * 1024  # 1 MiB -- stream, never load a whole CSV into memory just to hash it


def _dataset_files(path: Path, symbols: list[str] | None) -> list[tuple[str, Path]]:
    """Returns (relative_id, absolute_path) pairs for exactly the CSV
    file(s) talonx_backtest.data's loaders would actually read for this
    `path`/`symbols` combination -- mirrors load_ohlcv_directory's own
    flat-file/subdirectory/symbol-filter selection rule (data.py) rather
    than inventing a second definition of "the dataset". `relative_id`
    is POSIX-style (forward slashes, no drive letter, no parent
    directories outside `path`) so the same logical dataset at a
    different absolute path/machine still identifies the same way.

    A single-file `path` always yields just that one file (its bare
    filename, no directory component) -- `symbols` filtering only
    applies to a directory `path`, matching cli.py's own --symbols
    semantics: for a directory load it decides which FILES get read at
    all; for a single-file load it only filters already-loaded ROWS
    afterward, which this function -- answering "which files were
    read", not "which rows survived --start/--end/--symbols row
    filtering" -- has no reason to account for."""
    if path.is_file():
        return [(path.name, path)]
    if not path.is_dir():
        return []

    wanted = {s.upper() for s in symbols} if symbols else None
    found: list[tuple[str, Path]] = []
    for entry in sorted(path.iterdir()):
        if entry.is_dir():
            symbol = entry.name.upper()
            if wanted is not None and symbol not in wanted:
                continue
            for csv_path in sorted(entry.glob("*.csv")):
                found.append((csv_path.relative_to(path).as_posix(), csv_path))
        elif entry.is_file() and entry.suffix.lower() == ".csv":
            symbol = entry.stem.upper()
            if wanted is not None and symbol not in wanted:
                continue
            found.append((entry.relative_to(path).as_posix(), entry))
    return found


def get_dataset_hash(path: str | Path, symbols: list[str] | None = None) -> str | None:
    """sha256 (first 12 hex chars, matching get_strategy_version/
    config_hash's own truncation convention) over exactly the CSV
    file(s) a backtest run actually consumed: each matching file's
    relative filename (POSIX-style, so it's independent of absolute
    path/machine/OS) followed by that file's own bytes, streamed in
    fixed-size chunks -- never a whole-file read, since real historical
    datasets can be large -- for every matching file in canonical
    (relative_id, lexicographic) order regardless of filesystem
    enumeration order. Two copies of the same logical dataset at
    different absolute paths/machines produce the SAME hash; adding,
    removing, renaming, or changing the content of any file changes it;
    mtimes/inodes are never consulted.

    Returns None if `path` doesn't exist or no matching file(s) were
    found -- never a fabricated hash for a dataset that isn't really
    there, same "never guess" posture as get_git_commit()/
    get_working_tree_dirty() above. This function only fingerprints
    FILE identity/content -- it deliberately does not know about
    --start/--end row-level date filtering, which is a config-level
    concern, not a dataset-identity one."""
    root = Path(path)
    files = _dataset_files(root, symbols)
    if not files:
        return None

    digest = hashlib.sha256()
    for relative_id, file_path in sorted(files, key=lambda pair: pair[0]):
        digest.update(relative_id.encode("utf-8"))
        try:
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(_DATASET_HASH_CHUNK_SIZE), b""):
                    digest.update(chunk)
        except OSError:
            digest.update(b"UNREADABLE:" + relative_id.encode("utf-8"))
    return digest.hexdigest()[:12]


def _to_jsonable(obj):
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: _to_jsonable(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    return obj


def config_hash(config) -> str:
    """sha256 (first 12 hex chars) of every field of a BacktestConfig
    (QuantConfig + ExecutionConfig + backtest-mechanics settings) that
    affects behavior. Two runs with the SAME config_hash used the exact
    same effective configuration -- not just "similar" settings."""
    payload = _to_jsonable(config)
    encoded = json.dumps(payload, sort_keys=True, default=str).encode()
    return hashlib.sha256(encoded).hexdigest()[:12]


@dataclass(frozen=True)
class ReproducibilityMetadata:
    git_commit: str
    # bool|None -- see get_working_tree_dirty()'s own docstring for why
    # this isn't a plain bool: None means "couldn't be determined",
    # never silently treated as a clean tree.
    working_tree_dirty: bool | None
    backtester_version: str
    strategy_version: str
    config_hash: str
    # str|None -- None means no dataset_path was given to build_metadata()
    # (the caller didn't know/pass one), NOT "hashed an empty dataset".
    # See get_dataset_hash()'s own docstring for the None-vs-empty-dataset
    # distinction (2026-08-17 Task 5.2: closes the "what exact market-data
    # bytes were used" gap left open by Task 5.1's git/code/config
    # fingerprints alone).
    dataset_hash: str | None
    run_timestamp: str

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


def build_metadata(
    config,
    dataset_path: str | Path | None = None,
    dataset_symbols: list[str] | None = None,
) -> ReproducibilityMetadata:
    """`dataset_path`/`dataset_symbols`, if given, are exactly what a
    caller (e.g. cli.py) loaded its input data from/with -- passed
    straight through to get_dataset_hash(). Omitting `dataset_path`
    (the default) yields dataset_hash=None rather than guessing or
    hashing an unrelated default location; a caller building metadata
    with no knowledge of the original input files (e.g. a test building
    a BacktestConfig directly) gets an honestly absent dataset_hash, not
    a fabricated one."""
    return ReproducibilityMetadata(
        git_commit=get_git_commit(),
        working_tree_dirty=get_working_tree_dirty(),
        backtester_version=get_backtester_version(),
        strategy_version=get_strategy_version(),
        config_hash=config_hash(config),
        dataset_hash=None if dataset_path is None else get_dataset_hash(dataset_path, dataset_symbols),
        run_timestamp=datetime.now(timezone.utc).isoformat(),
    )
