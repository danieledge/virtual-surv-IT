"""
scripts/explain_rule.py - "why did this NOT alert?" trace for the spoofing worked example.

The absence counterpart of SpoofingAlert.reason: an alert that FIRES carries a rich audit
string, but every non-fire path in `detect_spoofing` is a silent skip (five of them). This
tool re-evaluates the rule's conditions WITHOUT short-circuit for a chosen session and
emits, per candidate order, the full truth table - condition, observed value, required
value, pass/fail - the FIRST failing condition in the rule's own evaluation order, and a
counterfactual distance-to-threshold for every failing numeric condition ("would alert at
large_qty_multiple <= 3.2; configured 5.0"). Alert-absence enhancement plan Phase 2
(docs/internal/alert-absence-enhancement-plan-2026-08-18.md); the technique is the
rule-engine "evaluation reasons" pattern plus query-based why-not provenance.

Deterministic, stdlib + repo imports only, no network, synthetic/masked input only (§5).
Every number printed is 📊 observed - that is the point: a consent-free route to an
observed absence diagnosis (the tool is team tooling, not code under review).

Reproduce:
    python -m scripts.explain_rule --generator spoofing --seed 3
    python -m scripts.explain_rule --file data/synthetic/orders.jsonl [--order O-17] [--json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rules.spoofing import (
    Order,
    SpoofingThresholds,
    _is_place_and_cancel,
    _median,
    detect_spoofing,
    reconstruct_orders,
)


def _load_events(args):
    if args.file:
        from scripts.gen_synthetic import record_to_event

        lines = Path(args.file).read_text(encoding="utf-8").splitlines()
        return [record_to_event(json.loads(ln)) for ln in lines if ln.strip()]
    from scripts import gen_synthetic

    gen = {
        "spoofing": gen_synthetic.spoofing_session,
        "benign": gen_synthetic.benign_session,
        "large_genuine": gen_synthetic.large_genuine_session,
    }[args.generator]
    return gen(seed=args.seed)


def _cond(cid: str, desc: str, observed, required, passed: bool, counterfactual: str = "") -> dict:
    return {
        "id": cid,
        "condition": desc,
        "observed": observed,
        "required": required,
        "pass": passed,
        "counterfactual": counterfactual,
    }


def explain_events(
    events, thresholds: SpoofingThresholds | None = None, order_id: str | None = None
) -> dict:
    """Pure evaluation - mirrors detect_spoofing stage for stage, but records every
    condition instead of skipping silently. Returns {"alerts": [...], "groups": [...]}
    where each group carries its gate/baseline stages and per-order truth tables."""
    th = thresholds or SpoofingThresholds()
    orders = reconstruct_orders(events)
    alerts = detect_spoofing(events, th)
    alerted_ids = {a.spoof_order_id for a in alerts}

    by_key: dict[tuple[str, str], list[Order]] = {}
    for o in orders.values():
        by_key.setdefault((o.trader, o.instrument), []).append(o)
    genuine_by_instrument: dict[str, list[float]] = {}
    for o in orders.values():
        if not _is_place_and_cancel(o, th):
            genuine_by_instrument.setdefault(o.instrument, []).append(o.qty)

    groups = []
    for (trader, instrument), olist in sorted(by_key.items()):
        group: dict = {"trader": trader, "instrument": instrument, "stages": [], "orders": []}
        # Stage: group gate (detect_spoofing line ~209)
        gate_ok = len(olist) >= th.min_orders_for_baseline
        group["stages"].append(
            _cond(
                "G1",
                "enough orders to establish a baseline (min_orders_for_baseline)",
                len(olist),
                f">= {th.min_orders_for_baseline}",
                gate_ok,
                "" if gate_ok else f"would evaluate at min_orders_for_baseline <= {len(olist)}",
            )
        )
        # Stage: baseline (lines ~220-228)
        trader_genuine = [o.qty for o in olist if not _is_place_and_cancel(o, th)]
        if len(trader_genuine) >= th.min_orders_for_baseline:
            median_qty = _median(trader_genuine)
            baseline_src = "trader median"
        else:
            median_qty = _median(genuine_by_instrument.get(instrument, []))
            baseline_src = "instrument median"
        group["stages"].append(
            _cond(
                "G2",
                f"a genuine size baseline exists ({baseline_src})",
                median_qty,
                "> 0",
                median_qty > 0,
                ""
                if median_qty > 0
                else "no genuine (non place-and-cancel) orders anywhere for this "
                "instrument - the documented no-baseline limitation "
                "(docs/scenarios/spoofing.md §7)",
            )
        )
        group["baseline"] = {"median_qty": median_qty, "source": baseline_src}

        for spoof in sorted(olist, key=lambda o: o.order_id):
            if order_id and spoof.order_id != order_id:
                continue
            conds = []
            # C1-C3: the place-and-cancel shape (predicate _is_place_and_cancel)
            cancelled = spoof.cancelled_ms is not None
            conds.append(_cond("C1", "order was cancelled", cancelled, "cancelled", cancelled))
            life = spoof.lifetime_ms
            life_ok = cancelled and life is not None and life <= th.max_spoof_lifetime_ms
            conds.append(
                _cond(
                    "C2",
                    "short-lived (max_spoof_lifetime_ms)",
                    life if life is not None else "n/a (never cancelled)",
                    f"<= {th.max_spoof_lifetime_ms}ms",
                    life_ok,
                    ""
                    if life_ok or life is None
                    else f"would pass at max_spoof_lifetime_ms >= {life} "
                    f"(distance {life - th.max_spoof_lifetime_ms}ms, "
                    f"{(life / th.max_spoof_lifetime_ms - 1) * 100:.1f}% over)",
                )
            )
            fr = spoof.fill_ratio
            fr_ok = fr <= th.max_fill_ratio
            conds.append(
                _cond(
                    "C3",
                    "near-unfilled (max_fill_ratio)",
                    round(fr, 4),
                    f"<= {th.max_fill_ratio}",
                    fr_ok,
                    ""
                    if fr_ok
                    else f"would pass at max_fill_ratio >= {fr:.4f} "
                    f"(distance {(fr - th.max_fill_ratio):.4f})",
                )
            )
            # C4: outsized vs baseline (line ~236)
            if median_qty > 0:
                multiple = spoof.qty / median_qty
                c4_ok = spoof.qty >= th.large_qty_multiple * median_qty
                conds.append(
                    _cond(
                        "C4",
                        f"outsized vs {baseline_src} (large_qty_multiple)",
                        f"{multiple:.2f}x median ({spoof.qty:g} vs median {median_qty:g})",
                        f">= {th.large_qty_multiple}x",
                        c4_ok,
                        ""
                        if c4_ok
                        else f"would alert at large_qty_multiple <= {multiple:.2f} "
                        f"(distance {(1 - multiple / th.large_qty_multiple) * 100:.1f}% "
                        "under the configured multiple)",
                    )
                )
            else:
                conds.append(
                    _cond("C4", "outsized vs baseline", "unevaluable", "baseline > 0", False)
                )
            # C5: benefiting opposite-side fill in window (lines ~241-254)
            if cancelled:
                window_start = spoof.placed_ms - th.opposite_exec_window_ms
                window_end = spoof.cancelled_ms + th.opposite_exec_window_ms
                nearest = None
                for other in olist:
                    if other.side is not spoof.side.opposite:
                        continue
                    if other.filled_qty <= 0 or other.last_fill_ms is None:
                        continue
                    gap_to_window = 0
                    if other.last_fill_ms < window_start:
                        gap_to_window = window_start - other.last_fill_ms
                    elif other.last_fill_ms > window_end:
                        gap_to_window = other.last_fill_ms - window_end
                    if nearest is None or gap_to_window < nearest[1]:
                        nearest = (other, gap_to_window)
                c5_ok = nearest is not None and nearest[1] == 0
                if nearest is None:
                    observed = "no opposite-side filled order in the session"
                    cf = ""
                else:
                    observed = f"nearest opposite fill {nearest[0].order_id} " + (
                        "inside window" if nearest[1] == 0 else f"{nearest[1]}ms outside window"
                    )
                    cf = (
                        ""
                        if c5_ok
                        else f"would pass at opposite_exec_window_ms >= "
                        f"{th.opposite_exec_window_ms + nearest[1]} "
                        f"(distance {nearest[1]}ms)"
                    )
                conds.append(
                    _cond(
                        "C5",
                        "benefiting opposite-side fill in window (opposite_exec_window_ms)",
                        observed,
                        f"within ±{th.opposite_exec_window_ms}ms of the live window",
                        c5_ok,
                        cf,
                    )
                )
            else:
                conds.append(
                    _cond("C5", "benefiting opposite-side fill in window", "n/a", "-", False)
                )

            first_fail = next((c["id"] for c in conds if not c["pass"]), None)
            group["orders"].append(
                {
                    "order_id": spoof.order_id,
                    "side": spoof.side.value,
                    "qty": spoof.qty,
                    "alerted": spoof.order_id in alerted_ids,
                    "group_gates_passed": gate_ok and median_qty > 0,
                    "first_failing_condition": None
                    if spoof.order_id in alerted_ids
                    else (
                        ("G1" if not gate_ok else "G2")
                        if not (gate_ok and median_qty > 0)
                        else first_fail
                    ),
                    "conditions": conds,
                }
            )
        groups.append(group)
    return {
        "alerts": [{"order_id": a.spoof_order_id, "reason": a.reason} for a in alerts],
        "groups": groups,
    }


def _print_markdown(result: dict) -> None:
    if result["alerts"]:
        print(f"## Alerts fired: {len(result['alerts'])}")
        for a in result["alerts"]:
            print(f"- {a['order_id']}: {a['reason']}")
    else:
        print("## Alerts fired: none")
    for g in result["groups"]:
        print(f"\n## {g['trader']} / {g['instrument']}")
        for s in g["stages"]:
            mark = "PASS" if s["pass"] else "FAIL"
            line = f"  [{s['id']} {mark}] {s['condition']}: observed {s['observed']}, required {s['required']}"
            if s["counterfactual"]:
                line += f" | {s['counterfactual']}"
            print(line)
        for o in g["orders"]:
            head = (
                "ALERTED"
                if o["alerted"]
                else f"no alert - first failing: {o['first_failing_condition']}"
            )
            print(f"\n  order {o['order_id']} ({o['side']}, qty {o['qty']:g}) -> {head}")
            for c in o["conditions"]:
                mark = "PASS" if c["pass"] else "FAIL"
                line = f"    [{c['id']} {mark}] {c['condition']}: observed {c['observed']}, required {c['required']}"
                if c["counterfactual"]:
                    line += f" | {c['counterfactual']}"
                print(line)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m scripts.explain_rule",
        description="Per-condition why/why-not trace for the spoofing rule (synthetic/masked data only).",
    )
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--file", help="orders JSONL (gen_synthetic record format)")
    src.add_argument(
        "--generator",
        choices=["spoofing", "benign", "large_genuine"],
        help="use a bundled synthetic session generator",
    )
    ap.add_argument("--seed", type=int, default=1, help="generator seed (default 1)")
    ap.add_argument("--order", help="focus a single order id")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)

    events = _load_events(args)
    result = explain_events(events, order_id=args.order)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        _print_markdown(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
