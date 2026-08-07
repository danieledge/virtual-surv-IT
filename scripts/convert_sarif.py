"""
scripts/convert_sarif.py - SARIF tool output -> the team's findings pack (ADR-009).

Most commercial analysers (registered via the company extensions contract) emit SARIF.
This deterministic converter maps a SARIF log to the findings-pack JSONL the review
pipeline already consumes (docs/review/findings-schema.json; on-disk format in
findings_pack_io.py), so company-tool findings keep 📊 measured status with the tool report
retained on disk as evidence, and render through the same `render_findings` path as every
other review. Zero LLM.

Mapping: each run's results become findings; severity from SARIF `level` through the
company severity map (default: error->critical, warning->warning, note->style); location
from the first physical location (uri:line); `standard` = ruleId; rule metadata fills the
impact line when present. Fields SARIF cannot supply are filled with explicit
triage-required text - never invented specifics.

Usage (consent-free team tooling):
  python -m scripts.convert_sarif report.sarif --slug <slug> --scope "<what was scanned>"
      [--tool NAME] [--severity-map error=critical,warning=warning,note=style]
      [--mode audit|change] [-o artifacts/<ws>/data/findings-<slug>.jsonl]
Default output: alongside the input as findings-<slug>.jsonl. Validate with
`python -m scripts.validate_findings <pack>`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from scripts.findings_pack_io import write_pack
except ImportError:  # pragma: no cover - direct-path invocation
    from findings_pack_io import write_pack  # type: ignore[no-redef]

_DEFAULT_SEV = {"error": "critical", "warning": "warning", "note": "style", "none": "style"}


def _force_utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def _sev_map(spec: str | None) -> dict[str, str]:
    mapping = dict(_DEFAULT_SEV)
    for pair in (spec or "").split(","):
        if "=" in pair:
            k, v = pair.split("=", 1)
            if v.strip() in ("critical", "warning", "medium", "style"):
                mapping[k.strip().lower()] = v.strip()
    return mapping


def _location(result: dict) -> str:
    for loc in result.get("locations") or []:
        phys = loc.get("physicalLocation") or {}
        uri = ((phys.get("artifactLocation") or {}).get("uri")) or "unknown"
        line = (phys.get("region") or {}).get("startLine")
        return f"{uri}:{line}" if line else uri
    return "unknown"


def convert(
    sarif: dict,
    slug: str,
    scope: str,
    tool: str | None,
    sev_spec: str | None,
    mode: str,
    source_name: str,
) -> dict:
    mapping = _sev_map(sev_spec)
    findings: list[dict] = []
    tool_names: list[str] = []
    for run in sarif.get("runs") or []:
        driver = ((run.get("tool") or {}).get("driver")) or {}
        run_tool = tool or driver.get("name") or "registered tool"
        tool_names.append(run_tool)
        rules = {r.get("id"): r for r in (driver.get("rules") or []) if isinstance(r, dict)}
        for result in run.get("results") or []:
            rule_id = result.get("ruleId") or "unspecified-rule"
            msg = ((result.get("message") or {}).get("text")) or rule_id
            level = (result.get("level") or "warning").lower()
            rule = rules.get(rule_id) or {}
            impact = (
                ((rule.get("shortDescription") or {}).get("text"))
                or ((rule.get("fullDescription") or {}).get("text"))
                or f"as assessed by {run_tool} rule {rule_id} - triage against our context required"
            )
            findings.append(
                {
                    "id": f"F{len(findings) + 1}",
                    "title": msg[:120],
                    "severity": mapping.get(level, "warning"),
                    "location": _location(result),
                    "basis": "measured",
                    "standard": f"{run_tool}:{rule_id}",
                    "problem": msg,
                    "likely_cause": f"reported by {run_tool} (rule {rule_id}); root cause "
                    "to be confirmed at the flagged location",
                    "impact": impact,
                    "fix": {
                        "diff": "",
                        "why": f"resolve at source per {run_tool} rule {rule_id}; "
                        "no automated diff - the tool report is the evidence",
                    },
                    "disposition": "open",
                }
            )
    counts = {"critical": 0, "warning": 0, "medium": 0, "style": 0}
    for f in findings:
        counts[f["severity"]] += 1
    verdict = (
        "not yet - open criticals"
        if counts["critical"]
        else ("conditional" if findings else "ready")
    )
    return {
        "slug": slug,
        "kind": "review",
        "title": f"{'/'.join(sorted(set(tool_names))) or 'Registered tool'} findings ({slug})",
        "scope": scope,
        "mode": mode,
        "verdict": verdict,
        "tooling_coverage": f"converted from SARIF: {source_name} "
        f"({', '.join(sorted(set(tool_names))) or 'unknown tool'}) - report retained as "
        "on-disk evidence (📊 measured)",
        "findings": findings,
    }


def main(argv: list[str] | None = None) -> int:
    _force_utf8_output()
    ap = argparse.ArgumentParser(prog="python -m scripts.convert_sarif")
    ap.add_argument("sarif", type=Path)
    ap.add_argument("--slug", required=True)
    ap.add_argument("--scope", required=True)
    ap.add_argument("--tool", default=None)
    ap.add_argument("--severity-map", default=None)
    ap.add_argument("--mode", choices=("audit", "change"), default="audit")
    ap.add_argument("-o", "--out", type=Path, default=None)
    args = ap.parse_args(argv)
    try:
        sarif = json.loads(args.sarif.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"cannot read SARIF: {exc}", file=sys.stderr)
        return 2
    pack = convert(
        sarif, args.slug, args.scope, args.tool, args.severity_map, args.mode, args.sarif.name
    )
    out = args.out or args.sarif.parent / f"findings-{args.slug}.jsonl"
    write_pack(out, pack)
    print(f"wrote {out} ({len(pack['findings'])} finding(s); verdict {pack['verdict']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
