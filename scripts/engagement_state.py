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
  show                         # print the state as-is; always exits 0 once found
  render                       # regenerate START-HERE.md + .html from the state
  set-status {in_progress,blocked,closing,closed} [--verdict TEXT]
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
  set-active SLUG              # ACTIVE-engagement marker (R1); cleared by clear-active/close
  clear-active
  record-consent-outcome {asked,declined} [--note TEXT]   # NON-granting outcomes only (R3)
  set-runtime [--mode {repo,plugin}] [--plugin-root P] [--interpreter CMD]   # probe cache (R7)

Schema v2 (2026-07-26): `log` holds completion notes and events; `outstanding` holds ONLY
open work (the live run parked "COMPLETE" notes in outstanding, hiding convergence).
`ratifications` make approval state structured - artifacts asserting a ratification the
state still records as pending is a `RATIFIED-CLAIM-PENDING` gate finding. v1 files remain
valid and upgrade in place on their first mutation.

Close ordering: `set-team` and `finalise-artifacts` must precede `set-status closed` -
closed-state validation requires a non-empty team and no interim artifact rows (born of the
2026-07-26 live run, which closed with both left at defaults for want of a mutator).

The close window (2026-07-29 register R5/G4/R6):
  * `set-status closing` marks the close as UNDERWAY on disk - close artifacts (delivery
    report, summary email) are legitimate during it, so a crash/compaction mid-close can
    never lead a resumed session to read them as premature (or worse, delete them);
  * `set-status closed` runs the full mechanical DoD checker (check_artifacts) over the
    pack and REFUSES on findings, rolling the state back - a resumed session can no longer
    mint a valid-looking ✅ pack that passed no gate;
  * the pre-close `outstanding` list is snapshotted into the log before it is wiped, so a
    mistaken close is reversible from disk.

All commands accept --dir ARTIFACTS_DIR (default: $CLAUDE_PROJECT_DIR/artifacts, else
./artifacts). --dir/--slug may go before OR after the subcommand (except on init, which
takes --dir before it only, and --slug as the new pack's own name). Every mutator ends
with validate + render.
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

_STATUSES = ("in_progress", "blocked", "closing", "closed")
_PHASES = ("open", "classify", "plan", "delivery", "close")
_PROFILES = ("standard", "light")
_ARTIFACT_STATUSES = ("interim", "final")

# The one hard exclusion (ADR-002 / ADR-006): consent must never gain a second home here.
_FORBIDDEN_KEY_FRAGMENTS = ("consent", "exec")

# The single sanctioned exception (2026-07-29 register R3): a root-level record of the
# NON-granting consent outcomes only, so a "No" is distinguishable from never-asked after
# compaction (re-asking is the path back to an accidental yes). The value is hard-limited
# to "asked"/"declined" by validation - anything grant-shaped fails - and the grant itself
# remains ONLY the human-created `.claude/.exec-consent` marker (ADR-002). Every other
# consent/exec-shaped key, at any depth, stays forbidden.
_CONSENT_OUTCOME_KEY = "execution_consent_outcome"
_CONSENT_OUTCOMES = ("asked", "declined")
_CONSENT_OUTCOME_FIELDS = {"outcome", "date", "note"}

_STATUS_RENDER = {
    "in_progress": "⏳ IN PROGRESS",
    "blocked": "⛔ BLOCKED - awaiting input",
    # No "in progress"/"closed" wording here: the words-only fallback parser must never
    # misread the closing line, and 🔒 is its single status emoji.
    "closing": "🔒 CLOSING - finishing close artifacts",
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
    base = Path(root) if root else Path.cwd()
    # A session that has cd'd INSIDE artifacts/ (e.g. into an existing workspace) must
    # not nest a new pack there - a live init from artifacts/<old>/ created
    # artifacts/<old>/artifacts/<new>/ (2026-07-30). Resolve to the OUTERMOST
    # `artifacts` directory on the path instead of blindly appending another one.
    resolved = base.resolve()
    tops = [p for p in (resolved, *resolved.parents) if p.name == "artifacts"]
    if tops:
        return tops[-1]  # outermost = the project's real artifacts root
    return base / "artifacts"


def _safe_slug_join(base: Path, slug: str) -> Path | None:
    """`base / slug` with a path-traversal check - returns None (never raises) when the
    join would escape `base`, so every call site can print its own error and exit 2.

    Found by a framework-wide audit (2026-08-07), verified before fixing: every workspace
    command builds its target directory as `<artifacts-root> / <slug>` with no validation
    at all, and `slug` is whatever a --slug flag (or a state file's own recorded slug, for
    `migrate`) happens to contain. Two real escapes, not just an unlikely edge case:
      1. Path.__truediv__ DISCARDS the left side entirely when the right is absolute -
         `Path("artifacts") / "/etc/passwd"` is literally `Path("/etc/passwd")`, not an
         error and not a relative join. A slug of `/etc/passwd` (or any absolute path)
         targets that path directly.
      2. A `..`-bearing slug resolves outside `base` on `.resolve()`, same as any other
         directory-traversal - `Path("artifacts") / "../../.claude/hooks"` resolves two
         levels above the intended root.
    A character-blocklist would chase these one symbol at a time and miss the next one;
    checking the RESOLVED result's actual containment inside `base` closes both by
    construction, regardless of what characters got there. `base` itself is resolved too,
    so this holds even when `base` itself hasn't been resolved by the caller yet."""
    if not slug:
        return None
    candidate = (base / slug).resolve()
    try:
        candidate.relative_to(base.resolve())
    except ValueError:
        return None
    return candidate


# ------------------------------------------------------------------ workspaces (0.31)
# Several engagements can coexist in one project at independent states: each lives in its
# own workspace `artifacts/<slug>/` with its own state + rendered index. The root carries a
# DERIVED registry (engagements.json + ENGAGEMENTS.md) regenerated from a scan on every
# mutation - it can never become a second source of truth. A legacy FLAT pack (state
# directly in artifacts/) keeps working everywhere; `migrate` moves it into a workspace.

REGISTRY_JSON = "engagements.json"
REGISTRY_MD = "ENGAGEMENTS.md"

# The ACTIVE-engagement marker (2026-07-29 register R1): ADR-008 says one engagement is
# ACTIVE per session, but the slug lived only in conversation - a resumed session with two
# open packs that guessed wrong silently mutated the wrong workspace. The marker lives at
# the artifacts root, is written by the workspaced init (newest engagement becomes ACTIVE)
# or `set-active`, resolves an ambiguous pack target, and is cleared at close.
ACTIVE_MARKER = ".active-engagement.json"


def read_active(root: Path) -> str | None:
    """The ACTIVE slug recorded on disk, or None. Fail-open: unreadable marker = no marker."""
    try:
        slug = json.loads((root / ACTIVE_MARKER).read_text(encoding="utf-8")).get("slug")
    except Exception:
        return None
    return slug if isinstance(slug, str) and slug else None


def write_active(root: Path, slug: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / ACTIVE_MARKER).write_text(
        json.dumps({"slug": slug, "set": _dt.date.today().isoformat()}, indent=2) + "\n",
        encoding="utf-8",
    )


def clear_active(root: Path, slug: str | None = None) -> None:
    """Remove the marker; with a slug given, only if it is the one recorded."""
    if slug is not None and read_active(root) != slug:
        return
    (root / ACTIVE_MARKER).unlink(missing_ok=True)


def workspace_states(root: Path) -> list[Path]:
    """Workspace state files directly under the artifacts root (one level, sorted)."""
    if not root.is_dir():
        return []
    return sorted(
        p / STATE_FILENAME for p in root.iterdir() if p.is_dir() and (p / STATE_FILENAME).is_file()
    )


# ------------------------------------------------------------------ archive (0.33.2)
# A directory containing a `.archive` marker file is OUT OF PLAY: every scanner (DoD
# checker, stop gate, registry, statusline, resume menu) skips it, so old engagements
# stop costing startup time. Archive-in-place by design - nothing moves, so relative
# links inside old reports keep working; `artifacts/archive/` exists purely as an
# optional tidy destination (it ships with its own marker). One safeguard lives in the
# checker: a marker on a pack whose state is still OPEN is ARCHIVED-OPEN, not a silent
# skip - archiving is not a way to dodge the close gate.

ARCHIVE_MARKER = ".archive"


def is_archived(pack: Path) -> bool:
    """True when the directory carries the `.archive` marker."""
    try:
        return (pack / ARCHIVE_MARKER).is_file()
    except OSError:
        return False


def archived_slugs(root: Path) -> list[str]:
    """Names of one-level subdirectories carrying the marker (packs or plain dirs)."""
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir() and is_archived(p))


# Files the closed-pack fingerprint ignores: the state file (the fingerprint is stored
# inside it), the generated index renders (re-rendered by the same mutation that stores
# the fingerprint) and the archive marker itself. Everything else - the deliverables -
# is covered by name, size and mtime.
_FINGERPRINT_EXCLUDE = {STATE_FILENAME, "START-HERE.md", "START-HERE.html", ARCHIVE_MARKER}


def compute_fingerprint(pack: Path) -> str:
    """A cheap stat-only fingerprint of the pack's deliverable files.

    Stored in the state at a successful close; while it still matches, scanners skip
    the full content re-scan (the verification the pack passed at close still stands).
    Any edit to a deliverable changes size or mtime and forces a real re-scan."""
    entries = []
    for p in sorted(pack.rglob("*")):
        if not p.is_file() or p.name in _FINGERPRINT_EXCLUDE:
            continue
        try:
            st = p.stat()
        except OSError:
            continue
        entries.append(f"{p.relative_to(pack)}|{st.st_size}|{int(st.st_mtime)}")
    return hashlib.sha256("\n".join(entries).encode("utf-8")).hexdigest()


def scan_engagements(root: Path, known: tuple[Path, dict] | None = None) -> list[dict]:
    """Registry rows derived from the packs on disk (flat pack first, then workspaces).
    Archived (`.archive`-marked) packs are excluded - the registry names them in its own
    collapsed line via archived_slugs().

    `known`, if given, is `(pack_dir, state)` for a pack whose state was JUST validated
    and written to disk by the caller (_write_state) - reusing it in-memory avoids
    reading the very file we just wrote back off disk. Every OTHER pack is still read
    fresh, unconditionally: this is a one-row substitution, not a cache, so the registry
    keeps its "always regenerated, never drifts" guarantee (2026-08-03 perf audit)."""
    rows: list[dict] = []
    candidates: list[tuple[str, Path]] = []
    if state_path(root).is_file():
        candidates.append(("(flat)", root))
    candidates.extend(
        (sp.parent.name, sp.parent) for sp in workspace_states(root) if not is_archived(sp.parent)
    )
    known_pack, known_state = known if known is not None else (None, None)
    for slug, pack in candidates:
        try:
            state = known_state if known is not None and pack == known_pack else load_state(pack)
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


_RENDER_HTML_MODULE_CACHE = None


def _load_render_html_module():
    """Import scripts.render_html in BOTH run modes (package import when available,
    __file__-relative load under direct-path plugin invocation). None = module
    unavailable; callers then degrade to .md-only rather than raising ImportError
    ("No module named 'scripts.render_html'" - live corp report 2026-07-31, where
    plugin-mode path invocation has no scripts.* package on sys.path).

    2026-08-03 perf audit: render_files() and render_registry() each call this
    independently within ONE _write_state() call - in plugin mode (fast branch always
    fails), that used to re-parse and re-exec render_html.py twice per mutation.
    Memoized in a module-level variable, same reasoning as check_artifacts.py's own
    loaders."""
    global _RENDER_HTML_MODULE_CACHE
    try:
        from scripts import render_html  # normal `-m` / package mode

        return render_html
    except Exception:  # nosec B110 - probe only; fall through to the file-relative loader
        pass
    if _RENDER_HTML_MODULE_CACHE is not None:
        return _RENDER_HTML_MODULE_CACHE
    try:
        import importlib.util

        path = Path(__file__).with_name("render_html.py")
        spec = importlib.util.spec_from_file_location("render_html", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _RENDER_HTML_MODULE_CACHE = module
        return module
    except Exception:
        return None


def render_registry(root: Path, known: tuple[Path, dict] | None = None) -> list[Path]:
    """(Re)generate the derived root registry. Removes it when no packs remain.

    `known` is threaded straight through to scan_engagements() - see its docstring."""
    rows = scan_engagements(root, known=known)
    archived = archived_slugs(root)
    json_path = root / REGISTRY_JSON
    md_path = root / REGISTRY_MD
    if not rows and not archived:
        for p in (json_path, md_path, md_path.with_suffix(".html")):
            p.unlink(missing_ok=True)
        return []
    root.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps({"derived": True, "engagements": rows}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    emoji = {"in_progress": "⏳", "blocked": "⛔", "closing": "🔒", "closed": "✅", "invalid": "❗"}
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
    if archived:
        lines += [
            "",
            f"Archived: {len(archived)} (`.archive` marker - excluded from scans): "
            + ", ".join(f"`{s}/`" for s in archived),
        ]
    lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    written = [json_path, md_path]
    render_html = _load_render_html_module()
    if render_html is not None:
        try:
            md_text = md_path.read_text(encoding="utf-8")
            html_path = md_path.with_suffix(".html")
            html_path.write_text(
                render_html.render(
                    md_text,
                    render_html._title_from(md_text, md_path.stem),
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
        safe = _safe_slug_join(root, slug)
        if safe is None:
            print(f"--slug {slug!r} escapes the artifacts root - refusing", file=sys.stderr)
            sys.exit(2)
        return safe
    candidates: list[Path] = []
    if state_path(root).is_file():
        candidates.append(root)
    candidates.extend(sp.parent for sp in workspace_states(root))
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        return root  # nothing yet - flat semantics (init resolves its own target)
    # R1: the on-disk ACTIVE marker resolves the ambiguity a resumed session used to guess.
    active = read_active(root)
    if active and (root / active) in candidates:
        print(f"note: targeting ACTIVE engagement '{active}' ({ACTIVE_MARKER})", file=sys.stderr)
        return root / active
    names = ", ".join(c.name if c != root else "(flat)" for c in candidates)
    print(
        f"multiple engagements in {root} ({names}) - say which with --slug <name> (or "
        "--dir), or record the session's engagement with `set-active <slug>`",
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


def content_hash(md_text: str) -> str:
    """Short hash of a rendered index's CONTENT (marker lines excluded, newlines
    normalised). 2026-07-29 register P7: the state-hash alone only caught JSON-to-index
    divergence - a hand-edit of the index copied the marker verbatim and went undetected.
    The render embeds this too; a mismatch is INDEX-HAND-EDITED."""
    lines = [ln for ln in md_text.splitlines() if not ln.strip().startswith(_HASH_MARKER_PREFIX)]
    while lines and lines[-1] == "":
        lines.pop()  # normalise trailing blanks - splitlines drops them asymmetrically
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()[:16]


def load_state(artifacts_dir: Path) -> dict:
    return json.loads(state_path(artifacts_dir).read_text(encoding="utf-8"))


def _forbidden_keys(obj, trail="") -> list[str]:
    found: list[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            where = f"{trail}.{key}" if trail else str(key)
            if where == _CONSENT_OUTCOME_KEY:
                # The one sanctioned, root-level exception (R3) - its VALUE is
                # hard-constrained to non-granting outcomes by validate_state below.
                found.extend(_forbidden_keys(value, where))
                continue
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

    # R3: the sanctioned consent-outcome record may hold NON-granting outcomes only.
    outcome_rec = state.get(_CONSENT_OUTCOME_KEY)
    if outcome_rec is not None:
        valid_shape = (
            isinstance(outcome_rec, dict)
            and outcome_rec.get("outcome") in _CONSENT_OUTCOMES
            and set(outcome_rec) <= _CONSENT_OUTCOME_FIELDS
            and all(isinstance(v, str) for v in outcome_rec.values())
        )
        if not valid_shape:
            problems.append(
                f"{_CONSENT_OUTCOME_KEY} may record only "
                f"{{'outcome': 'asked'|'declined', 'date', 'note'}} - a GRANT is never "
                "representable here; the only execution-consent grant is the human-created "
                ".claude/.exec-consent marker (ADR-002)"
            )

    # R7: the cached run-mode probe.
    runtime = state.get("runtime")
    if runtime is not None:
        valid_runtime = (
            isinstance(runtime, dict)
            and set(runtime) <= {"mode", "plugin_root", "interpreter"}
            and runtime.get("mode") in (None, "repo", "plugin")
            and all(v is None or isinstance(v, str) for v in runtime.values())
        )
        if not valid_runtime:
            problems.append(
                "'runtime' must be {mode: repo|plugin, plugin_root, interpreter} "
                "(the persisted step-0 probe result)"
            )

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
    elif status == "in_progress":
        # CSS-only pulse (render_html.py's own trusted _CSS, never bleach-sanitised model
        # content) - an `id`, not `class`: bleach's attribute allow-list permits `id` on any
        # tag but strips `class` from `span`, and START-HERE has exactly one status per page.
        status_line = f'<span id="status-in-progress">{status_line}</span>'

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
    outcome_rec = state.get(_CONSENT_OUTCOME_KEY) or {}
    if outcome_rec.get("outcome"):
        date_bit = f" {outcome_rec['date']}" if outcome_rec.get("date") else ""
        lines.append(
            f"| **Exec consent** | {outcome_rec['outcome']}{date_bit} - a grant is only "
            "ever the human-created marker (ADR-002) |"
        )
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
    elif status == "closing":
        lines.append(
            "*(Close in progress - the close artifacts are being finalised; the status "
            "flips to ✅ once the DoD gate passes.)*"
        )
        lines.append("")
        lines.append("1. The artifacts below, newest last.")
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
    lines.append(
        f"{_HASH_MARKER_PREFIX} {state_hash(state)} "
        f"content-hash: {content_hash(chr(10).join(lines))} {_HASH_MARKER_SUFFIX}"
    )
    lines.append("")
    return "\n".join(lines)


def _marker_tokens(index_text: str) -> list[str]:
    for line in index_text.splitlines():
        stripped = line.strip()
        if stripped.startswith(_HASH_MARKER_PREFIX):
            inner = stripped[len(_HASH_MARKER_PREFIX) :].removesuffix(_HASH_MARKER_SUFFIX)
            return inner.split()
    return []


def embedded_hash(index_text: str) -> str | None:
    """The state-hash recorded in a rendered START-HERE, or None if absent."""
    tokens = _marker_tokens(index_text)
    return tokens[0] if tokens else None


def embedded_content_hash(index_text: str) -> str | None:
    """The content-hash recorded in the render marker (P7), or None on a pre-P7 render -
    legacy renders without it are tolerated, never flagged."""
    tokens = _marker_tokens(index_text)
    for i, tok in enumerate(tokens):
        if tok == "content-hash:" and i + 1 < len(tokens):
            return tokens[i + 1]
    return None


def render_files(artifacts_dir: Path, known_state: dict | None = None) -> list[Path]:
    """Write START-HERE.md (+ .html when the renderer's deps exist) from the state file.

    `known_state`, if given, is used instead of re-reading `artifacts_dir`'s state off
    disk - for _write_state(), which already holds the just-validated, just-written state
    in memory (2026-08-03 perf audit). The standalone `render` command has no such state
    in hand and always reads fresh, exactly as before."""
    state = known_state if known_state is not None else load_state(artifacts_dir)
    problems = validate_state(state)
    if problems:
        raise ValueError("state invalid: " + "; ".join(problems))
    md_text = render_markdown(state)
    md_path = index_path(artifacts_dir)
    md_path.write_text(md_text, encoding="utf-8")
    written = [md_path]
    render_html = _load_render_html_module()
    if render_html is None:
        print(
            "note: .html sibling not rendered (scripts.render_html unavailable)",
            file=sys.stderr,
        )
        return written
    try:
        html_path = md_path.with_suffix(".html")
        html_path.write_text(
            render_html.render(
                md_text,
                render_html._title_from(md_text, md_path.stem),
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
    for path in render_files(artifacts_dir, known_state=state):
        print(f"wrote {path}")
    registry_root = _registry_root_for(artifacts_dir)
    if registry_root is not None:
        # The pack we just wrote is reused in-memory (known=) rather than re-read off
        # disk; every other row in the registry is still scanned fresh, unconditionally
        # (2026-08-03 perf audit) - see scan_engagements()'s docstring.
        render_registry(registry_root, known=(artifacts_dir, state))


# ---------------------------------------------------------------------------- commands


def _cmd_init(args: argparse.Namespace) -> int:
    # New engagements are WORKSPACED by default (artifacts/<slug>/); an explicit --dir
    # keeps flat semantics (tests, custom layouts, pre-0.31 behaviour).
    workspaced = args.dir is None
    if args.dir is None:
        safe = _safe_slug_join(_default_artifacts_dir(), args.slug)
        if safe is None:
            print(f"--slug {args.slug!r} escapes the artifacts root - refusing", file=sys.stderr)
            return 2
        args.dir = safe
    else:
        # Explicit --dir: refuse a target nested inside another engagement pack or a
        # second artifacts level (artifacts/<old>/artifacts/<new> - the 2026-07-30
        # live defect). Legal shapes stay legal: a flat pack at the artifacts root,
        # a workspace at artifacts/<slug>, any standalone dir (tests, custom layouts).
        d = Path(args.dir).resolve()
        chain = (d, *d.parents)
        parent = d.parent
        nested_in_pack = state_path(parent).is_file() and parent.name != "artifacts"
        if sum(1 for p in chain if p.name == "artifacts") > 1 or nested_in_pack:
            print(
                f"refusing to init inside another engagement pack: {d} - workspaces "
                "live at <project>/artifacts/<slug>/ only (run init from the project "
                "root, or pass --dir <project>/artifacts/<slug>)",
                file=sys.stderr,
            )
            return 2
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
    if workspaced:
        # R1: the newest engagement becomes this session's ACTIVE one, on disk.
        write_active(args.dir.parent, args.slug)
        print(f"ACTIVE engagement: {args.slug} ({ACTIVE_MARKER})")
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


def _cmd_show(args: argparse.Namespace) -> int:
    """Print this engagement's state as-is. Unlike validate (exits 1 on any finding) or
    list (only a one-line-per-engagement summary, no detail), show always exits 0 once a
    state file was found and parsed - safe to run purely for inspection, including on a
    pack that would currently fail validation."""
    try:
        state = load_state(args.dir)
    except FileNotFoundError:
        print(f"no {STATE_FILENAME} in {args.dir}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"{STATE_FILENAME} is not valid JSON: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(state, ensure_ascii=False, indent=2))
    return 0


def _cmd_render(args: argparse.Namespace) -> int:
    written = render_files(args.dir)
    for path in written:
        print(f"wrote {path}")
    # render_files degrades .html failures to a stderr note rather than raising (every
    # OTHER mutator ends with a render and must never brick on a missing renderer) - but
    # `render` is invoked FOR the render, so silently exiting 0 on a skipped .html sibling
    # falsely signalled success (live corp report 2026-07-31) with no way to script around
    # it. The .md is always written first; the .html is appended only on success.
    if index_path(args.dir).with_suffix(".html") not in written:
        return 2
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


_CHECK_ARTIFACTS_MODULE_CACHE = None


def _load_checker():
    """scripts.check_artifacts in BOTH run modes (package import, then __file__-relative -
    the same dual-mode pattern check_artifacts uses for THIS module). None = unavailable;
    the close gate then degrades to closed-state validation only (noted on stderr).
    Memoized (2026-08-03 perf audit) - same reasoning as the other loaders in this file
    and in check_artifacts.py: the fallback branch re-parses+re-execs a ~90KB file, and
    only needs to happen once per process regardless of how many times this is called."""
    global _CHECK_ARTIFACTS_MODULE_CACHE
    try:
        from scripts import check_artifacts  # normal `-m` / package mode

        return check_artifacts
    # Probe only; fall through to the file-relative loader.
    except Exception:  # nosec B110
        pass
    if _CHECK_ARTIFACTS_MODULE_CACHE is not None:
        return _CHECK_ARTIFACTS_MODULE_CACHE
    try:
        import importlib.util

        path = Path(__file__).with_name("check_artifacts.py")
        spec = importlib.util.spec_from_file_location("check_artifacts", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _CHECK_ARTIFACTS_MODULE_CACHE = module
        return module
    except Exception:
        return None


def _cmd_set_status(args: argparse.Namespace) -> int:
    state = load_state(args.dir)
    _upgrade(state)
    before = json.loads(json.dumps(state))  # rollback snapshot (register R6)
    state["status"] = args.status
    if args.verdict:
        state["verdict"] = args.verdict
    if args.status == "closed":
        # G4 audit trail: the wiped outstanding list survives in the log, so a mistaken
        # close stays reversible from disk.
        outstanding = state.get("outstanding") or []
        if outstanding:
            entry = (
                f"{_dt.date.today().isoformat()}: close: cleared {len(outstanding)} "
                "outstanding item(s): " + "; ".join(outstanding)
            )
            log = state.setdefault("log", [])
            if entry not in log:
                log.append(entry)
        state["engagement"]["closed"] = _dt.date.today().isoformat()
        state["outstanding"] = []
        state["phase"] = "close"
    else:
        state["engagement"]["closed"] = None
    _write_state(args.dir, state)

    if args.status != "closed":
        return 0

    # R6 close gate: a close is an EVIDENCED state, not a claim - run the full mechanical
    # DoD checker over the pack and refuse (rolling back) on findings. The sanctioned
    # sequence is: `set-status closing` -> write/finish the close artifacts ->
    # `python -m scripts.check_artifacts --fix` -> `set-status closed`.
    ca = _load_checker()
    if ca is None:
        print(
            "note: check_artifacts unavailable - close gate skipped (closed-state validation only)",
            file=sys.stderr,
        )
        clear_active(args.dir.parent, args.dir.name)
        return 0
    try:
        gate_findings = ca.check(args.dir)
    except Exception as exc:  # a broken checker must not strand the state half-written
        print(
            f"note: close gate errored ({exc}) - close kept, run the checker by hand",
            file=sys.stderr,
        )
        clear_active(args.dir.parent, args.dir.name)
        return 0
    if not gate_findings:
        # 0.33.2 fast path: the pack just passed the full gate - fingerprint it so later
        # scans can skip an unchanged closed pack instead of re-reading every file.
        state["scan_fingerprint"] = compute_fingerprint(args.dir)
        _write_state(args.dir, state)
        # R1: a closed engagement is no longer this session's ACTIVE one.
        clear_active(args.dir.parent, args.dir.name)
        return 0
    for finding in gate_findings:
        print(f"CLOSE-REFUSED: {finding}", file=sys.stderr)
    _write_state(args.dir, before)  # roll back to the pre-close state
    print(
        f"CLOSE-REFUSED: {len(gate_findings)} DoD finding(s) - the close was rolled back "
        f"to '{before.get('status')}'. Fix the findings (or run `python -m "
        "scripts.check_artifacts --fix`) and re-run `set-status closed`; use "
        "`set-status closing` to mark the close as underway meanwhile.",
        file=sys.stderr,
    )
    return 1


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
        # R8: after a crash, "remove the row or restore the artifact" must be decidable
        # from disk - a row recorded before its file existed says so explicitly.
        if not (args.dir / args.path).exists():
            entry["added_before_file_existed"] = True
            print(
                f"warning: {args.path} does not exist in {args.dir} yet - row recorded "
                "with added_before_file_existed (write the file, then re-run add-artifact "
                "to clear the flag)",
                file=sys.stderr,
            )
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


def _resolve_slug_arg(args: argparse.Namespace) -> str | None:
    """set-active/archive/unarchive take their slug positionally, unlike every other
    resolvable subcommand's `--slug TARGET_SLUG` - a live report (2026-08-03) found
    `archive --slug X` exits 2 with no hint that the flag isn't accepted there, because
    the positional (`args.slug`) and the mirrored flag (`args.target_slug`, from `common`)
    are different attributes and only the positional was ever read. Accept either; the
    positional wins if both are somehow given."""
    return getattr(args, "slug", None) or getattr(args, "target_slug", None)


def _cmd_set_active(args: argparse.Namespace) -> int:
    root = args.dir or _default_artifacts_dir()
    slug = _resolve_slug_arg(args)
    if not slug:
        print("set-active: give a <slug> or --slug", file=sys.stderr)
        return 2
    target = _safe_slug_join(root, slug)
    if target is None:
        print(f"--slug {slug!r} escapes the artifacts root - refusing", file=sys.stderr)
        return 2
    if not ((target / STATE_FILENAME).is_file() or (target / INDEX_FILENAME).is_file()):
        print(f"no engagement workspace at {target} - nothing to mark ACTIVE", file=sys.stderr)
        return 2
    write_active(root, slug)
    print(f"ACTIVE engagement: {slug} ({ACTIVE_MARKER})")
    return 0


def _cmd_clear_active(args: argparse.Namespace) -> int:
    clear_active(args.dir or _default_artifacts_dir())
    print("ACTIVE marker cleared")
    return 0


def _cmd_archive(args: argparse.Namespace) -> int:
    """Archive-in-place: write the `.archive` marker so every scanner skips the pack.
    Nothing moves (relative links inside old reports keep working). Closed packs only -
    archiving is not a way to dodge the close gate; --force records the exception."""
    root = args.dir or _default_artifacts_dir()
    targets: list[Path]
    if args.all_closed:
        targets = [sp.parent for sp in workspace_states(root) if not is_archived(sp.parent)]
    else:
        slug = _resolve_slug_arg(args)
        if not slug:
            print("archive: give a <slug> (or --slug), or --all-closed", file=sys.stderr)
            return 2
        safe = _safe_slug_join(root, slug)
        if safe is None:
            print(f"--slug {slug!r} escapes the artifacts root - refusing", file=sys.stderr)
            return 2
        targets = [safe]
    archived_now = 0
    for pack in targets:
        if not state_path(pack).is_file():
            if args.all_closed:
                continue
            if not args.force:
                print(
                    f"no engagement pack at {pack} (no {STATE_FILENAME}) - if this is a "
                    "legacy/non-workspace directory the DoD scan still walks, --force "
                    "excludes it from scope the same way (writes .archive, no state "
                    "required)",
                    file=sys.stderr,
                )
                return 2
            # No state to gate on - a legacy/pre-workspace directory, or any other
            # artifacts/ subdirectory the DoD scan still walks. Here --force means
            # "exclude it from scope", not "archive an open engagement" (live corp
            # report 2026-07-31: `archive <name> --force` on such a directory exited 2
            # with no way to mark it excluded at all - a manual empty .archive file was
            # the only workaround).
            if not pack.is_dir():
                print(f"no directory at {pack}", file=sys.stderr)
                return 2
            (pack / ARCHIVE_MARKER).write_text(
                f"archived {_dt.date.today().isoformat()} via engagement_state archive "
                "(--force; no engagement-state.json found - excluded from DoD scope only)\n",
                encoding="utf-8",
            )
            clear_active(root, pack.name)
            archived_now += 1
            print(
                f"archived: {pack.name}/ ({ARCHIVE_MARKER} written - excluded from "
                "scans; no engagement state found)"
            )
            continue
        try:
            state = load_state(pack)
        except Exception as exc:
            print(f"skipping {pack.name}: unreadable state ({exc})", file=sys.stderr)
            continue
        status = state.get("status")
        if status != "closed":
            if args.all_closed:
                continue  # --all-closed archives only the closed ones, silently
            if not args.force:
                print(
                    f"refusing to archive {pack.name}: status is '{status}', not closed - "
                    "close the engagement first (or --force to archive abandoned work; "
                    "the exception is logged in the pack)",
                    file=sys.stderr,
                )
                return 2
            state.setdefault("log", []).append(
                f"{_dt.date.today().isoformat()}: archived while '{status}' (--force) - "
                "close gate never passed"
            )
            _write_state(pack, state)
        (pack / ARCHIVE_MARKER).write_text(
            f"archived {_dt.date.today().isoformat()} via engagement_state archive "
            f"(status: {status})\n",
            encoding="utf-8",
        )
        clear_active(root, pack.name)
        archived_now += 1
        print(f"archived: {pack.name}/ ({ARCHIVE_MARKER} written - excluded from scans)")
    if args.all_closed and archived_now == 0:
        print("nothing to archive: no closed, unarchived packs")
    render_registry(root)
    return 0


def _cmd_unarchive(args: argparse.Namespace) -> int:
    root = args.dir or _default_artifacts_dir()
    slug = _resolve_slug_arg(args)
    if not slug:
        print("unarchive: give a <slug> or --slug", file=sys.stderr)
        return 2
    pack = _safe_slug_join(root, slug)
    if pack is None:
        print(f"--slug {slug!r} escapes the artifacts root - refusing", file=sys.stderr)
        return 2
    marker = pack / ARCHIVE_MARKER
    if not marker.is_file():
        print(f"{pack.name} is not archived (no {ARCHIVE_MARKER})", file=sys.stderr)
        return 2
    marker.unlink()
    render_registry(root)
    print(f"unarchived: {pack.name}/ (back in scan scope)")
    return 0


def _cmd_record_consent_outcome(args: argparse.Namespace) -> int:
    """R3: record a NON-granting execution-consent outcome ('asked'/'declined') so a "No"
    survives compaction and is never re-asked back into an accidental yes. The grant is not
    representable here - it remains ONLY the human-created marker (ADR-002)."""

    def fn(state: dict) -> None:
        rec = {"outcome": args.outcome, "date": _dt.date.today().isoformat()}
        if args.note:
            rec["note"] = args.note
        state[_CONSENT_OUTCOME_KEY] = rec

    return _mutate(args, fn)


def _cmd_set_runtime(args: argparse.Namespace) -> int:
    """R7: persist the step-0 run-mode probe (mode / plugin root / interpreter) so a
    resumed or compacted session re-reads it from the state instead of remembering."""

    def fn(state: dict) -> None:
        runtime = state.setdefault("runtime", {})
        if args.mode is not None:
            runtime["mode"] = args.mode
        if args.plugin_root is not None:
            runtime["plugin_root"] = args.plugin_root
        if args.interpreter is not None:
            runtime["interpreter"] = args.interpreter

    return _mutate(args, fn)


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


_OPEN_STATUSES = ("in_progress", "blocked", "closing")


def resume_menu(root: Path, max_shown: int = 3) -> dict:
    """The engage skill's step-0b resume-vs-new menu, COMPUTED rather than left for the
    model to re-derive from `list`'s text output (audit finding #1, 2026-07-30 - two
    DATED-TODAY live defects cited as evidence the prose version already fails: a menu
    offering only one open engagement when several existed, and a session folding a new
    engagement's artifacts into the wrong open pack).

    Returns {"open": [rows...], "shown": [...], "more": N, "archived": N, "default": slug
    or None}. `open` sorted by `opened` date descending (None sorts last - an unreadable
    open date is not "most recent"); `shown` is the top `max_shown`; `default` is the
    ACTIVE marker's slug when it is itself an open engagement, else the most recent open
    one, else None (nothing to resume - "start new" is the only real option)."""
    rows = [r for r in scan_engagements(root) if r.get("status") in _OPEN_STATUSES]
    rows.sort(key=lambda r: r.get("opened") or "", reverse=True)
    active = read_active(root)
    default = active if any((r.get("dir") or r.get("slug")) == active for r in rows) else None
    if default is None and rows:
        default = rows[0].get("dir") or rows[0].get("slug")
    shown = rows[:max_shown]
    return {
        "open": rows,
        "shown": shown,
        "more": max(0, len(rows) - len(shown)),
        "archived": len(archived_slugs(root)),
        "default": default,
    }


def _cmd_list(args: argparse.Namespace) -> int:
    root = args.dir or _default_artifacts_dir()
    if getattr(args, "menu", False):
        menu = resume_menu(root)
        print(json.dumps(menu, ensure_ascii=False, indent=2))
        return 0
    rows = scan_engagements(root)
    if not rows:
        print(f"no engagements in {root}")
        return 0
    active = read_active(root)
    for r in rows:
        where = r.get("dir") or r.get("slug")
        mark = " *ACTIVE*" if active and where == active else ""
        print(
            f"{where:24} {r.get('status'):12} "
            f"{r.get('profile') or '':9} {r.get('title') or ''}{mark}"
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
    target = _safe_slug_join(root, slug)
    if target is None:
        print(
            f"the pack's own recorded slug {slug!r} escapes the artifacts root - refusing "
            "to migrate; fix the slug in the state file first",
            file=sys.stderr,
        )
        return 2
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

    # argparse only looks at the top-level parser's own optionals until it hits the
    # subcommand positional - after that, remaining args go to the subparser, so a bare
    # "--dir"/"--slug" typed AFTER the subcommand name errors "unrecognized arguments"
    # (live corp report 2026-07-31: `log-note --slug X "..."` exited 2; `--slug X log-note
    # "..."` worked). Mirroring --dir/--slug onto every resolvable subcommand accepts both
    # orders; SUPPRESS defaults keep an omitted flag from overwriting a value already set
    # at the top level (argparse merges the subparser's namespace over the parent's, and an
    # ordinary default=None would clobber a correctly-parsed top-level value with None).
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--dir", type=Path, default=argparse.SUPPRESS)
    common.add_argument("--slug", dest="target_slug", default=argparse.SUPPRESS)

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

    p = sub.add_parser(
        "validate", parents=[common], help="check the state file; exit 1 on findings"
    )
    p.set_defaults(fn=_cmd_validate)

    p = sub.add_parser(
        "show",
        parents=[common],
        help="print the state as-is (always exits 0 once found - safe for inspection)",
    )
    p.set_defaults(fn=_cmd_show)

    p = sub.add_parser(
        "render", parents=[common], help="regenerate START-HERE.md/.html from the state"
    )
    p.set_defaults(fn=_cmd_render)

    p = sub.add_parser("set-status", parents=[common], help="change lifecycle status (renders)")
    p.add_argument("status", choices=_STATUSES)
    p.add_argument("--verdict", default=None)
    p.set_defaults(fn=_cmd_set_status)

    p = sub.add_parser("set-phase", parents=[common], help="change lifecycle phase (renders)")
    p.add_argument("phase", choices=_PHASES)
    p.set_defaults(fn=_cmd_set_phase)

    p = sub.add_parser(
        "set-profile",
        parents=[common],
        help="change ceremony profile (e.g. light -> standard upgrade)",
    )
    p.add_argument("profile", choices=_PROFILES)
    p.set_defaults(fn=_cmd_set_profile)

    p = sub.add_parser(
        "add-artifact", parents=[common], help="add/update an artifact row (renders)"
    )
    p.add_argument("path")
    p.add_argument("--title", required=True)
    p.add_argument("--final", action="store_true", help="mark final (default interim)")
    p.set_defaults(fn=_cmd_add_artifact)

    p = sub.add_parser(
        "add-outstanding", parents=[common], help="append an outstanding item (renders)"
    )
    p.add_argument("text")
    p.set_defaults(fn=_cmd_add_outstanding)

    p = sub.add_parser(
        "resolve-outstanding",
        parents=[common],
        help="remove outstanding items matching a substring",
    )
    p.add_argument("substring")
    p.set_defaults(fn=_cmd_resolve_outstanding)

    p = sub.add_parser(
        "set-decision", parents=[common], help="record a decision of record (renders)"
    )
    p.add_argument("key")
    p.add_argument("value")
    p.set_defaults(fn=_cmd_set_decision)

    p = sub.add_parser(
        "log-note",
        parents=[common],
        help="append a dated event/completion note to the log (renders)",
    )
    p.add_argument("text")
    p.set_defaults(fn=_cmd_log_note)

    p = sub.add_parser(
        "add-ratification",
        parents=[common],
        help="record a decision awaiting human ratification (renders)",
    )
    p.add_argument("text")
    p.set_defaults(fn=_cmd_add_ratification)

    p = sub.add_parser(
        "ratify",
        parents=[common],
        help="mark pending ratification(s) matching a substring as ratified",
    )
    p.add_argument("substring")
    p.add_argument("--by", default=None, help="who ratified (e.g. 'ops lead')")
    p.set_defaults(fn=_cmd_ratify)

    p = sub.add_parser("set-team", parents=[common], help="record the delivering team (renders)")
    p.add_argument("members", nargs="+", help='e.g. "Amara (BA)" "Linh (QA)"')
    p.set_defaults(fn=_cmd_set_team)

    p = sub.add_parser(
        "set-active",
        parents=[common],
        help="record the session's ACTIVE engagement on disk (R1 marker)",
    )
    p.add_argument("slug", nargs="?", help="or use --slug, like every other subcommand")
    p.set_defaults(fn=_cmd_set_active)

    p = sub.add_parser("clear-active", help="remove the ACTIVE-engagement marker")
    p.set_defaults(fn=_cmd_clear_active)

    p = sub.add_parser(
        "archive",
        parents=[common],
        help="mark a closed pack .archive - excluded from every scan (in-place, no move)",
    )
    p.add_argument(
        "slug", nargs="?", help="workspace directory name under artifacts/, or use --slug"
    )
    p.add_argument(
        "--all-closed", action="store_true", help="archive every closed, unarchived pack"
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="archive an OPEN pack (logged in the pack first), or a legacy/non-workspace "
        "directory with no engagement-state.json (excluded from scope only, nothing logged)",
    )
    p.set_defaults(fn=_cmd_archive)

    p = sub.add_parser(
        "unarchive", parents=[common], help="remove the .archive marker (back in scan scope)"
    )
    p.add_argument("slug", nargs="?", help="or use --slug, like every other subcommand")
    p.set_defaults(fn=_cmd_unarchive)

    p = sub.add_parser(
        "record-consent-outcome",
        parents=[common],
        help="record a NON-granting execution-consent outcome (asked/declined; renders). "
        "A grant is never representable - it is only the human-created marker (ADR-002)",
    )
    p.add_argument("outcome", choices=list(_CONSENT_OUTCOMES))
    p.add_argument("--note", default=None)
    p.set_defaults(fn=_cmd_record_consent_outcome)

    p = sub.add_parser(
        "set-runtime",
        parents=[common],
        help="persist the step-0 run-mode probe (mode/plugin-root/interpreter)",
    )
    p.add_argument("--mode", choices=("repo", "plugin"), default=None)
    p.add_argument("--plugin-root", dest="plugin_root", default=None)
    p.add_argument("--interpreter", default=None)
    p.set_defaults(fn=_cmd_set_runtime)

    p = sub.add_parser(
        "finalise-artifacts",
        parents=[common],
        help="mark every artifact row final (close step; renders)",
    )
    p.set_defaults(fn=_cmd_finalise_artifacts)

    p = sub.add_parser(
        "set-footprint", parents=[common], help="update agent/token footprint (renders)"
    )
    p.add_argument("--agents", type=int, default=None)
    p.add_argument("--tokens", default=None)
    p.set_defaults(fn=_cmd_set_footprint)

    p = sub.add_parser("list", help="list this project's engagements (registry scan)")
    p.add_argument(
        "--menu",
        action="store_true",
        help="print the computed resume-vs-new menu (JSON: open/shown/more/archived/default) "
        "instead of the plain table - the engage skill's step 0b renders this directly",
    )
    p.set_defaults(fn=_cmd_list)

    p = sub.add_parser(
        "migrate", help="move a legacy flat pack into its own artifacts/<slug>/ workspace"
    )
    p.set_defaults(fn=_cmd_migrate)

    args = parser.parse_args(argv)
    if args.dir is None and args.fn not in (
        _cmd_init,
        _cmd_list,
        _cmd_migrate,
        _cmd_set_active,
        _cmd_clear_active,
        _cmd_archive,
        _cmd_unarchive,
    ):
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
