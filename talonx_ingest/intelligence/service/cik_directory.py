"""
talonx_ingest.intelligence.service.cik_directory
================================================
``symbol -> CIK -> company`` resolution for the ingestion service.

Source of truth: SEC's official ``company_tickers.json`` (free, £0), the
same file ``EdgarClient`` already uses. It is cached to local disk
(``<state_dir>/company_tickers.json``) and only re-fetched when the cache
is missing or older than ``company_tickers_max_age_days``.

Two deterministic, explicit escape hatches — never a fuzzy guess:

* ``data/cik_overrides.json`` — a hand-maintained ``{"SYMBOL": {"cik": "...",
  "company_name": "...", "note": "..."}}`` map for tickers the SEC file is
  missing or maps wrongly (e.g. a recent symbol change). Ships empty.
* ``ServiceConfig.KNOWN_NON_FILERS`` — symbols known not to file
  8-K/10-Q/10-K (foreign private issuers, private companies). These are
  reported ``unresolved`` with a reason; the service does not try to map
  them.

An ambiguous or unknown symbol is returned as ``None`` and surfaced by the
watchlist resolver — it is never mapped silently.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

from talonx_ingest.intelligence.service.config import KNOWN_NON_FILERS

logger = logging.getLogger("talonx_ingest.intelligence.service.cik_directory")

_DATA_DIR = Path(__file__).resolve().parent / "data"
_OVERRIDES_FILE = _DATA_DIR / "cik_overrides.json"


@dataclass(frozen=True)
class CikRef:
    symbol: str
    cik: str            # zero-padded 10 digits
    company_name: str
    source: str          # "sec_company_tickers" | "override"


def _pad(cik) -> str:
    return str(cik).strip().lstrip("CIK").zfill(10)


def _load_overrides(path: Path = _OVERRIDES_FILE) -> dict[str, CikRef]:
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("cik_overrides.json unreadable (%s); ignoring", exc)
        return {}
    out: dict[str, CikRef] = {}
    for sym, entry in (raw or {}).items():
        if not isinstance(entry, dict) or "cik" not in entry:
            continue
        s = sym.strip().upper()
        out[s] = CikRef(
            symbol=s,
            cik=_pad(entry["cik"]),
            company_name=str(entry.get("company_name") or s),
            source="override",
        )
    return out


class CikDirectory:
    """Built from an in-memory ``{SYMBOL: CikRef}`` map. Use
    :meth:`from_company_tickers` (offline dict) or :meth:`load` (async,
    disk-cached SEC fetch)."""

    def __init__(
        self,
        by_symbol: dict[str, CikRef],
        *,
        overrides: dict[str, CikRef] | None = None,
        non_filers: dict[str, str] | None = None,
        fetched_at: float | None = None,
        from_cache: bool = False,
    ):
        self._non_filers = dict(non_filers if non_filers is not None else KNOWN_NON_FILERS)
        self._overrides = dict(overrides or {})
        self._map: dict[str, CikRef] = dict(by_symbol)
        # overrides win over the SEC file
        self._map.update(self._overrides)
        self.fetched_at = fetched_at
        self.from_cache = from_cache

    # ------------------------------------------------------------------
    def __len__(self) -> int:
        return len(self._map)

    def known_non_filer(self, symbol: str) -> str | None:
        return self._non_filers.get(symbol.strip().upper())

    def resolve(self, symbol: str) -> CikRef | None:
        s = symbol.strip().upper()
        if s in self._non_filers:
            return None
        return self._map.get(s)

    def resolve_many(self, symbols) -> dict[str, CikRef | None]:
        return {s: self.resolve(s) for s in symbols}

    # ------------------------------------------------------------------
    @classmethod
    def from_company_tickers(
        cls,
        company_tickers: dict,
        *,
        overrides_path: Path = _OVERRIDES_FILE,
        non_filers: dict[str, str] | None = None,
        from_cache: bool = False,
        fetched_at: float | None = None,
    ) -> "CikDirectory":
        by_symbol: dict[str, CikRef] = {}
        for entry in (company_tickers or {}).values():
            if not isinstance(entry, dict):
                continue
            tk = entry.get("ticker")
            ck = entry.get("cik_str", entry.get("cik"))
            if not tk or ck is None:
                continue
            s = str(tk).strip().upper()
            by_symbol[s] = CikRef(
                symbol=s,
                cik=_pad(ck),
                company_name=str(entry.get("title") or s),
                source="sec_company_tickers",
            )
        return cls(
            by_symbol,
            overrides=_load_overrides(overrides_path),
            non_filers=non_filers,
            fetched_at=fetched_at,
            from_cache=from_cache,
        )

    # ------------------------------------------------------------------
    @classmethod
    async def load(
        cls,
        client,
        *,
        cache_path: Path,
        max_age_days: int = 7,
        refresh: bool = False,
    ) -> "CikDirectory":
        """Return a directory from the disk cache when it is present and
        younger than ``max_age_days``; otherwise fetch SEC
        ``company_tickers.json`` through ``client`` (shared rate-limit /
        retry / User-Agent path) and rewrite the cache.

        On a fetch failure with a stale cache present, the stale cache is
        used (logged) — resolution degrades gracefully, it never hard-fails
        the service.
        """
        cache_path = Path(cache_path)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        now = time.time()

        cached_ok = cache_path.is_file() and (
            now - cache_path.stat().st_mtime < max_age_days * 86400
        )
        if cached_ok and not refresh:
            try:
                data = json.loads(cache_path.read_text(encoding="utf-8"))
                return cls.from_company_tickers(
                    data, from_cache=True, fetched_at=cache_path.stat().st_mtime
                )
            except (OSError, ValueError) as exc:
                logger.warning("company_tickers cache unreadable (%s); refetching", exc)

        url = client.config.ticker_map_url
        try:
            raw = await client.fetch_document(url)
            data = json.loads(raw)
        except Exception as exc:  # noqa: BLE001 - degrade to stale cache
            if cache_path.is_file():
                logger.warning(
                    "company_tickers fetch failed (%s); using stale cache %s", exc, cache_path
                )
                data = json.loads(cache_path.read_text(encoding="utf-8"))
                return cls.from_company_tickers(
                    data, from_cache=True, fetched_at=cache_path.stat().st_mtime
                )
            raise

        try:
            cache_path.write_text(json.dumps(data), encoding="utf-8")
        except OSError as exc:  # cache write is best-effort
            logger.warning("could not write company_tickers cache: %s", exc)

        return cls.from_company_tickers(data, from_cache=False, fetched_at=now)
