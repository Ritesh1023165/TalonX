"""
talonx_backtest.data
------------------------
Historical-data abstraction: loads 1-minute OHLCV bars (per symbol) into
a normalized in-memory form, and runs a data-quality pass BEFORE any
backtest is allowed to run on them.

Required columns (Requirement 2 of the backtest spec): timestamp, symbol,
open, high, low, close, volume. Only 1-minute OHLCV is required as input
-- HTF (15-minute) bars are reconstructed from this by
talonx_quant.aggregation.HtfBarAggregator (see engine.py), the SAME
aggregator the live consumer uses, not a second implementation.

This module never silently repairs bad data (Requirement 18): loading
never drops/fixes rows on its own. `check_data_quality` reports every
issue found; callers decide what to do about it (typically: fix the
source data, or explicitly call `sort_and_dedupe` and re-report).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import timezone
from pathlib import Path

import pandas as pd

from talonx_quant.session import get_session

_REQUIRED_COLUMNS = ("timestamp", "open", "high", "low", "close", "volume")


class DataValidationError(ValueError):
    """Raised when a dataset contains corruption too severe to safely
    backtest (see DataQualityReport.has_critical_corruption /
    abort_on_critical_corruption below) -- NaN/infinite values,
    non-positive prices, a physically impossible OHLC relationship, or
    negative volume. These are never auto-repaired; the caller must fix
    the source data."""


@dataclass(frozen=True)
class DataQualityReport:
    """One data-quality report per symbol. Every count is exact, never
    estimated -- see check_data_quality's own docstring for how each is
    computed. `is_clean` is a convenience (True iff every issue count is
    zero); the individual counts are what a caller should actually act
    on, not the boolean alone."""

    symbol: str
    rows: int
    duplicate_timestamps: int
    out_of_order_timestamps: int
    missing_bars: int
    invalid_prices: int  # zero/negative open/high/low/close
    invalid_ohlc_relationship: int  # high < low, or close/open outside [low, high]
    negative_volume: int
    nan_values: int
    infinite_values: int
    timezone: str
    first_timestamp: pd.Timestamp | None
    last_timestamp: pd.Timestamp | None
    inferred_bar_interval_seconds: float | None
    missing_bar_gaps: list[tuple[pd.Timestamp, pd.Timestamp]] = field(default_factory=list, repr=False)
    # Expected-vs-unexpected gap classification (spec section 6): a
    # missing bar outside the REGULAR session (09:30-16:00 ET -- i.e.
    # overnight/weekend/holiday closure, OR simply a pre-market minute a
    # dataset never covered, which is extremely common and not itself a
    # defect) is EXPECTED. A missing bar INSIDE the regular session is
    # the one that actually indicates a data problem. Both are already
    # counted once each in `missing_bars` above; these two fields are
    # that same total split by cause, not an additional count.
    expected_session_gap_bars: int = 0
    unexpected_intra_session_gap_bars: int = 0

    @property
    def has_critical_corruption(self) -> bool:
        """True if this dataset contains corruption severe enough that a
        backtest run on it should be REFUSED, not merely warned about --
        see DataValidationError/abort_on_critical_corruption. Duplicate
        or out-of-order timestamps are NOT included here: both are
        mechanically recoverable via sort_and_dedupe, so they're
        `has_recoverable_issues` instead."""
        return (
            self.invalid_prices > 0
            or self.invalid_ohlc_relationship > 0
            or self.negative_volume > 0
            or self.nan_values > 0
            or self.infinite_values > 0
        )

    @property
    def has_recoverable_issues(self) -> bool:
        """True if this dataset has issues that sort_and_dedupe (the
        one opt-in repair helper this module provides) can actually
        fix -- duplicate or out-of-order timestamps. Does NOT include
        missing bars: a gap isn't something dedup/sort can invent data
        to fill."""
        return self.duplicate_timestamps > 0 or self.out_of_order_timestamps > 0

    @property
    def is_clean(self) -> bool:
        return not self.has_critical_corruption and not self.has_recoverable_issues

    def summary(self) -> str:
        lines = [
            f"Data-quality report: {self.symbol}",
            f"  Rows:                    {self.rows:,}",
            f"  Range:                   {self.first_timestamp} -> {self.last_timestamp}",
            f"  Timezone:                {self.timezone}",
            f"  Inferred bar interval:   {self.inferred_bar_interval_seconds}s",
            f"  Duplicate timestamps:    {self.duplicate_timestamps}",
            f"  Out-of-order timestamps: {self.out_of_order_timestamps}",
            f"  Missing bars (total):    {self.missing_bars} ({len(self.missing_bar_gaps)} gap(s))",
            f"    Expected (session closed):    {self.expected_session_gap_bars}",
            f"    Unexpected (inside session):  {self.unexpected_intra_session_gap_bars}",
            f"  Invalid prices (<=0):    {self.invalid_prices}",
            f"  Invalid OHLC relations:  {self.invalid_ohlc_relationship}",
            f"  Negative volume:         {self.negative_volume}",
            f"  NaN values:              {self.nan_values}",
            f"  Infinite values:         {self.infinite_values}",
            f"  CRITICAL CORRUPTION:     {'YES -- backtest must be aborted' if self.has_critical_corruption else 'no'}",
        ]
        return "\n".join(lines)


def abort_on_critical_corruption(reports: dict[str, DataQualityReport]) -> None:
    """Raises DataValidationError if ANY report has
    has_critical_corruption -- the CLI (and any other caller) must call
    this BEFORE running a backtest and let the exception propagate,
    rather than silently continuing on corrupted data (spec section 5).
    A no-op when every report is free of critical corruption; duplicate/
    out-of-order timestamps (recoverable) do not trigger this."""
    bad = {symbol: r for symbol, r in reports.items() if r.has_critical_corruption}
    if not bad:
        return
    lines = ["Critical data corruption detected -- backtest aborted. Fix the source data before retrying."]
    for symbol, r in bad.items():
        lines.append(
            f"  {symbol}: invalid_prices={r.invalid_prices} invalid_ohlc_relationship={r.invalid_ohlc_relationship} "
            f"negative_volume={r.negative_volume} nan_values={r.nan_values} infinite_values={r.infinite_values}"
        )
    raise DataValidationError("\n".join(lines))


def load_ohlcv_csv(
    path: str | Path,
    symbol: str | None = None,
    tz: str = "UTC",
) -> pd.DataFrame:
    """Loads a single-symbol 1-minute OHLCV CSV with at least the columns
    timestamp,open,high,low,close,volume (case-insensitive; a `symbol`
    column is used instead of the `symbol` argument if present).

    `tz`: the IANA timezone naive timestamps in the file should be
    interpreted as (default UTC, matching every other bar_timestamp
    convention in talonx_quant). Already-tz-aware timestamps are
    converted to UTC and left alone otherwise.

    Does NOT sort, dedupe, or otherwise repair the data -- see this
    module's own docstring. Call check_data_quality on the result before
    using it in a backtest.
    """
    path = Path(path)
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]

    missing = [c for c in _REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"{path}: missing required column(s): {missing}")

    df["timestamp"] = _parse_and_localize(df["timestamp"], tz, source=str(path))

    if "symbol" not in df.columns:
        if symbol is None:
            raise ValueError(f"{path}: no `symbol` column and no `symbol` argument given")
        df["symbol"] = symbol.upper()
    else:
        df["symbol"] = df["symbol"].str.upper()

    return df[["timestamp", "symbol", "open", "high", "low", "close", "volume"]].copy()


def from_dataframe(
    df: pd.DataFrame,
    symbol: str | None = None,
    tz: str = "UTC",
) -> pd.DataFrame:
    """Same normalization as load_ohlcv_csv, for a DataFrame already in
    memory (e.g. built by a test fixture, or returned by a vendor SDK)."""
    df = df.copy()
    df.columns = [c.strip().lower() for c in df.columns]
    missing = [c for c in _REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"missing required column(s): {missing}")

    df["timestamp"] = _parse_and_localize(df["timestamp"], tz, source="<dataframe>")

    if "symbol" not in df.columns:
        if symbol is None:
            raise ValueError("no `symbol` column and no `symbol` argument given")
        df["symbol"] = symbol.upper()
    else:
        df["symbol"] = df["symbol"].astype(str).str.upper()

    return df[["timestamp", "symbol", "open", "high", "low", "close", "volume"]].copy()


def _parse_and_localize(raw: pd.Series, tz: str, source: str) -> pd.Series:
    """Parses a raw timestamp column and normalizes it to tz-aware UTC.
    Naive timestamps are localized to `tz` first (spec section 12 --
    `--tz` is how a caller says what timezone naive timestamps in their
    file actually are; UTC by default, matching every other
    bar_timestamp convention in talonx_quant).

    DST safety: `nonexistent="shift_forward"` and `ambiguous="NaT"`
    handle the two DST-transition edge cases explicitly rather than
    letting pandas raise -- a spring-forward "missing" local hour is
    shifted forward to the next valid instant, and a fall-back
    "ambiguous" hour (which occurs twice) becomes NaT rather than an
    unchecked guess at which occurrence was meant. Either produces an
    explicit, checked failure below (an "unusable timestamp" per spec
    section 5), never a silent wrong answer.
    """
    parsed = pd.to_datetime(raw, utc=False)
    if parsed.dt.tz is None:
        try:
            localized = parsed.dt.tz_localize(tz, nonexistent="shift_forward", ambiguous="NaT")
        except Exception as exc:  # noqa: BLE001 -- any tz_localize failure is an unusable-timestamp abort
            raise DataValidationError(f"{source}: could not interpret timestamps in timezone {tz!r}: {exc}") from exc
        result = localized.dt.tz_convert("UTC")
    else:
        result = parsed.dt.tz_convert("UTC")

    if result.isna().any():
        bad_count = int(result.isna().sum())
        raise DataValidationError(
            f"{source}: {bad_count} unusable timestamp(s) -- unparseable, or ambiguous under DST "
            f"for timezone {tz!r}. Backtest aborted; fix the source data before retrying."
        )
    return result


def load_ohlcv_directory(
    root: str | Path,
    symbols: list[str] | None = None,
    tz: str = "UTC",
) -> pd.DataFrame:
    """Loads and concatenates a directory of per-symbol OHLCV CSVs into
    one normalized multi-symbol frame. Supports two layouts:

      data/AAPL/2024.csv, data/AAPL/2025.csv, data/MSFT/2024.csv, ...
          -- one subdirectory per symbol (the subdirectory name is the
          symbol), any number of CSV files inside it, concatenated and
          sorted by timestamp. A file without its own `symbol` column
          gets the subdirectory's name.

      data/AAPL.csv, data/MSFT.csv, ...
          -- a flat directory of one CSV per symbol, named
          `<SYMBOL>.csv`. The file's stem (uppercased) is used as the
          symbol for any file without its own `symbol` column.

    Both layouts may be present at once. `symbols`, if given, filters to
    just those tickers (case-insensitive) -- files for any other symbol
    are skipped without being read. Raises FileNotFoundError if `root`
    doesn't exist, and ValueError if nothing matching was found.

    Does not sort/dedupe across files beyond a final chronological sort
    per symbol -- run check_dataset_quality on the result before backtesting,
    same as any other loader in this module.
    """
    root = Path(root)
    if not root.is_dir():
        raise FileNotFoundError(f"{root} is not a directory")

    wanted = {s.upper() for s in symbols} if symbols else None
    frames: list[pd.DataFrame] = []

    for entry in sorted(root.iterdir()):
        if entry.is_dir():
            symbol = entry.name.upper()
            if wanted is not None and symbol not in wanted:
                continue
            for csv_path in sorted(entry.glob("*.csv")):
                frames.append(load_ohlcv_csv(csv_path, symbol=symbol, tz=tz))
        elif entry.is_file() and entry.suffix.lower() == ".csv":
            symbol = entry.stem.upper()
            if wanted is not None and symbol not in wanted:
                continue
            frames.append(load_ohlcv_csv(entry, symbol=symbol, tz=tz))

    if not frames:
        raise ValueError(f"no matching OHLCV CSV files found under {root}")

    combined = pd.concat(frames, ignore_index=True)
    return combined.sort_values(["symbol", "timestamp"], kind="mergesort").reset_index(drop=True)


def _infer_interval_seconds(sorted_timestamps: pd.Series) -> float | None:
    if len(sorted_timestamps) < 3:
        return None
    diffs = sorted_timestamps.diff().dropna().dt.total_seconds()
    diffs = diffs[diffs > 0]
    if diffs.empty:
        return None
    return float(diffs.mode().iloc[0])


def check_data_quality(df: pd.DataFrame, symbol: str | None = None) -> DataQualityReport:
    """Runs every check called out by the backtest spec (Requirement 18)
    on a single symbol's OHLCV rows, exactly as loaded -- makes no
    changes to `df`. `symbol` is used only for the report label; pass it
    explicitly when `df` may contain more than one distinct value in its
    `symbol` column (this function still evaluates the WHOLE frame as one
    series, so callers with multi-symbol data should call this once per
    symbol via check_dataset_quality below instead).
    """
    label = symbol or (df["symbol"].iloc[0] if "symbol" in df.columns and not df.empty else "UNKNOWN")
    rows = len(df)
    if rows == 0:
        return DataQualityReport(
            symbol=label, rows=0, duplicate_timestamps=0, out_of_order_timestamps=0,
            missing_bars=0, invalid_prices=0, invalid_ohlc_relationship=0, negative_volume=0,
            nan_values=0, infinite_values=0, timezone="n/a", first_timestamp=None,
            last_timestamp=None, inferred_bar_interval_seconds=None,
        )

    ts = df["timestamp"]
    duplicate_timestamps = int(ts.duplicated().sum())

    # Out-of-order: a row whose timestamp is earlier than the row before
    # it IN FILE ORDER (not sorted order) -- sorting first would hide
    # exactly the defect this check exists to catch.
    out_of_order = int((ts.diff().dt.total_seconds() < 0).sum())

    price_cols = df[["open", "high", "low", "close"]]
    numeric_prices = price_cols.apply(pd.to_numeric, errors="coerce")
    invalid_prices = int((numeric_prices <= 0).sum().sum())

    high, low, open_, close = df["high"], df["low"], df["open"], df["close"]
    bad_relationship = (
        (high < low)
        | (open_ > high) | (open_ < low)
        | (close > high) | (close < low)
    )
    invalid_ohlc_relationship = int(bad_relationship.fillna(False).sum())

    negative_volume = int((pd.to_numeric(df["volume"], errors="coerce") < 0).sum())

    numeric_all = df[["open", "high", "low", "close", "volume"]].apply(pd.to_numeric, errors="coerce")
    nan_values = int(numeric_all.isna().sum().sum())
    infinite_values = int(numeric_all.apply(lambda col: (~col.isna() & ~col.apply(math.isfinite)).sum()).sum())

    sorted_ts = ts.sort_values().reset_index(drop=True)
    interval_seconds = _infer_interval_seconds(sorted_ts)

    missing_bars = 0
    expected_gap_bars = 0
    unexpected_gap_bars = 0
    gaps: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    if interval_seconds:
        deduped_sorted = sorted_ts.drop_duplicates()
        gap_seconds = deduped_sorted.diff().dt.total_seconds()
        for i, gap in enumerate(gap_seconds):
            if pd.isna(gap) or gap <= interval_seconds * 1.5:
                continue
            missing_here = int(round(gap / interval_seconds)) - 1
            if missing_here <= 0:
                continue
            missing_bars += missing_here
            gaps.append((deduped_sorted.iloc[i - 1], deduped_sorted.iloc[i]))

            # Session-aware classification of EACH missing minute in this
            # gap (spec section 6): only a missing REGULAR-session
            # (09:30-16:00 ET) minute is flagged UNEXPECTED. Both
            # "closed" (overnight/weekend/outside the 04:00-16:00 ET
            # window) AND "pre_market" count as EXPECTED here --
            # overnight/weekend closure is an obvious market fact, and a
            # huge fraction of legitimately-sourced 1-minute equity
            # datasets simply don't include pre-market bars at all (many
            # vendors don't offer them, or a user only cares about
            # regular-session evaluation) -- that absence is normal, not
            # a data defect, so it must not drown out a genuine
            # regular-session hole in noise.
            cursor = deduped_sorted.iloc[i - 1] + pd.Timedelta(seconds=interval_seconds)
            for _ in range(missing_here):
                if get_session(cursor) == "regular":
                    unexpected_gap_bars += 1
                else:
                    expected_gap_bars += 1
                cursor += pd.Timedelta(seconds=interval_seconds)

    tzinfo = str(ts.dt.tz) if hasattr(ts.dt, "tz") and ts.dt.tz is not None else "naive"

    return DataQualityReport(
        symbol=label,
        rows=rows,
        duplicate_timestamps=duplicate_timestamps,
        out_of_order_timestamps=out_of_order,
        missing_bars=missing_bars,
        invalid_prices=invalid_prices,
        invalid_ohlc_relationship=invalid_ohlc_relationship,
        negative_volume=negative_volume,
        nan_values=nan_values,
        infinite_values=infinite_values,
        timezone=tzinfo,
        first_timestamp=sorted_ts.iloc[0],
        last_timestamp=sorted_ts.iloc[-1],
        inferred_bar_interval_seconds=interval_seconds,
        missing_bar_gaps=gaps,
        expected_session_gap_bars=expected_gap_bars,
        unexpected_intra_session_gap_bars=unexpected_gap_bars,
    )


def check_dataset_quality(df: pd.DataFrame) -> dict[str, DataQualityReport]:
    """check_data_quality, run once per distinct `symbol` in a
    multi-symbol frame."""
    reports: dict[str, DataQualityReport] = {}
    for symbol, group in df.groupby("symbol"):
        reports[symbol] = check_data_quality(group.reset_index(drop=True), symbol=symbol)
    return reports


def sort_and_dedupe(df: pd.DataFrame, keep: str = "last") -> pd.DataFrame:
    """The ONLY data-repair helper this module provides, and it is never
    called implicitly -- a caller must opt in explicitly, per
    Requirement 18 ("do not silently repair bad data"). Sorts by
    (symbol, timestamp) and drops duplicate (symbol, timestamp) rows,
    keeping `keep` ("last" by default -- the most recently reported value
    for a re-reported bucket, matching buffer.py's own upsert-by-
    timestamp convention). Returns a NEW frame; the caller should re-run
    check_data_quality/check_dataset_quality on the result and log what
    changed, not assume this made the data perfect."""
    out = df.sort_values(["symbol", "timestamp"], kind="mergesort")
    out = out.drop_duplicates(subset=["symbol", "timestamp"], keep=keep)
    return out.reset_index(drop=True)


def to_utc_naive_free(timestamp) -> pd.Timestamp:
    """Normalizes a single timestamp to tz-aware UTC, matching every
    other timestamp convention in this package -- naive is assumed UTC."""
    ts = pd.Timestamp(timestamp)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
