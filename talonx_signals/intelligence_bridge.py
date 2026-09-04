"""Task 99B -- live bridge from the 96A/96B intelligence stores + the
watchlist earnings calendar into the Task 99A dispatch bus.

  EarningsRadarBridge   watchlist.upcoming_earnings  -> RADAR card rows
  PostEarningsBridge     96A EARNINGS_RESULTS events  -> POST-EARNINGS card rows
                         (+96C what_changed, +96D insider, +96E band)
  BridgeHealth           earnings + 96B freshness + bridge counters

Read-only over existing operational stores. NO new SEC polling, NO paid data,
NO AI. The 96-derived content is DESCRIPTIVE ONLY -- no BUY/SELL/BULLISH/
BEARISH/target/expected-return. Directional technical interpretation stays in
the Task 99A signal lane.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Callable

from talonx_signals.schemas import make_event_update_id, make_radar_id

PriceLookup = Callable[[str], float | None]
HoldingLookup = Callable[[str], str | None]

# Reminder milestones (calendar days before the estimated earnings date).
DEFAULT_MILESTONES: tuple[tuple[int, str], ...] = ((7, "T-7"), (2, "T-2"), (0, "T-0"))

# 96A EventType values that ARE an earnings/results disclosure.
EARNINGS_EVENT_TYPES: tuple[str, ...] = ("EARNINGS_RESULTS",)
# Additionally surfaced as post-earnings *enrichment* (they carry 96C what_changed).
PERIODIC_ENRICHMENT_TYPES: tuple[str, ...] = ("QUARTERLY_FILING", "ANNUAL_FILING")
# Contextual only -- never classified as an earnings update on its own.
CONTEXT_ONLY_TYPES: tuple[str, ...] = ("REGULATION_FD",)


def _parse_date(v: Any) -> date | None:
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        try:
            return date.fromisoformat(v[:10])
        except ValueError:
            return None
    return None


def _fmt_num(v: Any) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "n/a"
    for unit, div in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(f) >= div:
            return f"{f / div:.2f}{unit}"
    return f"{f:.2f}"


# ---------------------------------------------------------------------------
# Earnings RADAR
# ---------------------------------------------------------------------------

@dataclass
class EarningsRadarBridge:
    milestones: tuple[tuple[int, str], ...] = DEFAULT_MILESTONES

    def build_rows(
        self,
        upcoming_rows: list[dict],
        *,
        now: datetime | None = None,
        price_lookup: PriceLookup | None = None,
        holding_lookup: HoldingLookup | None = None,
    ) -> list[dict]:
        """One RADAR row per (symbol, earnings_date, milestone) that is DUE
        today. Deterministic `radar_id` -> a re-run of the same milestone is
        idempotent; a shifted earnings_date yields new ids (a real update)."""
        now = now or datetime.now(timezone.utc)
        today = now.astimezone(timezone.utc).date()
        out: list[dict] = []
        for row in upcoming_rows:
            sym = str(row.get("ticker") or row.get("symbol") or "").upper()
            ed = _parse_date(row.get("earnings_date"))
            if not sym or ed is None:
                continue
            days_until = (ed - today).days
            if days_until < 0:
                continue  # already reported -- the post-earnings bridge handles the aftermath
            session = str(row.get("session") or "UNSPECIFIED")
            for milestone_days, tag in self.milestones:
                due = days_until == milestone_days or (tag == "T-0" and days_until == 0)
                if not due:
                    continue
                reporting_when = f"{ed.isoformat()} (session {session})"
                context = (
                    "reports today" if days_until == 0
                    else f"reports in {days_until} day(s)"
                )
                out.append({
                    "radar_id": make_radar_id(
                        symbol=sym, reporting_when=f"{ed.isoformat()}|{tag}", day=now,
                    ),
                    "symbol": sym,
                    "company": row.get("company") or row.get("company_name"),
                    "reporting_when": reporting_when,
                    "current_price": (price_lookup(sym) if price_lookup else None),
                    "holding_status": (holding_lookup(sym) if holding_lookup else None),
                    "context": f"{context} [{tag} reminder] -- source: watchlist earnings calendar (yfinance, free)",
                })
        return out


# ---------------------------------------------------------------------------
# Post-earnings / fundamental
# ---------------------------------------------------------------------------

@dataclass
class PostEarningsBridge:
    include_periodic_enrichment: bool = True
    max_material_lines: int = 8

    def scan(
        self,
        api: Any,
        *,
        symbols: list[str] | None = None,
        since: datetime | None = None,
        limit: int = 60,
        price_lookup: PriceLookup | None = None,
    ) -> list[dict]:
        types = list(EARNINGS_EVENT_TYPES)
        if self.include_periodic_enrichment:
            types += list(PERIODIC_ENRICHMENT_TYPES)
        rows: list[dict] = []
        seen: set[str] = set()
        for et in types:
            page = api.ranked_events(event_type=et, symbols=symbols, since=since, limit=limit)
            for item in page.get("items", []):
                eid = item["event_id"]
                if eid in seen:
                    continue
                seen.add(eid)
                detail = api.event_detail(eid)
                if detail is None:
                    continue
                rows.append(self._to_row(detail, api, price_lookup, is_earnings=et in EARNINGS_EVENT_TYPES))
        return rows

    # ------------------------------------------------------------------
    def _to_row(self, d: dict, api: Any, price_lookup: PriceLookup | None, *, is_earnings: bool) -> dict:
        sym = d["symbol"]
        return {
            "event_id": make_event_update_id(
                symbol=sym, event_type=d["event_type"], accepted_at=str(d.get("accepted_at_utc")),
            ),
            "source_event_id": d["event_id"],
            "symbol": sym,
            "company": d.get("company_name"),
            "event_type": self._event_label(d, is_earnings),
            "accepted_at": d.get("accepted_at_utc"),
            "current_price": (price_lookup(sym) if price_lookup else None),
            "material_changes": self._material_changes(d),
            "insider_context": self._insider_ctx(api, sym),
            "significance_band": d.get("band"),
            "significance_reasons": list(d.get("significance_reasons") or []),
            "accession": d.get("accession"),
            "evidence_url": d.get("filing_index_url") or d.get("primary_document_url"),
            "session_bucket": d.get("session_bucket"),
        }

    @staticmethod
    def _event_label(d: dict, is_earnings: bool) -> str:
        items = d.get("filing_items") or []
        base = {
            "EARNINGS_RESULTS": "8-K Item 2.02 (results of operations)",
            "QUARTERLY_FILING": "10-Q quarterly filing",
            "ANNUAL_FILING": "10-K annual filing",
        }.get(d["event_type"], d["event_type"])
        if "7.01" in items and d["event_type"] == "EARNINGS_RESULTS":
            base += " + Item 7.01 (Reg FD)"
        return base

    def _material_changes(self, d: dict) -> list[str]:
        out: list[str] = []
        c = d.get("comparison")
        if c:
            for nc in c.get("notable_changes", []) or []:
                out.append(self._fmt_notable(nc))
            for x in (c.get("xbrl") or [])[:4]:
                if x.get("status") == "FOUND" and x.get("current_value") is not None:
                    rel = x.get("relative_delta")
                    rel_s = f" ({rel:+.1%})" if isinstance(rel, (int, float)) else ""
                    out.append(
                        f"XBRL {x.get('field')} {x.get('comparison')}: "
                        f"{_fmt_num(x.get('prior_value'))} -> {_fmt_num(x.get('current_value'))}{rel_s}"
                    )
        if not out:
            # an 8-K earnings release with no 10-Q comparison yet -> the 96E
            # reasons are the factual "what we know" set.
            out = [r for r in (d.get("significance_reasons") or []) if "watchlist" not in r.lower()]
        return out[: self.max_material_lines]

    @staticmethod
    def _fmt_notable(nc: dict) -> str:
        kind = nc.get("kind", "")
        if kind == "whole_document_changed_materially":
            return f"whole-document text change {nc.get('value'):.3f} (>{nc.get('threshold'):.3f} material)"
        if kind == "section_changed_materially":
            return f"section '{nc.get('section')}' changed materially ({nc.get('metric')} {nc.get('value'):.3f})"
        if kind == "new_material_passages":
            return f"{nc.get('value')} new material passage(s) (>={nc.get('min_words_each')} words each)"
        if kind == "keyword_category_count_changed":
            return f"keyword category '{nc.get('category')}' count changed by {nc.get('delta', nc.get('value'))}"
        if kind == "xbrl_metric_changed_materially":
            return f"XBRL {nc.get('field')} {nc.get('comparison')} moved {nc.get('relative_delta', nc.get('value'))}"
        return kind.replace("_", " ")

    @staticmethod
    def _insider_ctx(api: Any, symbol: str) -> str | None:
        try:
            ia = api.insider_activity(symbol)
        except Exception:  # noqa: BLE001
            return None
        if not ia or not ia.get("open_market_aggregates"):
            return None
        w = next((a for a in ia["open_market_aggregates"] if a.get("window_calendar_days") == 30), ia["open_market_aggregates"][0])
        net = w.get("net_value")
        if net is None:
            return None
        direction = "net selling" if net < 0 else "net buying" if net > 0 else "flat"
        return (
            f"{w.get('window_calendar_days')}d open-market P/S: {direction} "
            f"{_fmt_num(abs(net))} ({w.get('transaction_count')} txns, "
            f"{w.get('distinct_purchasers')} buyer(s) / {w.get('distinct_sellers')} seller(s))"
        )


# ---------------------------------------------------------------------------
# overnight SEC events for the pre-market bundle
# ---------------------------------------------------------------------------

def overnight_event_labels(
    api: Any, symbols: list[str] | None, *, since: datetime, limit_per_symbol: int = 5,
) -> dict[str, list[str]]:
    """{symbol: ["8-K Item 2.02 accepted 04:12 ET (band HIGH)", ...]} for events
    accepted since `since`. Fed into PremarketSymbolInput.overnight_events."""
    out: dict[str, list[str]] = {}
    page = api.ranked_events(symbols=symbols, since=since, limit=200)
    for item in page.get("items", []):
        acc = _parse_iso(item.get("accepted_at_utc"))
        if acc is None or acc < since:
            continue
        sym = item["symbol"]
        label = (
            f"{item.get('form_type') or item.get('event_type')} "
            f"{'/'.join(item.get('filing_items') or []) or item.get('event_type')} "
            f"accepted {acc.strftime('%H:%M UTC')}"
            + (f" (band {item['band']})" if item.get("band") else "")
        )
        out.setdefault(sym, [])
        if len(out[sym]) < limit_per_symbol:
            out[sym].append(label)
    return out


def _parse_iso(v: Any) -> datetime | None:
    if isinstance(v, str):
        try:
            dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    return None


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------

@dataclass
class BridgeMetrics:
    radar_rows_built: int = 0
    radar_dispatched: int = 0
    event_rows_built: int = 0
    event_dispatched: int = 0
    bridge_failures: int = 0
    bridge_retries: int = 0
    last_radar_refresh_utc: str | None = None
    last_event_bridge_utc: str | None = None


def bridge_health(
    api: Any,
    upcoming_rows: list[dict],
    metrics: BridgeMetrics,
    *,
    now: datetime | None = None,
) -> dict:
    now = now or datetime.now(timezone.utc)
    # earnings source
    ages = []
    for r in upcoming_rows:
        lu = _parse_iso(r.get("last_updated"))
        if lu:
            ages.append((now - lu).total_seconds() / 3600.0)
    earn_age = min(ages) if ages else None
    earn_status = "healthy" if (upcoming_rows and (earn_age is None or earn_age < 24 * 8)) else (
        "degraded" if upcoming_rows else "down"
    )
    # 96B freshness
    intel = {}
    try:
        fs = api.freshness_state()
        for s in fs.get("sources", []):
            intel[s["source"]] = s["status"]
        intel_worst = fs.get("worst", "UNKNOWN")
    except Exception:  # noqa: BLE001
        intel_worst = "UNKNOWN"
    # a quiet / empty store is NOT a failure
    intel_status = {
        "FRESH": "healthy", "STALE": "degraded", "DOWN": "down", "UNKNOWN": "idle",
    }.get(str(intel_worst).upper(), "idle")
    return {
        "earnings_source": {
            "status": earn_status,
            "detail": f"{len(upcoming_rows)} upcoming-earnings rows"
                      + (f", oldest {earn_age:.1f}h" if earn_age is not None else ""),
        },
        "intelligence_source": {
            "status": intel_status, "detail": intel or "no 96B events yet (quiet != failure)",
            "worst": intel_worst,
        },
        "dispatch_bridge": {
            "status": "healthy" if metrics.bridge_failures == 0 else "degraded",
            "last_radar_refresh": metrics.last_radar_refresh_utc,
            "last_event_bridge": metrics.last_event_bridge_utc,
            "failures": metrics.bridge_failures,
            "retries": metrics.bridge_retries,
            "radar_dispatched": metrics.radar_dispatched,
            "event_dispatched": metrics.event_dispatched,
        },
    }
