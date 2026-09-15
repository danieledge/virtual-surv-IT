#!/usr/bin/env python3
"""Render a validated findings pack to the canonical REVIEW-<slug>.md (and optionally .html).

This script owns 100% of the report layout, so the model can never drift a finding's format
(5C / C-word labels / inline runs / inconsistent fields): it supplies the pack's field VALUES;
this renderer lays them out - the same five fields, in order, on their own lines, for every
finding, every time. It refuses to render an invalid pack (validate_findings), so a missing field
is caught, not silently dropped.

Folder convention: the pack lives in a subfolder (artifacts/data/findings-<slug>.jsonl) so the
top-level artifacts/ stays user-navigable; by default the rendered REVIEW-<slug>.md is written UP to
that top-level artifacts/ (the pack's grandparent when the pack is in a `data/` dir), keeping the
.md/.html beside the other user-facing deliverables.

Output is forced to UTF-8 (Windows-safe). No third-party deps for the Markdown; `--html` imports
the bundled render_html.py in-process (resolved dual-mode, so it works in repo and
installed-plugin modes - no subprocess spawn, 2026-08-05).
Usage: python -m scripts.render_findings <pack.jsonl> [--out REVIEW-<slug>.md] [--html]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Works in both invocation modes: `python -m scripts.render_findings` (package context) AND
# `python <path>/scripts/render_findings.py` (direct path, e.g. from check_artifacts --fix or an
# installed plugin) - the latter puts scripts/ on sys.path[0], so the sibling import resolves.
try:
    from scripts.validate_findings import load_and_validate
    from scripts.findings_pack_io import read_pack
except ImportError:  # pragma: no cover - direct-path invocation
    from validate_findings import load_and_validate  # type: ignore[no-redef]
    from findings_pack_io import read_pack  # type: ignore[no-redef]

_SEV = {"critical": "🔴", "warning": "🟠", "medium": "🟡", "style": "🔵"}
_SEV_WORD = {"critical": "Critical", "warning": "Warning", "medium": "Medium", "style": "Style"}
_SEV_ORDER = ["critical", "warning", "medium", "style"]
_BASIS = {"measured": "📊 measured", "coded": "📄 coded", "inferred": "🧠 inferred"}
_DISP = {"open": "🔴 Open", "fixed": "✅ Fixed", "accepted": "⚖️ Accepted", "deferred": "⏭️ Deferred"}
# The review-scorer / self-scoring line is standardised as "Found N · Reported R · Filtered F"
# (docs/code-review-method.md §Transparency). We surface those numbers as a prominent
# false-positive-transparency line even when the pack only carries them inside the free-text
# 'scoring' field, so a report never hides how many findings were seen and set aside.
_FRF_RE = re.compile(r"Found\s+(\d+).*?Reported\s+(\d+).*?Filtered\s+(\d+)", re.S | re.I)
# kind -> (artifact filename prefix, default report title). Same five-field finding shape for all;
# performance findings add the optional cost/gain fields (rendered when present).
_KIND = {
    "review": ("REVIEW", "Review report"),
    "security-audit": ("SECURITY-AUDIT", "Security audit"),
    "performance": ("PERF", "Performance review"),
    # 2026-09-13 (step 4.6): the data-quality reviewer's coverage matrix as a pack. Never
    # scored or filtered (check_artifacts._SCORED_PACK_KINDS excludes it): a missed venue is
    # a gap, not a low-confidence finding.
    "coverage": ("COVERAGE", "Data-quality and coverage review"),
}


def _force_utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            # mypy cannot prove sys.stdout is a real stream (TextIO has no .reconfigure in
            # the stubs); CPython's always is, and a swap-in that isn't lands in the except.
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError, OSError):
            pass


def _anchor(fid: str) -> str:
    """A stable in-document anchor id for a finding, so the at-a-glance table can link
    straight to the full entry. Deterministic from the finding id (not the title, whose
    auto-slug is long and unpredictable): CR-01 -> f-cr-01."""
    return "f-" + re.sub(r"[^a-z0-9]+", "-", fid.lower()).strip("-")


def _tags_line(f: dict) -> str | None:
    """Optional taxonomy tags (CWE / OWASP / rule ids) rendered only when the pack supplies
    them - never fabricated. The cited 'standard' stays the authoritative reference; these are
    the machine-filterable labels that SARIF/Semgrep/CodeQL carry alongside it."""
    tags = f.get("tags")
    if not tags:
        return None
    return "**Tags:** " + "  ·  ".join(f"`{t}`" for t in tags)


def _finding_block(f: dict) -> str:
    sev = _SEV.get(f["severity"], "•")
    basis = _BASIS.get(f.get("basis", ""), f.get("basis", ""))
    conf = f.get("confidence")
    conf_str = f"  ·  **Confidence:** {conf}/100" if conf is not None else ""
    impact = f["impact"]
    if f.get("impact_basis"):
        impact = f"{impact}  ({_BASIS.get(f['impact_basis'], f['impact_basis'])})"
    fix = f["fix"]
    tags_line = _tags_line(f)
    effort = f.get("effort")
    disposition = f"**Disposition:** {_DISP.get(f['disposition'], f['disposition'])}"
    if effort:
        disposition += f"  ·  **Fix effort:** {effort}"
    return "\n".join(
        [
            # Explicit anchor so the at-a-glance table links straight here (the heading's own
            # auto-slug is long and emoji-stripped, so it is not a reliable link target).
            f'<a id="{_anchor(f["id"])}"></a>',
            f"### {sev} {f['id']} — {f['title']}",
            f"**Location:** `{f['location']}`{conf_str}  ·  **Basis:** {basis}",
        ]
        + ([tags_line] if tags_line else [])
        + [
            "",
            f"**Standard:** {f['standard']}",
            "",
            f"**Problem:** {f['problem']}",
            "",
            f"**Likely cause:** {f['likely_cause']}",
            "",
            f"**Impact if unaddressed:** {impact}",
            "",
            "**Fix:**",
            "```diff",
            fix["diff"].rstrip("\n"),
            "```",
            f"*Why this works:* {fix['why']}",
        ]
        + (
            # Performance findings: show the cost/gain line when present.
            [
                "",
                f"**Performance:** {f.get('current_cost', '?')} → {f.get('projected_cost', '?')}"
                + (f"  (gain: {f['gain']})" if f.get("gain") else ""),
            ]
            if any(f.get(k) for k in ("current_cost", "projected_cost", "gain"))
            else []
        )
        + [
            "",
            disposition,
        ]
    )


def _transparency(pack: dict, findings: list) -> tuple[int, int, int] | None:
    """Found / Reported / Filtered - false-positive transparency. `found` and `filtered` are
    historical facts about the scoring pass and can only come from the pack (explicit integer
    fields, else recovered from the standardised 'scoring' prose line). `reported` is always the
    LIVE len(findings), never trusted from the pack/prose: a pack-supplied reported count is
    review-scorer's count at scoring time, and goes stale the moment the PM edits, merges or
    challenges findings afterwards - trusting it verbatim let the printed transparency line
    silently disagree with a direct recount of the rendered rows (ISRT 2026-09-15). Returns None
    when neither `found` nor a scoring line is present (a pack that never scored), so nothing is
    invented."""
    found, filtered = pack.get("found"), pack.get("filtered")
    reported = len(findings)
    if isinstance(found, int) and isinstance(filtered, int):
        return found, reported, filtered
    m = _FRF_RE.search(pack.get("scoring") or "")
    if m:
        return int(m.group(1)), reported, int(m.group(3))
    return None


def _cell(text: str) -> str:
    """Escape a value for a Markdown table cell: pipes would end the column, newlines the row."""
    return str(text).replace("|", "\\|").replace("\n", " ").strip()


def _summary_table(ordered: list) -> list[str]:
    """The findings-at-a-glance index: one row per finding, worst-first, each id linking to its
    full entry. The single most common gap versus GitHub code scanning / SonarQube / SARIF, which
    all lead with a scannable per-finding list before the detail. Tags and Fix-effort columns
    appear only when at least one finding carries them, so a pack that uses neither is unchanged."""
    has_tags = any(f.get("tags") for f in ordered)
    has_effort = any(f.get("effort") for f in ordered)
    headers = ["ID", "Severity", "Title", "Location", "Conf."]
    if has_tags:
        headers.append("Tags")
    if has_effort:
        headers.append("Fix effort")
    headers.append("Disposition")
    rows = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    for f in ordered:
        sev = f.get("severity", "style")
        conf = f.get("confidence")
        cells = [
            f"[{_cell(f['id'])}](#{_anchor(f['id'])})",
            f"{_SEV.get(sev, '•')} {_SEV_WORD.get(sev, sev)}",
            _cell(f["title"]),
            f"`{_cell(f['location'])}`",
            f"{conf}" if conf is not None else "-",
        ]
        if has_tags:
            tags = f.get("tags") or []
            cells.append("  ·  ".join(f"`{_cell(t)}`" for t in tags) if tags else "-")
        if has_effort:
            cells.append(_cell(f["effort"]) if f.get("effort") else "-")
        cells.append(_DISP.get(f.get("disposition", ""), f.get("disposition", "")))
        rows.append("| " + " | ".join(cells) + " |")
    return rows


def _fix_first_line(ordered: list) -> str:
    """Remediation priority - the fix-first call-out. Worst-first ordering answers 'how bad',
    not 'what to fix first': the actionable order is the still-OPEN blocking findings (critical
    and warning), highest severity then highest confidence. Medium and style are non-blocking and
    left to follow-up, matching the severity lanes in docs/code-review-method.md."""
    blocking = [
        f
        for f in ordered
        if f.get("disposition") == "open" and f.get("severity") in ("critical", "warning")
    ]
    blocking.sort(
        key=lambda f: (_SEV_ORDER.index(f.get("severity", "style")), -(f.get("confidence") or 0))
    )
    if not blocking:
        return "**Fix first:** no open critical or warning findings."
    refs = "  ·  ".join(
        f"{_SEV.get(f.get('severity'), '•')} [{f['id']}](#{_anchor(f['id'])})" for f in blocking
    )
    return "**Fix first** (open critical/warning, highest severity then confidence): " + refs


_LEGEND = (
    "**Legend** · Severity 🔴 Critical · 🟠 Warning · 🟡 Medium · 🔵 Style/form · "
    "Basis 📊 measured · 📄 coded · 🧠 inferred · "
    "Disposition ✅ Fixed · 🔴 Open · ⚖️ Accepted · ⏭️ Deferred"
)


def render(pack: dict) -> str:
    findings = pack.get("findings", [])
    counts = {sev: sum(1 for f in findings if f.get("severity") == sev) for sev in _SEV_ORDER}
    scoreboard = "  ·  ".join(f"{_SEV[s]} {counts[s]}" for s in _SEV_ORDER)
    disp_counts = {
        d: sum(1 for f in findings if f.get("disposition") == d)
        for d in ("fixed", "open", "accepted", "deferred")
    }
    tally = (
        f"✅ {disp_counts['fixed']}  ·  🔴 {disp_counts['open']}  ·  "
        f"⚖️ {disp_counts['accepted']}  ·  ⏭️ {disp_counts['deferred']}"
    )
    # Findings ordered by severity so the report reads worst-first.
    ordered = sorted(findings, key=lambda f: _SEV_ORDER.index(f.get("severity", "style")))

    kind = pack.get("kind", "review")
    title = pack.get("title") or f"{_KIND.get(kind, _KIND['review'])[1]} — {pack['slug']}"
    lines = [
        f"# {title}",
        "",
        # 🤖 on the framework's own generated review document (2026-08-20): it is handed to
        # developers and auditors, and until now said nothing about being AI-produced.
        f"> 🤖 Generated by `render_findings` from the findings pack, by the virtual "
        f"compliance-surveillance engineering team (AI agents, Virtual Surveillance IT) · "
        f"**Mode** {pack['mode']} · "
        f"**Verdict** {pack['verdict']}",
        f"> **Scope:** {pack['scope']}"
        + (f"  ·  **Commit:** `{pack['commit']}`" if pack.get("commit") else "")
        + (
            f"  ·  **Reviewer independence:** {pack['reviewer_independence']}"
            if pack.get("reviewer_independence")
            else ""
        ),
        "",
        "**Contents**",
        "",
        "[TOC]",
        "",
        "## Executive summary",
        pack.get("executive_summary", "_(none provided)_"),
        "",
    ]
    if pack.get("methodology"):
        lines += ["## Method", pack["methodology"], ""]
    lines += [
        "## Scoreboard",
        scoreboard,
        "",
    ]
    tr = _transparency(pack, findings)
    if tr:
        found, reported, filtered = tr
        lines += [
            f"**Found {found}**  ·  **Reported {reported}**  ·  **Filtered {filtered}**  "
            "*(filtered items were seen and set aside with a reason, not missed)*",
            "",
        ]
    if pack.get("scoring"):
        lines += [f"> **Scoring & filtering.** {pack['scoring']}", ""]
    # Findings at a glance: the fix-first order + a per-finding index table, so a reader sees the
    # whole shape and the priority before the detail. Skipped on an empty pack (nothing to index).
    if findings:
        lines += ["## Findings at a glance", _fix_first_line(ordered), ""]
        lines += _summary_table(ordered)
        lines += ["", _LEGEND, ""]
    if pack.get("tooling_coverage"):
        # A SECTION, not a bold line (2026-09-13): the DoD gate looks for a
        # '## 🔬 Tooling coverage' heading (check_artifacts FINDINGS-NO-TOOLING-COVERAGE), so a
        # report rendered from a pack that named its analysers used to fail the very gate the
        # pack exists to satisfy. Found by the first token-free try run.
        lines += ["## 🔬 Tooling coverage", pack["tooling_coverage"], ""]
    lines += ["## Findings"]
    if ordered:
        for f in ordered:
            lines.append("")
            lines.append(_finding_block(f))
    else:
        lines.append("")
        lines.append("_No findings._")
    lines += [
        "",
        "## 🔵 Developer guidance - improving future code",
        pack.get("developer_guidance", "_(none provided)_"),
        "",
        "## Limitations & residual risk",
        pack.get("limitations", "_(none stated)_"),
        "",
        f"**Disposition tally:** {tally}",
        "",
    ]
    return "\n".join(line for line in lines if line is not None) + "\n"


def _default_out(pack_path: Path, slug: str, prefix: str = "REVIEW") -> Path:
    # Pack in artifacts/data/ -> report up in artifacts/; otherwise alongside the pack.
    # The prefix is the kind's (REVIEW- / SECURITY-AUDIT- / PERF-).
    root = pack_path.parent.parent if pack_path.parent.name == "data" else pack_path.parent
    return root / f"{prefix}-{slug}.md"


def render_pack_file(
    pack_path: Path, out_path: Path | None = None, want_html: bool = False
) -> Path:
    """Validate + render one findings pack to its canonical REVIEW-<slug>.md, in-process.
    Shared by main() (CLI) and check_artifacts.apply_fixes() (2026-08-05 perf fix - apply_fixes
    used to shell out to this script once per pack, immediately followed by a subprocess per
    un-rendered .md - on a host where every python.exe spawn is inflated by endpoint-security
    scanning (corp Windows), that chain of untimed spawns could present as the whole close step
    hanging). Raises ValueError (with the schema violations) on an invalid pack - never renders
    a bad report silently."""
    errs = load_and_validate(pack_path)
    if errs:
        raise ValueError(f"{len(errs)} schema violation(s): " + "; ".join(errs))
    pack = read_pack(pack_path)
    prefix = _KIND.get(pack.get("kind", "review"), _KIND["review"])[0]
    out = out_path or _default_out(pack_path, pack["slug"], prefix)
    out.write_text(render(pack), encoding="utf-8")
    if want_html:
        try:
            from scripts.render_html import render_file as _render_html_file
        except ImportError:  # pragma: no cover - direct-path invocation
            from render_html import render_file as _render_html_file  # type: ignore[no-redef]
        _render_html_file(out)
    return out


def main(argv: list[str]) -> int:
    _force_utf8_output()
    args = [a for a in argv[1:] if not a.startswith("--")]
    do_html = "--html" in argv[1:]
    out_flag = next(
        (argv[i + 1] for i, a in enumerate(argv) if a == "--out" and i + 1 < len(argv)), None
    )
    if not args:
        print("usage: python -m scripts.render_findings <pack.jsonl> [--out FILE] [--html]")
        return 2
    pack_path = Path(args[0])
    out_override = Path(out_flag) if out_flag else None
    try:
        out = render_pack_file(pack_path, out_override, want_html=do_html)
    except ValueError as exc:
        print(f"REFUSING to render {pack_path}: {exc} - run validate_findings")
        return 1
    print(f"Rendered findings pack -> {out}" + (" (+ HTML)" if do_html else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
