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
  set-decisions --json '{"key": "value", ...}'  # batch form, one process for several decisions
  set-team "Name (role)" ...
  finalise-artifacts
  set-footprint [--agents N] [--tokens TEXT]
  set-budget [--daily-usd N] [--engagement-usd N]   # advisory pacing - the org spend limit
                                                    # stays the hard stop
  budget-status                # spent-vs-cap from this project's transcripts (read-only)
  log-note TEXT [--tag NAME]   # dated event/completion note - NOT the outstanding list;
                                # --tag (e.g. review-loop) marks a bracketed prefix the
                                # dashboard timeline reads to pick an icon - plain notes
                                # need no tag and render exactly as before
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

`settings_snapshot` (additive, 2026-08-08, no schema bump - same treatment as `footprint`):
`init` best-effort snapshots the 5 team-preferences flags (docx/citations/review-split/
workflow-dispatch/map-skeleton), fully resolved through the project -> machine-default ->
built-in precedence chain (`engage_probe.resolve_preferences()`), as a point-in-time record
of what was enabled when the engagement OPENED - never re-resolved later, so it stays true
to history even if the project's preferences change afterwards. `None` when the probe
module can't be loaded (foreign install edge case) or the project has no preferences file
- optional metadata, never load-bearing. Feeds the dashboard's per-engagement settings chips.

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
import contextlib
import datetime as _dt
import hashlib
import json
import os
import pathlib
import sys
import time
from pathlib import Path, PurePosixPath

STATE_FILENAME = "engagement-state.json"
INDEX_FILENAME = "START-HERE.md"
SCHEMA_VERSION = 2
_ACCEPTED_SCHEMAS = (1, 2)  # v1 files stay valid; first mutation upgrades them in place
_RATIFICATION_STATUSES = ("pending", "ratified")

_STATUSES = ("in_progress", "blocked", "closing", "closed")
_PHASES = ("open", "classify", "plan", "delivery", "close")
_PROFILES = ("standard", "light")
# How much INDEPENDENT QA this engagement bought (2026-08-20). Breadth is tierable;
# existence, independence, evidence preservation and the per-deliverable-type test
# minima are NOT - so there is deliberately no "none". "quick" always closes
# DoD: PARTIAL (check_artifacts QA-QUICK-NOT-PARTIAL), which is what stops a reduced
# level from reading as a full pass.
_QA_DEPTHS = ("quick", "deep", "audit")
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
    # 2026-08-14 Fable-model audit finding (C2): the ancestor-walk below used to run
    # UNCONDITIONALLY, even when CLAUDE_PROJECT_DIR is explicitly set - but that value
    # is already authoritative (Claude Code's own notion of "the project"), so walking
    # ABOVE it to find some OTHER directory named "artifacts" can only ever escape the
    # intended project, never correctly refine it. Concrete failure: a project at
    # /home/user/artifacts/myproject (nothing to do with an engagement pack, just an
    # unrelated directory name one level up) resolved to /home/user/artifacts as the
    # "artifacts root" - outside the project entirely, and every engagement pack wrote
    # there. The walk is only safe, and only needed, for the cwd FALLBACK case this
    # comment already documents (a session that has genuinely cd'd inside an existing
    # artifacts/<slug>/ workspace of the CURRENT project) - CLAUDE_PROJECT_DIR being
    # set means that ambiguity doesn't exist; trust it directly.
    if root:
        return Path(root) / "artifacts"
    base = Path.cwd()
    # A session that has cd'd INSIDE artifacts/ (e.g. into an existing workspace) must
    # not nest a new pack there - a live init from artifacts/<old>/ created
    # artifacts/<old>/artifacts/<new>/ (2026-07-30). Resolve to the NEAREST `artifacts`
    # ancestor on the path (the one we're actually inside), not blindly appending
    # another one - and not the outermost either (2026-08-14: the original fix took
    # the outermost match, which has the identical escape risk one level down if any
    # ancestor further up cwd also happened to be named "artifacts").
    resolved = base.resolve()
    tops = [p for p in (resolved, *resolved.parents) if p.name == "artifacts"]
    if tops:
        return tops[0]  # nearest match = the workspace we're actually inside
    return base / "artifacts"


def _project_root_for(pack_dir: Path) -> Path:
    """Best-effort working-project root for a pack dir (init's settings-snapshot lookup
    only - never load-bearing for validation or the registry): the parent of the NEAREST
    `artifacts` ancestor, mirroring _default_artifacts_dir()'s logic in reverse
    (2026-08-14: both now take the nearest match, not the outermost - the outermost had
    the same project-escape risk _default_artifacts_dir's own audit finding (C2)
    describes, if any ancestor further up pack_dir also happened to be named
    "artifacts"). Falls back to the pack's own parent for a bespoke --dir layout with no
    `artifacts` ancestor at all (e.g. some test fixtures) - team-preferences.json simply
    won't be found there, which resolve_preferences() already treats as "no project
    preferences set" (built-in defaults)."""
    resolved = pack_dir.resolve()
    tops = [p for p in (resolved, *resolved.parents) if p.name == "artifacts"]
    if tops:
        return tops[0].parent
    return resolved.parent


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
    """Records WHICH SESSION set the marker too (2026-08-17 live report): a new
    engagement's intake runs before its workspace init, so at that turn's end the
    marker still names the PREVIOUS engagement - and the DoD stop gate, keying its
    auto-fix instruction on the marker alone, sent the model off repairing the old
    pack the moment the user opened new work. With the setting session recorded, the
    gate can scope its fix instruction to a pack THIS session actually activated and
    surface everything else without actioning it."""
    root.mkdir(parents=True, exist_ok=True)
    record = {"slug": slug, "set": _dt.date.today().isoformat()}
    sid = os.environ.get("CLAUDE_CODE_SESSION_ID")
    if sid:
        record["session"] = sid
    (root / ACTIVE_MARKER).write_text(
        json.dumps(record, indent=2) + "\n",
        encoding="utf-8",
    )


def clear_active(root: Path, slug: str | None = None) -> None:
    """Remove the marker; with a slug given, only if it is the one recorded."""
    if slug is not None and read_active(root) != slug:
        return
    (root / ACTIVE_MARKER).unlink(missing_ok=True)


# Which Claude Code SESSION last acted on this project's engagement layer (2026-08-16
# live report: a pure-dormant "hello" session was pulled into another session's leftover
# open engagement, because the engagement-scoped hooks keyed on disk state alone - one
# open pack gated every later session in the project, and true dormancy became
# impossible there). Every mutating CLI call (plus set-active) stamps the calling
# session's id here, read from the CLAUDE_CODE_SESSION_ID env var Claude Code exposes to
# Bash tool commands; the persona anchor and the DoD stop gate arm only when their own
# hook payload's session_id matches the stamp, so a session that never drove the team
# stays genuinely dormant (user decision: fully silent - open engagements still surface
# at every front door: the /engage resume menu, virt-surv go, and the statusline).
# An absent env var (a human running the CLI from a plain terminal, or an older Claude
# Code) leaves any existing stamp untouched: session ids are unique, so a stale stamp
# can only ever match the session that wrote it, never a new one.
TEAM_SESSION_MARKER = ".team-session.json"


def stamp_team_session(root: Path) -> None:
    """Record the calling session as the one driving this project's engagements.
    Advisory marker - never fails a state mutation over it, and writes nothing when the
    session id isn't in the environment."""
    sid = os.environ.get("CLAUDE_CODE_SESSION_ID")
    if not sid:
        return
    try:
        root.mkdir(parents=True, exist_ok=True)
        (root / TEAM_SESSION_MARKER).write_text(
            json.dumps({"session": sid, "stamped": _dt.date.today().isoformat()}) + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass


def read_team_session(root: Path) -> str | None:
    """The stamped session id, or None. Fail toward None (= hooks stay dormant)."""
    try:
        sid = json.loads((root / TEAM_SESSION_MARKER).read_text(encoding="utf-8")).get("session")
    except Exception:
        return None
    return sid if isinstance(sid, str) and sid else None


def _stamp_root(pack_dir: Path | None) -> Path:
    """The artifacts root the session stamp belongs to - the same level the hooks read
    (project_root/artifacts). Mirrors _registry_root_for's shape rule: a flat pack IS
    the artifacts root; a workspace pack's root is its parent; no pack dir resolved yet
    (init/set-active before resolution) means the default artifacts dir."""
    if pack_dir is None:
        return _default_artifacts_dir()
    if pack_dir.name == "artifacts":
        return pack_dir
    return pack_dir.parent


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

# C5's per-pack mutation lock (see _state_lock below) - moved up here, next to the other
# filename constants, so _FINGERPRINT_EXCLUDE can reference it without a forward-reference
# NameError.
LOCK_FILENAME = ".engagement-state.lock"


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


def finished_engagements(root: Path) -> list[dict]:
    """Full rows for the packs the resume menu never shows: closed and/or archived.

    A deliberate SEPARATE function rather than a widening of scan_engagements - its
    archived-exclusion at the workspace_states call is depended on by the DoD checker,
    the stop gate, the registry and the statusline, and resume_menu's return shape is
    pinned by tests. Same row shape as scan_engagements plus `"archived": bool`
    (archived is a filesystem marker orthogonal to status - an ARCHIVED-OPEN pack
    belongs here too, because it is invisible to the resume menu either way).
    Sorted newest-finished first (closed date, falling back to opened)."""
    rows: list[dict] = []
    candidates: list[tuple[str, Path]] = []
    if state_path(root).is_file():
        candidates.append(("(flat)", root))
    candidates.extend((sp.parent.name, sp.parent) for sp in workspace_states(root))
    for slug, pack in candidates:
        archived = is_archived(pack)
        try:
            state = load_state(pack)
        except Exception:
            if archived:
                rows.append(
                    {
                        "slug": slug,
                        "dir": slug,
                        "title": "(unreadable state)",
                        "status": "invalid",
                        "profile": None,
                        "opened": None,
                        "closed": None,
                        "phase": None,
                        "outstanding": 0,
                        "outstanding_first": "",
                        "archived": True,
                    }
                )
            continue
        if not archived and state.get("status") != "closed":
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
                "phase": state.get("phase"),
                "outstanding": len(state.get("outstanding") or []),
                "outstanding_first": next(
                    (
                        str(item.get("item") if isinstance(item, dict) else item)
                        for item in (state.get("outstanding") or [])
                    ),
                    "",
                ),
                "archived": archived,
            }
        )
    rows.sort(key=lambda r: str(r.get("closed") or r.get("opened") or ""), reverse=True)
    return rows


# Files the closed-pack fingerprint's STAT-ONLY walk ignores: the state file (hashed by
# CONTENT instead - see compute_fingerprint's docstring, M3), the generated index renders
# (re-rendered by the same mutation that stores the fingerprint), the archive marker, and
# the mutation lock file itself. LOCK_FILENAME was added after a real regression (2026-08
# full-suite run): compute_fingerprint runs from INSIDE _cmd_set_status, i.e. inside the
# C5 lock - the lock file exists on disk at that exact moment, gets stat-walked into the
# stored fingerprint, and is then deleted (the lock releases) before anything else ever
# recomputes it - so a later, unlocked recomputation could never match the stored value.
# Purely operational bookkeeping, same category as the state file and index renders -
# never a deliverable, never legitimately part of what the fingerprint is verifying.
_FINGERPRINT_EXCLUDE = {
    STATE_FILENAME,
    "START-HERE.md",
    "START-HERE.html",
    ARCHIVE_MARKER,
    LOCK_FILENAME,
}


def compute_fingerprint(pack: Path) -> str:
    """A cheap stat-only fingerprint of the pack's deliverable files, PLUS the state
    file's own content.

    Stored in the state at a successful close; while it still matches, scanners skip
    the full content re-scan (the verification the pack passed at close still stands).
    Any edit to a deliverable changes size or mtime and forces a real re-scan.

    M3 (2026-08 Fable audit): the state file itself used to be excluded from the walk
    below with nothing to replace it - a hand-edit to engagement-state.json after close
    (status flipped back, verdict tampered, an outstanding item quietly removed) left
    every stat-only deliverable untouched, so the fingerprint still matched and a later
    scan silently skipped re-validating the very record that had changed. The exclusion
    from the stat-only walk stays (self-referential otherwise: the fingerprint gets
    written back INTO the file it was computed from, so its own size/mtime would never
    stabilise) but a CURATED subset of its content is now hashed in separately - the
    fields that actually determine whether the close is still valid (status, close date,
    verdict, outstanding, team, artifacts), not the whole state dict. Whole-dict hashing
    was the first attempt and broke a real, deliberate pre-existing contract
    (test_fingerprint_ignores_state_and_renders): a `log-note` after close only appends to
    `log` - harmless, no bearing on close validity - and must not force a full re-scan any
    more than a routine index re-render should. Narrowing to the validity-relevant fields
    catches every tampering case the docstring above actually names while leaving that
    contract intact."""
    entries = []
    for p in sorted(pack.rglob("*")):
        if not p.is_file() or p.name in _FINGERPRINT_EXCLUDE:
            continue
        try:
            st = p.stat()
        except OSError:
            continue
        entries.append(f"{p.relative_to(pack)}|{st.st_size}|{int(st.st_mtime)}")
    try:
        full_state = json.loads((pack / STATE_FILENAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        full_state = None
    if isinstance(full_state, dict):
        eng = full_state.get("engagement") or {}
        validity_subset = {
            "status": full_state.get("status"),
            "closed": eng.get("closed") if isinstance(eng, dict) else None,
            "verdict": full_state.get("verdict"),
            "outstanding": full_state.get("outstanding"),
            "team": full_state.get("team"),
            "artifacts": full_state.get("artifacts"),
        }
        entries.append(
            f"{STATE_FILENAME}|" + json.dumps(validity_subset, sort_keys=True, ensure_ascii=False)
        )
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
                # Additive (2026-08-19 launcher UX pass): the go menu shows "what state
                # is this in", which needs the phase and how much is still open. Both
                # already sit in the state file this function has just parsed - callers
                # that don't want them simply ignore the extra keys.
                "phase": state.get("phase"),
                "outstanding": len(state.get("outstanding") or []),
                # The first open item, for the launcher's "blocked on WHAT" line - a
                # blocked engagement whose reason you must open a file to discover is
                # the thing the go screen exists to prevent.
                "outstanding_first": next(
                    (
                        str(item.get("item") if isinstance(item, dict) else item)
                        for item in (state.get("outstanding") or [])
                    ),
                    "",
                ),
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


def render_registry(
    root: Path, known: tuple[Path, dict] | None = None, force: bool = False
) -> list[Path]:
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
    registry_md = "\n".join(lines)
    try:
        previous_registry = md_path.read_text(encoding="utf-8")
    except OSError:
        previous_registry = None
    md_path.write_text(registry_md, encoding="utf-8")
    written = [json_path, md_path]
    # Same skip as render_files, and the one that actually pays here: the registry changes
    # only when an engagement's status, title or dates change, so on the great majority of
    # mutations (a decision, a note, an artifact row) it is byte-identical and re-rendering
    # it buys nothing but the Markdown+bleach import (2026-08-25 performance review).
    registry_html = md_path.with_suffix(".html")
    if not force and previous_registry == registry_md and registry_html.is_file():
        written.append(registry_html)  # up to date, not skipped - see render_files above
        return written
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
    pack (e.g. a test tmp dir with no sibling workspaces and no registry).

    2026-08-14 Fable-model audit finding (C3): this used to compute `pack_dir.parent`
    and treat it uniformly as "the artifacts root" - correct for a WORKSPACE pack
    (pack_dir = artifacts/<slug>/, parent = artifacts/, genuinely the registry-worthy
    level) but wrong for a FLAT pack, where pack_dir IS the artifacts root itself
    (artifacts/engagement-state.json directly) and pack_dir.parent is the PROJECT
    ROOT one level too high. workspace_states(project_root) then found artifacts/
    (with its own state file) indistinguishable from any genuine workspace
    subdirectory, so a standalone flat pack with NO real siblings still satisfied the
    "has a workspace" check and returned the project root as the registry root -
    every flat-pack mutation wrote engagements.json/ENGAGEMENTS.md/.html into the
    user's own git-tracked repo. Fixed by branching on pack_dir's own shape instead
    of always trusting pack_dir.parent: a flat pack (pack_dir.name == "artifacts")
    only ever consults its OWN subdirectories for genuine siblings, never its parent;
    a workspace pack keeps the original, correct parent-based logic - including
    "trivially counts as its own sibling", which is intentional there (ANY workspace
    pack gets a registry, single or not - see test_init_default_creates_workspace_
    and_registry, unaffected by this fix). Note: this does not migrate a registry
    file a pre-fix run may have already written at the wrong location - a separate,
    one-time cleanup concern, not something to silently move here."""
    if pack_dir.name == "artifacts":
        if state_path(pack_dir).is_file() and workspace_states(pack_dir):
            return pack_dir  # flat pack that ALSO has genuine sibling workspaces
        return None
    parent = pack_dir.parent
    if workspace_states(parent) or (parent / REGISTRY_JSON).is_file():
        return parent
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

    qa_depth = state.get("qa_depth")
    if qa_depth is not None and qa_depth not in _QA_DEPTHS:
        problems.append(f"qa_depth must be one of {_QA_DEPTHS} (got {qa_depth!r})")

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

    settings_snapshot = state.get("settings_snapshot")
    if settings_snapshot is not None and not isinstance(settings_snapshot, dict):
        problems.append("'settings_snapshot' must be an object")

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
        # 🤖 marker on the framework's OWN generated artifact (2026-08-20, spotted in a live
        # corporate session). START-HERE is the first thing a reader opens, and it attributed
        # the work to a team without ever saying that team is AI - the exact thing the
        # AI-identity rule exists to prevent, missing from the one artifact the rule's own
        # checker never inspects for it (AGENT-UNMARKED matches "Name (Role)" personas, and
        # "the team" is not one, so nothing flagged it).
        "🤖 Produced by the virtual compliance-surveillance engineering team"
        f"{version_bit} - AI agents, Virtual Surveillance IT. "
        "Evidence basis tags: 📊 measured · 🧠 inferred."
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


def render_files(
    artifacts_dir: Path, known_state: dict | None = None, force: bool = False
) -> list[Path]:
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
    try:
        previous = md_path.read_text(encoding="utf-8")
    except OSError:
        previous = None
    md_path.write_text(md_text, encoding="utf-8")
    written = [md_path]
    # Skip the HTML when the markdown did not change AND the sibling already exists
    # (2026-08-25 performance review). Measured: one set-decision cost 0.38s against a 0.03s
    # interpreter floor, of which ~173ms was importing Markdown+bleach and ~90-150ms the
    # render itself - paid by EVERY mutator in the engage flow, and ~40% of the test suite.
    #
    # Safe for the freshness gates rather than merely faster: the .md is still written every
    # time, so STATE-STALE-RENDER is unaffected; the .html still exists, so MISSING-HTML is
    # unaffected; and identical markdown renders to identical HTML, so skipping cannot make
    # the sibling wrong. The only thing lost is a refreshed `generated` date on a file whose
    # content did not change, which is churn, not information.
    html_path = md_path.with_suffix(".html")
    if not force and previous == md_text and html_path.is_file():
        # Report the sibling as up to date, not as skipped. Callers use this list to decide
        # whether the HTML exists and is current - the `render` command exits non-zero when
        # it is missing - and an unchanged file that was already correct satisfies that. A
        # bare early return made a current sibling look absent (caught by
        # test_render_exits_nonzero_when_html_sibling_skipped, which is exactly its job).
        written.append(html_path)
        return written
    render_html = _load_render_html_module()
    if render_html is None:
        print(
            "note: .html sibling not rendered (scripts.render_html unavailable)",
            file=sys.stderr,
        )
        return written
    try:
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


_LOCK_STALE_SECONDS = 30  # a single CLI mutation is a short in-process op; older = a dead holder
_LOCK_WAIT_SECONDS = 5


@contextlib.contextmanager
def _state_lock(artifacts_dir: Path):
    """Advisory cross-process mutex around one read-modify-write cycle on
    engagement-state.json. 2026-08 audit (C5): parallel Workflow-tool dispatch can run
    several mutating commands (set-status, add-artifact, log-note, ...) against the SAME
    pack concurrently - without this, two concurrent load_state()/_write_state() cycles
    race (classic lost-update: second writer silently clobbers the first's change) with
    no error from either process. Portable (os.O_CREAT | os.O_EXCL only, no fcntl/msvcrt
    dependency) since this project's install targets include Windows; a stale lock from a
    process that died mid-mutation is reclaimed by age rather than left to jam every
    future command against the pack forever."""
    lock_path = artifacts_dir / LOCK_FILENAME
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + _LOCK_WAIT_SECONDS
    fd = None
    while fd is None:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                age = time.time() - lock_path.stat().st_mtime
            except FileNotFoundError:
                continue  # released between our open() and stat() - retry immediately
            if age > _LOCK_STALE_SECONDS:
                lock_path.unlink(missing_ok=True)  # holder is gone - reclaim it
                continue
            if time.time() >= deadline:
                raise SystemExit(
                    f"another engagement_state process holds the lock on {artifacts_dir} "
                    f"(age {age:.1f}s) - if it's genuinely dead, delete {lock_path} by hand"
                )
            time.sleep(0.05)
    try:
        os.close(fd)
        yield
    finally:
        lock_path.unlink(missing_ok=True)


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


AUTO_HANDOFF = ".auto-pending.json"


def project_root_for(target_dir) -> pathlib.Path:
    """Best-effort project root for a workspace path: the directory containing the
    `artifacts/` tree, else the target's parent. Only used to locate the launcher's
    handoff file, so a miss degrades to "not an auto run" rather than failing."""
    # --dir is None on the default workspaced path (the caller defaults it AFTER this runs),
    # and the workspace then lands under the cwd's artifacts/ - so cwd IS the project root.
    if target_dir is None:
        return pathlib.Path.cwd()
    p = pathlib.Path(target_dir).resolve()
    for parent in (p, *p.parents):
        if parent.name == "artifacts":
            return parent.parent
    return p.parent


# What an unattended run does when spend reaches the cap. The attended flow offers a degrade
# ladder through the question tool (orchestration guide) - which an unattended run has nobody
# to ask, and which `--permission-mode dontAsk` denies outright. So the human picks a rung
# ONCE at the pre-flight screen and the run applies it silently.
# Four rungs since 2026-08-25. The first three are ADVISORY - the ceiling is a threshold the
# run reports against and can pass. "stop" is ENFORCED by the CLI's own --max-budget-usd,
# which a run cannot talk its way past because it is the process that refuses. Both kept
# deliberately: a ceiling can be pacing or a wall, and the human says which.
AUTO_ON_BUDGET = ("park", "light", "continue", "stop")


def _consume_auto_handoff(project_root: pathlib.Path) -> dict:
    """True when the launcher started this as an unattended run, consuming the handoff.

    The launcher knows the run is unattended; the session should not have to be told and
    then remembered to record it (that indirection is exactly what made the AUTO-* gates
    dead code - 2026-08-21 audit C1). ONE-SHOT: the file is deleted as it is read, so a
    stale handoff cannot silently mark a later, attended engagement as autonomous."""
    handoff = pathlib.Path(project_root) / ".claude" / AUTO_HANDOFF
    try:
        if not handoff.is_file():
            return {}
        payload = json.loads(handoff.read_text(encoding="utf-8"))
        handoff.unlink()
        return payload if isinstance(payload, dict) else {"auto": True}
    except (OSError, ValueError):
        # Unreadable but present: the run IS unattended, which is the safety-relevant half.
        # Losing the budget is a smaller error than losing the flag that makes the AUTO-*
        # gates fire, so consume it and carry on rather than treating it as absent.
        try:
            handoff.unlink()
        except OSError:
            pass
        return {"auto": True}


REQUEST_HANDOFF = ".request-pending.txt"


def consume_request_handoff(project_root: pathlib.Path) -> str:
    """The typed request the launcher left for this session, consuming the file.

    ONE-SHOT, for the same reason the auto handoff is: the skill is TOLD to delete it after
    reading, and "told to" is not a control that engages - the AUTO-* gates were dead code
    for exactly that reason (2026-08-21 audit C1). Creating the workspace deletes it
    whatever the session did or forgot to do, so a stale request cannot be picked up by a
    later engagement that never asked for one.

    Returns the text, or "" when there is nothing pending."""
    handoff = pathlib.Path(project_root) / ".claude" / REQUEST_HANDOFF
    try:
        if not handoff.is_file():
            return ""
        text = handoff.read_text(encoding="utf-8").strip()
    except OSError:
        text = ""
    try:
        handoff.unlink()
    except OSError:
        pass  # unreadable or gone; either way it must not survive as a live request
    return text


def _cmd_init(args: argparse.Namespace) -> int:
    # New engagements are WORKSPACED by default (artifacts/<slug>/); an explicit --dir
    # keeps flat semantics (tests, custom layouts, pre-0.31 behaviour).
    # The typed request is consumed here too - see consume_request_handoff for why the skill
    # being told to delete it is not enough on its own.
    #
    # And its VALUE IS KEPT. The first version discarded it on the reasoning that the session
    # had already read it - which assumed an ordering nothing guarantees. Creating the
    # workspace before reading the request deleted the human's own words and the session then
    # reported the file did not exist (live report, 2026-08-26). The request is the
    # engagement's brief; the pack is where it belongs, and storing it makes the read
    # order irrelevant.
    try:
        _typed_request = consume_request_handoff(project_root_for(getattr(args, "dir", None)))
    except Exception:
        _typed_request = ""  # never let handoff cleanup break workspace creation
    # Read the launcher's handoff ONCE, before the state dict is built: it carries the
    # unattended flag AND the pre-answered budget/degrade choice, and consuming it twice
    # would lose whichever half read second.
    _handoff = _consume_auto_handoff(project_root_for(args.dir))
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
    settings_snapshot = None
    probe = _load_engage_probe()
    if probe is not None:
        try:
            settings_snapshot = probe.resolve_preferences(_project_root_for(args.dir))
        except Exception:  # nosec B110 - best-effort snapshot, never blocks init
            settings_snapshot = None
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
        # None until a QA pass actually happens - an engagement that builds nothing never
        # sets it, and absence must never read as "quick".
        "qa_depth": None,
        # True only for a run the human authorised as unattended at the launcher. Drives
        # the AUTO-* Definition-of-Done gates: such a run may never read as signed off.
        #
        # Read from the launcher's handoff file, NOT from an instruction (2026-08-21 audit,
        # finding C1). It was previously set only by `mark-auto`, which nothing in any skill
        # or document ever told a session to run - so `auto` stayed False on every real
        # unattended engagement and both AUTO-* gates skipped it. The enforcement existed
        # only in tests that hand-built packs with auto=True. An unattended run must not
        # depend on the unattended session remembering to declare itself.
        "auto": bool(_handoff),
        # Pre-answered at the pre-flight screen, because the attended degrade ladder is a
        # question and an unattended run has nobody to ask (and dontAsk denies the question
        # tool outright). Absent for an attended run, which keeps the ladder.
        "auto_on_budget": (
            _handoff.get("on_budget")
            if _handoff.get("on_budget") in AUTO_ON_BUDGET
            else ("park" if _handoff else None)
        ),
        "budget": (
            {
                "engagement_usd": _handoff["engagement_usd"],
                "set": _dt.date.today().isoformat(),
                # The ENFORCED cap, kept apart from the advisory ceiling above it. They are
                # two different promises (2026-08-25) and a reader must never have to infer
                # which one this engagement was given.
                **(
                    {"hard_cap_usd": _handoff["hard_cap_usd"]}
                    if isinstance(_handoff.get("hard_cap_usd"), (int, float))
                    else {}
                ),
            }
            if isinstance(_handoff.get("engagement_usd"), (int, float))
            else {}
        ),
        # How the run was started, and WHICH session is doing it. The session id is chosen by
        # the launcher before anything starts and passed to the CLI as --session-id, so the
        # run and this pack are the same thing by construction - not matched afterwards by
        # date or by whichever transcript was touched last, which is what the deleted
        # transcript reader had to do and could never do reliably.
        "run_mode": _handoff.get("run_mode") or None,
        "session_id": _handoff.get("session_id") or None,
        # What the human actually typed at the launcher, verbatim. Recorded so it survives
        # the one-shot handoff being consumed, and so a reader months later can see the ask
        # the engagement answered rather than only the answer.
        "request": _typed_request or None,
        "phase": args.phase,
        "team": [],
        "verdict": None,
        "footprint": {"agents": None, "approx_tokens": None},
        "settings_snapshot": settings_snapshot,
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
    written = render_files(args.dir, force=True)
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


_ENGAGE_PROBE_MODULE_CACHE = None


def _load_engage_probe():
    """scripts.engage_probe in BOTH run modes, same dual-mode/memoized pattern as
    _load_checker(). None = unavailable; _cmd_init then simply skips the settings
    snapshot - optional metadata, never load-bearing for the engagement itself."""
    global _ENGAGE_PROBE_MODULE_CACHE
    try:
        from scripts import engage_probe  # normal `-m` / package mode

        return engage_probe
    except Exception:  # nosec B110 - probe only; fall through to the file-relative loader
        pass
    if _ENGAGE_PROBE_MODULE_CACHE is not None:
        return _ENGAGE_PROBE_MODULE_CACHE
    try:
        import importlib.util

        path = Path(__file__).with_name("engage_probe.py")
        spec = importlib.util.spec_from_file_location("engage_probe", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _ENGAGE_PROBE_MODULE_CACHE = module
        return module
    except Exception:
        return None


def _cmd_set_status(args: argparse.Namespace) -> int:
    state = load_state(args.dir)
    _upgrade(state)
    before = json.loads(json.dumps(state))  # rollback snapshot (register R6)
    if args.status == "closed":
        # C4a (2026-08 Fable audit): the close path below writes the closed state to
        # disk FIRST, then rolls back to `before` if the gate refuses. That rollback is
        # itself a validated write - if `before` (the pre-close snapshot) is not
        # itself schema-valid, the rollback write raises SystemExit before the
        # CLOSE-REFUSED explanation ever prints, stranding the pack CLOSED on disk with
        # no findings gate having actually passed it. Check this upfront, before any
        # write happens, so a close attempt against an already-invalid state fails
        # loudly here instead of silently later.
        before_problems = validate_state(before)
        if before_problems:
            for problem in before_problems:
                print(f"INVALID (pre-close state): {problem}", file=sys.stderr)
            print(
                "CLOSE-REFUSED: the state file is not valid before this close attempt - "
                "fixing the underlying state (not the close command) resolves this. No "
                "write was made.",
                file=sys.stderr,
            )
            return 1
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
    except Exception as exc:
        # C4b (2026-08 Fable audit): this used to fail OPEN - keep the close, tell the
        # user to run the checker by hand. A checker crash proves nothing about whether
        # the pack actually meets the DoD; keeping an unevidenced close on a crash
        # contradicts the whole "done is evidenced, not claimed" posture this gate
        # exists to enforce. Fail closed instead, the same as a real findings list: roll
        # back to `before` (already validated above, so this write cannot itself fail)
        # and refuse the close.
        print(
            f"CLOSE-REFUSED: the close gate crashed ({exc}) - treating this as a gate "
            "failure, not a pass.",
            file=sys.stderr,
        )
        _write_state(args.dir, before)
        print(
            f"CLOSE-REFUSED: rolled back to '{before.get('status')}'. Run `python -m "
            "scripts.check_artifacts` by hand to see the underlying error, fix it, and "
            "re-run `set-status closed`.",
            file=sys.stderr,
        )
        return 1
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


def _cmd_set_qa_depth(args: argparse.Namespace) -> int:
    """Record the QA level as a TYPED field, not a prose decision, so check_artifacts can
    read it deterministically (the PARTIAL gate depends on that). The *why* still belongs
    in a `set-decision qa-depth "..."` alongside it."""
    return _mutate(args, lambda s: s.__setitem__("qa_depth", args.qa_depth))


def _cmd_mark_auto(args) -> int:
    """Flag the engagement as unattended. One-way on purpose: a run that proceeded without
    asking anyone cannot later be relabelled as attended to dodge the AUTO-* gates."""
    return _mutate(args, lambda s: s.__setitem__("auto", True))


def _cmd_add_artifact(args: argparse.Namespace) -> int:
    def _heal_path(raw: str) -> str:
        """Paths are recorded relative to the PACK dir, but heal the two misspellings a
        live session actually produced (2026-08-16, corp Windows): a PROJECT-relative
        path that re-names the pack ("artifacts/<slug>/x.md" while --dir already points
        at artifacts/<slug>/, which double-resolved and wrongly flagged the row
        added_before_file_existed) and an absolute path inside the pack. Only rewrites
        when the given form does NOT resolve and the healed form DOES - an honestly
        missing file keeps its given path and its flag."""
        # Absolute first: `pack_dir / <absolute>` IS the absolute path, so the
        # relative-form existence check below would short-circuit and record the
        # absolute path verbatim instead of healing it.
        given = Path(raw)
        if given.is_absolute():
            try:
                healed = given.resolve().relative_to(args.dir.resolve()).as_posix()
            except (ValueError, OSError):
                return raw
            if (args.dir / healed).exists():
                print(
                    f"note: healed absolute path {raw} -> {healed} (artifact paths "
                    "are recorded relative to the pack dir)",
                    file=sys.stderr,
                )
                return healed
            return raw
        if (args.dir / raw).exists():
            return raw
        parts = PurePosixPath(raw.replace("\\", "/")).parts
        if len(parts) > 2 and parts[0] == "artifacts" and parts[1] == args.dir.name:
            healed = str(PurePosixPath(*parts[2:]))
            if (args.dir / healed).exists():
                print(
                    f"note: healed project-relative path {raw} -> {healed} (artifact "
                    "paths are recorded relative to the pack dir)",
                    file=sys.stderr,
                )
                return healed
        return raw

    args.path = _heal_path(args.path)

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


def _reject_consent_decision_keys(keys) -> bool:
    """True (having explained why on stderr) when a decision key tries to record the
    execution-consent answer through the generic decisions map. Live block (2026-08-16,
    corp Windows): the model ran `set-decision "execution-consent" "Yes - marker present
    at .claude/.exec-consent"` and the consent-write guard default-denied the whole Bash
    call - to a lexical guard, an interpreter command whose argument text names the
    protected marker is indistinguishable from an attempt to write it. The dedicated
    command exists precisely to avoid that shape (`record-consent-outcome asked|declined`
    carries no marker path, and a recorded outcome is never a grant, ADR-006 §5).
    Refusing here makes the safe path the only path, instead of leaving two documented
    ways to record the same fact where one of them trips the guard."""
    for key in keys:
        if "consent" in str(key).lower():
            print(
                f"refusing to record {key!r} via set-decision(s): consent outcomes have "
                "one sanctioned, guard-safe command - `record-consent-outcome "
                "asked|declined` - and never belong in the generic decisions map. "
                "Keep the consent marker's filename/path out of every decision and "
                "log-note text.",
                file=sys.stderr,
            )
            return True
    return False


def _cmd_set_decision(args: argparse.Namespace) -> int:
    if _reject_consent_decision_keys([args.key]):
        return 2
    return _mutate(args, lambda s: s.setdefault("decisions", {}).__setitem__(args.key, args.value))


def _cmd_set_decisions(args: argparse.Namespace) -> int:
    """Batch form of set-decision (corp perf report, 2026-08-10): intake commonly records
    several decisions in one breath (data-attestation, fix-cycle, and others) via one Bash
    call chaining N separate `set-decision` invocations with `&&` - N full interpreter cold
    starts for what is conceptually one write. This does the same mutation in ONE process,
    ONE load/upgrade/render cycle, same reasoning as bash_hook_dispatcher.py's 5-processes-
    to-1 consolidation, different call site. `set-decision` (singular) is unchanged and
    still the right tool for a single decision."""
    try:
        pairs = json.loads(args.json)
    except (json.JSONDecodeError, TypeError) as e:
        print(f"invalid --json: {e}", file=sys.stderr)
        return 2
    if not isinstance(pairs, dict) or not pairs:
        print("--json must be a non-empty JSON object of {key: value}", file=sys.stderr)
        return 2
    if _reject_consent_decision_keys(pairs.keys()):
        return 2

    def fn(state: dict) -> None:
        decisions = state.setdefault("decisions", {})
        for key, value in pairs.items():
            decisions[key] = value

    return _mutate(args, fn)


def _cmd_log_note(args: argparse.Namespace) -> int:
    def fn(state: dict) -> None:
        date = _dt.date.today().isoformat()
        tag = getattr(args, "tag", None)
        # Bracket-tag convention, not a new field: `log` stays a plain list[str] (zero
        # validate_state/schema change) while giving the dashboard timeline enough signal
        # to pick an icon (e.g. --tag review-loop for a "sent back to X" handoff). Untagged
        # notes render byte-identical to before this existed.
        entry = f"{date} [{tag}]: {args.text}" if tag else f"{date}: {args.text}"
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


def _now_stamp() -> str:
    import datetime

    return datetime.datetime.now().isoformat(timespec="seconds")


SIGN_OFF_PREFIX = "human sign-off"


def _cmd_sign_off(args: argparse.Namespace) -> int:
    """Record a HUMAN's sign-off on a finished engagement (2026-08-21).

    The reopen problem, solved without reopening. A PARTIAL close - which every unattended
    run produces by design, and which any engagement with outstanding items produces -
    leaves delivery complete but unsigned. Without this, putting a name to it meant either
    editing a closed pack (destroying the as-found record the QA evidence rules exist to
    protect) or starting a whole new engagement to sign the last one, which is absurd.

    APPEND-ONLY: adds a ratification entry and leaves status, verdict and every artifact
    exactly as they were closed. The pack still says PARTIAL, because it WAS partial at
    close; what changes is that a person has now accepted it, and who and when.

    Deliberately a launcher/CLI command a human runs, never something a session does for
    itself - the same reasoning as the execution-consent grant. An agent signing off its
    own work is the one thing the whole Definition-of-Done gate exists to prevent."""
    state = load_state(args.dir)
    _upgrade(state)
    who = str(args.by or "").strip()
    if not who:
        print("sign-off: --by '<name>' is required - a signature needs a name", file=sys.stderr)
        return 2
    existing = [
        r
        for r in state.get("ratifications", [])
        if isinstance(r, dict) and str(r.get("text", "")).startswith(SIGN_OFF_PREFIX)
    ]
    if existing:
        print(f"already signed off: {existing[0].get('text')}", file=sys.stderr)
        return 0

    def fn(s: dict) -> None:
        s.setdefault("ratifications", []).append(
            {
                "text": f"{SIGN_OFF_PREFIX}: {who}",
                "status": "ratified",
                "at": _now_stamp(),
            }
        )

    rc = _mutate(args, fn)
    if rc == 0:
        print(f"signed off by {who}")
    return rc


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


def _cmd_set_budget(args: argparse.Namespace) -> int:
    """Record the engagement's spend budget (2026-08-17, assessment recommendation 1).
    Advisory pacing state, never enforcement: the hard stop stays the org-side spend
    limit (workspace/member caps); this exists so the PM can SEE the cap coming at every
    gate (budget-status below) and degrade or park deliberately instead of being
    hard-stopped mid-review by a limit the session never knew about."""

    def fn(state: dict) -> None:
        budget = state.setdefault("budget", {})
        if args.daily_usd is not None:
            budget["daily_usd"] = args.daily_usd
        if args.engagement_usd is not None:
            budget["engagement_usd"] = args.engagement_usd
        budget["set"] = _dt.date.today().isoformat()

    return _mutate(args, fn)


def _load_dashboard_module():
    """dashboard.py's transcript pricing, importable in BOTH run modes - the same
    package-then-file-relative fallback pattern as the render_html import."""
    try:
        from scripts import dashboard

        return dashboard
    # Probe only; fall through to the file-relative loader.
    except Exception:  # nosec B110
        pass
    import importlib.util

    candidate = Path(__file__).resolve().with_name("dashboard.py")
    try:
        spec = importlib.util.spec_from_file_location("dashboard", candidate)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception:
        return None


def _cmd_budget_status(args: argparse.Namespace) -> int:
    """Spent-vs-cap at a gate, in one compact block the PM states beside the team-sizing
    line. Spend is 📊 measured from this project's session transcripts at list prices
    (dashboard.py's pricing, cache tiers included) but the ATTRIBUTION is an
    approximation and says so: transcripts are per session and project-wide, so parallel
    work in the same project counts toward the same number. HEADROOM= gives the PM a
    categorical to act on (ok / approaching at >=70% / exceeded) - the degrade ladder
    lives in the engage skill, the org-side spend limit stays the hard stop. Read-only;
    no budget recorded prints one pointer line and exits 0."""
    state = load_state(args.dir)
    budget = state.get("budget") or {}
    daily = budget.get("daily_usd")
    ceiling = budget.get("engagement_usd")
    if not daily and not ceiling:
        print(
            "no budget recorded - set one with: set-budget --daily-usd <N> "
            "[--engagement-usd <N>] (docs/INTEGRATIONS.md is unrelated; this is "
            "advisory pacing state, ADR-006)"
        )
        return 0
    spent_today = spent_since_open = None
    dash = _load_dashboard_module()
    if dash is not None:
        try:
            project_root = _stamp_root(args.dir).parent
            parsed = dash.parse_transcripts(
                dash.transcripts_dir_for(project_root, Path.home() / ".claude")
            )
            today = _dt.date.today().isoformat()
            opened = (state.get("engagement") or {}).get("opened") or today
            spent_today = sum(s["cost_usd"] for s in parsed["sessions"] if s.get("date") == today)
            spent_since_open = sum(
                s["cost_usd"] for s in parsed["sessions"] if (s.get("date") or "") >= opened
            )
        except Exception:
            spent_today = spent_since_open = None

    def verdict(spent, cap):
        if spent is None or not cap:
            return "unknown"
        if spent >= cap:
            return "exceeded"
        if spent >= 0.7 * cap:
            return "approaching"
        return "ok"

    def money(v):
        return f"${v:.2f}" if v is not None else "unknown"

    worst = "unknown"
    for spent, cap in ((spent_today, daily), (spent_since_open, ceiling)):
        v = verdict(spent, cap)
        rank = {"unknown": 0, "ok": 1, "approaching": 2, "exceeded": 3}
        if rank[v] > rank[worst]:
            worst = v
    if daily:
        print(f"DAILY cap={money(daily)} spent_today={money(spent_today)}")
    if ceiling:
        print(f"ENGAGEMENT ceiling={money(ceiling)} spent_since_open={money(spent_since_open)}")
    # No trailing attribution disclaimer: it restated a rule the docstring and the engage
    # skill already carry, ~190B consumed by nothing at every gate (token audit Track C,
    # 2026-08-18). The caveat lives in this function's docstring and ADR-006.
    print(f"HEADROOM={worst}")
    return 0


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
    one, else None (nothing to resume - "start new" is the only real option).

    In-process consumers (the launcher's archive-all iterates `open`'s FULL rows) use
    this; anything serialising the menu for a model context uses resume_menu_json()."""
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


def resume_menu_json(root: Path, max_shown: int = 3) -> dict:
    """The MODEL-FACING serialisation of resume_menu(): identical shape except `open` is
    slugs only. Its two prompt-side consumers are "is it empty?" and `--resume <slug>`
    membership validation, and the full rows duplicated `shown`'s top entries verbatim,
    doubling the JSON at every non---new open (token audit Track C, 2026-08-18). The
    first cut changed resume_menu() itself and broke the launcher's archive-all (full
    suite, same day) - hence the split: rows in process, slugs on the wire."""
    menu = resume_menu(root, max_shown)
    return {**menu, "open": [r.get("dir") or r.get("slug") for r in menu["open"]]}


def _cmd_list(args: argparse.Namespace) -> int:
    root = args.dir or _default_artifacts_dir()
    if getattr(args, "menu", False):
        menu = resume_menu_json(root)
        print(json.dumps(menu, ensure_ascii=False, indent=2))
        return 0
    if getattr(args, "finished", False):
        print(json.dumps(finished_engagements(root), ensure_ascii=False, indent=2))
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
    root except existing workspace dirs, the registry, and the root-level ACTIVE/lock
    markers), then regenerate the registry."""
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
    # M2 (2026-08 Fable audit): ACTIVE_MARKER and LOCK_FILENAME are root-level, cross-
    # workspace bookkeeping - not part of any one pack's own files. A root that already
    # has a genuine sibling workspace (the flat-pack-with-siblings case _registry_root_for
    # supports) can carry both alongside the flat pack being migrated; leaving them out of
    # `keep` swept them into the new workspace dir instead, losing the root's ACTIVE
    # tracking (read_active(root) silently goes back to None) and stranding a stale lock
    # file inside the migrated pack instead of at the root it actually locks.
    keep = {
        REGISTRY_JSON,
        REGISTRY_MD,
        Path(REGISTRY_MD).stem + ".html",
        ACTIVE_MARKER,
        LOCK_FILENAME,
        slug,
    }
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


# C5: commands that read-modify-write engagement-state.json (directly or via _mutate()) -
# gated through _state_lock in main()'s dispatch below. _cmd_init/_cmd_archive lock the
# ROOT they resolve args.dir to (they can create/touch more than one pack), which is a
# coarser-grained but still-correct simplification: one mutation at a time per root, not
# per pack. Deliberately excludes genuinely read-only commands (_cmd_validate, _cmd_show,
# _cmd_list), _cmd_render (rewrites the human view/registry, never engagement-state.json
# itself - _write_state's atomic os.replace already makes concurrent reads of that file
# safe without a lock), and _cmd_set_active/_cmd_clear_active/_cmd_unarchive/_cmd_migrate
# (single-value marker writes or one-off structural moves, not read-modify-write races).
_MUTATING_CMDS = {
    _cmd_init,
    _cmd_set_status,
    _cmd_set_phase,
    _cmd_set_profile,
    _cmd_add_artifact,
    _cmd_add_outstanding,
    _cmd_resolve_outstanding,
    _cmd_set_decision,
    _cmd_set_decisions,
    _cmd_log_note,
    _cmd_add_ratification,
    _cmd_ratify,
    _cmd_set_team,
    _cmd_archive,
    _cmd_record_consent_outcome,
    _cmd_set_runtime,
    _cmd_finalise_artifacts,
    _cmd_set_footprint,
    _cmd_set_budget,
}


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
    # Not parents=[common]: common's own --slug (dest target_slug, "which pack to operate
    # on") would collide with init's --slug below (a different meaning - the NEW
    # engagement's slug). --dir alone, same SUPPRESS-default reasoning as common's, so an
    # omitted --dir here doesn't clobber a value already parsed at the top level (see the
    # comment above common's own definition).
    p.add_argument("--dir", type=Path, default=argparse.SUPPRESS)
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
        "sign-off",
        parents=[common],
        help="record a HUMAN's sign-off on a finished engagement (append-only)",
    )
    p.add_argument("--by", required=True, help="who is signing off")
    p.set_defaults(fn=_cmd_sign_off)

    p = sub.add_parser(
        "mark-auto",
        parents=[common],
        help="record that this engagement is running UNATTENDED (--auto)",
    )
    p.set_defaults(fn=_cmd_mark_auto)

    p = sub.add_parser(
        "set-qa-depth",
        parents=[common],
        help="record how much INDEPENDENT QA this engagement bought (quick|deep|audit)",
    )
    p.add_argument("qa_depth", choices=_QA_DEPTHS)
    p.set_defaults(fn=_cmd_set_qa_depth)

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
        "set-decisions",
        parents=[common],
        help="record several decisions in one process (renders once) - batch form of "
        "set-decision, for intake sequences that used to chain N separate invocations",
    )
    p.add_argument(
        "--json",
        required=True,
        help='JSON object, e.g. \'{"data-attestation": "...", "fix-cycle": "..."}\'',
    )
    p.set_defaults(fn=_cmd_set_decisions)

    p = sub.add_parser(
        "log-note",
        parents=[common],
        help="append a dated event/completion note to the log (renders)",
    )
    p.add_argument("text")
    p.add_argument(
        "--tag",
        default=None,
        help="optional short tag (e.g. review-loop) rendered as a bracketed prefix - the "
        "dashboard timeline uses it to pick an icon; plain notes need no tag",
    )
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

    p = sub.add_parser("clear-active", parents=[common], help="remove the ACTIVE-engagement marker")
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

    p = sub.add_parser(
        "set-budget",
        parents=[common],
        help="record the engagement's spend budget - advisory pacing, never the hard stop",
    )
    p.add_argument("--daily-usd", dest="daily_usd", type=float, default=None)
    p.add_argument("--engagement-usd", dest="engagement_usd", type=float, default=None)
    p.set_defaults(fn=_cmd_set_budget)

    p = sub.add_parser(
        "budget-status",
        parents=[common],
        help="spent-vs-cap from this project's transcripts (read-only; safe at any gate)",
    )
    p.set_defaults(fn=_cmd_budget_status)

    p = sub.add_parser(
        "list", parents=[common], help="list this project's engagements (registry scan)"
    )
    p.add_argument(
        "--menu",
        action="store_true",
        help="print the computed resume-vs-new menu (JSON: open/shown/more/archived/default) "
        "instead of the plain table - the engage skill's step 0b renders this directly",
    )
    p.add_argument(
        "--finished",
        action="store_true",
        help="print closed and/or archived packs as JSON rows - the launcher's browse "
        "screen and the engage skill's --review validation read this",
    )
    p.set_defaults(fn=_cmd_list)

    p = sub.add_parser(
        "migrate",
        parents=[common],
        help="move a legacy flat pack into its own artifacts/<slug>/ workspace",
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
        if args.fn in _MUTATING_CMDS or args.fn is _cmd_set_active:
            # Any team-layer ACTION marks this session as the engaged one (set-active
            # included: it is how a resumed session claims its workspace). Read-only
            # commands (list/show/validate/render) deliberately do not stamp - a
            # dormant session that merely inspected state must stay dormant.
            stamp_team_session(_stamp_root(args.dir))
        if args.fn in _MUTATING_CMDS:
            # _cmd_init/_cmd_archive resolve their own root when args.dir wasn't given
            # (see the exclusion list above) - lock the same directory they'll actually
            # touch, not None.
            lock_dir = args.dir if args.dir is not None else _default_artifacts_dir()
            with _state_lock(lock_dir):
                return args.fn(args)
        return args.fn(args)
    except FileNotFoundError:
        print(f"no {STATE_FILENAME} in {args.dir} - run init first", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"{STATE_FILENAME} is not valid JSON: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
