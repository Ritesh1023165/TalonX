"""
talonx_v2.sizing -- Package 4: whole-share, fee-inclusive sizing and
exit economics for V2 ONLY.

Deliberately NOT wired into ``talonx_paper.engine.calculate_buy``/
``calculate_sell_pnl`` -- those remain Original's own, unmodified
accounting; V2's own frozen "no fractional shares for the first-
release paper strategy" requirement does not extend to Original,
whose own fractional-share sizing is a separate, out-of-scope
concern.

Cost-model boundary (this module's own explicit contract): this
module NEVER invents a numerical commission/spread/slippage/tax/SEC-
fee/exchange-fee/FX-cost assumption. ``fee_fn`` is a pluggable
``(quantity, price) -> float`` callable; the DEFAULT, ``zero_fee``,
returns 0.0 -- an explicit statement that the CURRENTLY approved/
frozen assumption is zero-cost (matching the pre-Package-4 codebase's
own actual behavior, `talonx_paper.engine.calculate_buy` never
applied a fee at all). Real numerical cost parameters remain
`S10-22`/`OPS-014`'s own explicitly deferred, unresolved question --
this module makes the MECHANISM fee-function-capable without
resolving that question.

Money precision boundary: the "largest integer Q" search below uses
``decimal.Decimal`` (via ``Decimal(str(x))``, never ``Decimal(x)``
directly on a float, to avoid importing a float's own binary
imprecision into the decimal domain) for every comparison against the
allocation/available-cash caps -- this is the ONE place a binary-
float summation error could produce a wrong boundary decision (e.g.
an allocation that "exactly" fits N shares at a price like 33.33).
Every function here still returns and accepts plain Python floats at
its own boundary, matching this codebase's existing float-based
persistence (`positions`/`trades` REAL columns) -- Package 4 does not
migrate the wider codebase to Decimal (a giant, out-of-scope
migration); Decimal is used ONLY internally, for this one
integer-boundary-sensitive calculation.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from typing import Callable

FeeFn = Callable[[float, float], float]


def zero_fee(quantity: float, price: float) -> float:
    """The current, frozen, approved cost assumption: zero. See this
    module's own docstring -- S10-22/OPS-014 remain unresolved; this
    is NOT new profitability evidence, and NOT an invented realistic
    fee."""
    return 0.0


def _d(x: float) -> Decimal:
    """Float -> Decimal via its string repr, never the float's own
    raw binary value -- avoids importing binary-float imprecision
    into the decimal comparison (e.g. Decimal(0.1) != Decimal("0.1"))."""
    return Decimal(str(x))


@dataclass(frozen=True)
class SizingResult:
    shares: int
    entry_notional: float
    entry_fee: float
    entry_total: float          # entry_notional + entry_fee -- the fee-inclusive reservation/cost-basis
    ok: bool
    reason: str


def size_whole_shares_fee_inclusive(
    *, price: float, allocation_usd: float, available_cash: float,
    fee_fn: FeeFn = zero_fee,
) -> SizingResult:
    """Session 10 Section C's agreed formula: the largest non-negative
    whole quantity Q such that
        Q * price + fee_fn(Q, price) <= allocation_usd
    -- computed against the ALLOCATION cap only, never reduced merely
    because AVAILABLE cash is smaller (Section C's own explicit
    distinction). Quantity is NEVER rounded up.

    Separately: if the resulting Q's own fee-inclusive total exceeds
    AVAILABLE cash, the trade is refused ENTIRELY (an explicit SKIP,
    ``INSUFFICIENT_AVAILABLE_CASH``) -- never silently re-sized down
    to whatever smaller amount available cash would support. This is
    the "safest non-overexposure" reading of Section C's own language
    ("insufficient cash to reserve the approved allocation causes a
    skip, not a smaller reservation"), and is deliberately, explicitly
    NOT ambiguous: Session 10 Section C resolves this exact question.

    Uses a bounded backward search (never assumes ``fee_fn`` is flat/
    monotonic/independent of quantity -- correct for ANY fee shape,
    at the cost of at most ``floor(allocation/price)`` iterations,
    bounded by the frozen liquidity floor of $5/share against a
    $10,000-scale allocation -- a few thousand iterations at most,
    not an unbounded loop)."""
    if price is None or not math.isfinite(price) or price <= 0:
        return SizingResult(0, 0.0, 0.0, 0.0, False, "BAD_PRICE")
    if allocation_usd is None or not math.isfinite(allocation_usd) or allocation_usd <= 0:
        return SizingResult(0, 0.0, 0.0, 0.0, False, "NO_ALLOCATION")

    dprice = _d(price)
    dalloc = _d(allocation_usd)
    davail = _d(available_cash) if available_cash is not None and math.isfinite(available_cash) else Decimal(0)

    q_max = int((dalloc / dprice).to_integral_value(rounding=ROUND_DOWN))
    if q_max < 1:
        return SizingResult(0, 0.0, 0.0, 0.0, False, "ALLOCATION_BELOW_ONE_SHARE")

    for q in range(q_max, 0, -1):
        raw_fee = fee_fn(q, price)
        dfee = _d(raw_fee) if raw_fee is not None and math.isfinite(raw_fee) and raw_fee > 0 else Decimal(0)
        notional = dprice * q
        total = notional + dfee
        if total <= dalloc:
            if total > davail:
                return SizingResult(0, float(notional), float(dfee), float(total), False,
                                    "INSUFFICIENT_AVAILABLE_CASH")
            return SizingResult(q, float(notional), float(dfee), float(total), True, "OK")
    # even 1 share plus its own fee exceeds the allocation.
    return SizingResult(0, 0.0, 0.0, 0.0, False, "ONE_SHARE_PLUS_FEE_EXCEEDS_ALLOCATION")


@dataclass(frozen=True)
class ExitEconomics:
    exit_notional: float
    exit_fee: float
    exit_net: float              # exit_notional - exit_fee
    realized_pnl_usd: float      # exit_net - entry_total
    realized_pnl_pct: float      # realized_pnl_usd / entry_total * 100


def compute_exit_economics(
    *, shares: float, exit_price: float, entry_total: float, fee_fn: FeeFn = zero_fee,
) -> ExitEconomics:
    """Session 10 Section D's agreed formulas:
        exit_net     = quantity * modeled_sell_price - exit_fees
        realized_pnl = exit_net - entry_total
    ``entry_total`` MUST be the authoritative, persisted, fee-inclusive
    entry cost (``positions.position_cost``) -- never re-derived as
    ``shares * entry_price`` alone (that omits the entry fee, double-
    counting-by-omission once a non-zero fee model is ever configured;
    dormant/invisible under today's zero-fee default, but wrong in
    general -- exactly the defect this function exists to avoid,
    Package 2 acceptance's own A5 principle applied to the fee
    dimension)."""
    # PQ-2A: ``shares`` may be a ``Decimal`` (the exact post-corporate-action
    # economic quantity, e.g. a fractional reverse-split entitlement) -- never
    # round-tripped through a binary float.
    dshares = shares if isinstance(shares, Decimal) else _d(shares)
    dprice = _d(exit_price)
    dentry_total = _d(entry_total)
    notional = dshares * dprice
    raw_fee = fee_fn(float(shares), exit_price)
    dfee = _d(raw_fee) if raw_fee is not None and math.isfinite(raw_fee) and raw_fee > 0 else Decimal(0)
    net = notional - dfee
    pnl_usd = net - dentry_total
    pnl_pct = (pnl_usd / dentry_total * 100) if dentry_total != 0 else Decimal(0)
    return ExitEconomics(float(notional), float(dfee), float(net), float(pnl_usd), float(pnl_pct))
