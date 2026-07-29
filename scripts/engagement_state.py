"""
scripts/engagement_state.py - the machine-readable engagement state (ADR-006).

One JSON file per engagement, `artifacts/engagement-state.json`, is the authoritative
record of lifecycle state: status, phase, outstanding items, artifact inventory, decisions
and footprint. The human-readable `START-HERE.md` (and its `.html` sibling) is a RENDERED
VIEW generated from this file - never hand-edited. "The index leads reality" becomes "the
state leads reality": every mutation below re-validates and re-renders in the same command,
so the human view can never lag the state by more than a crash window, and
`check_artifacts` closes that window with `STATE-STALE-RENDER` (auto-fixed by re-render).

Design constraints:
- stdlib only (runs in foreign plugin installs with no pip; the `.html` sibling degrades
  gracefully when the Markdown package is absent - the DoD `MISSING-HTML` check catches it).
- NO consent field, ever. Execution consent is the human-created `.claude/.exec-consent`
  marker and nothing else (ADR-002). A state file carrying a consent-like key fails
  validation - a second, model-writable "source of truth" for consent is the exact
  confusion the threat model forbids.
- Fail-safe rendering: the status line renders with exactly one state emoji so the
  emoji-sniffing consumers (`_index_status`, legacy hook fallback) read it unambiguously.

Usage (all consent-free team tooling, `python -m scripts.engagement_state <cmd>`):
  init --title T --slug S [--requested-by R] [--team-version V] [--phase plan]
  validate                     # exit 1 with findings if the state is invalid
  render                       # regenerate START-HERE.md + .html from the state
  set-status {in_progress,blocked,closed} [--verdict TEXT]
  set-phase {open,classify,plan,delivery,close}
  add-artifact PATH --title TEXT [--final]
  add-outstanding TEXT
  resolve-outstanding SUBSTRING
  set-decision KEY VALUE
  set-team "Name (role)" ...
  finalise-artifacts
  set-footprint [--agents N] [--tokens TEXT]
  log-note TEXT                # dated event/completion note - NOT the outstanding list
  add-ratification TEXT        # a decision awaiting human ratification (status pending)
  ratify SUBSTRING [--by WHO]  # human-confirmed: pending -> ratified, dated

Schema v2 (2026-07-26): `log` holds completion notes and events; `outstanding` holds ONLY
open work (the live run parked "COMPLETE" notes in outstanding, hiding convergence).
`ratifications` make approval state structured - artifacts asserting a ratification the
state still records as pending is a `RATIFIED-CLAIM-PENDING` gate finding. v1 files remain
valid and upgrade in place on their first mutation.

Close ordering: `set-team` and `finalise-artifacts` must precede `set-status closed` -
closed-state validation requires a non-empty team and no interim artifact rows (born of the
2026-07-26 live run, which closed with both left at defaults for want of a mutator).
All commands accept --dir ARTIFACTS_DIR (default: $CLAUDE_PROJECT_DIR/artifacts, else
./artifacts). Every mutator ends with validate + render.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import sys
from pathlib import Path

STATE_FILENAME = "engagement-state.json"
INDEX_FILENAME = "START-HERE.md"
SCHEMA_VERSION = 2
_ACCEPTED_SCHEMAS = (1, 2)  # v1 files stay valid; first mutation upgrades them in place
_RATIFICATION_STATUSES = ("pending", "ratified")

_STATUSES = ("in_progress", "blocked", "closed")
_PHASES = ("open", "classify", "plan", "delivery", "close")
_PROFILES = ("standard", "light")
_ARTIFACT_STATUSES = ("interim", "final")

# The one hard exclusion (ADR-002 / ADR-006): consent must never gain a second home here.
_FORBIDDEN_KEY_FRAGMENTS = ("consent", "exec")

_STATUS_RENDER = {
    "in_progress": "⏳ IN PROGRESS",
    "blocked": "⛔ BLOCKED - awaiting input",
    "closed": "✅ CLOSED",
}

_HASH_MARKER_PREFIX = "<!-- rendered-from: engagement-state.json state-hash:"
_HASH_MARKER_SUFFIX = "-->"


def _force_utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def _default_artifacts_dir() -> Path:
    root = os.environ.get("CLAUDE_PROJECT_DIR")
    return (Path(root) if root else Path.cwd()) / "artifacts"


# ------------------------------------------------------------------ workspaces (0.31)
# Several engagements can coexist in one project at independent states: each lives in its
# own workspace `artifacts/<slug>/` with its own state + rendered index. The root carries a
# DERIVED registry (engagements.json + ENGAGEMENTS.md) regenerated from a scan on every
# mutation - it can never become a second source of truth. A legacy FLAT pack (state
# directly in artifacts/) keeps working everywhere; `migrate` moves it into a workspace.

REGISTRY_JSON = "engagements.json"
REGISTRY_MD = "ENGAGEMENTS.md"


def workspace_states(root: Path) -> list[Path]:
    """Workspace state files directly under the artifacts root (one level, sorted)."""
    if not root.is_dir():
        return []
    return sorted(
        p / STATE_FILENAME for p in root.iterdir() if p.is_dir() and (p / STATE_FILENAME).is_file()
    )


def scan_engagements(root: Path) -> list[dict]:
    """Registry rows derived from the packs on disk (flat pack first, then workspaces)."""
    rows: list[dict] = []
    candidates: list[tuple[str, Path]] = []
    if state_path(root).is_file():
        candidates.append(("(flat)", root))
    candidates.extend((sp.parent.name, sp.parent) for sp in workspace_states(root))
    for slug, pack in candidates:
        try:
            state = load_state(pack)
        except Exception:
            rows.append(
                {
                    "slug": slug,
                    "title": "(unreadable state)",
                    "status": "invalid",
                    "profile": None,
                    "opened": None,
                    "closed": None,
                }
            )
            continue
        eng = state.get("engagement") or {}
        rows.append(
            {
                "slug": slug if slug != "(flat)" else (eng.get("slug") or "(flat)"),
                "dir": slug,
                "title": eng.get("title"),
                "status": state.get("status"),
                "profile": state.get("profile") or "standard",
                "opened": eng.get("opened"),
                "closed": eng.get("closed"),
            }
        )
    return rows


def render_registry(root: Path) -> list[Path]:
    """(Re)generate the derived root registry. Removes it when no packs remain."""
    rows = scan_engagements(root)
    json_path = root / REGISTRY_JSON
    md_path = root / REGISTRY_MD
    if not rows:
        for p in (json_path, md_path, md_path.with_suffix(".html")):
            p.unlink(missing_ok=True)
        return []
    root.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps({"derived": True, "engagements": rows}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    emoji = {"in_progress": "⏳", "blocked": "⛔", "closed": "✅", "invalid": "❗"}
    lines = [
        "# Engagements in this project",
        "",
        "> DERIVED registry - regenerated from each workspace's `engagement-state.json` on",
        "> every mutation; never hand-edit (`REGISTRY-STALE` if it drifts). Open the",
        "> engagement's own `START-HERE.md` for detail.",
        "",
        "| Engagement | Status | Profile | Title | Opened | Closed |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        mark = emoji.get(r.get("status"), r.get("status") or "?")
        where = r.get("dir") or r.get("slug")
        link = f"[`{where}/`]({where}/START-HERE.md)" if where != "(flat)" else "`(flat pack)`"
        lines.append(
            f"| {link} | {mark} {r.get('status')} | {r.get('profile') or ''} "
            f"| {r.get('title') or ''} | {r.get('opened') or ''} | {r.get('closed') or ''} |"
        )
    lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    written = [json_path, md_path]
    try:
        from scripts.render_html import _title_from, render

        md_text = md_path.read_text(encoding="utf-8")
        html_path = md_path.with_suffix(".html")
        html_path.write_text(
            render(
                md_text,
                _title_from(md_text, md_path.stem),
                source=md_path.name,
                generated=_dt.date.today().isoformat(),
            ),
            encoding="utf-8",
        )
        written.append(html_path)
    # The HTML mirror is best-effort; the .md/.json are already written.
    except Exception:  # nosec B110
        pass
    return written


def _registry_root_for(pack_dir: Path) -> Path | None:
    """The artifacts root whose registry covers this pack, or None for a standalone flat
    pack (e.g. a test tmp dir with no sibling workspaces and no registry)."""
    parent = pack_dir.parent
    if workspace_states(parent) or (parent / REGISTRY_JSON).is_file():
        return parent
    if state_path(pack_dir).is_file() and workspace_states(pack_dir):
        return pack_dir  # flat pack that ALSO has sibling workspaces under it
    return None


def resolve_pack_dir(args: argparse.Namespace) -> Path:
    """Which pack a command targets: --dir wins; then --slug under the root; then the only
    pack in the project (flat or single workspace); ambiguity is an explicit error."""
    if args.dir is not None:
        return args.dir
    root = _default_artifacts_dir()
    slug = getattr(args, "target_slug", None)
    if slug:
        return root / slug
    candidates: list[Path] = []
    if state_path(root).is_file():
        candidates.append(root)
    candidates.extend(sp.parent for sp in workspace_states(root))
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        return root  # nothing yet - flat semantics (init resolves its own target)
    names = ", ".join(c.name if c != root else "(flat)" for c in candidates)
    print(
        f"multiple engagements in {root} ({names}) - say which with --slug <name> (or --dir)",
        file=sys.stderr,
    )
    raise SystemExit(2)


def state_path(artifacts_dir: Path) -> Path:
    return artifacts_dir / STATE_FILENAME


def index_path(artifacts_dir: Path) -> Path:
    return artifacts_dir / INDEX_FILENAME


def state_hash(state: dict) -> str:
    """Stable short hash of the state content - embedded in the render, checked by the DoD."""
    canon = json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]


def load_state(artifacts_dir: Path) -> dict:
    return json.loads(state_path(artifacts_dir).read_text(encoding="utf-8"))


def _forbidden_keys(obj, trail="") -> list[str]:
    found: list[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            where = f"{trail}.{key}" if trail else str(key)
            if any(frag in str(key).lower() for frag in _FORBIDDEN_KEY_FRAGMENTS):
                found.append(where)
            found.extend(_forbidden_keys(value, where))
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            found.extend(_forbidden_keys(value, f"{trail}[{i}]"))
    return found


def validate_state(state: dict) -> list[str]:
    """Hand-rolled stdlib validation; returns a list of problems (empty = valid)."""
    problems: list[str] = []
    if not isinstance(state, dict):
        return ["state root must be a JSON object"]

    for bad in _forbidden_keys(state):
        problems.append(
            f"forbidden key {bad!r}: consent/execution state must never live in this file - "
            "the only execution-consent record is the human-created .claude/.exec-consent "
            "marker (ADR-002)"
        )

    if state.get("schema") not in _ACCEPTED_SCHEMAS:
        problems.append(f"schema must be one of {_ACCEPTED_SCHEMAS} (got {state.get('schema')!r})")

    eng = state.get("engagement")
    if not isinstance(eng, dict):
        problems.append("missing/invalid 'engagement' object")
        eng = {}
    for field in ("title", "slug", "opened"):
        if not isinstance(eng.get(field), str) or not eng.get(field):
            problems.append(f"engagement.{field} must be a non-empty string")

    status = state.get("status")
    if status not in _STATUSES:
        problems.append(f"status must be one of {_STATUSES} (got {status!r})")
    if status == "closed" and not eng.get("closed"):
        problems.append("status is 'closed' but engagement.closed date is not set")
    if status != "closed" and eng.get("closed"):
        problems.append("engagement.closed is set but status is not 'closed'")

    if state.get("phase") not in _PHASES:
        problems.append(f"phase must be one of {_PHASES} (got {state.get('phase')!r})")

    profile = state.get("profile")
    if profile is not None and profile not in _PROFILES:
        problems.append(f"profile must be one of {_PROFILES} (got {profile!r})")

    outstanding = state.get("outstanding")
    if not isinstance(outstanding, list) or not all(isinstance(i, str) and i for i in outstanding):
        problems.append("'outstanding' must be a list of non-empty strings")
    elif status == "closed" and outstanding:
        problems.append("status is 'closed' but 'outstanding' is not empty")
    elif status == "blocked" and outstanding == []:
        problems.append("status is 'blocked' but 'outstanding' is empty - record what it waits on")

    # Schema v2: the log is for completion notes and events; outstanding is ONLY open work
    # (2026-07-26 live run parked "Fix cycle 3 COMPLETE" notes in outstanding, inflating it
    # 9 -> 12 and hiding true convergence).
    log = state.get("log")
    if log is not None and not (
        isinstance(log, list) and all(isinstance(e, str) and e for e in log)
    ):
        problems.append("'log' must be a list of non-empty strings")

    ratifications = state.get("ratifications")
    if ratifications is not None:
        if not isinstance(ratifications, list):
            problems.append("'ratifications' must be a list")
        else:
            for i, r in enumerate(ratifications):
                if not isinstance(r, dict) or not (
                    isinstance(r.get("text"), str) and r.get("text")
                ):
                    problems.append(f"ratifications[{i}] must be an object with 'text'")
                    continue
                if r.get("status") not in _RATIFICATION_STATUSES:
                    problems.append(
                        f"ratifications[{i}].status must be one of "
                        f"{_RATIFICATION_STATUSES} (got {r.get('status')!r})"
                    )

    team = state.get("team")
    if team is not None and not (
        isinstance(team, list) and all(isinstance(t, str) and t for t in team)
    ):
        problems.append("'team' must be a list of non-empty strings")
    # Closed-state completeness (2026-07-26 live-run review: a closed pack shipped with
    # team: [] and every artifact still interim because nothing enforced the close):
    if status == "closed":
        if not team:
            problems.append(
                "status is 'closed' but 'team' is empty - record who delivered "
                "(set-team) before closing"
            )
        interim = [
            a.get("path")
            for a in (state.get("artifacts") or [])
            if isinstance(a, dict) and a.get("status") == "interim"
        ]
        if interim:
            problems.append(
                f"status is 'closed' but {len(interim)} artifact(s) still 'interim' "
                f"(e.g. {interim[0]}) - run finalise-artifacts before closing"
            )

    artifacts = state.get("artifacts")
    if not isinstance(artifacts, list):
        problems.append("'artifacts' must be a list")
        artifacts = []
    seen: set[str] = set()
    for i, art in enumerate(artifacts):
        if not isinstance(art, dict):
            problems.append(f"artifacts[{i}] must be an object")
            continue
        path = art.get("path")
        if not isinstance(path, str) or not path:
            problems.append(f"artifacts[{i}].path must be a non-empty string")
        elif path in seen:
            problems.append(f"artifacts[{i}].path duplicates {path!r}")
        else:
            seen.add(path)
        if not isinstance(art.get("title"), str) or not art.get("title"):
            problems.append(f"artifacts[{i}].title must be a non-empty string")
        if art.get("status") not in _ARTIFACT_STATUSES:
            problems.append(
                f"artifacts[{i}].status must be one of {_ARTIFACT_STATUSES} "
                f"(got {art.get('status')!r})"
            )

    decisions = state.get("decisions")
    if decisions is not None and not (
        isinstance(decisions, dict) and all(isinstance(v, str) for v in decisions.values())
    ):
        problems.append("'decisions' must be an object of string values")

    footprint = state.get("footprint")
    if footprint is not None and not isinstance(footprint, dict):
        problems.append("'footprint' must be an object")

    return problems


# ---------------------------------------------------------------------------- rendering


def render_markdown(state: dict) -> str:
    """Build the START-HERE.md text from the state. Pure function - no I/O."""
    eng = state.get("engagement", {})
    status = state.get("status", "in_progress")
    closed_date = eng.get("closed") or ""
    status_line = _STATUS_RENDER.get(status, status)
    if status == "closed" and closed_date:
        status_line = f"{_STATUS_RENDER['closed']} {closed_date}"

    verdict = state.get("verdict") or (
        "none yet - engagement not closed, DoD not yet run"
        if status != "closed"
        else "closed - see the Delivery Report"
    )
    team = state.get("team") or []
    team_line = ", ".join(team) if team else "not yet assigned"
    footprint = state.get("footprint") or {}
    agents = footprint.get("agents")
    tokens = footprint.get("approx_tokens")
    if agents or tokens:
        so_far = "" if status == "closed" else " so far"
        footprint_line = (
            f"~{agents if agents is not None else '?'} agents · "
            f"roughly {tokens if tokens else '?'} tokens{so_far}"
        )
    else:
        footprint_line = "not yet recorded"

    lines: list[str] = []
    lines.append(f"# START HERE - {eng.get('title', '')}")
    lines.append("")
    lines.append("> **Generated view - do not hand-edit.** The machine-readable source of truth is")
    lines.append(
        "> [`engagement-state.json`](engagement-state.json) (schema v1, ADR-006). Update the"
    )
    lines.append(
        "> state (`python -m scripts.engagement_state ...`) and this file re-renders; a stale"
    )
    lines.append("> render is a DoD finding (`STATE-STALE-RENDER`).")
    lines.append("")
    lines.append("| | |")
    lines.append("|---|---|")
    lines.append(f"| **Engagement** | {eng.get('title', '')} |")
    lines.append(f"| **Status** | {status_line} |")
    lines.append(f"| **Opened** | {eng.get('opened', '')} |")
    lines.append(f"| **Requested by** | {eng.get('requested_by') or 'unknown'} |")
    lines.append(f"| **Profile** | {state.get('profile') or 'standard'} |")
    lines.append(f"| **Phase** | {state.get('phase', '')} |")
    lines.append(f"| **Verdict** | {verdict} |")
    lines.append(f"| **Team** | {team_line} |")
    lines.append(f"| **Footprint** | {footprint_line} |")
    lines.append("")
    lines.append("## ⚠️ Outstanding before this is done")
    lines.append("")
    outstanding = state.get("outstanding") or []
    if status == "closed":
        lines.append(f"Nothing - closed {closed_date}.")
    elif outstanding:
        lines.extend(f"- {item}" for item in outstanding)
    else:
        lines.append("- none recorded yet - seed this with the gates ahead")
    lines.append("")

    artifacts = state.get("artifacts") or []
    paths = {a.get("path") for a in artifacts}
    lines.append("## Read in this order")
    lines.append("")
    if status == "closed":
        order = 1
        email = next((p for p in paths if str(p).startswith("engagement-summary-")), None)
        if email:
            lines.append(f"{order}. [`{email}`]({email}) - the two-minute cover note.")
            order += 1
        if "delivery-report.md" in paths:
            lines.append(
                f"{order}. [`delivery-report.md`](delivery-report.md) - the consolidated "
                "report: iteration log, findings with dispositions, QA evidence, limitations."
            )
            order += 1
        lines.append(f"{order}. *Then by interest:* the artifacts below.")
    else:
        lines.append(
            "*(Interim pack - the summary email and Delivery Report exist only at ✅ close.)*"
        )
        lines.append("")
        if "engagement-brief.md" in paths:
            lines.append(
                "1. [`engagement-brief.md`](engagement-brief.md) - scope, decisions, plan."
            )
            lines.append("2. *Then by interest:* the artifacts below.")
        else:
            lines.append("1. The artifacts below, newest last.")
    lines.append("")
    lines.append("## Everything in this delivery")
    lines.append("")
    lines.append("| Artifact | What it is | Status |")
    lines.append("|----------|------------|--------|")
    if artifacts:
        for art in artifacts:
            lines.append(
                f"| [`{art.get('path')}`]({art.get('path')}) | {art.get('title')} "
                f"| {art.get('status')} |"
            )
    else:
        lines.append("| *(none yet)* | | |")
    lines.append("")

    decisions = state.get("decisions") or {}
    if decisions:
        lines.append("## Decisions of record")
        lines.append("")
        for key in sorted(decisions):
            lines.append(f"- **{key}**: {decisions[key]}")
        lines.append("")

    ratifications = state.get("ratifications") or []
    if ratifications:
        lines.append("## Ratifications")
        lines.append("")
        for r in ratifications:
            mark = "✔ ratified" if r.get("status") == "ratified" else "⏳ PENDING"
            by = f" by {r.get('by')}" if r.get("by") else ""
            date = f" {r.get('date')}" if r.get("date") else ""
            lines.append(f"- {mark}{date}{by}: {r.get('text')}")
        lines.append("")

    log = state.get("log") or []
    if log:
        lines.append("## Engagement log")
        lines.append("")
        lines.extend(f"- {entry}" for entry in log)
        lines.append("")

    lines.append("## Provenance")
    lines.append("")
    version = state.get("team_version") or ""
    version_bit = f" ({version})" if version else ""
    lines.append(
        "Produced by the virtual compliance-surveillance engineering team"
        f"{version_bit}. Evidence basis tags: 📊 measured · 🧠 inferred."
    )
    lines.append("")
    lines.append(f"{_HASH_MARKER_PREFIX} {state_hash(state)} {_HASH_MARKER_SUFFIX}")
    lines.append("")
    return "\n".join(lines)


def embedded_hash(index_text: str) -> str | None:
    """The state-hash recorded in a rendered START-HERE, or None if absent."""
    for line in index_text.splitlines():
        stripped = line.strip()
        if stripped.startswith(_HASH_MARKER_PREFIX):
            inner = stripped[len(_HASH_MARKER_PREFIX) :].removesuffix(_HASH_MARKER_SUFFIX)
            return inner.strip() or None
    return None


def render_files(artifacts_dir: Path) -> list[Path]:
    """Write START-HERE.md (+ .html when the renderer's deps exist) from the state file."""
    state = load_state(artifacts_dir)
    problems = validate_state(state)
    if problems:
        raise ValueError("state invalid: " + "; ".join(problems))
    md_text = render_markdown(state)
    md_path = index_path(artifacts_dir)
    md_path.write_text(md_text, encoding="utf-8")
    written = [md_path]
    try:
        from scripts.render_html import _title_from, render  # stdlib-safe import point

        html_path = md_path.with_suffix(".html")
        html_path.write_text(
            render(
                md_text,
                _title_from(md_text, md_path.stem),
                source=md_path.name,
                generated=_dt.date.today().isoformat(),
            ),
            encoding="utf-8",
        )
        written.append(html_path)
    except Exception as exc:  # degrade: MISSING-HTML in the DoD check will surface it
        print(f"note: .html sibling not rendered ({exc})", file=sys.stderr)
    return written


def _write_state(artifacts_dir: Path, state: dict) -> None:
    """Validate, then atomically write the state and re-render the human view."""
    problems = validate_state(state)
    if problems:
        for problem in problems:
            print(f"INVALID: {problem}", file=sys.stderr)
        raise SystemExit(1)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    target = state_path(artifacts_dir)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, target)
    for path in render_files(artifacts_dir):
        print(f"wrote {path}")
    registry_root = _registry_root_for(artifacts_dir)
    if registry_root is not None:
        render_registry(registry_root)


# ---------------------------------------------------------------------------- commands


def _cmd_init(args: argparse.Namespace) -> int:
    # New engagements are WORKSPACED by default (artifacts/<slug>/); an explicit --dir
    # keeps flat semantics (tests, custom layouts, pre-0.31 behaviour).
    if args.dir is None:
        args.dir = _default_artifacts_dir() / args.slug
    target = state_path(args.dir)
    if target.exists():
        print(f"refusing to overwrite existing {target}", file=sys.stderr)
        return 2
    state = {
        "schema": SCHEMA_VERSION,
        "engagement": {
            "title": args.title,
            "slug": args.slug,
            "requested_by": args.requested_by,
            "opened": _dt.date.today().isoformat(),
            "closed": None,
        },
        "status": "in_progress",
        "profile": args.profile,
        "phase": args.phase,
        "team": [],
        "verdict": None,
        "footprint": {"agents": None, "approx_tokens": None},
        "outstanding": [
            "independent QA - not yet run",
            "DoD check_artifacts - not yet run",
        ],
        "log": [],
        "ratifications": [],
        "artifacts": [],
        "decisions": {},
        "team_version": args.team_version,
    }
    _write_state(args.dir, state)
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    try:
        state = load_state(args.dir)
    except FileNotFoundError:
        print(f"no {STATE_FILENAME} in {args.dir}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"INVALID: not valid JSON: {exc}", file=sys.stderr)
        return 1
    problems = validate_state(state)
    for problem in problems:
        print(f"INVALID: {problem}", file=sys.stderr)
    if not problems:
        print("state valid")
    return 1 if problems else 0


def _cmd_render(args: argparse.Namespace) -> int:
    for path in render_files(args.dir):
        print(f"wrote {path}")
    return 0


def _upgrade(state: dict) -> None:
    """In-place v1 -> v2 migration: additive fields only, applied at first mutation."""
    if state.get("schema") == 1:
        state["schema"] = 2
        state.setdefault("log", [])
        state.setdefault("ratifications", [])


def _mutate(args: argparse.Namespace, fn) -> int:
    state = load_state(args.dir)
    _upgrade(state)
    fn(state)
    _write_state(args.dir, state)
    return 0


def _cmd_set_status(args: argparse.Namespace) -> int:
    def fn(state: dict) -> None:
        state["status"] = args.status
        if args.verdict:
            state["verdict"] = args.verdict
        if args.status == "closed":
            state["engagement"]["closed"] = _dt.date.today().isoformat()
            state["outstanding"] = []
            state["phase"] = "close"
        else:
            state["engagement"]["closed"] = None

    return _mutate(args, fn)


def _cmd_set_phase(args: argparse.Namespace) -> int:
    return _mutate(args, lambda s: s.__setitem__("phase", args.phase))


def _cmd_set_profile(args: argparse.Namespace) -> int:
    return _mutate(args, lambda s: s.__setitem__("profile", args.profile))


def _cmd_add_artifact(args: argparse.Namespace) -> int:
    def fn(state: dict) -> None:
        entry = {
            "path": args.path,
            "title": args.title,
            "status": "final" if args.final else "interim",
            "added": _dt.date.today().isoformat(),
        }
        arts = state.setdefault("artifacts", [])
        for i, existing in enumerate(arts):
            if existing.get("path") == args.path:
                entry["added"] = existing.get("added", entry["added"])
                arts[i] = entry
                return
        arts.append(entry)

    return _mutate(args, fn)


def _cmd_add_outstanding(args: argparse.Namespace) -> int:
    def fn(state: dict) -> None:
        items = state.setdefault("outstanding", [])
        if args.text not in items:
            items.append(args.text)

    return _mutate(args, fn)


def _cmd_resolve_outstanding(args: argparse.Namespace) -> int:
    state = load_state(args.dir)
    items = state.get("outstanding", [])
    kept = [i for i in items if args.substring.lower() not in i.lower()]
    if len(kept) == len(items):
        print(f"no outstanding item matches {args.substring!r}", file=sys.stderr)
        return 2
    state["outstanding"] = kept
    _write_state(args.dir, state)
    return 0


def _cmd_set_decision(args: argparse.Namespace) -> int:
    return _mutate(args, lambda s: s.setdefault("decisions", {}).__setitem__(args.key, args.value))


def _cmd_log_note(args: argparse.Namespace) -> int:
    def fn(state: dict) -> None:
        entry = f"{_dt.date.today().isoformat()}: {args.text}"
        log = state.setdefault("log", [])
        if entry not in log:
            log.append(entry)

    return _mutate(args, fn)


def _cmd_add_ratification(args: argparse.Namespace) -> int:
    def fn(state: dict) -> None:
        rats = state.setdefault("ratifications", [])
        if not any(r.get("text") == args.text for r in rats if isinstance(r, dict)):
            rats.append({"text": args.text, "status": "pending"})

    return _mutate(args, fn)


def _cmd_ratify(args: argparse.Namespace) -> int:
    state = load_state(args.dir)
    _upgrade(state)
    matched = [
        r
        for r in state.get("ratifications", [])
        if isinstance(r, dict)
        and args.substring.lower() in str(r.get("text", "")).lower()
        and r.get("status") == "pending"
    ]
    if not matched:
        print(f"no pending ratification matches {args.substring!r}", file=sys.stderr)
        return 2
    for r in matched:
        r["status"] = "ratified"
        r["date"] = _dt.date.today().isoformat()
        if args.by:
            r["by"] = args.by
    _write_state(args.dir, state)
    return 0


def _cmd_set_team(args: argparse.Namespace) -> int:
    return _mutate(args, lambda s: s.__setitem__("team", list(args.members)))


def _cmd_finalise_artifacts(args: argparse.Namespace) -> int:
    def fn(state: dict) -> None:
        for art in state.get("artifacts") or []:
            if isinstance(art, dict):
                art["status"] = "final"

    return _mutate(args, fn)


def _cmd_set_footprint(args: argparse.Namespace) -> int:
    def fn(state: dict) -> None:
        footprint = state.setdefault("footprint", {})
        if args.agents is not None:
            footprint["agents"] = args.agents
        if args.tokens is not None:
            footprint["approx_tokens"] = args.tokens

    return _mutate(args, fn)


def _cmd_list(args: argparse.Namespace) -> int:
    root = args.dir or _default_artifacts_dir()
    rows = scan_engagements(root)
    if not rows:
        print(f"no engagements in {root}")
        return 0
    for r in rows:
        print(
            f"{r.get('dir') or r.get('slug'):24} {r.get('status'):12} "
            f"{r.get('profile') or '':9} {r.get('title') or ''}"
        )
    return 0


def _cmd_migrate(args: argparse.Namespace) -> int:
    """Move a legacy FLAT pack into its own workspace artifacts/<slug>/ (everything in the
    root except existing workspace dirs and the registry), then regenerate the registry."""
    root = args.dir or _default_artifacts_dir()
    if not state_path(root).is_file():
        print(f"no flat pack at {root} - nothing to migrate", file=sys.stderr)
        return 2
    state = load_state(root)
    slug = (state.get("engagement") or {}).get("slug") or "engagement"
    target = root / slug
    if target.exists():
        print(f"refusing: {target} already exists", file=sys.stderr)
        return 2
    target.mkdir(parents=True)
    keep = {REGISTRY_JSON, REGISTRY_MD, Path(REGISTRY_MD).stem + ".html", slug}
    workspace_dirs = {sp.parent.name for sp in workspace_states(root)}
    import shutil

    moved = 0
    for item in sorted(root.iterdir()):
        if item.name in keep or item.name in workspace_dirs or item == target:
            continue
        shutil.move(str(item), str(target / item.name))
        moved += 1
    print(f"migrated flat pack -> {target} ({moved} item(s))")
    render_registry(root)
    return 0


def main(argv: list[str] | None = None) -> int:
    _force_utf8_output()
    parser = argparse.ArgumentParser(
        prog="python -m scripts.engagement_state",
        description="Authoritative machine-readable engagement state (ADR-006).",
    )
    parser.add_argument(
        "--dir",
        type=Path,
        default=None,
        help="pack directory (overrides workspace resolution; default: resolve via --slug "
        "or the project's only engagement)",
    )
    parser.add_argument(
        "--slug",
        dest="target_slug",
        default=None,
        help="target workspace under artifacts/ (required when several engagements exist)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="create the state file and first render")
    p.add_argument("--title", required=True)
    p.add_argument("--slug", required=True)
    p.add_argument("--requested-by", default=None)
    p.add_argument("--team-version", default=None)
    p.add_argument("--phase", choices=_PHASES, default="plan")
    p.add_argument(
        "--profile",
        choices=_PROFILES,
        default="standard",
        help="engagement ceremony profile - 'light' only when the USER invoked /engage-light",
    )
    p.set_defaults(fn=_cmd_init)

    p = sub.add_parser("validate", help="check the state file; exit 1 on findings")
    p.set_defaults(fn=_cmd_validate)

    p = sub.add_parser("render", help="regenerate START-HERE.md/.html from the state")
    p.set_defaults(fn=_cmd_render)

    p = sub.add_parser("set-status", help="change lifecycle status (renders)")
    p.add_argument("status", choices=_STATUSES)
    p.add_argument("--verdict", default=None)
    p.set_defaults(fn=_cmd_set_status)

    p = sub.add_parser("set-phase", help="change lifecycle phase (renders)")
    p.add_argument("phase", choices=_PHASES)
    p.set_defaults(fn=_cmd_set_phase)

    p = sub.add_parser(
        "set-profile", help="change ceremony profile (e.g. light -> standard upgrade)"
    )
    p.add_argument("profile", choices=_PROFILES)
    p.set_defaults(fn=_cmd_set_profile)

    p = sub.add_parser("add-artifact", help="add/update an artifact row (renders)")
    p.add_argument("path")
    p.add_argument("--title", required=True)
    p.add_argument("--final", action="store_true", help="mark final (default interim)")
    p.set_defaults(fn=_cmd_add_artifact)

    p = sub.add_parser("add-outstanding", help="append an outstanding item (renders)")
    p.add_argument("text")
    p.set_defaults(fn=_cmd_add_outstanding)

    p = sub.add_parser("resolve-outstanding", help="remove outstanding items matching a substring")
    p.add_argument("substring")
    p.set_defaults(fn=_cmd_resolve_outstanding)

    p = sub.add_parser("set-decision", help="record a decision of record (renders)")
    p.add_argument("key")
    p.add_argument("value")
    p.set_defaults(fn=_cmd_set_decision)

    p = sub.add_parser("log-note", help="append a dated event/completion note to the log (renders)")
    p.add_argument("text")
    p.set_defaults(fn=_cmd_log_note)

    p = sub.add_parser(
        "add-ratification", help="record a decision awaiting human ratification (renders)"
    )
    p.add_argument("text")
    p.set_defaults(fn=_cmd_add_ratification)

    p = sub.add_parser(
        "ratify", help="mark pending ratification(s) matching a substring as ratified"
    )
    p.add_argument("substring")
    p.add_argument("--by", default=None, help="who ratified (e.g. 'ops lead')")
    p.set_defaults(fn=_cmd_ratify)

    p = sub.add_parser("set-team", help="record the delivering team (renders)")
    p.add_argument("members", nargs="+", help='e.g. "Amara (BA)" "Linh (QA)"')
    p.set_defaults(fn=_cmd_set_team)

    p = sub.add_parser(
        "finalise-artifacts", help="mark every artifact row final (close step; renders)"
    )
    p.set_defaults(fn=_cmd_finalise_artifacts)

    p = sub.add_parser("set-footprint", help="update agent/token footprint (renders)")
    p.add_argument("--agents", type=int, default=None)
    p.add_argument("--tokens", default=None)
    p.set_defaults(fn=_cmd_set_footprint)

    p = sub.add_parser("list", help="list this project's engagements (registry scan)")
    p.set_defaults(fn=_cmd_list)

    p = sub.add_parser(
        "migrate", help="move a legacy flat pack into its own artifacts/<slug>/ workspace"
    )
    p.set_defaults(fn=_cmd_migrate)

    args = parser.parse_args(argv)
    if args.dir is None and args.fn not in (_cmd_init, _cmd_list, _cmd_migrate):
        args.dir = resolve_pack_dir(args)
    try:
        return args.fn(args)
    except FileNotFoundError:
        print(f"no {STATE_FILENAME} in {args.dir} - run init first", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"{STATE_FILENAME} is not valid JSON: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
