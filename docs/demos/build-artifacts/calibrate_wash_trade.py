"""
calibrate_wash_trade.py - DEMO: synthesise a LABELLED wash-trade dataset and run real ATL/BTL.

Answers "why only illustrative thresholds?" - by synthesising data with KNOWN ground-truth labels
(injected wash pairs vs legit pairs), so precision (ATL) and recall (BTL coverage) can be MEASURED
across candidate thresholds, not guessed. All data is fabricated (CLAUDE.md §5).

Honest scope: measured on a SYNTHETIC distribution we control - it validates the calibration METHOD
and the volume<->coverage trade-off curve. Real deployment values still need a real labelled set;
the synthetic distribution is not the market's.

Run:  python3 docs/demos/build-artifacts/calibrate_wash_trade.py
"""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta

from wash_trade import detect_wash_trades

MID = 100.0
INSTRUMENT = "ACME"
AS_OF = date(2026, 1, 15)
FRESH_UBO = date(2026, 1, 10)
_T0 = datetime(2026, 1, 15, 10, 0, 0)


def _trade(tid, acct, side, price, ts_offset_s, notional=50_000):
    return {
        "trade_id": tid, "account_id": acct, "instrument": INSTRUMENT, "side": side,
        "price": price, "quantity": int(notional / price), "notional": notional,
        "timestamp": _T0 + timedelta(seconds=ts_offset_s),
    }


def synthesise(seed: int = 7, n_wash: int = 60, n_legit: int = 240):
    """Build a labelled set: injected wash pairs (label 1) + legit activity (label 0).

    Returns (trades, truth) where truth is a set of frozenset({buy_id, sell_id}) for the
    genuine wash pairs - the ground truth ATL/BTL is scored against.
    """
    rng = random.Random(seed)
    trades, truth, ubo = [], set(), {}
    tid = 0

    def nxt():
        nonlocal tid
        tid += 1
        return f"T{tid:04d}"

    # WASH pairs: same UBO, opposite side, off-market (one leg 0.3-3% from mid), close in time.
    for g in range(n_wash):
        a, b = f"WA-{g}-x", f"WA-{g}-y"
        ubo[frozenset({a, b})] = {"linked": True, "as_of": FRESH_UBO, "ubo_id": f"UBO-W{g}"}
        dev = rng.uniform(0.3, 3.0) / 100.0  # truly off-market
        price = MID * (1 + dev * rng.choice([-1, 1]))
        t = rng.uniform(0, 120)
        bid, sid = nxt(), nxt()
        trades.append(_trade(bid, a, "B", round(price, 2), t))
        trades.append(_trade(sid, b, "S", round(price, 2), t + rng.uniform(1, 60)))
        truth.add(frozenset({bid, sid}))

    # LEGIT activity: a mix of the SME's named false-positive drivers, all at/near mid (competitive).
    for g in range(n_legit):
        kind = rng.choice(["unaffiliated", "affiliated_competitive", "market_maker"])
        price = round(MID * (1 + rng.uniform(-0.08, 0.08) / 100.0), 2)  # competitive (<0.1%)
        t = rng.uniform(0, 120)
        bid, sid = nxt(), nxt()
        if kind == "unaffiliated":
            a, b = f"U-{g}-x", f"U-{g}-y"  # no UBO link
        else:  # affiliated but competitive price (legit two-way / MM)
            a, b = f"L-{g}-x", f"L-{g}-y"
            ubo[frozenset({a, b})] = {"linked": True, "as_of": FRESH_UBO, "ubo_id": f"UBO-L{g}"}
        trades.append(_trade(bid, a, "B", price, t))
        trades.append(_trade(sid, b, "S", price, t + rng.uniform(1, 60)))

    rng.shuffle(trades)
    return trades, truth, ubo


def calibrate():
    trades, truth, ubo = synthesise()

    def ubo_link(a, b):
        return ubo.get(frozenset({a, b}))

    base = {
        "ubo_staleness_days": 180, "min_notional": 1_000, "lookback_seconds": 300,
        "market_mid": {INSTRUMENT: MID}, "as_of_date": AS_OF,
    }
    print(f"Synthetic set: {len(trades)} trades, {len(truth)} injected wash pairs (ground truth).\n")
    print(f"{'price_tol_%':>11} | {'alerts':>6} | {'TP':>4} | {'FP':>4} | "
          f"{'precision(ATL)':>14} | {'recall(coverage)':>16} | {'missed(BTL)':>11}")
    print("-" * 92)
    for tol in [0.05, 0.10, 0.20, 0.50, 1.0, 2.0]:
        params = {**base, "price_tolerance_pct": tol}
        alerts = detect_wash_trades(trades, params, ubo_link, exemptions=set())
        flagged = {frozenset({a.buy_trade_id, a.sell_trade_id}) for a in alerts}
        tp = len(flagged & truth)
        fp = len(flagged - truth)
        precision = tp / len(flagged) if flagged else 1.0
        recall = tp / len(truth) if truth else 1.0
        missed = len(truth) - tp
        print(f"{tol:>11.2f} | {len(alerts):>6} | {tp:>4} | {fp:>4} | "
              f"{precision:>13.1%} | {recall:>15.1%} | {missed:>11}")
    print("\nATL = precision among flagged; coverage/recall = injected washes caught; "
          "BTL 'missed' = washes below the line. 📊 measured on synthetic ground truth.")


if __name__ == "__main__":
    calibrate()
