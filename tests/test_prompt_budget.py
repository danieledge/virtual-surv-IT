"""Prompt budget backstop (2026-08-18, token-optimisation plan Phase 0 Track A).

Every prompt-bearing file the runtime can load (CLAUDE.md, skills, shared openers, agent
definitions, the operating guide and its deferred references) is inventoried, classified by
load tier, and held against a checked-in baseline in tests/prompt-budgets.json. The point is
not the absolute numbers - bytes/4 is an estimate - but that growth becomes a deliberate,
reviewed act instead of silent drift: a file that outgrows its baseline by more than the
tolerance fails CI until the baseline is re-pinned on purpose.

Distinct from test_budget.py (engagement dollar spend, advisory) - this one is about the
standing prompt text itself and is a hard gate.

Maintenance:
    python tests/test_prompt_budget.py --report   # inventory table (markdown)
    python tests/test_prompt_budget.py --pin      # re-pin baselines/budgets after a deliberate change

--pin preserves existing tier and loads_per_engagement assignments; only baselines and tier
budgets are recomputed. New files get a guessed tier (rules below) - review the guess in the
diff like any other code change.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BUDGETS = REPO_ROOT / "tests" / "prompt-budgets.json"

TIERS = ("ALWAYS_LOADED", "OPEN_TIME", "ROUTE_TIME", "AGENT_TIME", "DEFERRED")

# The prompt surfaces whose files MUST be classified - a new file here fails the test until
# it gets a budgets entry, which is the mechanism that forces the "why is this loaded at
# this point?" question at review time.
MANDATORY_GLOBS = (
    "CLAUDE.md",
    ".claude/skills/**/*.md",
    ".claude/agents/*.md",
    "docs/team-operating-guide.md",
    "docs/team-operating-guide-orchestration.md",
    "docs/operating-guide.d/*.md",
)

# Files loaded at every standard engagement open (engage-open.md instructs the guide read;
# the two front-door skills carry the open themselves).
_OPEN_TIME = {
    "docs/team-operating-guide.md",
    ".claude/skills/.shared/engage-open.md",
    ".claude/skills/engage/SKILL.md",
    ".claude/skills/engage-light/SKILL.md",
}


def _estimate_tokens(path: Path) -> int:
    return math.ceil(len(path.read_text(encoding="utf-8").encode("utf-8")) / 4)


def _discover() -> list[str]:
    found: set[str] = set()
    for pattern in MANDATORY_GLOBS:
        for hit in REPO_ROOT.glob(pattern):
            if hit.is_file():
                found.add(hit.relative_to(REPO_ROOT).as_posix())
    return sorted(found)


def _guess_tier(rel: str) -> str:
    if rel == "CLAUDE.md":
        return "ALWAYS_LOADED"
    if rel in _OPEN_TIME:
        return "OPEN_TIME"
    if "/references/" in rel or rel.startswith("docs/"):
        return "DEFERRED"
    if rel.startswith(".claude/agents/"):
        return "AGENT_TIME"
    return "ROUTE_TIME"


def _load_budgets() -> dict:
    assert BUDGETS.is_file(), (
        f"{BUDGETS.relative_to(REPO_ROOT)} is missing - generate it with "
        "`python tests/test_prompt_budget.py --pin` and commit it."
    )
    return json.loads(BUDGETS.read_text(encoding="utf-8"))


def _tracked_paths(budgets: dict) -> list[str]:
    return sorted(set(_discover()) | set(budgets.get("extra_tracked", [])))


# ---------------------------------------------------------------- tests


def test_every_prompt_file_is_classified():
    budgets = _load_budgets()
    missing = [p for p in _tracked_paths(budgets) if p not in budgets["files"]]
    assert not missing, (
        "Prompt-bearing files without a budgets entry (classify them - which tier pays for "
        f"this text, and when?): {missing}. Re-pin with --pin, then review the guessed tiers."
    )


def test_no_stale_budget_entries():
    budgets = _load_budgets()
    stale = [p for p in budgets["files"] if not (REPO_ROOT / p).is_file()]
    assert not stale, f"Budgets entries for files that no longer exist (remove them): {stale}"


def test_tiers_are_valid():
    budgets = _load_budgets()
    bad = {p: e["tier"] for p, e in budgets["files"].items() if e["tier"] not in TIERS}
    assert not bad, f"Unknown tier names: {bad} (valid: {TIERS})"


def test_file_growth_within_tolerance():
    budgets = _load_budgets()
    tol = budgets["growth_tolerance"]
    over = []
    for rel, entry in budgets["files"].items():
        path = REPO_ROOT / rel
        if not path.is_file():
            continue  # test_no_stale_budget_entries owns this failure
        now = _estimate_tokens(path)
        ceiling = math.ceil(entry["baseline_tokens"] * (1 + tol))
        if now > ceiling:
            over.append(f"{rel}: ~{now} tok vs baseline {entry['baseline_tokens']} (+{tol:.0%})")
    assert not over, (
        "Files grown past their pinned baseline - shrink them, or re-pin deliberately with "
        "--pin and justify the growth in the commit: " + "; ".join(over)
    )


def test_tier_totals_within_budget():
    budgets = _load_budgets()
    totals: dict[str, int] = {t: 0 for t in TIERS}
    for rel, entry in budgets["files"].items():
        path = REPO_ROOT / rel
        if path.is_file():
            totals[entry["tier"]] += _estimate_tokens(path)
    over = []
    for tier, cap in budgets["tier_budgets"].items():
        if cap is not None and totals.get(tier, 0) > cap:
            over.append(f"{tier}: ~{totals[tier]} tok vs budget {cap}")
    assert not over, (
        "Tier budgets exceeded (this is the whole-surface cap, independent of per-file "
        "growth): " + "; ".join(over)
    )


# ---------------------------------------------------------------- maintenance CLI


def _pin() -> dict:
    old = json.loads(BUDGETS.read_text(encoding="utf-8")) if BUDGETS.is_file() else {}
    old_files = old.get("files", {})
    files = {}
    for rel in sorted(set(_discover()) | set(old.get("extra_tracked", []))):
        prev = old_files.get(rel, {})
        files[rel] = {
            "tier": prev.get("tier", _guess_tier(rel)),
            "loads_per_engagement": prev.get("loads_per_engagement", 1.0),
            "baseline_tokens": _estimate_tokens(REPO_ROOT / rel),
        }
    totals: dict[str, int] = {t: 0 for t in TIERS}
    for entry in files.values():
        totals[entry["tier"]] += entry["baseline_tokens"]
    # Budget = baseline + 10% headroom, rounded up to the next 100. DEFERRED is uncapped by
    # design: text moved there is the SUCCESS of the optimisation plan, so a cap would fight
    # phases 1-4; per-file growth tolerance still applies to every deferred file.
    tier_budgets = {
        t: (None if t == "DEFERRED" else math.ceil(totals[t] * 1.10 / 100) * 100) for t in TIERS
    }
    return {
        "notes": (
            "Prompt-surface baselines. tokens = utf8_bytes/4 (estimate). "
            "loads_per_engagement is a typical-engagement multiplier used for ranking in "
            "--report, refined by eval-transcript data (plan Phase 0 Track D). "
            "Maintained by tests/test_prompt_budget.py --pin; see its docstring."
        ),
        "growth_tolerance": old.get("growth_tolerance", 0.15),
        "extra_tracked": old.get("extra_tracked", []),
        "tier_budgets": tier_budgets,
        "files": files,
    }


def _report(budgets: dict) -> str:
    rows = []
    for rel, entry in budgets["files"].items():
        path = REPO_ROOT / rel
        if not path.is_file():
            continue
        tokens = _estimate_tokens(path)
        weight = entry["loads_per_engagement"]
        rows.append((tokens * weight, tokens, weight, entry["tier"], rel))
    rows.sort(reverse=True)
    lines = [
        "| File | Tier | ~Tokens | Loads/eng | Weighted |",
        "|---|---|---:|---:|---:|",
    ]
    for weighted, tokens, weight, tier, rel in rows:
        lines.append(f"| `{rel}` | {tier} | {tokens:,} | {weight:g} | {weighted:,.0f} |")
    totals: dict[str, int] = {t: 0 for t in TIERS}
    for _, tokens, _, tier, _ in rows:
        totals[tier] += tokens
    lines += ["", "| Tier | ~Tokens | Budget |", "|---|---:|---:|"]
    for tier in TIERS:
        cap = budgets["tier_budgets"].get(tier)
        lines.append(f"| {tier} | {totals[tier]:,} | {cap if cap is not None else 'uncapped'} |")
    return "\n".join(lines)


if __name__ == "__main__":
    if "--pin" in sys.argv:
        BUDGETS.write_text(json.dumps(_pin(), indent=2) + "\n", encoding="utf-8")
        print(f"pinned {BUDGETS.relative_to(REPO_ROOT)}")
    elif "--report" in sys.argv:
        print(_report(_load_budgets()))
    else:
        print(__doc__)
