#!/usr/bin/env python3
"""
install_helper.py (repo root) - guided install/update for the Claude Code plugin.

Morgan, the team's PM persona, walks a human through the real install path from README
"Quick start": clone or update a local copy of the repo, pick a release channel (main =
stable, dev = cutting edge), point the Claude Code marketplace at the clone, and install
or update the compliance-surveillance-team plugin - with a step-by-step console trail and
a closing summary of the actions that stay manual (per-project enablement, a session
restart - the hooks ship pre-wired; apply-*.sh scripts are maintainer tools, not user
steps).

Default channel is currently **dev**, not main: this is a fast-moving proof-of-concept
phase, and promoting dev to main is eval-gated (CONTRIBUTING.md) - it costs real API
tokens to run, so it happens once there's enough accumulated work to justify it, not on
every dev commit. main can lag dev by weeks of real fixes and docs during this phase.

Run with no arguments on a terminal and a menu offers the subsets: full run, environment
setup only (no code pull), status line only, per-project enablement, or a demo. The CLI
flags remain the non-interactive equivalents for scripts and CI.

--demo runs the REAL interactive flow as a dry run: the same prompts, the same step
logic, but every command prints as a dimmed "would run:" line instead of executing and
no file is written. Read-only probes (PATH lookups, directory checks) stay real.

Design constraints:
- stdlib only, Python 3.9+ - the helper must run before any pip install has happened.
- Human-run from a terminal. It shells out to the `claude` CLI (`claude plugin ...`),
  which is the scriptable twin of the interactive `/plugin` commands; it never writes
  secrets and never runs the repo's apply-*.sh scripts (those are deliberate separate
  human actions - the summary lists them as reminders instead). Every settings write it
  can do is explicit opt-in, each scoped and backed-up: `--permissions <project-dir>`
  merges the README's recommended permissions.allow entries into that project's
  .claude/settings.json (add-only, deny/hooks untouched); `--env-tuning <project-dir>`
  upserts the recommended API-timeout/stream-idle/output-size env vars into that same
  file's env block (every other env var and setting left untouched); `--env-tuning-betas
  <project-dir>` upserts CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1 the same way - an opt-in
  workaround for an LLM gateway that rejects Anthropic's beta tool-schema fields, off
  unless you're actually hitting it (also offered as an interactive yes/no during normal
  project enablement, same opt-in default, not just reachable as this standalone flag);
  `--model-project`/`--model-default` set Morgan's
  model. Each refuses on an unparseable settings file and
  backs the existing file up first rather than overwrite blind. Because you run this
  helper yourself, these writes are a human act (ADR-002 rec 5 governs the model, which
  stays blocked).
- Never destructive: a dirty working tree is detected before any reset and the run
  refuses (or stashes, only on an explicit interactive choice). Local commits ahead of
  origin block a non-interactive reset.
- Re-runnable: every step is idempotent or best-effort with a clear FAIL/SKIP mark.
- Settings persist in ~/.config/virt-surv-it/installer.json (XDG_CONFIG_HOME honoured),
  never by rewriting this script.
- Windows-friendly: pathlib throughout, no ANSI when the stream is not a tty or NO_COLOR
  is set, ASCII fallbacks for every non-ASCII glyph (check marks, box drawing, the 🎩)
  when the console encoding cannot carry them.

Usage:
  python install_helper.py                 # menu on a terminal; full run when piped
  python install_helper.py install         # fresh clone + marketplace + plugin install
  python install_helper.py update          # fetch/reset + marketplace + plugin update
  python install_helper.py --branch dev    # pick the channel up front
  python install_helper.py --yes           # non-interactive full run, safe defaults
  python install_helper.py --yes --pip     # also install requirements-dev.txt
  python install_helper.py --model-project . --model opus     # pin Morgan to opus
  python install_helper.py --model-project . --model default  # reset Morgan to sonnet
  python install_helper.py --demo          # the real flow as a dry run, nothing executed
"""

from __future__ import annotations

import argparse
import json
import copy
import os
import re
import shutil
import subprocess  # fixed-argv calls to git/claude/pip, no shell  # nosec B404
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from typing import Optional

REPO_URL = "https://github.com/danieledge/virtual-surv-IT.git"
MARKETPLACE = "virtual-surv-it"
PLUGIN_ID = "compliance-surveillance-team@virtual-surv-it"
BRANCHES = ("main", "dev")
DEFAULT_CLONE_DIR = Path.home() / "virtual-surv-IT"
CLAUDE_DOCS_URL = "https://claude.com/claude-code"

BANNER_TITLE = "Virtual Surv-IT - team installer"
RULE_WIDTH = 64  # ruled step headers pad to this width

# The README's recommended per-project allow-list: fewer permission prompts on the team's
# own consent-free tooling. Merged ADD-ONLY by --permissions; the safety model is
# unaffected (allow entries cannot override deny rules or the guard hooks).
RECOMMENDED_ALLOW = (
    "Bash(ruff *)",
    "Bash(mypy *)",
    "Bash(bandit *)",
    "Bash(shellcheck *)",
    "Bash(python -m scripts.*)",
    "Bash(python3 -m scripts.*)",
    "Bash(py -m scripts.*)",
    "Bash(*scripts/check-review-tools.sh*)",
    "Bash(*scripts/render_html.py*)",
    "Bash(*scripts/check_artifacts.py*)",
    "Bash(*scripts/gen_synthetic.py*)",
)


def team_read_entries(home: Optional[Path] = None, repo_hint: Optional[str] = None) -> tuple:
    """`Read(...)` rules for the team's OWN files, resolved for this machine.

    Without these, the very first thing `/engage` does - read docs/team-operating-guide.md -
    raises a permission prompt, because in plugin mode that file lives outside the project
    (live report 2026-08-25, in a clean container: prompted on the operating guide before
    the engagement had begun). RECOMMENDED_ALLOW covered Bash commands only and had no Read
    rule at all, so this was every engagement on every new project.

    Reads of the team's own directory, and nothing else: the user installed this plugin, the
    files are its own code and documentation, and reading them changes nothing. It stays
    narrow deliberately - the project's own data is untouched by these rules, and the
    protected-directory deny rule still applies on top.

    Paths are machine-specific, so they cannot live in a static constant. Returns whatever
    resolves - a clone, an installed plugin copy, or both."""
    return tuple(f"Read({root}/**)" for root in _team_roots(home=home, repo_hint=repo_hint))


def _team_roots(home=None, repo_hint=None) -> tuple:
    """Every directory that holds a copy of THIS team, resolved for this machine."""
    roots: list = []
    try:
        clone = _resolve_repo_root(repo_hint)
        if clone:
            roots.append(Path(clone).resolve())
    except Exception:
        pass
    try:
        for candidate in _registry_install_paths(home or Path.home()):
            resolved = Path(candidate).expanduser()
            # THIS plugin only. The registry names every installed plugin, and a first pass
            # here granted access to four other vendors' directories - not ours to give.
            if not resolved.is_dir() or not _looks_like_this_plugin(resolved):
                continue
            if resolved.resolve() not in roots:
                roots.append(resolved.resolve())
    except Exception:
        pass
    return tuple(roots)


def team_script_entries(home=None, repo_hint=None) -> tuple:
    """`Bash(...)` rules for running the team's OWN scripts by absolute path.

    RECOMMENDED_ALLOW covers the module form (`python -m scripts.x`) and three scripts by
    path. In PLUGIN mode the team lives outside the project, so the skill invokes its tools
    by absolute path instead - and `engagement_state.py`, the most-used script of all, was
    not among the three. A live unattended run on Windows had its `engagement_state.py init`
    refused twice (2026-08-26), which is the command that creates the engagement.

    Scoped to the resolved team directories rather than "any folder called scripts": the
    module form is already allowed wholesale, so this adds the same reach in path form and
    no more."""
    rules = []
    for root in _team_roots(home=home, repo_hint=repo_hint):
        scripts = root / "scripts"
        if scripts.is_dir():
            rules.append(f"Bash(*{scripts}*)")
    return tuple(rules)


def merge_allow(settings: dict, entries=RECOMMENDED_ALLOW):
    """Add-only merge of allow entries into a settings dict. Returns (settings, added).

    Everything already present is preserved untouched - deny rules, hooks, other keys,
    existing allow entries and their order; new entries append in the given order."""
    permissions = settings.setdefault("permissions", {})
    allow = permissions.setdefault("allow", [])
    if not isinstance(allow, list):
        raise InstallAbort(
            "permissions.allow in the target settings is not a list - not touching it"
        )
    added = [e for e in entries if e not in allow]
    allow.extend(added)
    return settings, added


# Timeout/output-size tuning: raises the API request and stream-idle timeouts (helps on slow
# networks or behind a corporate proxy) and caps single-tool output sizes (helps avoid the
# large-output/timeout pattern this repo has hit before). Merged UPSERT by --env-tuning: any
# OTHER env var already in the project's settings.json is left untouched; these specific keys
# are added if missing and corrected if present with a different value.
#
# Trade-off (2026-08-07 latency investigation, kept by explicit user decision): this set buys
# resilience by WAITING instead of failing fast. API_TIMEOUT_MS allows up to 30 minutes per
# request, and CLAUDE_CODE_RETRY_WATCHDOG raises the transient-error retry ceiling to ~300
# attempts (roughly three hours of backoff) - and ordinary rate-limit throttling counts as a
# transient error, so a healthy-infra session can still sit in that backoff. The documented
# symptom is a run that grinds silently for hours with no visible progress (a ~3-hour deep
# review of a small codebase was traced to this area). None of these cost anything on a clean,
# unthrottled run. To fail fast instead, the human removes API_TIMEOUT_MS and
# CLAUDE_CODE_RETRY_WATCHDOG from the project settings' env block.
RECOMMENDED_ENV = {
    # 1-hour prompt-cache TTL for API-key/cloud sessions (subscription seats already get
    # 1h): the default 5-minute TTL makes every stop-start gap re-pay the cold prefix at
    # full input price - on this plugin's front-loaded opens that is the difference
    # between a cheap and an expensive day (2026-08-17 cost-model refresh; README
    # §Token usage). Harmless where unsupported: unknown env vars are ignored.
    "ENABLE_PROMPT_CACHING_1H": "1",
    "API_TIMEOUT_MS": "1800000",
    "API_FORCE_IDLE_TIMEOUT": "0",
    "CLAUDE_STREAM_IDLE_TIMEOUT_MS": "600000",
    "CLAUDE_ENABLE_BYTE_WATCHDOG": "1",
    "CLAUDE_CODE_RETRY_WATCHDOG": "1",
    "CLAUDE_CODE_ENABLE_FINE_GRAINED_TOOL_STREAMING": "1",
    "ENABLE_TOOL_SEARCH": "auto",
    "MAX_MCP_OUTPUT_TOKENS": "15000",
    "BASH_MAX_OUTPUT_LENGTH": "20000",
    "TASK_MAX_OUTPUT_LENGTH": "24000",
}


def merge_env(settings: dict, entries=RECOMMENDED_ENV):
    """Upsert merge of tuning env vars into a settings dict's top-level "env" block.
    Returns (settings, added, updated) - the keys touched, for reporting.

    Unlike merge_allow (add-only), this corrects a key that's already present with a
    stale/different value - "update if they have other values, add new ones" (explicit user
    instruction) - while every OTHER env var, and every other top-level settings key, is left
    exactly as found. A key already equal to the recommended value is silently skipped (not
    reported as added or updated)."""
    env = settings.setdefault("env", {})
    if not isinstance(env, dict):
        raise InstallAbort('"env" in the target settings is not an object - not touching it')
    added, updated = [], []
    for key, value in entries.items():
        if key not in env:
            added.append(key)
        elif env[key] != value:
            updated.append(key)
        env[key] = value
    return settings, added, updated


# Workaround for an LLM-gateway compatibility issue (2026-08-07 live report): a haiku-tier
# subagent call (review-scorer is the one agent in this roster pinned to model: haiku) failed
# with "API Error: 400 tools.0.custom.eager_input_streaming: Extra inputs are not permitted" -
# the exact signature CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS's own docs name for a gateway that
# rejects the Anthropic-specific beta tool-schema fields Claude Code sends by default. Kept
# SEPARATE from RECOMMENDED_ENV (not folded into --env-tuning) because it has a real tradeoff
# of its own - MCP tool search is disabled and every MCP tool loads upfront.
#
# Default posture is context-dependent, by explicit user decision (2026-08-10): asked
# individually, default OFF, for --env-tuning-betas / --configure / manually walking through
# project enablement one question at a time - the tradeoff only makes sense for someone
# actually hitting the gateway incompatibility, so it stays a deliberate opt-in there. Applied
# WITHOUT asking when a full install/update chose "recommended defaults for everything" at
# quick_setup_choice (enable_step) - same "no further question, just do it" idiom
# optional_pip already uses for that mode.
EXPERIMENTAL_BETAS_ENV = {
    "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS": "1",
}


# ------------------------------------------------------------------ config persistence


def config_path() -> Path:
    """~/.config/virt-surv-it/installer.json, honouring XDG_CONFIG_HOME."""
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / "virt-surv-it" / "installer.json"


def load_config(path: Path) -> dict:
    """Missing or corrupt config is not an error - the run just starts fresh.

    utf-8-sig: tolerates a BOM left by a Windows editor; reads BOM-less files too."""
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_config(path: Path, cfg: dict) -> bool:
    """Best-effort atomic write: temp file + os.replace, so a concurrent or interrupted
    run never leaves a half-written config (last writer wins whole). Returns False
    instead of raising when the location is unwritable - the run continues, it just
    will not remember its settings."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
        return True
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return False


# ------------------------------------------------------------------ console styling


def supports_color(stream=None, env: Optional[dict] = None) -> bool:
    """ANSI only on a real tty with NO_COLOR unset (https://no-color.org)."""
    stream = stream if stream is not None else sys.stdout
    env = env if env is not None else os.environ
    if "NO_COLOR" in env:
        return False
    if env.get("TERM") == "dumb":
        return False
    if not bool(getattr(stream, "isatty", lambda: False)()):
        return False
    if os.name == "nt":
        # A Windows console can be a tty and still not interpret ANSI: legacy conhost
        # renders the escapes literally, so `virt-surv` printed raw ←[36m over its whole
        # menu on exactly the boxes this plugin targets. The launcher has always checked
        # this (virt_team_launcher._color_enabled); the installer did not, so the same
        # product disagreed with itself about the same console.
        return any(env.get(v) for v in ("WT_SESSION", "TERM", "TERM_PROGRAM", "ANSICON"))
    return True


class Style:
    """Tiny ANSI painter; a disabled instance returns text unchanged."""

    def __init__(self, enabled: bool):
        self.enabled = enabled

    def _paint(self, text: str, code: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.enabled else text

    def bold(self, text: str) -> str:
        return self._paint(text, "1")

    def green(self, text: str) -> str:
        return self._paint(text, "32")

    def red(self, text: str) -> str:
        return self._paint(text, "31")

    def yellow(self, text: str) -> str:
        return self._paint(text, "33")

    def cyan(self, text: str) -> str:
        return self._paint(text, "36")

    def dim(self, text: str) -> str:
        return self._paint(text, "2")

    def magenta(self, text: str) -> str:
        """The violet in the brand banner's cyan -> violet -> green wordmark gradient."""
        return self._paint(text, "35")


def _can_encode(text: str, stream=None) -> bool:
    """True when the stream's encoding can carry every character in text."""
    stream = stream if stream is not None else sys.stdout
    encoding = getattr(stream, "encoding", None) or "utf-8"
    try:
        text.encode(encoding)
        return True
    except (UnicodeEncodeError, LookupError):
        return False


def marks(stream=None) -> dict:
    """Unicode check marks, with ASCII fallbacks for consoles that cannot encode them."""
    if _can_encode("✓✗", stream):
        return {"ok": "✓", "fail": "✗", "skip": "~"}
    return {"ok": "OK", "fail": "X", "skip": "~"}


def box_chars(stream=None) -> dict:
    """Box-drawing characters, with ASCII fallbacks like marks()."""
    if _can_encode("┌─┐│└┘", stream):
        return {"tl": "┌", "tr": "┐", "bl": "└", "br": "┘", "h": "─", "v": "│"}
    return {"tl": "+", "tr": "+", "bl": "+", "br": "+", "h": "-", "v": "|"}


def render_banner(lines, style: Style, stream=None) -> list:
    """The boxed banner as a list of printable rows, cyan/bold when styled."""
    c = box_chars(stream)
    inner = max(len(line) for line in lines)
    rows = [c["tl"] + c["h"] * (inner + 2) + c["tr"]]
    for line in lines:
        rows.append(f"{c['v']} {line.ljust(inner)} {c['v']}")
    rows.append(c["bl"] + c["h"] * (inner + 2) + c["br"])
    return [style.cyan(style.bold(row)) for row in rows]


def render_kv_table(rows: list, style: Style, stream=None) -> list:
    """Two-column box-drawn summary table, box_chars-based like render_banner for visual
    consistency. rows: (label, value, state) - state True colors the whole row green
    (on/applied), False dims it (off/declined), None leaves it unstyled (informational,
    not an on/off toggle - e.g. a list of overrides or a free-text value). Colors the
    WHOLE row rather than per-cell: Style._paint wraps text in its own reset code, so
    nesting a second color inside an already-painted line only reliably colors the
    innermost span, not the border/label around it - painting one flat string per row
    sidesteps that instead of fighting it."""
    c = box_chars(stream)
    label_w = max(len(r[0]) for r in rows)
    value_w = max(len(r[1]) for r in rows)
    border = c["h"] * (label_w + value_w + 5)
    lines = [c["tl"] + border + c["tr"]]
    for label, value, state in rows:
        plain = f"{c['v']} {label.ljust(label_w)} {c['v']} {value.ljust(value_w)} {c['v']}"
        if state is True:
            lines.append(style.green(plain))
        elif state is False:
            lines.append(style.dim(plain))
        else:
            lines.append(plain)
    lines.append(c["bl"] + border + c["br"])
    return lines


def rule_header(number: int, total: int, title: str, style: Style, stream=None) -> str:
    """A ruled step header padded to RULE_WIDTH, e.g. '── Step 3 of 9: Local clone ────'."""
    h = box_chars(stream)["h"]
    label = f"{h * 2} Step {number} of {total}: {title} "
    pad = h * max(0, RULE_WIDTH - len(label))
    return style.bold(label) + style.dim(pad)


def morgan_intro(stream=None) -> str:
    """Morgan's opening line with the mandatory AI-identity attribution.

    The 🎩 persona marker is encoding-probed like every other glyph."""
    hat = "🎩 " if _can_encode("🎩", stream) else ""
    return (
        f"{hat}Morgan (PM) here - I'm an AI agent with Virtual Surveillance IT. "
        "Let's get the team set up."
    )


def banner_version_line() -> str:
    """The banner's second line - always present, never a crash.

    Resolution order: the script's own sibling manifest (the helper sits at the clone
    root, so this covers every normal run including demo and fresh installs), then the
    configured clone's manifest, then a fixed fallback (a standalone-downloaded helper
    file has no manifest anywhere yet)."""
    version = installed_version(clone_asset())
    if not version:
        repo = load_config(config_path()).get("repo_path")
        if isinstance(repo, str) and repo:
            version = installed_version(Path(repo))
    suffix = f"v{version}" if version else "(version shown after install)"
    return f"compliance-surveillance-team {suffix}"


def _installed_cache_note() -> str:
    """One warning line when the marketplace-INSTALLED copy's version differs from this
    clone's, '' otherwise - the same just-in-time check `virt-surv go` performs
    (2026-08-18: the banner said v0.34.0 while sessions would load the older installed
    copy; here the fix is literally menu option 1)."""
    try:
        clone_v = installed_version(clone_asset()) or ""
        if not clone_v:
            return ""
        for raw in _registry_install_paths(Path.home()):
            rp = Path(raw)
            if not _looks_like_this_plugin(rp):
                continue
            v = installed_version(rp) or ""
            if v and v != clone_v:
                return (
                    f"! installed plugin is v{v}, this clone is v{clone_v} - sessions "
                    "load the INSTALLED copy; option 1 (full run) updates it"
                )
            return ""
    except Exception:
        pass
    return ""


def brand_banner_rows(style: Style, width: Optional[int] = None) -> list:
    """The shared VSIT brand banner (scripts/brand_banner.py), painted with this Style.

    Returns [] when the module cannot be imported, which is a real case rather than a
    theoretical one: this helper is also distributed as a single curl-bootstrapped file
    with no scripts/ sibling (same reason _parse_extensions and _PLUGIN_CACHE_MARKER are
    written the way they are). print_banner falls back to its own boxed banner then - the
    art is shared, never duplicated, and never a hard dependency."""
    try:
        # Through the shared resolver, NOT Path(__file__): the installer re-execs from a
        # bare temp copy of itself for most of a session, so scripts/ is not beside it and
        # the import failed on every real run. The designed banner was therefore never
        # seen - `virt-surv go` showed the VSIT mascot and `virt-surv` showed a plain
        # ASCII box, which read as two visual identities for one product and was actually
        # the same defect in a third place (2026-08-28).
        brand_banner = _import_from_scripts("brand_banner")
        if brand_banner is None:
            return []
    except Exception:
        return []
    painters = {
        "plain": lambda t: t,
        "dim": style.dim,
        "cyan": style.cyan,
        "violet": style.magenta,
        "green": style.green,
        "amber": style.yellow,
        "bold": style.bold,
    }
    if width is None:
        width = shutil.get_terminal_size((80, 24)).columns
    try:
        return brand_banner.render(width, lambda role, t: painters[role](t))
    except Exception:
        return []


# Set the first time the banner is printed. The app tier draws the brand INSIDE its frame
# (the alternate screen hides anything printed before it, for as long as anyone is
# actually using the menu), so the terminal print is skipped when that tier is going to
# run - and the numbered tier prints it on the way past instead. Exactly one banner,
# wherever it can be seen.
_BANNER_SHOWN = False


def banner_already_shown() -> bool:
    return _BANNER_SHOWN


def print_banner(style: Style, stream=None) -> None:
    """The brand banner (or the boxed fallback), the version line and Morgan's intro."""
    global _BANNER_SHOWN
    _BANNER_SHOWN = True
    rows = brand_banner_rows(style)
    if rows:
        for row in rows:
            print(row)
        # ASCII on purpose, like the banner above it: this line rides the same cp1252
        # corp-console path (a middot survives cp1252, but nothing here needs to test that).
        print(style.dim(f"  team installer  -  {banner_version_line()}"))
    else:
        for row in render_banner([BANNER_TITLE, banner_version_line()], style, stream):
            print(row)
    note = _installed_cache_note()
    if note:
        print(style.yellow(note))
    print(morgan_intro(stream))


# ------------------------------------------------------------------ step tracking


class StepTracker:
    """Collects (name, status, detail) rows; status is one of ok / fail / skip."""

    STATUSES = ("ok", "fail", "skip")

    def __init__(self):
        self.steps = []

    def record(self, name: str, status: str, detail: str = "") -> None:
        if status not in self.STATUSES:
            raise ValueError(f"unknown step status: {status!r}")
        self.steps.append((name, status, detail))

    @property
    def failed(self) -> bool:
        return any(status == "fail" for _, status, _ in self.steps)

    def summary_lines(self, mark_map: Optional[dict] = None) -> list:
        """Flat one-line-per-step view (kept for callers that want the ungrouped form)."""
        mark_map = mark_map or {"ok": "✓", "fail": "✗", "skip": "~"}
        lines = []
        for name, status, detail in self.steps:
            suffix = f"  ({detail})" if detail else ""
            lines.append(f"  {mark_map[status]} {name}{suffix}")
        return lines


class InstallAbort(Exception):
    """Raised to stop the run after a fatal step; the summary still prints."""


# ------------------------------------------------------------------ subprocess wrapper


def installed_version(repo: Path) -> Optional[str]:
    """The plugin version in the clone's manifest, or None when unreadable.

    utf-8-sig read: BOM-tolerant for files a Windows editor may have touched."""
    try:
        manifest = json.loads(
            (repo / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8-sig")
        )
        version = manifest.get("version")
        return version if isinstance(version, str) and version else None
    except (OSError, ValueError):
        return None


def parse_manifest_version(text) -> Optional[str]:
    """Version string from a plugin.json BODY (e.g. `git show` output). Tolerant of
    garbage, non-dict JSON, a missing/empty version and a leading BOM; never raises."""
    try:
        data = json.loads(str(text).lstrip("\ufeff"))
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    version = data.get("version")
    return version if isinstance(version, str) and version else None


def changelog_headline(changelog: Path, version: str) -> Optional[str]:
    """The `## [<version>] - date - title` line from the changelog, cleaned for console."""
    try:
        for line in changelog.read_text(encoding="utf-8-sig").splitlines():
            if line.startswith(f"## [{version}]"):
                return line[3:].strip()
    except (OSError, UnicodeDecodeError):
        # UnicodeDecodeError is NOT an OSError (found in review, 2026-08-13): a
        # CHANGELOG.md that isn't clean UTF-8 used to crash the installer here instead of
        # just skipping the headline, same class of gap fixed below in
        # check_pending_hook_fixes/run_daemon_start_diagnostic.
        pass
    return None


# A changelog section holding nothing but a placeholder. Matched on the BODY, so it works
# whatever wording the placeholder uses, rather than pattern-matching one phrase.
_PLACEHOLDER_BODY = {"", "_nothing yet._", "nothing yet.", "_none._", "none.", "-", "n/a"}


def list_headlines_between(changelog_text, local_version: Optional[str]) -> list:
    """What an update would actually bring: `## [x.y.z] - date - description` headlines from
    the top of a changelog BODY down to (not including) the entry for local_version.

    Two things this does beyond slicing the lines, both from a live report (2026-08-25:
    "why does it say 2 commits and then [unreleased] rather than what changed"):

    - a section with NEITHER a description NOR content is skipped. `## [Unreleased]` is a
      standing placeholder in this repo, so it was always the first headline, and the
      reader was told the name of an empty section instead of the release underneath. The
      test is deliberately "neither", not "empty body": a released heading carries its
      summary on the headline itself and stays news even with nothing beneath it;
    - a headline with NO DESCRIPTION borrows the first `### ` sub-heading beneath it.
      Release headlines carry their own summary after the date; `[Unreleased]` never does,
      so on a dev-branch update - where unreleased commits are exactly what you get - the
      one line that said what changed was the sub-heading, and it was thrown away.

    A local version that never appears (or None) yields every headline - the caller caps
    the display. Pure and total: any input coerces via str(), worst case an empty list."""
    lines = str(changelog_text).splitlines()
    marks = [i for i, line in enumerate(lines) if line.startswith("## [")]
    headlines = []
    for position, index in enumerate(marks):
        line = lines[index]
        if local_version and line.startswith(f"## [{local_version}]"):
            break
        end = marks[position + 1] if position + 1 < len(marks) else len(lines)
        body = [row for row in lines[index + 1 : end] if row.strip()]
        empty = not body or (len(body) == 1 and body[0].strip().lower() in _PLACEHOLDER_BODY)
        headline = line[3:].strip()
        # "[1.2.3] - date - what changed" already explains itself; "[Unreleased]" does not.
        described = headline.count(" - ") >= 2
        if empty and not described:
            continue  # nothing to say and nothing beneath it - not news
        if not described:
            sub = next((row[4:].strip() for row in body if row.startswith("### ")), "")
            if sub:
                headline = f"{headline} - {sub}"
        headlines.append(headline)
    return headlines


def user_settings_path() -> Path:
    """The user-level Claude Code settings file (~/.claude/settings.json)."""
    return Path.home() / ".claude" / "settings.json"


def find_bash() -> Optional[str]:
    """bash for the status line, surviving Git for Windows' default PATH: the
    installer only adds Git\\cmd (git.exe), not Git\\bin (bash.exe) - so `git` works
    while `bash` misses ('installed but not on PATH', seen live 2026-07-30). Derive
    bash from git's own install root first, then the standard install dirs, then a
    fresh registry PATH read. POSIX: just which()."""
    hit = shutil.which("bash")
    if hit:
        return hit
    if sys.platform != "win32":
        return None
    candidates = []
    git = shutil.which("git")
    if git:
        root = Path(git).resolve().parent.parent  # Git\cmd\git.exe -> Git
        candidates += [root / "bin" / "bash.exe", root / "usr" / "bin" / "bash.exe"]
    for env in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
        base = os.environ.get(env)
        if base:
            candidates.append(Path(base) / "Git" / "bin" / "bash.exe")
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(Path(local) / "Programs" / "Git" / "bin" / "bash.exe")
    for c in candidates:
        if _is_file_safe(c):
            return str(c)
    for d in _windows_registry_path_dirs():
        p = Path(d) / "bash.exe"
        if _is_file_safe(p):
            return str(p)
    return None


def statusline_command(repo: Path, bash: str = "bash") -> str:
    """The statusLine command pointing at the clone's script by absolute path, so the
    status line works from every project (dormant ones just show 'team dormant').
    `bash` may be a full path (quoted if needed) when it is not on PATH."""
    bash_part = bash if bash == "bash" else f'"{bash}"'
    return f'{bash_part} "{(repo / "scripts" / "statusline.sh").resolve()}"'


# statusline_command() always ends the quoted path with .../scripts/statusline.sh" (both
# slash directions, since a Windows-written command may use backslashes) - matched exactly
# here, anchored to the end of the string, rather than a bare "statusline.sh" substring
# (found in review, 2026-08-13: that could false-positive on any unrelated script merely
# named *statusline.sh, e.g. "my-statusline.sh" or "notstatusline.sh", silently overwriting
# a genuinely foreign statusLine instead of showing the conflict prompt).
_OUR_STATUSLINE_COMMAND_RE = re.compile(r'[/\\]scripts[/\\]statusline\.sh"$')


def merge_statusline(settings: dict, command: str):
    """Set statusLine in a settings dict. Returns (settings, verdict):
    'added' (none existed), 'already' (identical command present, nothing to do),
    'ours-moved' (OUR statusline.sh at another path - e.g. an old clone location -
    updated in place without a scare prompt), or 'conflict' (a genuinely foreign
    statusLine - the caller must show it to the user and get explicit confirmation)."""
    current = settings.get("statusLine")
    if isinstance(current, dict) and current.get("command") == command:
        return settings, "already"
    if isinstance(current, dict) and _OUR_STATUSLINE_COMMAND_RE.search(
        str(current.get("command", ""))
    ):
        settings["statusLine"] = {"type": "command", "command": command}
        return settings, "ours-moved"
    if current is not None:
        return settings, "conflict"
    settings["statusLine"] = {"type": "command", "command": command}
    return settings, "added"


def current_statusline_command(settings: dict) -> str:
    """The existing statusLine command for display, best-effort."""
    current = settings.get("statusLine")
    if isinstance(current, dict):
        return str(current.get("command", "")) or "(unreadable command)"
    return str(current) if current is not None else ""


def _windows_registry_path_dirs() -> list:
    """PATH directories re-read FRESH from the registry (user then machine).

    Corporate Windows: an installer updates the registry PATH, but every already-open
    terminal (and anything launched from it, like this script) keeps the stale copy it
    inherited at start - so `shutil.which` misses a CLI that a brand-new shell would
    find. Reading the registry sees what that new shell would see. Best-effort: any
    failure returns what was gathered so far."""
    dirs: list = []
    try:
        import winreg  # Windows-only stdlib; guarded by the caller's platform check

        for hive, key in (
            (winreg.HKEY_CURRENT_USER, r"Environment"),
            (
                winreg.HKEY_LOCAL_MACHINE,
                r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
            ),
        ):
            try:
                with winreg.OpenKey(hive, key) as k:
                    val, _ = winreg.QueryValueEx(k, "Path")
                dirs += [os.path.expandvars(d) for d in str(val).split(";") if d.strip()]
            except OSError:
                continue
    except Exception:  # best-effort registry probe; any failure just yields no dirs  # nosec B110
        pass
    return dirs


def _read_json_dict(path: Path) -> dict:
    """A dict from a JSON file, or {} on absence/garbage/BOM trouble. Never raises."""
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _atomic_write_text(path: Path, text: str) -> None:
    """Write `text` to `path` atomically: temp file in the same directory, then
    os.replace - same pattern as save_config/_write_json_backup above and
    engagement_state.py's _write_state. Shared by the settings.json writers below
    (run_permissions/_run_env_upsert/statusline_step/_write_model_to_settings_file) so an
    interrupted write (Ctrl-C, crash, disk full) never leaves the target truncated or
    corrupt (found in review, 2026-08-13 - each of those previously wrote straight to the
    target path)."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _write_json_backup(path: Path, data: dict) -> None:
    """utf-8, trailing newline, .bak of any existing content first. The final write is
    atomic (temp file in the same directory, then os.replace - same pattern as save_config
    above and engagement_state.py's _write_state): an interrupted write (Ctrl-C, crash,
    disk full) leaves either the old content or the new content, never a truncated file
    (found in review, 2026-08-13 - this previously wrote straight to `path`)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        backup = path.with_suffix(path.suffix + ".bak")
        backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    _atomic_write_text(path, json.dumps(data, indent=2) + "\n")


# A claude CLI that is ON PATH but cannot actually be executed, in the words the OS
# uses to say so. Live report 2026-08-28, from a locked-down corporate Windows box: an
# npm shim resolved on PATH (so discovery reported "claude CLI found"), but the shim's
# own target no longer existed, and cmd answered "is not recognized as an internal or
# external command". That matched neither "group policy" nor "blocked", so the run took
# the fatal branch and ABORTED - on a box where direct registration would have finished
# the install without the CLI at all.
#
# Matched against the CLI's stderr, lower-cased. Every entry means the same thing: the
# binary never ran, so nothing can be concluded about the request that was made to it.
_CLI_UNUSABLE_MARKERS = (
    "group policy",
    "blocked",
    "is not recognized as an internal or external command",
    "operable program or batch file",
    "the system cannot find the file specified",
    "the system cannot find the path specified",
    "cannot find the path specified",
    "command not found",
    "no such file or directory",
    "access is denied",
    "permission denied",
    "winerror 1260",
    "winerror 2",
)


def cli_unusable_reason(err: str) -> str:
    """Why the claude CLI could not run, or "" if it ran and simply returned an error.

    The distinction decides between falling back to direct registration (the CLI is the
    route, not the goal) and reporting a real failure - so it is one function both
    callers share rather than two drifting lists of substrings."""
    lowered = (err or "").lower()
    if "group policy" in lowered:
        return "the claude CLI launch is blocked by policy"
    for marker in _CLI_UNUSABLE_MARKERS:
        if marker in lowered:
            return "the claude CLI is on PATH but could not be executed"
    return ""


def register_plugin_directly(repo: Path, claude_dir: Path, version: Optional[str]) -> list:
    """Register the marketplace + plugin by writing the same JSON the claude CLI
    writes, for boxes where group policy blocks launching the CLI at all (the
    interactive Claude Code app still runs and reads these files at startup).

    Schema captured by running the real CLI against a directory marketplace and
    diffing every file it touched (2026-07-30):
      plugins/known_marketplaces.json  name -> {source: {source: directory, path},
                                                installLocation: path, lastUpdated}
      plugins/installed_plugins.json   {version: 2, plugins: {id: [{scope, ...}]}}
      settings.json                    enabledPlugins: {id: true} AND
                                       extraKnownMarketplaces: {name: {source}}
    installPath = the clone (the repo root IS the plugin; the CLI copies to a cache
    dir but loads from whatever installPath records). Merge-only: other marketplaces,
    plugins and settings are preserved, .bak written beside each file. Returns the
    list of files touched."""
    now = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    plugins_dir = claude_dir / "plugins"
    touched = []
    source = {"source": "directory", "path": str(repo)}

    # settings.json is the shared, higher-stakes file (hooks/permissions can live there
    # too) - refuse to touch ANYTHING here if it's present but unparseable, same safety
    # bar run_permissions/_write_model_to_settings_file already hold for this exact file,
    # rather than silently discarding its content via _read_json_dict's garbage-becomes-{}
    # fallback (found in review, 2026-08-13: this was the one settings.json write site that
    # skipped the refuse-on-unparseable check every other call site already had). Checked
    # BEFORE km_path/ip_path are written so a corrupt settings.json aborts with no partial
    # state at all, not just a skipped last file.
    st_path = claude_dir / "settings.json"
    if st_path.is_file():
        try:
            st = json.loads(st_path.read_text(encoding="utf-8-sig"))
            if not isinstance(st, dict):
                raise ValueError("settings root is not an object")
        except (OSError, ValueError) as exc:
            raise InstallAbort(
                f"{st_path} is not readable JSON ({exc}) - refusing to touch it"
            ) from exc
    else:
        st = {}

    km_path = plugins_dir / "known_marketplaces.json"
    km = _read_json_dict(km_path)
    km[MARKETPLACE] = {
        "source": source,
        "installLocation": str(repo),
        "lastUpdated": now,
    }
    _write_json_backup(km_path, km)
    touched.append(str(km_path))

    ip_path = plugins_dir / "installed_plugins.json"
    ip = _read_json_dict(ip_path)
    ip.setdefault("version", 2)
    plugins = ip.get("plugins")
    if not isinstance(plugins, dict):
        plugins = {}
        ip["plugins"] = plugins
    plugins[PLUGIN_ID] = [
        {
            "scope": "user",
            "installPath": str(repo),
            "version": version or "unknown",
            "installedAt": now,
            "lastUpdated": now,
        }
    ]
    _write_json_backup(ip_path, ip)
    touched.append(str(ip_path))

    enabled = st.get("enabledPlugins")
    if not isinstance(enabled, dict):
        enabled = {}
        st["enabledPlugins"] = enabled
    enabled[PLUGIN_ID] = True
    extra = st.get("extraKnownMarketplaces")
    if not isinstance(extra, dict):
        extra = {}
        st["extraKnownMarketplaces"] = extra
    extra[MARKETPLACE] = {"source": source}
    _write_json_backup(st_path, st)
    touched.append(str(st_path))
    return touched


def _demo_active() -> bool:
    """True while --demo has swapped run_cmd for the dry-run stand-in.

    Read off the installed runner rather than a module flag: main() swaps run_cmd at
    three separate sites, and a flag would have to be set and restored at every one."""
    return bool(getattr(run_cmd, "is_demo", False))


def _claude_via_npm_prefix() -> Optional[str]:
    """Ask npm where its prefix is, then look for claude under it. Covers custom
    corporate prefixes no hardcoded candidate list can know. Best-effort: npm absent,
    blocked or slow just returns None.

    This is the one discovery tier that needs its own subprocess (the others read the
    filesystem or the registry), so it is also the one that has to opt out of --demo:
    the dry run's contract is that it spawns nothing at all. Only reached when PATH and
    the known locations came up empty, so it stayed invisible on any box with claude on
    PATH and only ever failed where claude was missing - CI, and the corporate machines
    this tier exists for (CI red from 2026-08-28)."""
    if _demo_active():
        return None
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if not npm:
        return None
    if npm.lower().endswith((".cmd", ".bat")):
        # CreateProcess cannot launch a batch file from a plain argv; same quoted
        # cmd /s /c form run_cmd uses for shims.
        cmdline = windows_shim_cmdline(npm, ["config", "get", "prefix"])
    else:
        cmdline = [npm, "config", "get", "prefix"]
    try:
        proc = subprocess.run(  # fixed command line built above, shell=False  # nosec B603
            cmdline,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    prefix = (proc.stdout or "").strip()
    if proc.returncode != 0 or not prefix:
        return None
    root = Path(prefix)
    if sys.platform == "win32":
        candidates = [root / n for n in ("claude.cmd", "claude.bat", "claude.exe")]
        pkg = root / "node_modules" / "@anthropic-ai" / "claude-code"
    else:
        candidates = [root / "bin" / "claude"]
        pkg = root / "lib" / "node_modules" / "@anthropic-ai" / "claude-code"
    candidates += [pkg / "bin" / n for n in ("claude.exe", "claude.cmd", "claude")]
    candidates += [pkg / "cli.js"]
    return next((str(c) for c in candidates if _is_file_safe(c)), None)


_claude_cache: Optional[tuple] = None  # memo for find_claude (registry reads once per run)


# Set only by a caller that has launched a candidate and seen it work. Distinct from
# _claude_cache, which records where claude WAS FOUND - a weaker claim, and the one that
# turned out not to be enough.
_claude_verified: Optional[str] = None


def remember_working_claude(path) -> None:
    """Pin the CLI that ran, so every later launch uses it."""
    global _claude_verified, _claude_cache
    _claude_verified = str(path) if path else None
    if path:
        _claude_cache = None  # force re-resolution against the verified path


def _claude_candidates():
    """Every place claude might be, best first, as (path, how) - lazily.

    A GENERATOR because the later tiers cost real time on Windows (a registry PATH read,
    an `npm prefix` subprocess) and are only worth paying for when the earlier ones did
    not produce something that works. Callers that want one answer take the first;
    callers that need a WORKING one keep pulling.

    Splitting this out of find_claude is what makes falling through possible at all: a
    PATH hit used to short-circuit the entire search, so a package-manager shim left
    behind by a half-removed install hid a perfectly good native install sitting in the
    next tier down (live report 2026-08-28). Never raises."""
    seen = set()

    def _offer(path, how):
        key = str(path).lower()
        if key in seen:
            return None
        seen.add(key)
        return (str(path), how)

    hit = shutil.which("claude")
    if hit:
        got = _offer(hit, "path")
        if got:
            yield got
    home = Path.home()
    if sys.platform == "win32":
        names = ("claude.exe", "claude.cmd", "claude.bat")
        candidates = [home / ".local" / "bin" / "claude.exe"]
        appdata = os.environ.get("APPDATA")
        if appdata:
            npm_dir = Path(appdata) / "npm"
            candidates += [npm_dir / n for n in ("claude.cmd", "claude.bat")]
            # Seen on corporate devices: the npm shims are absent/blocked and only
            # the package's own bin dir is reachable (npm\node_modules\...\bin).
            pkg_bin = npm_dir / "node_modules" / "@anthropic-ai" / "claude-code" / "bin"
            candidates += [pkg_bin / n for n in names]
    else:
        names = ("claude",)
        candidates = [
            home / ".local" / "bin" / "claude",
            home / ".claude" / "local" / "claude",
            home / ".npm-global" / "bin" / "claude",
            Path("/usr/local/bin/claude"),
            Path("/opt/homebrew/bin/claude"),
        ]
    for c in candidates:
        if _is_file_safe(c):
            got = _offer(c, "known-location")
            if got:
                yield got
    npm_hit = _claude_via_npm_prefix()
    if npm_hit:
        got = _offer(npm_hit, "npm-prefix")
        if got:
            yield got
    if sys.platform == "win32":
        for d in _windows_registry_path_dirs():
            found = next((p for n in names if (p := Path(d) / n) and _is_file_safe(p)), None)
            if found:
                got = _offer(found, "registry")
                if got:
                    yield got


def find_claude(refresh: bool = False) -> tuple:
    """Locate the Claude CLI even when this session's PATH is stale.

    Returns (absolute_path_or_None, how) with how in "path" | "known-location" |
    "npm-prefix" | "registry" | "". The FIRST candidate, which is the live PATH when
    there is one - existence only, no check that it runs. find_working_claude is the
    one that verifies. Never raises."""
    global _claude_cache
    if _claude_cache is not None and not refresh:
        return _claude_cache
    found = next(_claude_candidates(), (None, ""))
    # A demo run skips the npm-prefix tier, so its answer is narrower than the real
    # one. Caching it would let a one-shot "Demo" from the menu poison every later
    # menu action in the same process with a claude it only "failed" to find because
    # the probe was suppressed.
    if not _demo_active():
        _claude_cache = found
    return found


def find_working_claude(probe) -> tuple:
    """The first candidate that actually RUNS, as (path, how) - (None, "") if none do.

    `probe` takes an argv and returns True when it worked, so the caller owns the
    subprocess policy (timeouts, capture) and this stays testable without launching
    anything.

    Existence is not the test that matters. A package-manager shim survives the removal
    of the binary it points at, so `which` answers, discovery reports a tick, and the
    first real call fails - the shim's own `%~dp0` line reaching a file that is no
    longer there (which is why the failing path in the report carried a doubled
    separator: %~dp0 already ends in one). Walking on to the next candidate turns that
    from a dead end into a different install being used."""
    for path, how in _claude_candidates():
        try:
            if probe(command_argv("claude", resolved=path)):
                return (path, how)
        except Exception:
            continue
    return (None, "")


def _is_file_safe(p: Path) -> bool:
    try:
        return p.is_file()
    except OSError:
        return False


def _find_node() -> Optional[str]:
    """node.exe, surviving the same stale-PATH problem as claude: live PATH first,
    then the standard Program Files install dirs, then a fresh registry PATH read.
    Without this, the policy-safe node launch silently falls back to the blocked
    cmd/APPDATA path exactly on the boxes that need it."""
    hit = shutil.which("node")
    if hit:
        return hit
    if sys.platform != "win32":
        return None
    for env in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
        base = os.environ.get(env)
        if base and _is_file_safe(Path(base) / "nodejs" / "node.exe"):
            return str(Path(base) / "nodejs" / "node.exe")
    for d in _windows_registry_path_dirs():
        p = Path(d) / "node.exe"
        if _is_file_safe(p):
            return str(p)
    return None


def node_launch_for(resolved) -> Optional[list]:
    """A [node.exe, cli.js] argv for an npm-installed claude, or None.

    Corporate group policy (AppLocker/SRP) routinely blocks cmd.exe and any
    executable under user-writable paths like %APPDATA% - which kills both the
    claude.cmd shim AND a claude.exe in the npm package dir ('blocked by group
    policy', seen live 2026-07-30). node.exe lives in Program Files (policy-allowed)
    and cli.js is data, not an executable, so `node cli.js ...` sidesteps the block
    entirely. Windows-only concern: POSIX shims launch fine on their own."""
    p = Path(str(resolved))
    is_shim = p.suffix.lower() in (".cmd", ".bat")
    if not (is_shim or p.suffix.lower() == ".js" or sys.platform == "win32"):
        return None
    pkg = None
    if "node_modules" in p.parts:
        for parent in p.parents:
            if parent.name == "claude-code" and parent.parent.name == "@anthropic-ai":
                pkg = parent
                break
    elif is_shim:
        cand = p.parent / "node_modules" / "@anthropic-ai" / "claude-code"
        try:
            if cand.is_dir():
                pkg = cand
        except OSError:
            pass
    if pkg is None:
        return None
    node = _find_node()
    if not node:
        return None
    for rel in ("cli.js", "bin/cli.js", "bin/claude.js", "bin/claude"):
        cli = pkg / rel
        if _is_file_safe(cli):
            return [node, str(cli)]
    return None


def command_argv(name: str, resolved: Optional[str] = None) -> list:
    """The argv prefix that identifies how to launch `name` on this platform.

    Windows npm shims are `.cmd`/`.bat` batch files: `shutil.which` finds them but
    CreateProcess cannot launch a batch file by bare name without a shell, so those
    return a `cmd /c` prefix - which run_cmd converts to the safe /s string form
    (windows_shim_cmdline) before launching. Everywhere else (and for real
    executables) the resolved absolute path is used directly. `claude` gets the
    find_claude fallback so a stale corporate PATH still launches it by full path."""
    if resolved is None:
        if name == "claude" and _claude_verified:
            # A candidate the preflight actually RAN beats whatever `which` answers.
            # Without this, a broken shim on PATH keeps winning even after a working
            # install has been found further down the list (2026-08-28).
            resolved = _claude_verified
        else:
            resolved = shutil.which(name)
            if resolved is None and name == "claude":
                resolved = find_claude()[0]
        resolved = resolved or name
    if name == "claude" or str(resolved).lower().endswith((".cmd", ".bat", ".js")):
        # Prefer node + cli.js for npm layouts: no cmd.exe, no executable under
        # %APPDATA% - the two things corporate group policy blocks (2026-07-30).
        via_node = node_launch_for(resolved)
        if via_node:
            return via_node
    if str(resolved).lower().endswith((".cmd", ".bat")):
        return ["cmd", "/c", str(resolved)]
    return [str(resolved)]


def windows_shim_cmdline(shim_path: str, rest) -> str:
    """The full cmd.exe command line for a .cmd/.bat shim, safe for spaces anywhere.

    The naive list form ["cmd", "/c", shim, *args] breaks when two or more arguments
    need quoting: cmd /c re-parses its tail and strips the FIRST and LAST quote
    character on the line, mangling a shim path with spaces (e.g. a username with a
    space) combined with a quoted repo path. `/s` plus one outer quote pair pins the
    parse (documented in `cmd /?`); the inner line is built by list2cmdline, the same
    quoting CreateProcess itself uses."""
    inner = subprocess.list2cmdline([str(shim_path)] + [str(a) for a in rest])
    return f'cmd.exe /s /c "{inner}"'


def run_cmd(argv, cwd: Optional[Path] = None, timeout: int = 300):
    """Fixed-argv runner, output captured. Tests monkeypatch this symbol; --demo swaps
    it for make_demo_runner's dry-run stand-in for the duration of the run.

    The first element is resolved via command_argv; Windows `.cmd`/`.bat` shims (the
    npm-installed `claude`) launch via the quoted cmd.exe string form so paths with
    spaces survive.

    Output decodes as UTF-8 with replacement, never the console codepage: git and
    claude emit UTF-8, and plain text=True on Windows decodes with cp1252 whose
    undefined bytes (0x81/0x8d/...) raise UnicodeDecodeError inside subprocess's
    reader thread ('Exception in Thread-N', seen live on a corporate box, 2026-07-30).
    errors='replace' makes the decode total: worst case is a mangled character in a
    log line, never a crash. Path arguments (e.g. `["git", "-C", repo, ...]`) normalize
    via .as_posix() rather than native str() - git accepts forward slashes on every
    platform, and a bare str(WindowsPath) renders backslashes that several call sites'
    own tests assert against in posix form."""
    argv = [a.as_posix() if isinstance(a, Path) else str(a) for a in argv]
    prefix = command_argv(argv[0])
    decode = {"encoding": "utf-8", "errors": "replace"}
    # NOTHING WE SPAWN READS THE TERMINAL. capture_output routes stdout and stderr away
    # but leaves stdin attached, and git asks for credentials on /dev/tty regardless of
    # stdin - turning echo OFF to read a password. With our output captured, the prompt is
    # invisible: the user sees a terminal that has stopped echoing and no reason why. Live
    # report, 2026-08-29: "when I exit virt-surv I can't type in that same terminal, the
    # letters I type don't echo at the prompt."
    #
    # Both halves are needed. DEVNULL stops a child consuming keystrokes meant for the
    # shell; GIT_TERMINAL_PROMPT=0 stops git going around stdin to the tty and is what
    # actually fixes the echo. A credential prompt nobody can see is never useful - failing
    # fast turns a silent hang into an error message.
    env = dict(os.environ)
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    env.setdefault("GIT_ASKPASS", "")
    env.setdefault("SSH_ASKPASS", "")
    quiet_stdin = {"stdin": subprocess.DEVNULL, "env": env}
    if prefix[0] == "cmd":
        # Batch shim: one explicit string, shell=False. This branch is unreachable on
        # POSIX (which() never resolves a bare name to *.cmd/*.bat there).
        return subprocess.run(  # fixed command line built above, shell=False  # nosec B603
            windows_shim_cmdline(prefix[-1], argv[1:]),
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            timeout=timeout,
            **quiet_stdin,
            **decode,
        )
    return subprocess.run(  # argv is a fixed list built here, shell=False  # nosec B603
        prefix + argv[1:],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        timeout=timeout,
        **quiet_stdin,
        **decode,
    )


# ------------------------------------------------------------------ demo dry-run layer


def demo_stdout(argv) -> str:
    """Canned stdout per command shape, so the real step logic behaves in a dry run:
    clean working tree, zero commits ahead, a few commits behind (so the update
    preview shows), reachable remote, a placeholder commit and remote files."""
    argv = [str(a) for a in argv]
    if "rev-parse" in argv:
        return "abc1234"
    if "rev-list" in argv:
        # HEAD..origin/x = commits behind (plausible preview); origin/x..HEAD = ahead.
        return "3" if str(argv[-1]).startswith("HEAD..") else "0"
    if "ls-remote" in argv:
        return "ref"
    if "show" in argv:
        target = str(argv[-1])
        if target.endswith("plugin.json"):
            return '{"version": "9.9.9"}'
        if target.endswith("CHANGELOG.md"):
            return (
                "# Changelog\n\n"
                "## [9.9.9] - 2026-01-02 - Demo release\n\n"
                "## [9.9.8] - 2026-01-01 - Earlier demo release\n"
            )
        return ""
    # Includes `git status --porcelain`: empty output means a clean tree.
    return ""


def make_demo_runner(style: Style):
    """A run_cmd stand-in for --demo: prints the exact argv, executes nothing.

    Returns a successful CompletedProcess carrying demo_stdout's canned output; no
    subprocess is spawned and returncode is always 0."""

    def runner(argv, cwd: Optional[Path] = None, timeout: int = 300):
        argv = [str(a) for a in argv]
        print(style.dim("    would run: " + " ".join(argv)))
        return subprocess.CompletedProcess(argv, 0, stdout=demo_stdout(argv), stderr="")

    # Marks this as the dry-run stand-in so helpers that would otherwise probe the
    # system with their own subprocess (_claude_via_npm_prefix) can tell demo mode is
    # active. Checking the installed runner beats a separate module flag: main() swaps
    # run_cmd at three sites, and a flag would have to be set and restored at each -
    # one missed site and "--demo spawns nothing" silently stops being true.
    runner.is_demo = True
    return runner


# ------------------------------------------------------------------ pure git helpers


def validate_branch(branch: str) -> str:
    if branch not in BRANCHES:
        raise ValueError(f"branch must be one of {'/'.join(BRANCHES)}, not {branch!r}")
    return branch


def is_dirty(repo: Path, runner=None) -> bool:
    """True when `git status --porcelain` reports anything (staged, unstaged or untracked)."""
    runner = runner or run_cmd
    proc = runner(["git", "-C", repo.as_posix(), "status", "--porcelain"])
    if proc.returncode != 0:
        raise InstallAbort(f"git status failed in {repo}: {proc.stderr.strip()}")
    return bool(proc.stdout.strip())


def commits_ahead(repo: Path, branch: str, runner=None) -> int:
    """Local commits on HEAD that origin/<branch> does not have (0 on any lookup failure)."""
    runner = runner or run_cmd
    proc = runner(["git", "-C", repo.as_posix(), "rev-list", "--count", f"origin/{branch}..HEAD"])
    if proc.returncode != 0:
        return 0
    try:
        return int(proc.stdout.strip())
    except ValueError:
        return 0


def looks_like_repo(path: Path) -> bool:
    """.git may be a directory (normal clone) or a FILE (git worktree) - .exists()
    covers both. A bare repo has neither a .git child nor the manifest, so it is
    correctly rejected."""
    return (path / ".git").exists() and (path / ".claude-plugin" / "plugin.json").exists()


def gather_update_preview(repo: Path, branch: str, local_version: Optional[str], runner=None):
    """Read-only look at what origin/<branch> would bring, AFTER a fetch.

    Informational and total: every probe fails soft (error rc, garbage output, a
    raising runner - shallow clones and detached HEADs included) into None/[] plus a
    human note. It must never raise and never block the update itself."""
    runner = runner or run_cmd

    def probe(argv):
        try:
            proc = runner(argv)
        except (subprocess.TimeoutExpired, OSError):
            return None
        return proc if proc is not None and proc.returncode == 0 else None

    info = {"behind": None, "remote_version": None, "headlines": [], "notes": []}
    proc = probe(["git", "-C", repo.as_posix(), "rev-list", "--count", f"HEAD..origin/{branch}"])
    if proc is not None:
        try:
            info["behind"] = int(proc.stdout.strip())
        except (ValueError, TypeError, AttributeError):
            pass
    if info["behind"] is None:
        info["notes"].append("could not count new commits (shallow clone or detached HEAD?)")
    proc = probe(
        ["git", "-C", repo.as_posix(), "show", f"origin/{branch}:.claude-plugin/plugin.json"]
    )
    if proc is not None:
        info["remote_version"] = parse_manifest_version(proc.stdout)
    if info["remote_version"] is None:
        info["notes"].append("could not read the remote manifest")
    proc = probe(["git", "-C", repo.as_posix(), "show", f"origin/{branch}:CHANGELOG.md"])
    if proc is not None and str(proc.stdout or "").strip():
        info["headlines"] = list_headlines_between(proc.stdout, local_version)
    else:
        info["notes"].append("could not read the remote changelog")
    return info


def check_for_update_upfront(cfg: dict, style: Style, args) -> None:
    """A quick glance at whether a newer version is on origin, shown right after the
    banner and before the menu - so "there's an update" is visible no matter which
    option the user ends up picking (previously it only surfaced deep inside a full
    run's sync step, or the dedicated "check for updates" option - invisible to anyone
    who picked statusline/enable/preferences/etc). Silent, not just soft-failing, on
    anything short of "a newer version exists": no clone yet (first install - nothing
    to compare), unreachable network, or already up to date all print nothing, so a
    routine run stays exactly as quiet as before. A short fetch timeout keeps a slow or
    dead network from delaying the menu itself."""
    if args.repo:
        repo = Path(args.repo).expanduser().resolve()
    else:
        configured = cfg.get("repo_path")
        script_root = Path(__file__).resolve().parent
        if isinstance(configured, str) and configured and looks_like_repo(Path(configured)):
            repo = Path(configured)
        elif looks_like_repo(script_root):
            repo = script_root
        else:
            return  # no clone yet - nothing to compare on a first install
    if not looks_like_repo(repo):
        return
    branch = cfg.get("branch")
    branch = branch if branch in BRANCHES else "dev"
    try:
        proc = run_cmd(["git", "-C", repo.as_posix(), "fetch", "origin", branch], timeout=8)
    except (subprocess.TimeoutExpired, OSError):
        return
    if proc is None or proc.returncode != 0:
        return
    local_version = installed_version(repo)
    preview = gather_update_preview(repo, branch, local_version)
    remote = preview.get("remote_version")
    if not remote or not local_version or remote == local_version:
        return
    # PROBED, like every other non-ASCII glyph in this file (marks(), box_chars(), the
    # hat). This one was not, and it prints from check_for_update_upfront - before the
    # menu, guarded by nothing but `except KeyboardInterrupt`. On a cp1252 console with
    # an update waiting, `virt-surv` tracebacked instead of drawing a menu, and the more
    # up to date the user kept the plugin the more often they hit it.
    box = "📦 " if _can_encode("📦", sys.stdout) else ""
    print(style.yellow(f"{box}A newer version is available: {local_version} -> {remote}"))
    headline = (preview.get("headlines") or [None])[0]
    if headline:
        print(f"   {headline}")
    # Derived from MENU_ACTIONS, not typed out. It read "Diagnostics (5)" while Diagnostics
    # was option 3 (found 2026-08-25) - a number in prose is a number that goes stale the
    # first time the menu is reordered, and nothing tells you.
    _diag = next((k for k, v in MENU_ACTIONS.items() if v == "diagnostics"), "3")
    _upd = next((k for k, v in MENU_ACTIONS.items() if v == "update"), "u")
    print(
        style.dim(
            f"   Pick option {_upd} for a quick update (new code + plugin, keeps your "
            f"settings), or Diagnostics ({_diag}) -> 1 to preview first."
        )
    )
    print("")


def decide_mode(explicit: Optional[str], cfg: dict) -> str:
    """install | update. Explicit wins; else update when the configured clone still exists."""
    if explicit:
        return explicit
    repo = cfg.get("repo_path")
    if repo and looks_like_repo(Path(repo)):
        return "update"
    return "install"


# ------------------------------------------------------------------ prompts


def ask(prompt: str, default: str, assume_yes: bool, style: Optional[Style] = None) -> str:
    """One-line prompt with a default; --yes or a closed stdin takes the default."""
    if assume_yes or not sys.stdin.isatty():
        return default
    s = style or Style(False)
    try:
        answer = input(f"{s.cyan(prompt)} {s.bold('[' + default + ']')}: ").strip()
    except EOFError:
        return default
    return answer or default


def confirm(prompt: str, default: bool, assume_yes: bool, style: Optional[Style] = None) -> bool:
    if assume_yes or not sys.stdin.isatty():
        return default
    s = style or Style(False)
    hint = "Y/n" if default else "y/N"
    try:
        answer = input(f"{s.cyan(prompt)} {s.bold('[' + hint + ']')}: ").strip().lower()
    except EOFError:
        return default
    if not answer:
        return default
    return answer in ("y", "yes")


# ------------------------------------------------------------------ interactive menu


# 2026-08-17 restructure (user requests): "Manage engagements" retired from the menu
# (its jobs live on as the folder subcommands - virt-surv list-engagements / archive -
# and run_manage_engagements stays for them); the alias item moved under Advanced as a
# two-option manager (register/update, or change the 'go' launch command).
def _menu_key_hint() -> str:
    """The valid keys, read from MENU_ACTIONS so the hint cannot fall behind the menu."""
    keys = list(MENU_ACTIONS)
    digits = [k for k in keys if k.isdigit()]
    letters = [k for k in keys if not k.isdigit()]
    span = f"{digits[0]}-{digits[-1]}" if len(digits) > 1 else "".join(digits)
    return ", ".join(x for x in [span] + letters if x)


MENU_ACTIONS = {
    "1": "full",
    "2": "configure",
    "3": "diagnostics",
    "4": "advanced",
    "5": "howto",
    # 2026-08-25: updating used to mean option 1 - the whole 13-step install, pip and all,
    # re-asking every question the human had already answered. That is a reason not to
    # update, which is the worst thing a plugin's update path can be.
    #
    # A LETTER, not a number, and not for looks. Inserting it as "2" shifted every option
    # below it, and the scripted menu tests immediately began selecting different actions
    # than they meant to - one landing on this very update step and running live git
    # operations until the suite hung. Renumbering a menu silently re-points every stored
    # keystroke: in tests, in documentation, and in muscle memory.
    "u": "update",
    "q": "quit",
}

# Submenus (2026-08-04 reorganisation - the top-level menu had grown to 10 flat numbered
# options and felt clunky; diagnostics/one-off settings now live one level down).
_DIAGNOSTICS_ACTIONS = {
    "1": "check",
    "2": "toolcheck",
    "3": "envcheck",
    "4": "selftest",
    "5": "hooklatency",
    "6": "adr014smoke",
    "7": "daemonstart",
    "b": "back",
}
_ADVANCED_ACTIONS = {
    "1": "setup",
    "2": "statusline",
    "3": "formats",
    "4": "model",
    "5": "demo",
    "6": "machinedefaults",
    "7": "dashboard",
    "8": "fixbashrc",
    "9": "cleanplugincache",
    "10": "aliasmanage",
    "11": "gitbashperf",
    "12": "codeintel",
    "13": "extensions",
    "14": "reprobe",
    "15": "relocate",
    "b": "back",
}


def app_tier_available() -> bool:
    """Whether a full-screen screen can actually run here.

    Asked by BOTH the banner (to decide whether to print) and the menus (to decide which
    tier to draw), so the two cannot disagree and leave a run with no banner at all."""
    if os.environ.get("VIRT_SURV_NO_APP"):
        return False
    if not os.environ.get("VIRT_SURV_FORCE_PTK"):
        try:
            if not (sys.stdin.isatty() and sys.stderr.isatty()):
                return False
        except Exception:
            return False
    module = _import_from_scripts("installer_app")
    if module is None:
        return False
    try:
        module._vendor_on_path()
        import prompt_toolkit  # noqa: F401

        return True
    except Exception:
        return False


class _PlainQuestions:
    """The framework's promise - always an answer, never a crash - when scripts/ is not
    there to keep it.

    install_helper is routinely run as a single downloaded file from a temp directory,
    before any clone exists. That is rare and it is not nothing: without this, `_ask()`
    would raise and the caller would be back to writing its own fallback, which is the
    duplication the framework removed. One fallback, in one place.
    """

    class _Answer:
        # No __bool__ here either. A stand-in that is MORE permissive than the real thing
        # is worse than no stand-in: code would work on the box without scripts/ and fail
        # on every other one.
        def __init__(self, value, cancelled):
            self.value, self.cancelled = value, cancelled

    def choose(self, title, options, **_kw):
        print("")
        print(f"  {title}")
        for number, row in enumerate(options, 1):
            print(f"    [{number}] {row[1]}")
        print("    [b] back")
        try:
            raw = input("    Choice: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return self._Answer(None, True)
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return self._Answer(options[int(raw) - 1][0], False)
        return self._Answer(None, True)

    def confirm(self, title, yes, no, **_kw):
        # Present for PARITY, not for completeness' sake: a stand-in that offers less than
        # the real module means code that works on a box without scripts/ and breaks on
        # every other one, which is the worst way round for a fallback to be wrong.
        return self.choose(title, [(True, yes, ""), (False, no, "")])


def _ask():
    """The questions framework, or the plain stand-in above. Never raises.

    An accessor rather than a top-level import because install_helper is routinely run as
    a single downloaded file from a temp directory where `scripts/` does not exist yet -
    the same reason every other scripts/ import here is resolved late.
    """
    return _import_from_scripts("questions") or _PlainQuestions()


def _submenu_screen(style: Style, title: str, options: tuple, actions: dict):
    """The full-screen tier of _choose_submenu, or None when it cannot run.

    Isolated behind a bare `except Exception` on purpose: this is presentation, and the
    installer has to keep working on a box where prompt_toolkit will not start - which is
    the same box that most needs the installer to work."""
    if os.environ.get("VIRT_SURV_NO_APP"):
        return None  # documented escape hatch, and what the numbered-tier tests use
    # Textual first, prompt_toolkit underneath, numbered menu below that. None from a
    # tier means "it could not draw", so each falls through to the next; "" is a real
    # answer (Esc/back) and stops here.
    for _tier in ("launcher_textual", "installer_app"):
        try:
            module = _import_from_scripts(_tier)
            if module is None:
                continue
            picked = module.chooser_screen(
                options,
                _this_module(),
                title=title,
                # The caller's OWN table, never guessed: the same key means different
                # things in different menus, and guessing showed the wrong consequence
                # for the most prominent option on the most-seen screen (2026-08-28).
                actions=actions,
                repo=_repo_hint(),
            )
            if picked is not None:
                return picked
        except Exception:
            continue
    return None


# Subsets that may run inside a progress screen, and the title each one wears there.
#
# MEMBERSHIP IS A JUDGEMENT ABOUT QUESTIONS, not about tidiness. A subset here must ask
# the human nothing once it starts: a worker thread cannot prompt while a full-screen app
# owns the keyboard, so a subset that asks would hang against a screen that can never show
# the prompt. `update` is absent because it asks two questions, and answers them on a
# decision screen in front instead (run_update_in_app).
#
# The diagnostics are absent for a different reason and deliberately still stream: their
# OUTPUT is the deliverable, meant to be read and scrolled back through, and a bounded
# pane would hide the thing someone opened them for.
_IN_APP_SUBSETS = {
    # One step, a soft probe, and it asks nothing - it reports "already available" and
    # moves on rather than prompting for anything.
    "codeintel": "Code intelligence",
    # Two steps, and no prompt is reachable from either. Established by walking the call
    # graph out of each step rather than by reading the step itself: fixbashrc and
    # cleanplugincache both LOOK quiet and both ask, one and two calls down, and a wrong
    # answer here does not degrade - it hangs, against a screen that can never show the
    # prompt (2026-08-30).
    "dashboard": "Rebuilding the team dashboard",
}


def run_subset_in_app(args, style: Style, subset: str, title: str) -> "Optional[int]":
    """One Installer subset, rendered as a live progress screen instead of a scrolling log.

    Returns the exit code, or None when the screen could not run and the caller should
    stream as it always has.

    ONLY FOR SUBSETS THAT ASK NOTHING, and that is a hard constraint rather than a
    preference: a question cannot be asked from a worker thread while a full-screen app
    owns the keyboard, so a subset that prompts mid-run would hang against a screen that
    can never show the prompt. The update solves this by moving its two questions to a
    decision screen in front (run_update_in_app); anything routed here must simply have
    none. The allow-list at the call site is where that judgement is recorded.

    Nor is it for every quiet subset. The diagnostics deliberately still stream: their
    output is the deliverable, meant to be read and scrolled back through, and a bounded
    pane would hide the very thing someone opened them for.
    """
    if _import_from_scripts("installer_app") is None:
        return None
    try:
        probe = Installer(args, style, marks(), subset=subset)
        titles = [(name() if callable(name) else name) for name, _step in probe.build_plan()]
    except Exception:
        return None
    if not titles:
        return None

    def _run(observer):
        inst = Installer(copy.copy(args), style, marks(), subset=subset)
        inst.observer = observer
        return inst.run()

    return _tiered_installer_screen(
        "progress_screen",
        titles,
        _run,
        _this_module(),
        title=title,
        repo=_repo_hint(),
    )


def run_update_in_app(args, style: Style) -> "Optional[int]":
    """The update, rendered as a live progress screen instead of a scrolling log.

    Returns the exit code, or None when the screen could not run and the caller should
    fall back to the streaming Installer it has always used.

    THE FLOW IS DELIBERATELY REORDERED. sync_branch asks two questions mid-run - "shall I
    bring you up to date?" after showing a preview, and "shall I stash them?" on a dirty
    tree - and a question cannot be asked from a worker thread while a full-screen app
    owns the keyboard. Rather than fight that, the decisions move to the FRONT: the
    preview is gathered and shown first, the human answers once, and then the run has
    nothing left to ask. Deciding up front and then watching is a better shape anyway
    than being interrupted twice by a log.

    assume_yes is set for the run itself, which is honest here precisely because the
    questions it would have asked have already been put to the human on the screen above.
    """
    installer_app = _import_from_scripts("installer_app")
    if installer_app is None:
        return None
    probe = Installer(args, style, marks(), subset="update")
    try:
        titles = [(title() if callable(title) else title) for title, _step in probe.build_plan()]
    except Exception:
        return None

    decision = _tiered_installer_screen("update_decision_screen", _this_module(), repo=_repo_hint())
    if decision is None:
        return None  # screen unavailable - the caller streams instead
    if decision == "cancel":
        return 0

    def _run(observer):
        run_args = copy.copy(args)
        run_args.yes = True  # every question it would ask was answered on the screen above
        inst = Installer(run_args, style, marks(), subset="update")
        inst.observer = observer
        return inst.run()

    return _tiered_installer_screen(
        "progress_screen",
        titles,
        _run,
        _this_module(),
        title="Updating the team",
        repo=_repo_hint(),
    )


def _tiered_installer_screen(name: str, *args, **kwargs):
    """Call `name` on the best tier that can draw it: Textual, then prompt_toolkit.

    Same rule as the launcher's _tiered_screen and for the same reason: None means a tier
    could not draw, so the next is tried; anything else is that screen's real answer.
    """
    for module_name in ("launcher_textual", "installer_app"):
        module = _import_from_scripts(module_name)
        if module is None:
            continue
        screen = getattr(module, name, None)
        if screen is None:
            continue
        before = getattr(module, "APPS_RUN", None)
        try:
            answer = screen(*args, **kwargs)
        except Exception:
            continue  # a tier that raises is a tier that cannot draw
        if answer is not None:
            return answer
        # It drew and still said None: there is nothing below a screen that ran, and
        # opening the older renderer over it is what the owner reported on 2026-08-31.
        after = getattr(module, "APPS_RUN", None)
        if before is not None and after is not None and after != before:
            return None
    return None


# The real clone, for the many callers that have no `args` to hand. Set once by _main.
_REPO_HINT: Optional[str] = None


def _real_clone() -> Optional[str]:
    """Where the real clone is, or None - WITHOUT trusting __file__.

    _relocate_if_running_inside_target_repo copies this file to a bare temp directory and
    re-execs from there for the rest of the session, so that `git checkout` can overwrite
    the original safely. It already passes the real clone through as `--repo` precisely so
    later code does not have to trust __file__ - but only callers holding `args` were
    reading it, and _import_from_scripts holds nothing.

    The consequence was silent and total: in a relocated session _resolve_repo_root(None)
    fell through to __file__'s parent (a temp dir with one .py file in it) and returned
    None, so EVERY scripts/ module was unreachable and every tiered screen degraded to a
    numbered prompt. Not just the new ones - launcher_textual and installer_app too, and
    for as long as the tiers have existed. It hid because installer.json's `repo_path`
    covers it, and that key is written by any completed Installer run, so a machine that
    has ever finished one never sees it (measured on a dev clone whose runs always abort
    on the dirty tree, 2026-08-30).

    argv is read as the fallback rather than the primary source because a caller running
    before _main has parsed anything still needs an answer, and the flag is right there.
    """
    if _REPO_HINT:
        return _REPO_HINT
    argv = sys.argv[1:]
    for index, token in enumerate(argv):
        if token == "--repo" and index + 1 < len(argv):
            return argv[index + 1]
        if token.startswith("--repo="):
            return token.split("=", 1)[1]
    return None


def _import_from_scripts(name: str):
    """Import a module out of the real clone's scripts/ directory, or None.

    EXPLICIT, not a bare `import name` inside a try. This helper sits at the clone root
    and scripts/ is a sibling, so a bare import raises ImportError - which the caller's
    `except Exception` would swallow, leaving the feature permanently and silently off.

    AND NOT FROM __file__, which is the mistake that made this whole tier invisible.
    _relocate_if_running_inside_target_repo copies this file to a bare temp directory and
    re-execs from there for the REST of the session, so that git checkout can overwrite
    the original safely. From that point `Path(__file__).parent` is
    /tmp/virt-surv-it-installer-XXXX, which contains one .py file and no scripts/ sibling.
    Every candidate missed, this returned None, and the new screens silently never ran
    on any real installation - only in a checkout being developed in place (found by
    instrumenting the actual container, 2026-08-28, after two wrong guesses).

    _resolve_repo_root already documents this hazard in its own docstring and already
    handles it: the re-exec passes the real clone through as --repo precisely so callers
    do not have to trust __file__ afterwards. Asking it is the whole fix."""
    import importlib

    roots = []
    try:
        # The hint first, then installer.json's repo_path, then __file__ - see
        # _real_clone() for why passing None here was silently fatal in a relocated run.
        resolved = _resolve_repo_root(_real_clone())
        if resolved:
            roots.append(resolved / "scripts")
    except Exception:
        pass  # config unreadable - the __file__ candidates below still cover a dev run
    here = Path(__file__).resolve().parent
    roots += [here / "scripts", here, here.parent / "scripts"]
    for candidate in roots:
        if (candidate / f"{name}.py").is_file():
            if str(candidate) not in sys.path:
                sys.path.insert(0, str(candidate))
            try:
                return importlib.import_module(name)
            except Exception:
                return None
    return None


def _this_module():
    """This module, however it was loaded - run as __main__, imported, or neither."""
    return sys.modules.get(__name__) or sys.modules.get("__main__")


def _repo_hint():
    """The clone, for the frame title's version. None is fine.

    Asks _real_clone() first. It used to read installer.json alone, which meant that in a
    relocated session on a machine with no `repo_path` written yet, these screens lost
    their version line for exactly the reason _import_from_scripts lost the whole tier -
    one blind spot, two symptoms, so it is fixed in one place (2026-08-30)."""
    try:
        hint = _real_clone()
        if hint:
            return Path(hint)
        configured = load_config(config_path()).get("repo_path")
        return Path(configured) if isinstance(configured, str) and configured else None
    except Exception:
        return None


def _choose_submenu(style: Style, title: str, options: tuple, actions: dict) -> Optional[str]:
    """Shared submenu loop: prints options, returns the resolved action string, or None
    if the user chose 'back' (caller should redraw the top-level menu). A row with an
    empty-string key (`("", "some label")`) renders as a plain dim divider line instead
    of a numbered choice - never added to `actions`, never selectable - for grouping
    unrelated option classes within one submenu (2026-08-12 onboarding UX audit:
    Diagnostics mixed everyday checks with internal/prototype items with no visual
    separation)."""
    s = style
    # Full-screen picker first, numbered list wherever it cannot run (2026-08-28). Same
    # `options`/`actions` tables underneath, so the two tiers cannot disagree about what
    # a key does - the pattern `virt-surv go` has used since 2026-08-20, and the reason
    # its two menu tiers stopped drifting.
    #
    # None means the SCREEN could not run and the list below takes over; "" means the
    # user chose back, which is a decision and must not be retried as a fallback.
    picked = _submenu_screen(style, title, options, actions)
    if picked is not None:
        if not picked or actions.get(picked) == "back":
            return None
        return actions.get(picked)
    print("")
    print(s.bold(title))
    for key, text in options:
        if key == "":
            print(f"  {s.dim(text)}")
        else:
            print(f"  {s.cyan(key + ')')} {text}")
    while True:
        try:
            answer = input(f"{s.cyan('  Which one?')} {s.bold('[b]')}: ").strip().lower()
        except EOFError:
            return None
        if not answer or answer == "b":
            return None
        if answer in actions:
            resolved = actions[answer]
            return None if resolved == "back" else resolved
        # len(actions), not len(options): options may include non-selectable divider
        # rows (empty-string key), which actions never does - actions is the
        # authoritative set of real choices, options is only what gets printed.
        print(f"  1-{len(actions) - 1} or b, please.")


def choose_action(style: Style) -> str:
    """The interactive front door: pick which subset to run. Callers gate on a tty;
    a closed stdin or empty answer takes the full run. 'diagnostics'/'advanced' open a
    submenu and loop back to this top-level menu on 'back' rather than returning
    directly - the caller only ever sees a final, concrete action."""
    s = style
    while True:
        options = (
            # NOT "update" (2026-08-29). Both this and [u] said it, and this one said it
            # first and louder, so someone wanting to update reasonably picked the 14-step
            # interactive run and met "which channel shall I track for you?" - a question
            # the quick update deliberately never asks. The word now appears once, on the
            # option that actually means it.
            ("1", "Install or reconfigure the team (full run - asks everything)"),
            ("2", "Configure a project (per project - enable/permissions/preferences/model)"),
            ("3", "Diagnostics..."),
            ("4", "Advanced / one-off settings..."),
            ("5", "Help: using the plugin (Morgan explains)"),
            ("u", "Update only (quick - new code + plugin, keeps every setting)"),
            ("q", "Quit"),
        )
        # THE TOP-LEVEL MENU GOES THROUGH THE PICKER TOO (2026-08-28). The submenus were
        # wired to it first, which left the one screen everybody sees on every run - the
        # first impression of the whole product - exactly as it was. The change was
        # invisible unless you went three levels deep. Owner report: "the menu system
        # still feels ugly", and it was right.
        #
        # It only supplies the ANSWER. Everything below - the diagnostics and advanced
        # submenus, looping back on "back" - is the code that was already here, so the two
        # tiers cannot disagree about what a key does.
        picked = _submenu_screen(style, "What can I do for you?", options, MENU_ACTIONS)
        if picked is not None:
            # Esc means quit, not "full run". Blank-is-a-full-install is a fine default
            # for a typed prompt, where the keypress is deliberate. It is a bad one for a
            # full-screen app, where Esc is how people leave a screen - and would start a
            # thirteen-step install for someone trying to back out of one.
            if not picked:
                return "quit"
            answer = picked
        else:
            # This tier has no frame, so it owns the banner - and prints it only if the
            # app tier was expected to and then could not, which is the one path where
            # nobody has shown it yet.
            if not banner_already_shown():
                print_banner(style)
            # The heading belongs to THIS tier only. Printed before the tier is chosen, it
            # landed in the scrollback above a full-screen app that then covered it, and
            # was left behind as debris when the app exited - the picker's own frame title
            # already says what screen you are on.
            print("")
            print(s.bold("What can I do for you?"))
            for key, text in options:
                print(f"  {s.cyan(key + ')')} {text}")
            # Redraws the menu on entering/re-entering this loop (fresh session, or back
            # from a submenu) but NOT on a simple invalid keystroke - an inner retry loop
            # just re-asks (2026-08-04 user request: "don't reprint entire menu, just the
            # item that the user is on"), matching how _choose_submenu already behaved.
            while True:
                try:
                    answer = (
                        input(f"{s.cyan('  What shall it be?')} {s.bold('[1]')}: ").strip().lower()
                    )
                except EOFError:
                    return "full"
                if not answer:
                    return "full"
                if answer in MENU_ACTIONS:
                    break
                # Derived, not typed out: "u" (update) is a real key and was missing from
                # this line, so the one option a user most needs to find was named nowhere.
                print(f"  {_menu_key_hint()}, please.")
        action = MENU_ACTIONS[answer]
        if action == "diagnostics":
            resolved = _choose_submenu(
                style,
                "Diagnostics",
                (
                    ("1", "Check for updates (read-only)"),
                    ("2", "Quick: analyser output cleanliness only"),
                    ("3", "Comprehensive: the full environment + synthetic-engagement report"),
                    ("4", "Self-test only: just the synthetic engagement"),
                    ("", "-- internal / prototype diagnostics --"),
                    (
                        "5",
                        "Hook latency: feeds the ADR-014 daemon decision (slower - repeated + concurrent)",
                    ),
                    ("6", "ADR-014 spike smoke test (PROTOTYPE - starts a real daemon process)"),
                    (
                        "7",
                        "Guard daemon start diagnostic (starts the REAL daemon - why isn't it starting)",
                    ),
                    ("b", "Back"),
                ),
                _DIAGNOSTICS_ACTIONS,
            )
        elif action == "advanced":
            resolved = _choose_submenu(
                style,
                "Advanced / one-off settings",
                (
                    ("1", "Environment setup only (this machine - no code pull)"),
                    ("2", "Status line (this machine - shown in every project)"),
                    ("3", "Project preferences (docx, citations, review tools)"),
                    ("4", "Morgan's model (per project only)"),
                    ("5", "Demo - watch the whole run, nothing executed or written"),
                    (
                        "6",
                        "This machine's defaults (view/edit - no project needed)",
                    ),
                    ("7", "Rebuild the local team dashboard"),
                    ("8", "Fix a slow ~/.bashrc (checks first, applies only if needed)"),
                    ("9", "Clean stale plugin cache (removes old installs, keeps the active one)"),
                    (
                        "10",
                        "Manage the 'virt-surv' alias (register/update it, or change the 'go' launch command)",
                    ),
                    (
                        "11",
                        "Git Bash performance fix (Claude Code shell-snapshot slowness on Windows)",
                    ),
                    (
                        "12",
                        "Code intelligence (install/refresh tree-sitter - sharper codebase "
                        "orientation; optional, degrades to pattern matching without it)",
                    ),
                    (
                        "13",
                        "Org extensions (review/edit the standard workflow this machine "
                        "applies to every project - analysers, close actions, instructions)",
                    ),
                    (
                        "14",
                        "Re-probe installed tools (run after installing an analyser or "
                        "tree-sitter, so the team stops reporting it missing)",
                    ),
                    (
                        "15",
                        "Move team files into VSIT/ (one folder instead of scattered across "
                        "your docs/ and repo root - shows you the plan before moving anything)",
                    ),
                    ("b", "Back"),
                ),
                _ADVANCED_ACTIONS,
            )
        else:
            return action
        if resolved is not None:
            return resolved
        # 'back' was chosen - loop and redraw the top-level menu.


# ------------------------------------------------------------------ the installer


class Installer:
    """Runs a plan of steps. subset picks the plan: 'full' (default), 'setup'
    (environment only, clone used as-is), 'statusline', or 'enable'."""

    def __init__(self, args, style: Style, mark_map: dict, subset: str = "full"):
        self.args = args
        self.style = style
        self.marks = mark_map
        self.subset = subset
        self.demo = bool(getattr(args, "demo", False))
        self.tracker = StepTracker()
        self.cfg_path = config_path()
        self.cfg = load_config(self.cfg_path)
        self.repo: Optional[Path] = None
        self.branch = "dev"
        self.mode = "install"
        self.stashed = False
        self.code_stale = False  # user declined the update: clone used as-is
        # 2026-08-07 user request: an upfront "go with defaults vs manually configure"
        # choice for the optional post-install steps (pip, status line, alias, machine
        # settings) - set by quick_setup_choice(), read by each of those steps. Defaults
        # to False (ask individually) so a step reached WITHOUT quick_setup_choice ever
        # running (a subset other than "full") keeps its own original per-step question.
        self.quick_defaults = False
        # Set to swap this run's output for structured callbacks - see say() and
        # step_header(). None keeps the streaming behaviour every existing caller has.
        self.observer = None

    # ---- console helpers

    def say(self, text: str = "") -> None:
        # An observer TAKES the output rather than echoing it: a full-screen progress view
        # owns the terminal, and a stray print would tear its frame. Every line the
        # installer emits goes through here, which is why this one method is the whole
        # hook (2026-08-29 - "when doing an update we drop out of the new interface").
        if self.observer is not None:
            self.observer.line(text)
            return
        print(text)

    def step_header(self, number: int, total: int, title: str) -> None:
        if self.observer is not None:
            self.observer.step(number, total, title)
            return
        self.say("")
        self.say(rule_header(number, total, title, self.style))

    def step_ok(self, name: str, detail: str = "") -> None:
        self.tracker.record(name, "ok", detail)
        if self.observer is not None:
            # The observer gets the RESULT, not the rendered line: a screen draws its own
            # row from the status, and echoing the line as well would report the same fact
            # twice in two places that can disagree.
            self.observer.result(name, "ok", detail)
            return
        suffix = f" {self.style.dim('(' + detail + ')')}" if detail else ""
        self.say(f"  {self.style.green(self.marks['ok'])} {name}{suffix}")

    def step_skip(self, name: str, detail: str = "") -> None:
        self.tracker.record(name, "skip", detail)
        if self.observer is not None:
            # The observer gets the RESULT, not the rendered line: a screen draws its own
            # row from the status, and echoing the line as well would report the same fact
            # twice in two places that can disagree.
            self.observer.result(name, "skip", detail)
            return
        suffix = f" {self.style.dim('(' + detail + ')')}" if detail else ""
        self.say(f"  {self.style.yellow(self.marks['skip'])} {name}{suffix}")

    def step_fail(self, name: str, detail: str = "", fatal: bool = True) -> None:
        self.tracker.record(name, "fail", detail)
        if self.observer is not None:
            self.observer.result(name, "fail", detail)
        else:
            suffix = f" {self.style.dim('(' + detail + ')')}" if detail else ""
            self.say(f"  {self.style.red(self.marks['fail'])} {name}{suffix}")
        if fatal:
            raise InstallAbort(detail or name)

    def did(self, past: str, conditional: str) -> str:
        """Honest wording: the conditional form in demo, the past tense for real runs."""
        return conditional if self.demo else past

    def step_intro(self, text: str) -> None:
        """One dimmed line under the step header: what this step does, Morgan's voice."""
        self.say(self.style.dim(f"  {text}"))

    # ---- steps

    def preflight(self) -> None:
        self.step_intro("Checking you have what I need: Python, git and the Claude CLI.")
        if sys.version_info >= (3, 9):
            self.step_ok(f"Python {sys.version_info.major}.{sys.version_info.minor}")
        else:
            self.step_fail("Python version", "3.9 or newer required")
        # PATH probes stay real in demo (honest preflight); a missing tool downgrades to
        # a skip there because the dry run executes nothing anyway.
        if shutil.which("git"):
            self.step_ok("git found")
        elif self.demo:
            self.step_skip("git", "not found - a real run needs it")
        else:
            self.step_fail("git", "git is required - install it and re-run")
        claude_path, how = find_claude(refresh=True)
        if how == "path":
            self.step_ok("claude CLI found")
        elif claude_path:
            # Installed, but this terminal's PATH copy predates the install (common on
            # corporate Windows). Full-path launches keep the run working regardless.
            self.step_ok(f"claude CLI found at {claude_path}")
            self.say(
                self.style.dim(
                    "  (it is not on this terminal's PATH - I will launch it by full path;"
                    " open a fresh terminal and `claude` will work by name.)"
                )
            )
        elif self.demo:
            self.step_skip("claude CLI", f"not found - a real run needs it: {CLAUDE_DOCS_URL}")
        else:
            self.step_fail(
                "claude CLI",
                "not on PATH and not in the usual install locations - install it first"
                f" ({CLAUDE_DOCS_URL}), then open a NEW terminal and re-run me",
            )
        # FOUND is not the same as WORKS. A package-manager shim stays on PATH after the
        # binary it points at has gone, so discovery reports a tick and the first real
        # call fails - which is how a run reached "Add marketplace" before finding out
        # (live report 2026-08-28). One cheap call settles it here, where the answer can
        # still change the plan, instead of three steps later where it read as an error.
        self.cli_runs = True
        if claude_path:
            first = self._claude_version_error(["claude", "--version"])
            if first:
                # The one on PATH does not run. Before concluding the CLI is unusable,
                # try the OTHER places it installs to - a leftover shim on PATH hides a
                # working install in the next tier down, and existence was all discovery
                # ever checked (2026-08-28).
                better, how = find_working_claude(
                    lambda argv: not self._claude_version_error(argv + ["--version"])
                )
                if better:
                    remember_working_claude(better)
                    self.step_ok(
                        f"claude CLI runnable at {better}",
                        f"the one on PATH does not run; using this {how} copy instead",
                    )
                else:
                    asked = self._ask_for_claude_path(first)
                    if asked:
                        remember_working_claude(asked)
                        self.step_ok(f"claude CLI runnable at {asked}", "as you told me")
                    else:
                        self.cli_runs = False
                        self.step_skip(
                            "claude CLI runnable",
                            f"{first} - registering the plugin directly instead",
                        )
        try:
            proc = run_cmd(["git", "ls-remote", "--heads", REPO_URL, "main"], timeout=30)
            if proc.returncode == 0:
                self.step_ok("GitHub remote reachable")
            else:
                self.step_skip("GitHub remote", "unreachable - clone/fetch may fail")
        except (subprocess.TimeoutExpired, OSError):
            self.step_skip("GitHub remote", "check timed out - clone/fetch may fail")

    def choose_branch(self) -> None:
        default = self.args.branch or self.cfg.get("branch", "dev")
        self.step_intro(
            "Picking your release channel - dev is the recommended default right now: this is"
            " a fast-moving proof-of-concept phase, and promoting dev to main is eval-gated"
            " (it costs real API tokens to run), so main can lag noticeably behind."
        )
        while True:
            picked = ask(
                "  Which channel shall I track for you (main/dev)?",
                default,
                self.args.yes,
                style=self.style,
            ).lower()
            try:
                self.branch = validate_branch(picked)
                break
            except ValueError as exc:
                if self.args.yes or not sys.stdin.isatty():
                    self.step_fail("Branch choice", str(exc))
                self.say(f"  {exc}")
        self.step_ok(f"Channel: {self.branch}")

    def resolve_repo(self) -> None:
        self.step_intro("Finding your local clone of the team repo - or making one for you.")
        if self.args.repo:
            candidate = Path(self.args.repo).expanduser().resolve()
        elif self.mode == "update":
            configured = self.cfg.get("repo_path")
            script_root = Path(__file__).resolve().parent  # helper sits at the repo ROOT
            if configured and looks_like_repo(Path(configured)):
                candidate = Path(configured)
            elif looks_like_repo(script_root):
                candidate = script_root
            elif self.demo:
                # Dry run: fall through to the would-clone path with the default target.
                candidate = Path(self.cfg.get("repo_path", str(DEFAULT_CLONE_DIR))).expanduser()
            else:
                self.step_fail(
                    "Locate clone",
                    "no known clone - run: python install_helper.py install",
                )
                return
        else:
            # A new user who manually `git clone`d the repo and is running this script
            # from inside that clone (the only copy they have - there's no separate
            # distributed installer) had no configured repo_path yet, so "install" mode
            # asked where to put a clone and defaulted to DEFAULT_CLONE_DIR, ignoring the
            # perfectly good one it was already running from - the friendly path (accept
            # the default) silently created a second, orphaned clone. Default to the
            # script's own directory when that's a real clone instead.
            script_root = Path(__file__).resolve().parent
            default = self.cfg.get("repo_path") or (
                str(script_root) if looks_like_repo(script_root) else str(DEFAULT_CLONE_DIR)
            )
            candidate = (
                Path(
                    ask(
                        "  Where shall I keep your local clone?",
                        default,
                        self.args.yes,
                        style=self.style,
                    )
                )
                .expanduser()
                .resolve()
            )

        if looks_like_repo(candidate):
            self.repo = candidate
            self.step_ok(f"Using existing clone: {candidate}")
        elif self.demo and not (candidate.exists() and any(candidate.iterdir())):
            # Dry run: show the clone command and accept the path without cloning.
            run_cmd(["git", "clone", REPO_URL, candidate], timeout=600)
            self.repo = candidate
            self.step_ok(f"Would clone to {candidate}")
        elif candidate.exists() and any(candidate.iterdir()):
            self.step_fail(
                "Clone directory",
                f"{candidate} exists and is not a clone of this repo - pick another path",
            )
        else:
            self.say(self.style.dim(f"  Cloning {REPO_URL} ..."))
            proc = run_cmd(["git", "clone", REPO_URL, candidate], timeout=600)
            if proc.returncode != 0:
                err = proc.stderr.strip().splitlines()
                self.step_fail("Clone repository", err[-1] if err else "git clone failed")
            self.repo = candidate
            self.step_ok(f"Cloned to {candidate}")

    def locate_clone_asis(self) -> None:
        """Setup-style runs use the clone exactly as it sits on disk - no fetch, no reset.
        A missing or invalid clone is a clean failure pointing at the full install."""
        self.step_intro("Using your existing clone exactly as it sits - no code pull in this run.")
        if self.args.repo:
            candidate = Path(self.args.repo).expanduser().resolve()
        else:
            configured = self.cfg.get("repo_path")
            script_root = Path(__file__).resolve().parent
            if configured and looks_like_repo(Path(configured)):
                candidate = Path(configured)
            else:
                candidate = script_root
        if looks_like_repo(candidate):
            self.repo = candidate
            self.step_ok(f"Using clone as-is: {candidate}", "code not updated")
        elif self.demo:
            self.repo = candidate
            self.step_ok(f"Would use clone at {candidate}", "demo")
        else:
            self.step_fail(
                "Locate clone",
                "no usable clone found - run a full install first "
                "(menu option 1, or: python install_helper.py install)",
            )

    def sync_branch(self) -> None:
        self.step_intro(
            "Bringing your clone up to date with the chosen channel - "
            "your local changes are protected."
        )
        repo = self.repo
        proc = run_cmd(["git", "-C", repo.as_posix(), "fetch", "origin", self.branch], timeout=300)
        if proc.returncode != 0:
            self.step_fail("Fetch origin", proc.stderr.strip() or "git fetch failed")
        self.step_ok(self.did("Fetched", "Would fetch") + f" origin/{self.branch}")

        # Update preview: read-only, fail-soft, before anything is checked out. A
        # declined update is a skip, not a failure - the later steps still run
        # against the clone as-is.
        local_version = installed_version(repo)
        preview = gather_update_preview(repo, self.branch, local_version)
        if preview["behind"] == 0:
            self.step_ok(f"Already up to date with origin/{self.branch}")
        else:
            self.say(self.style.bold("  Here is what an update would bring:"))
            self.print_update_preview(preview, self.branch, local_version)
            if not confirm(
                "  Shall I bring you up to date?",
                default=True,
                assume_yes=self.args.yes,
                style=self.style,
            ):
                self.code_stale = True
                self.step_skip("Sync", "declined - staying on your current code")
                return

        if is_dirty(repo):
            self.say(self.style.yellow("  The clone has uncommitted local changes."))
            if self.args.yes or not sys.stdin.isatty():
                self.step_fail(
                    "Working tree",
                    "dirty - refusing to reset; commit or stash your changes, then re-run",
                )
            if confirm(
                "  Shall I stash them and carry on?",
                default=False,
                assume_yes=False,
                style=self.style,
            ):
                proc = run_cmd(
                    [
                        "git",
                        "-C",
                        repo,
                        "stash",
                        "push",
                        "--include-untracked",
                        "-m",
                        f"install_helper {datetime.now().strftime('%Y-%m-%d')}",
                    ]
                )
                if proc.returncode != 0:
                    self.step_fail("Stash changes", proc.stderr.strip() or "git stash failed")
                self.stashed = True
                self.step_ok("Local changes stashed", "restore later with: git stash pop")
            else:
                self.step_fail(
                    "Working tree",
                    "dirty - refusing to reset; commit or stash your changes, then re-run",
                )

        ahead = commits_ahead(repo, self.branch)
        if ahead:
            detail = f"{ahead} local commit(s) not on origin/{self.branch}"
            if self.args.yes or not sys.stdin.isatty():
                self.step_fail("Local commits", detail + " - refusing to discard them")
            if not confirm(
                f"  {detail}. Shall I discard them and match origin?",
                False,
                False,
                style=self.style,
            ):
                self.step_fail("Local commits", detail + " - left in place, aborting")

        proc = run_cmd(
            ["git", "-C", repo.as_posix(), "checkout", "-B", self.branch, f"origin/{self.branch}"]
        )
        if proc.returncode != 0:
            self.step_fail("Checkout branch", proc.stderr.strip() or "git checkout failed")
        head = run_cmd(["git", "-C", repo.as_posix(), "rev-parse", "--short", "HEAD"])
        commit = head.stdout.strip() if head.returncode == 0 else "?"
        self.step_ok(
            self.did(f"On {self.branch} at {commit}", f"Would be on {self.branch} at {commit}"),
            f"matches origin/{self.branch}",
        )
        self._reexec_if_self_updated()

    def _reexec_if_self_updated(self) -> None:
        """If the sync above just pulled a NEW install_helper.py, the rest of THIS run
        would otherwise keep executing the OLD in-memory logic - defeating the entire
        point of shipping a fix at the installer level. Re-exec the freshly-checked-out
        script with the same choices this run already made (repo location, branch) baked
        in via argv, so nothing gets re-asked; the new process's own summary is the one
        the user sees. Best-effort throughout: any failure just falls through to finish
        THIS run on the old code, same philosophy as _relocate_if_running_inside_target_repo."""
        if self.demo:
            return  # never spawns a subprocess outside run_cmd's mocked demo path
        new_script = self.repo / "install_helper.py"
        try:
            if not new_script.is_file():
                return
            running = Path(__file__).resolve().read_bytes()
            fresh = new_script.read_bytes()
            if running == fresh:
                return
            self.say(
                self.style.yellow(
                    "  install_helper.py itself was updated - restarting with the new version..."
                )
            )
            child_argv = _argv_from_args(
                self.args, repo=self.repo, branch=self.branch, mode=self.mode
            )
            proc = subprocess.run(  # fixed argv (sys.executable + freshly-pulled script), shell=False  # nosec B603
                [sys.executable, str(new_script), *child_argv]
            )
        except OSError:
            return
        sys.exit(proc.returncode)

    def prewarm_guard_cache(self) -> None:
        """P1 (2026-07-31 corp report): the safety guards' interpreter cache
        (.claude/.guard-interpreter, read by run-guard.sh) was previously written only
        on a project's first real /engage - so every fresh install/update paid the full
        cold-start probe cost (worst case on Windows: the python3 Store-stub hang,
        repeated across five PreToolUse hooks) on its very next session. Writes the cache
        once at install time instead - free for every project that later resolves to
        this same plugin root (CLAUDE_PLUGIN_ROOT is one shared value per install, not
        per-project).

        Probes each candidate DIRECTLY (not by shelling out to run-guard.sh through sh +
        exec): a live report (2026-07-31) showed that nested chain hanging for MINUTES on
        a corporate Windows box even with a 30s subprocess timeout set - the timeout
        killed the direct `sh` child, but the Store-stub `python3.exe` it had exec'd into
        can survive as an orphaned process still holding the output pipe open, which
        subprocess.run then blocks reading from regardless of the nominal timeout (a
        known Windows child-process-tree gotcha). Probing python.exe directly makes it
        the immediate child of THIS process, so a short, PER-CANDIDATE timeout reliably
        bounds it (Windows' TerminateProcess is forceful, unlike POSIX SIGTERM). Same
        Windows-aware order as P2's run-guard.sh fix, kept in sync by comment, not code -
        this never invokes the launcher, so it cannot drift into calling it differently,
        only into forgetting to update the order if run-guard.sh's ever changes again.

        Best-effort throughout: a missing clone-side launcher (nothing to warm for) or no
        interpreter found at all just skips - the guard still self-warms on first real
        use exactly as before, this is a pure latency optimisation, never a hard
        requirement, and it must never be the thing that makes an install look hung."""
        self.step_intro(
            "Priming the safety guards' interpreter cache so your first real /engage "
            "doesn't pay that cost itself."
        )
        launcher = self.repo / ".claude" / "hooks" / "run-guard.sh"
        if not launcher.is_file():
            self.step_skip("Guard interpreter cache", "launcher not found in this clone")
            return
        cache = _guard_interpreter_cache(self.repo)
        if self.demo:
            self.step_ok(f"Would warm {cache}", "demo")
            return
        order = (
            ("python", "py", "python3") if sys.platform == "win32" else ("python3", "python", "py")
        )
        self.say(self.style.dim("  probing... (tightly bounded - a few seconds at most)"))
        sys.stdout.flush()
        chosen = None
        for name in order:
            resolved = shutil.which(name)
            if not resolved:
                continue
            try:
                proc = run_cmd(
                    [
                        resolved,
                        "-c",
                        "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)",
                    ],
                    timeout=3,
                )
            except (subprocess.TimeoutExpired, OSError):
                continue  # this candidate is the hung/broken one - move on, don't wait on it
            if proc.returncode == 0:
                chosen = resolved
                break
        if chosen is None:
            self.step_skip("Guard interpreter cache", "no suitable interpreter found yet")
            return
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(chosen, encoding="utf-8")
        except OSError as exc:
            self.step_skip("Guard interpreter cache", f"could not write cache ({exc})")
            return
        self.step_ok(f"Cached: {chosen}")

    def check_pending_hook_fixes(self) -> None:
        """Read-only nudge, on by default (no toggle) - never applies anything itself.

        Prompted by a live question: guard_daemon now defaults to true (see
        run_configure), but the daemon files it needs are staged, not live, until a
        human runs scripts/apply-guard-daemon.sh - so a fresh clone could carry a
        preference that quietly does nothing, with no way to notice short of reading
        docs or running pytest by hand. install_helper.py is the one place every
        install/update already passes through, so it is the right place to surface
        the gap loudly.

        Deliberately does NOT copy the files itself, even though install_helper.py
        is always human-invoked. ADR-002 rec 5's boundary ("the model cannot edit
        .claude/hooks/**") has to hold regardless of who is nominally driving - and in
        practice, THIS script gets run by the model via Bash constantly, same as every
        other step in this file. Teaching it to self-apply staged hooks would hand the
        model an indirect route to modify its own guard files just by running the
        installer normally - exactly the loophole that boundary exists to close (see
        scripts/apply-outstanding.sh's own docstring: it sequences already-approved
        human-run scripts and grants itself no exemption; this step affords the same
        courtesy - and gives the same test command in dont-edit-safety-hooks spirit).

        Uses the identical staged-vs-live discovery as tests/test_hooks_in_sync.py's
        _live_path_for (kept in sync by convention, not import: this module runs
        standalone before any pip/test setup exists, so it can't depend on the tests
        package) - guard-prefixed files and run-guard.sh live under .claude/hooks/,
        everything else staged is a scripts/ tool. Best-effort: any read error on a
        given file just skips that one file rather than failing the whole step."""
        self.step_intro(
            "Checking whether any staged safety-hook fixes are waiting on a human to apply them."
        )
        staged_dir = self.repo / "scripts" / "staged_hooks"
        if not staged_dir.is_dir():
            self.step_skip("Pending hook fixes", "no staged_hooks directory in this clone")
            return

        def live_path_for(staged: Path) -> Path:
            if staged.name.startswith("guard-") or staged.name == "run-guard.sh":
                return self.repo / ".claude" / "hooks" / staged.name
            return self.repo / "scripts" / staged.name

        pending = []
        for staged in sorted(staged_dir.iterdir()):
            if not staged.is_file() or staged.name.startswith("."):
                continue
            live = live_path_for(staged)
            try:
                staged_text = staged.read_text(encoding="utf-8")
                live_text = live.read_text(encoding="utf-8") if live.is_file() else None
            except (OSError, UnicodeDecodeError):
                # UnicodeDecodeError is NOT an OSError (found in review, 2026-08-13): a
                # non-UTF-8 staged/live file used to crash this step instead of just
                # skipping it, contradicting this method's own "any read error on a given
                # file just skips that one file" docstring promise.
                continue
            if live_text != staged_text:
                pending.append(staged.name)

        if not pending:
            self.step_ok("Pending hook fixes", "none - staged and live hooks match")
            return

        self.say(
            self.style.yellow(
                f"  {len(pending)} staged fix(es) not yet applied: {', '.join(pending)}"
            )
        )
        self.say(
            self.style.yellow(
                "  Inert until applied - e.g. a true guard_daemon preference does nothing "
                "until this runs. A human (not this script) should run:"
            )
        )
        self.say(f"    cd {self.repo} && bash scripts/apply-outstanding.sh")
        # Who is reading this matters (2026-08-26 owner report). Applying a staged safety
        # hook is a MAINTAINER action: it edits guard code, and on a managed plugin install
        # the next update overwrites it anyway, so the fix would silently revert. Someone
        # running an installed copy needs a different instruction from someone standing in
        # their own clone - and telling them to run a script that cannot help them is worse
        # than saying nothing, because it reads as "you forgot a step" for a step that was
        # never theirs.
        if self._is_managed_plugin_install():
            self.say(
                self.style.yellow(
                    "  This looks like an INSTALLED plugin copy, not your own clone - so "
                    "this is not yours to apply, and a plugin update would overwrite it. "
                    "Please report it to the plugin author instead:"
                )
            )
            self.say(f"    {REPO_URL.removesuffix('.git')}/issues")
            self.say(
                self.style.dim(
                    "    Quote the file name(s) above and this plugin version. Nothing is "
                    "broken meanwhile - an unapplied fix means the OLD behaviour, never a "
                    "disabled guard."
                )
            )
        self.step_skip("Pending hook fixes", f"{len(pending)} waiting - see command above")

    def _is_managed_plugin_install(self) -> bool:
        """Is self.repo a plugin install directory rather than a clone the user maintains?

        Best-effort and deliberately conservative: an unclear answer returns False, so the
        extra guidance is only ever ADDED when we are fairly sure, never substituted for
        the apply command. Signals: the clone sits under a registered plugin install path,
        or under a .claude/plugins directory, or has no .git at all (a marketplace copy is
        not a checkout, so there is nothing to commit an applied fix into)."""
        try:
            repo = Path(self.repo).resolve()
        except (OSError, ValueError):
            return False
        try:
            for candidate in _registry_install_paths(Path.home()):
                resolved = Path(candidate).expanduser().resolve()
                if repo == resolved or resolved in repo.parents:
                    return True
        except Exception:
            pass
        if any(part == "plugins" for part in repo.parts) and any(
            part in (".claude", "claude") for part in repo.parts
        ):
            return True
        return not (repo / ".git").exists()

    def print_update_preview(self, preview: dict, branch: str, local_version) -> None:
        """Console rendering of gather_update_preview's result. Purely informational:
        missing fields simply do not print; degradation notes print dimmed."""
        s = self.style
        behind, remote = preview.get("behind"), preview.get("remote_version")
        if behind is not None:
            self.say(f"  {behind} new commit(s) on origin/{branch}")
        if remote and local_version and remote != local_version:
            self.say(f"  Version: {local_version} -> {remote}")
        elif remote and not local_version:
            self.say(f"  Remote version: {remote}")
        headlines = list(preview.get("headlines") or [])
        shown = headlines[:5]
        if shown:
            for line in shown:
                self.say(f"    {line}")
            if len(headlines) > 5:
                self.say(s.dim(f"    ... and {len(headlines) - 5} more"))
        for note in preview.get("notes") or []:
            self.say(s.dim(f"  note: {note}"))

    def preflight_lite(self) -> None:
        """Just enough for a read-only check: Python is running, git exists."""
        self.step_intro("Just the basics for a read-only check: git and your clone.")
        if shutil.which("git"):
            self.step_ok("git found")
        else:
            self.step_fail("git", "git is required - install it and re-run")

    def check_updates_step(self) -> None:
        """Menu option: fetch + show the update preview, then STOP. Nothing is checked
        out, installed or written; every probe fails soft into a clear line."""
        self.step_intro(
            "Fetching origin and showing what an update would bring - changing nothing."
        )
        if self.args.repo:
            repo = Path(self.args.repo).expanduser().resolve()
        else:
            configured = self.cfg.get("repo_path")
            script_root = Path(__file__).resolve().parent
            if isinstance(configured, str) and configured and looks_like_repo(Path(configured)):
                repo = Path(configured)
            elif looks_like_repo(script_root):
                repo = script_root
            else:
                self.step_fail(
                    "Check for updates",
                    "no usable clone found - run a full install first (menu option 1)",
                    fatal=False,
                )
                return
        branch = self.cfg.get("branch")
        branch = branch if branch in BRANCHES else "dev"
        proc = run_cmd(["git", "-C", repo.as_posix(), "fetch", "origin", branch], timeout=300)
        if proc.returncode != 0:
            self.step_fail(
                "Fetch origin",
                (proc.stderr.strip().splitlines() or ["git fetch failed"])[-1]
                + " - check your connection and re-run",
                fatal=False,
            )
            return
        local_version = installed_version(repo)
        preview = gather_update_preview(repo, branch, local_version)
        if preview["behind"] == 0:
            self.step_ok(f"Already up to date with origin/{branch}")
            return
        self.say(self.style.bold("  Here is what an update would bring:"))
        self.print_update_preview(preview, branch, local_version)
        self.step_ok("Check complete - nothing changed", "run a full update (option 1) to apply")

    def quick_setup_choice(self) -> None:
        """First of the optional post-install steps for a full install/update
        (2026-08-07 user request): one upfront choice instead of a question per step -
        "go with defaults" (fast: dev requirements, status line, the 'virt-surv' alias,
        and - 2026-08-12 user request, extending the ORIGINAL narrower scope - every
        remaining project-enablement question too: permissions allow-list, env tuning,
        the LLM-gateway beta-fields workaround, docx, and Morgan's model, all wired or
        skipped per their own sensible default with zero further questions) or "manually
        configure" (walk through each one individually, exactly as this installer did
        before). "Go with defaults" genuinely means that now - only this machine's own
        defaults (machine_defaults_offer) stay a deliberate ask either way, since that
        changes what every FUTURE project inherits, not just this one. --yes always
        implies the fast path (a scripted/CI run can't answer an interactive question),
        matching this installer's `--yes` semantics everywhere else."""
        if self.args.yes:
            self.quick_defaults = True
            return
        self.step_intro(
            "A few more optional bits follow: dev requirements, the status line, the "
            "'virt-surv' shell alias, and this machine's default settings. Enabling the "
            "plugin for a specific project is a separate step - 'virt-surv configure' "
            "(or 'engage'/'onboard' for zero-prompt setup) from inside that project."
        )
        self.quick_defaults = confirm(
            "  Go with the recommended defaults for all of these (fast, recommended), "
            "or walk through each one individually?",
            # isatty()-gated, same reasoning as every downstream step's own fallback: a
            # REAL terminal gets the inviting True default; non-tty/non-`--yes` (piped
            # input, a test harness) gets the conservative False - "manually configure" -
            # so each downstream step falls back to ITS OWN original, already-safe
            # non-tty handling instead of silently fast-pathing something like the alias
            # step's real (if harmless) interpreter probe with no human watching.
            default=True if sys.stdin.isatty() else False,
            assume_yes=False,
            style=self.style,
        )

    def optional_pip(self) -> None:
        self.step_intro(
            "Optional extras, installed once per Python environment (not per project): the HTML "
            "renderer's libraries (without them artifact .html rendering degrades) plus test "
            "tooling. The plugin core needs no pip at all."
        )
        req = self.repo / "requirements-dev.txt"
        # In demo the clone may not exist yet; still walk the real prompt.
        if not req.exists() and not self.demo:
            self.step_skip("Dev requirements", "requirements-dev.txt not present")
            return
        if self.args.yes:
            wanted = self.args.pip  # unattended: unchanged, flag-gated
        elif self.subset == "full" and self.quick_defaults:
            # 2026-08-07 user request: chose "go with defaults" at quick_setup_choice -
            # no further question, just install them (still skipped above when
            # requirements-dev.txt isn't present).
            wanted = True
        else:
            wanted = confirm(
                "  Shall I install the optional dev requirements (pytest, render deps)?",
                default=self.args.pip,
                assume_yes=False,
                style=self.style,
            )
        if not wanted:
            self.step_skip("Dev requirements", "skipped - the plugin works without them")
            return
        proc = run_cmd([sys.executable, "-m", "pip", "install", "-r", req], timeout=600)
        if proc.returncode == 0:
            self.step_ok("Dev requirements " + self.did("installed", "would be installed"))
        else:
            # pip may be absent or blocked in locked-down environments; never fatal.
            self.step_fail(
                "Dev requirements",
                "pip install failed - the plugin itself needs no pip packages",
                fatal=False,
            )

    # The packages live in requirements-review.txt, not in a list here (2026-08-27, owner:
    # "there's an existing install requirements path"). Exactly right - that file already
    # means "optional, sharpens reviews, not required to use the team", which is what these
    # are, and a second hardcoded list would be a second place to forget to update.
    # Named explicitly rather than installing the whole file, because the analysers in it
    # are a separate decision the user may already have taken.
    # Read from requirements-review.txt rather than restated here (2026-08-27). The previous
    # version kept a bare-name tuple beside a comment saying the names lived in the file,
    # which was not only duplication: installing bare names ignored the version floors, so
    # the <1.0 pin that keeps this offline would have been silently bypassed. Now there is
    # one source and the pin actually applies.
    CODE_INTEL_REQUIREMENTS = "requirements-review.txt"
    CODE_INTEL_PREFIXES = ("tree-sitter", "tree-sitter-language-pack")

    def code_intel_specs(self) -> list:
        """The pinned specs for the code-intelligence packages, from the requirements file.

        Falls back to bare names only if the file cannot be read - an install without the
        pin is worse than none, so this is logged rather than silent."""
        path = self.repo / self.CODE_INTEL_REQUIREMENTS
        specs = []
        try:
            for raw in path.read_text(encoding="utf-8").splitlines():
                line = raw.split("#", 1)[0].strip()
                if not line:
                    continue
                name = line.split(">")[0].split("<")[0].split("=")[0].strip()
                if name in self.CODE_INTEL_PREFIXES:
                    specs.append(line)
        except OSError:
            specs = []
        if len(specs) != len(self.CODE_INTEL_PREFIXES):
            self.say(
                self.style.dim(
                    f"    could not read pins from {self.CODE_INTEL_REQUIREMENTS} - "
                    "installing unpinned names"
                )
            )
            return list(self.CODE_INTEL_PREFIXES)
        return specs

    def code_intel_step(self) -> None:
        """Attempt the code-intelligence extras, and treat failure as a normal outcome.

        WHY IT IS ATTEMPTED BY DEFAULT (2026-08-26). repo_skeleton's tree-sitter tier was a
        stub for its whole life on the reasoning that a compiled extension could not work on
        a locked-down corporate box. Measured on the actual box: it installs by plain pip,
        loads, and parses. The objection did not survive contact. With the tier implemented,
        having the library present is the difference between exact symbols and ranges for
        ~15 languages and a regex approximation - and on a Java/Scala/SQL estate, which is
        what this team reviews, that is most of the value.

        WHY FAILURE IS NOT AN ERROR. It genuinely cannot be installed everywhere - this
        project's own dev box refuses it under PEP 668 (externally-managed environment), and
        elsewhere it will be no network, no pip, or a DLL the policy will not load. Every one
        of those is fine: the tier is a SOFT probe, so the plugin behaves exactly as it did
        before, using stdlib ast for Python and the regex tier for everything else. So this
        reports the outcome and moves on. It must never fail an install, and it must never
        leave a user thinking something is broken when nothing is.
        """
        self.step_intro(
            "Optional code-intelligence extras (tree-sitter). With them, codebase "
            "orientation gets exact symbols and line ranges for Java, Scala, C#, SQL, "
            "TypeScript and more; without them it falls back to pattern matching. Either "
            "way the plugin works - this is sharpness, not function."
        )
        # NO PROMPT, deliberately, unlike optional_pip (owner: "attempts install by
        # default"). The walkthrough convention is that a non-quick path keeps its own
        # per-step question; this step departs from it because the thing being installed
        # is optional in the strongest sense - failing to install it changes nothing a
        # user would notice - so a question would be asking permission for something
        # with no downside to decline and no consequence to accept.
        if self.demo:
            self.step_ok("Code intelligence", "would attempt pip install (demo)")
            return
        if self._code_intel_present():
            warmed = self._prewarm_code_intel()
            if warmed == -1:
                detail = "already available - grammars bundled in the wheel"
            elif warmed:
                detail = f"already available - {warmed} grammars cached for offline use"
            else:
                detail = "already available, but no grammars are cached yet"
            self._invalidate_tool_cache()
            self.step_ok("Code intelligence", detail)
            return
        proc = run_cmd(
            [sys.executable, "-m", "pip", "install", "--quiet", *self.code_intel_specs()],
            timeout=600,
        )
        if proc.returncode == 0 and self._code_intel_present():
            warmed = self._prewarm_code_intel()
            if warmed == -1:
                detail = "installed - exact symbols for ~15 languages (grammars bundled)"
            elif warmed:
                detail = f"installed - {warmed} grammars fetched now, none at runtime"
            else:
                detail = (
                    "installed, but no grammars could be fetched - orientation will use "
                    "the pattern tier until they can be"
                )
            self._invalidate_tool_cache()
            self.step_ok("Code intelligence", detail)
            return
        # Distinguish the two failures, because they mean different things to a reader: pip
        # refused (no network, no pip, externally-managed), versus pip succeeded and the
        # compiled extension still will not load (the policy case). Neither is fatal.
        reason = "pip could not install it"
        blob = ((proc.stderr or "") + (proc.stdout or "")).lower()
        if "externally-managed" in blob or "pep 668" in blob:
            reason = "this Python is externally managed (PEP 668)"
        elif "network" in blob or "resolve" in blob or "timed out" in blob:
            reason = "no package index reachable"
        elif proc.returncode == 0:
            reason = "installed but the compiled extension will not load here"
        self.say(
            self.style.dim(
                f"    {reason} - orientation will use the built-in pattern tier instead. "
                "Nothing is broken; symbols are approximate rather than exact."
            )
        )
        self.step_skip("Code intelligence", f"unavailable - {reason}")

    def _prewarm_code_intel(self) -> int:
        """Download every supported grammar ONCE, here, where a human is watching.

        From pack 1.0 grammars are fetched on demand instead of shipping in the wheel. The
        team refuses to let that happen at runtime (repo_skeleton checks the cache and falls
        through rather than fetching), so if it does not happen here it does not happen -
        the tier would silently stay on the pattern floor. Best-effort and never fatal: a
        language that will not warm is one language less, not a failed install.

        Returns how many warmed, or -1 when the version bundles its grammars and there is
        nothing to warm."""
        probe = (
            "import sys\n"
            "try:\n"
            "    from tree_sitter_language_pack import cache_dir, get_parser\n"
            "except ImportError:\n"
            "    print('BUNDLED'); sys.exit(0)\n"
            "langs = ['python','java','scala','kotlin','csharp','typescript','tsx',"
            "'javascript','sql','bash','go','ruby','rust','c','cpp']\n"
            "ok = 0\n"
            "for lang in langs:\n"
            "    try:\n"
            "        get_parser(lang).parse(b'x'); ok += 1\n"
            "    except Exception:\n"
            "        pass\n"
            "print(ok)\n"
        )
        try:
            proc = run_cmd([sys.executable, "-c", probe], timeout=900)
        except Exception:
            return 0
        out = (proc.stdout or "").strip().splitlines()
        if not out:
            return 0
        if out[-1] == "BUNDLED":
            return -1
        try:
            return int(out[-1])
        except ValueError:
            return 0

    def _invalidate_tool_cache(self) -> None:
        """Drop the cached tool inventory, because this step just changed the answer.

        The probe caches to `.claude/.tool-availability` on a 7-day TTL, and Morgan reads
        it at engagement open. Installing tree-sitter and leaving that cache alone means
        the team keeps reporting the tool missing for up to a week AFTER the user installed
        it - they did the thing they were told to do and nothing changed, which is the
        worst shape a stale cache can take.

        Deleting rather than re-probing: the next `go` or open re-probes anyway, and a
        delete cannot half-write a cache. Best-effort and silent - a cache that will not
        delete costs freshness, never the install.

        Only THIS project's cache: the install is machine-wide but the cache is per-project,
        and there is no register of every project on the box. Others self-heal on their own
        TTL, or on `bash scripts/check-review-tools.sh --refresh`.
        """
        root = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
        cache = Path(root) / ".claude" / ".tool-availability"
        try:
            if cache.is_file():
                cache.unlink()
                self.say(self.style.dim("    tool inventory cache cleared - it will re-probe"))
        except OSError:
            pass

    def _code_intel_present(self) -> bool:
        """Importable AND usable. A probe that only checks importability would report
        success on a machine where the DLL fails to load, which is the one case worth
        distinguishing."""
        probe = (
            "from tree_sitter_language_pack import get_parser;get_parser('python').parse(b'x = 1')"
        )
        try:
            return run_cmd([sys.executable, "-c", probe], timeout=120).returncode == 0
        except Exception:
            return False

    def _ask_for_claude_path(self, why: str) -> str:
        """Ask where the CLI is, when every place we know to look failed to produce one
        that runs. Returns a VERIFIED path, or "" to carry on without the CLI.

        Asked once and stored (installer.json), the same contract as the `virt-surv go`
        launch command: a corporate image can put the CLI somewhere no amount of
        searching would guess, and the human knows where it is. But a path is only
        accepted once it has RUN - taking someone's word for it would rebuild the exact
        bug this whole path exists to fix, one prompt further along.

        Silent on a non-interactive run: direct registration completes the install
        anyway, so an unanswerable question must never be the thing that stops it."""
        cfg = load_config(config_path())
        stored = cfg.get(_CLAUDE_CLI_PATH_KEY)
        if (
            isinstance(stored, str)
            and stored
            and not self._claude_version_error(
                command_argv("claude", resolved=stored) + ["--version"]
            )
        ):
            return stored
        if self.demo or getattr(self.args, "yes", False) or not sys.stdin.isatty():
            return ""
        self.say(self.style.dim(f"    ({why})"))
        self.say(
            self.style.dim(
                "    I looked on PATH and in the usual install locations. If you know where"
                " the Claude Code CLI is on this machine, give me the full path - otherwise"
                " press Enter and I will register the plugin directly, which works too."
            )
        )
        given = ask("  Full path to the claude CLI", "", False, style=self.style).strip()
        given = given.strip('"').strip("'")
        if not given:
            return ""
        if not _is_file_safe(Path(given)):
            self.say(self.style.yellow(f"    no file there: {given}"))
            return ""
        problem = self._claude_version_error(command_argv("claude", resolved=given) + ["--version"])
        if problem:
            self.say(self.style.yellow(f"    that one does not run either: {problem}"))
            return ""
        cfg[_CLAUDE_CLI_PATH_KEY] = given
        save_config(config_path(), cfg)
        return given

    def _claude_version_error(self, argv) -> str:
        """ "" if this argv runs, otherwise one line saying why not. Never raises: an
        unlaunchable CLI is a fact to route on, not an exception to escape through."""
        try:
            proc = run_cmd(argv, timeout=60)
        except OSError as exc:
            return f"could not be launched: {exc}"
        if proc.returncode == 0:
            return ""
        lines = (proc.stderr.strip() or proc.stdout.strip() or "").splitlines()
        return lines[0] if lines else "it did not run"

    def say_claude_launch_trace(self) -> None:
        """One dim line naming exactly how claude is being launched - the difference
        between 'cmd.exe is blocked', 'the APPDATA exe is blocked' and 'the CLI ran
        and failed' when reading a report from a locked-down box."""
        try:
            argv = command_argv("claude")
        except Exception:
            argv = ["claude"]
        self.say(self.style.dim(f"    (claude launched as: {' '.join(argv)})"))

    def register_directly(self, reason: str) -> None:
        """The no-CLI path: write the registration JSON the CLI would have written.
        The interactive Claude Code app reads these at startup, so a box that can run
        Claude Code but blocks OUR launch of the CLI binary still gets the plugin."""
        self.say(self.style.dim(f"    ({reason} - registering directly in ~/.claude instead)"))
        if self.demo:
            for name in ("known_marketplaces.json", "installed_plugins.json", "settings.json"):
                self.say(self.style.dim(f"    would update ~/.claude/.../{name}"))
        else:
            version = installed_version(self.repo) if self.repo else None
            try:
                register_plugin_directly(self.repo, user_settings_path().parent, version)
            except InstallAbort as exc:
                self.step_fail("Marketplace + plugin registration", str(exc))
                return
        self.direct_registered = True
        self.step_ok(
            "Marketplace + plugin " + self.did("registered directly", "would register directly"),
            "restart Claude Code to load it",
        )

    def marketplace(self) -> None:
        self.step_intro("Pointing Claude Code's marketplace at your clone.")
        self.direct_registered = False
        if not getattr(self, "cli_runs", True):
            # Already established in the preflight - do not spend two more timeouts
            # rediscovering it, and do not report it as a failure of this step.
            self.register_directly("the claude CLI is present but cannot be executed")
            return
        try:
            if self.mode == "update":
                proc = run_cmd(
                    ["claude", "plugin", "marketplace", "update", MARKETPLACE], timeout=120
                )
                if proc.returncode == 0:
                    self.step_ok(
                        f"Marketplace {MARKETPLACE} " + self.did("refreshed", "would refresh")
                    )
                    return
            # Fresh add (install mode, or an update where the marketplace was missing/broken).
            run_cmd(["claude", "plugin", "marketplace", "remove", MARKETPLACE], timeout=120)
            proc = run_cmd(["claude", "plugin", "marketplace", "add", self.repo], timeout=120)
        except OSError as exc:
            # CreateProcess refused the CLI binary itself (WinError 1260 = blocked by
            # group policy). The CLI is only a JSON writer here - write it ourselves.
            self.say_claude_launch_trace()
            self.register_directly(f"could not launch the claude CLI: {exc}")
            return
        if proc.returncode != 0:
            err = proc.stderr.strip() or proc.stdout.strip()
            self.say_claude_launch_trace()
            reason = cli_unusable_reason(err)
            if reason:
                self.register_directly(reason)
                return
            self.step_fail("Add marketplace", err or "claude plugin marketplace add failed")
        self.step_ok(
            f"Marketplace {MARKETPLACE} " + self.did("->", "would point at") + f" {self.repo}"
        )

    def plugin(self) -> None:
        verb = "Updating" if self.mode == "update" else "Installing"
        self.step_intro(f"{verb} the team plugin from that marketplace.")
        if not self.demo:
            # Live report, 2026-08-12: the claude CLI call below is fully blocking (up to
            # a 300s timeout) with nothing printed between this line and the eventual
            # result - on a slow network or corporate proxy this can genuinely take real
            # time, and with zero visual feedback in between it reads as hung rather than
            # working. One dim line to set the expectation; a real progress indicator
            # would need run_cmd to stream rather than fully capture output, a bigger
            # change not attempted here.
            self.say(self.style.dim("    (can take a moment - slow network or corporate proxy)"))
        if getattr(self, "direct_registered", False):
            # register_plugin_directly already wrote the installed-plugin record.
            self.step_ok(f"Plugin {PLUGIN_ID} registered directly (see previous step)")
            return
        try:
            if self.mode == "update":
                proc = run_cmd(["claude", "plugin", "update", PLUGIN_ID], timeout=300)
                if proc.returncode == 0:
                    self.step_ok(f"Plugin {PLUGIN_ID} " + self.did("updated", "would be updated"))
                    return
            run_cmd(["claude", "plugin", "uninstall", PLUGIN_ID], timeout=120)
            proc = run_cmd(["claude", "plugin", "install", PLUGIN_ID], timeout=300)
        except OSError as exc:
            self.say_claude_launch_trace()
            self.register_directly(f"could not launch the claude CLI: {exc}")
            return
        if proc.returncode != 0:
            err = proc.stderr.strip() or proc.stdout.strip()
            lowered = err.lower()
            reason = cli_unusable_reason(err)
            if reason:
                self.say_claude_launch_trace()
                self.register_directly(reason)
                return
            if "already installed" in lowered:
                # Already at the desired end state - informational, not a failure
                # (2026-08-07 user report: this was aborting the whole run via step_fail's
                # default fatal=True, for a condition that isn't actually a problem).
                self.step_ok(f"Plugin {PLUGIN_ID} already installed")
                return
            self.say_claude_launch_trace()
            self.step_fail("Install plugin", err or "claude plugin install failed")
        self.step_ok(f"Plugin {PLUGIN_ID} " + self.did("installed", "would be installed"))

    def persist(self) -> None:
        if self.demo:
            self.say(self.style.dim(f"    would save settings to {self.cfg_path}"))
            return
        self.cfg.update(
            {
                "repo_path": str(self.repo),
                "branch": self.branch,
                "last_run": datetime.now().strftime("%Y-%m-%d"),
            }
        )
        version = installed_version(self.repo) if self.repo else None
        if version:
            self.cfg["last_version"] = version
        if save_config(self.cfg_path, self.cfg):
            self.step_ok(f"Settings saved to {self.cfg_path}")
        else:
            # Read-only home or a locked config dir: a warning, never a crash.
            self.step_skip(
                "Settings", f"could not write {self.cfg_path} - continuing without saving"
            )

    def whats_new(self, previous: Optional[str]) -> None:
        """After a successful install/update: what did you just get."""
        s = self.style
        version = installed_version(self.repo) if self.repo else None
        if not version:
            if self.demo:
                self.say("")
                self.say(s.bold(s.cyan("What's new")))
                self.say(s.dim("  shown after a real run"))
            return
        self.say("")
        if previous and previous != version:
            self.say(s.bold(s.cyan(f"What's new: {previous} -> {version}")))
        else:
            self.say(s.bold(s.cyan(f"What's new in {version}")))
        headline = changelog_headline(self.repo / "CHANGELOG.md", version)
        if headline:
            self.say(f"  {headline}")
        overview = self.repo / "docs" / "releases" / f"{version}.md"
        if not overview.is_file():
            # Release cycles share one page (e.g. 0.33.md covers all 0.33.x).
            major_minor = ".".join(version.split(".")[:2])
            overview = self.repo / "docs" / "releases" / f"{major_minor}.md"
        if overview.is_file():
            self.say(f"  Overview: {overview}")
        self.say(f"  Full detail: {self.repo / 'CHANGELOG.md'}")

    # ---- summary

    def apply_scripts(self) -> list:
        """apply-*.sh present in the clone - human-run hook/settings steps, listed as reminders."""
        if not self.repo:
            return []
        found = sorted(self.repo.glob("apply-*.sh")) + sorted(
            (self.repo / "scripts").glob("apply-*.sh")
        )
        return [p.relative_to(self.repo).as_posix() for p in found]

    def print_summary(self, aborted: bool) -> None:
        s = self.style
        m = self.marks
        self.say("")
        self.say(s.bold(s.cyan("Summary" + (" (aborted)" if aborted else ""))))
        groups = (
            ("Completed", "ok", s.green, m["ok"]),
            ("Skipped", "skip", s.yellow, m["skip"]),
            ("Failed", "fail", s.red, m["fail"]),
        )
        for title, status, paint, mark in groups:
            rows = [(name, detail) for name, st, detail in self.tracker.steps if st == status]
            if not rows:
                continue
            self.say(paint(f"  {title}"))
            for name, detail in rows:
                suffix = f"  {s.dim('(' + detail + ')')}" if detail else ""
                self.say(f"    {paint(mark)} {name}{suffix}")
        if self.stashed:
            self.say(s.yellow("  Your local changes are stashed: git stash pop to restore."))
        if aborted:
            self.say("")
            self.say("Fix the failed step above and run me again - I'm safe to repeat.")
            self._demo_footer()
            return
        if self.subset == "setup" or self.code_stale:
            self.say("")
            self.say(
                s.yellow(
                    "Code not updated - run a full install or update when you want the latest."
                )
            )
        if self.subset in ("full", "setup"):
            self.say("")
            self.say(s.bold("Over to you:"))
            # ONE instruction, and it is `go` (2026-08-25 user request: "the over to you
            # instructions are too long and it should signpost users to virt-surv go, not
            # virt-surv configure"). Both were true. `go` offers first-time setup itself
            # (virt_team_launcher._offer_first_time_setup), so telling people to configure
            # first added a step that does not exist - and the old block spent ten lines
            # listing four commands for what is really one.
            fallback = (
                f"python {self.repo / 'install_helper.py'} --configure ."
                if self.repo
                else "install_helper.py --configure ."
            )
            self.say(
                f"  cd into your project and run {s.yellow('virt-surv go')} - it sets up a "
                "new project on first use, then launches Claude Code with resume-or-new "
                "already decided."
            )
            self.say(s.dim(f"  No alias yet? Use: {fallback}"))
            self.say(s.dim("  A Claude Code session already open elsewhere needs a restart."))
        self.say("")
        # The celebratory "summon the team" close is only accurate for a full/setup run
        # that actually finished clean - live-caught (fable UX review, 2026-08-05): a
        # failed-but-non-fatal step (e.g. "no usable clone found" in a diagnostic) still
        # left `aborted` False, so this printed regardless, inviting the user to summon
        # a team that was just reported as not working. Diagnostics/one-off subsets get
        # a plain close instead - they were never "installing the team" to begin with.
        any_failed = any(status == "fail" for _name, status, _detail in self.tracker.steps)
        if self.subset in ("full", "setup") and not any_failed:
            # The instruction is above; this said the same thing again three lines later.
            self.say(
                s.green(
                    "Done. (Or launch claude yourself and summon the team with "
                    "/compliance-surveillance-team:engage.)"
                )
            )
            hat = "🎩 " if _can_encode("🎩") else ""
            self.say(f"{hat}I look forward to working with you. - Morgan")
        elif any_failed:
            self.say(s.yellow("Finished with issues - see above."))
        else:
            self.say(s.dim("Nothing else to do - back to the menu."))
        self._demo_footer()

    def _demo_footer(self) -> None:
        if self.demo:
            self.say(self.style.yellow("DEMO MODE ended - nothing was executed or written."))

    @property
    def asks_on_screen(self) -> bool:
        """Whether this run's questions should be put on a screen rather than typed.

        TRUE ONLY WHEN THE SUBSET WAS CHOSEN ON PURPOSE. These steps are shared with the
        full install, which the owner has asked stays exactly as it is (2026-08-31) - and
        that is a reasonable thing to want: it is the most load-bearing path in the
        product, it asks a dozen questions in a deliberate order, and lifting them onto
        screens is a change to make on its own rather than as a side effect of fixing the
        one-off items.

        So a step reached from "Advanced -> Morgan's model" asks on a screen, and the same
        step reached as part of a full run asks exactly as it did yesterday.
        """
        return self.subset not in ("full", "setup", None)

    def agree(self, *, title, facts, detail, yes, no, prompt, default) -> bool:
        """A yes/no decision, on a screen when this subset was chosen on purpose."""
        if self.args.yes:
            return bool(default)
        if not self.asks_on_screen:
            return bool(confirm(prompt, default=default, assume_yes=False, style=self.style))
        return _agreed(
            self.style,
            title=title,
            facts=facts,
            detail=detail,
            yes=yes,
            no=no,
            assume_yes=False,
            prompt=prompt,
            default=default,
        )

    def pick_project(self, title: str, prompt: str):
        """Which project, on a screen when this subset was chosen on purpose.

        A Path, or None if the human left - which callers must treat as "do nothing",
        never as "use the current directory". Falling back to a default on a cancel is how
        a screen ends up acting on a project nobody named.
        """
        if not self.asks_on_screen:
            raw = ask(
                f"  Which project directory? (blank = {Path.cwd()})", ".", False, style=self.style
            )
            return Path(raw).expanduser().resolve()
        return _pick_project(self.style, title, prompt)

    def statusline_step(self) -> None:
        """Optional: wire the team status line into the USER-level Claude settings so it
        shows in every project. Opt-in (interactive yes, --statusline with --yes, or the
        menu's status-line-only choice); add-only with backup; a DIFFERENT existing
        statusLine is never overwritten without an explicit interactive yes. Windows
        note: the command runs via bash (Git Bash ships with Git for Windows). In demo
        the current file is read for real, but nothing is written or backed up."""
        self.step_intro("An optional status line: the team's state and session cost at a glance.")
        bash = find_bash()
        if sys.platform == "win32" and not bash:
            # The wired command runs bash; with Git Bash truly absent it would be a
            # broken setting. Honest skip instead of wiring it.
            self.step_skip(
                "Status line",
                "needs Git Bash (ships with Git for Windows) - install it and re-run",
            )
            return
        if bash and bash != shutil.which("bash"):
            self.say(self.style.dim(f"    (bash found off PATH at {bash} - wiring by full path)"))
        if self.subset == "statusline":
            wanted = True  # the user picked this from the menu
        elif self.args.yes:
            wanted = self.args.statusline  # unattended run: unchanged, flag-gated
        elif self.subset == "full" and self.quick_defaults:
            # 2026-08-07 user request: chose "go with defaults" at quick_setup_choice -
            # no further question, just wire it (still skipped above on Windows without
            # Git Bash, and the conflict-resolution prompt below still asks before
            # replacing a DIFFERENT existing statusLine).
            wanted = True
        else:
            wanted = confirm(
                "  Shall I wire the status line - it shows the team's state and session "
                "cost at zero token cost?",
                default=True if sys.stdin.isatty() else self.args.statusline,
                assume_yes=False,
                style=self.style,
            )
        if not wanted:
            self.step_skip("Status line", "skipped - bash scripts/apply-statusline.sh any time")
            return
        target = user_settings_path()
        settings = {}
        if target.is_file():
            try:
                settings = json.loads(target.read_text(encoding="utf-8-sig"))
                if not isinstance(settings, dict):
                    raise ValueError("settings root is not an object")
            except (OSError, ValueError) as exc:
                self.step_fail(
                    "Status line", f"{target} unreadable ({exc}) - not touching it", fatal=False
                )
                return
        # Bare `bash` when it resolves on PATH (portable across reinstalls); the full
        # discovered path only when that is the sole way to reach it.
        command = statusline_command(
            self.repo, "bash" if shutil.which("bash") else (bash or "bash")
        )
        # Display the existing command from the ALREADY-PARSED settings; a second
        # read of the file could race an editor or trip over a BOM.
        existing = current_statusline_command(settings)
        settings, verdict = merge_statusline(settings, command)
        if verdict == "already":
            self.step_ok("Status line", "already wired to this clone")
            return
        if verdict == "ours-moved":
            # Our own script at another path (an old clone location): update without a
            # scare prompt, but say what happened.
            self.say(
                self.style.dim(
                    "    Found my status line pointing at an older clone path - updating it."
                )
            )
        if verdict == "conflict":
            self.say(
                self.style.yellow(
                    f"    You already have a status line configured that is not mine:\n"
                    f"      {existing}"
                )
            )
            keep = self.agree(
                title="Status line",
                facts=[
                    ("head", "  Replace the status line you already have?\n"),
                    ("dim", f"  {target}\n"),
                ],
                detail=[
                    ("head", "Yours, now"),
                    ("plain", existing or "(none)"),
                    ("head", "The team's"),
                    ("plain", command),
                    (
                        "dim",
                        "A dated backup of settings.json is written before anything "
                        "is changed, either way.",
                    ),
                ],
                yes="replace it with the team's",
                no="keep the one I have",
                prompt="  Shall I replace it with the team's status line?",
                default=False,
            )
            if not keep:
                self.step_skip("Status line", "your existing statusLine kept")
                return
            settings["statusLine"] = {"type": "command", "command": command}
        if self.demo:
            self.say(self.style.dim(f"    would write statusLine into {target} (backup first)"))
            self.step_ok("Status line", "demo - nothing written")
            return
        if target.is_file():
            today = datetime.now().strftime("%Y-%m-%d")
            backup = target.with_name(f"settings.json.bak-{today}")
            n = 1
            while backup.exists():
                n += 1
                backup = target.with_name(f"settings.json.bak-{today}.{n}")
            backup.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
        target.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_text(target, json.dumps(settings, indent=2) + "\n")
        self.step_ok("Status line", f"wired in {target} (restart to see it)")

    def alias_step(self) -> None:
        """Optional, last step of a full install: offers the 'virt-surv' shell alias so
        the installer is reachable from any folder afterward, same outer-confirm pattern
        as statusline_step (2026-08-04 user request: "should be added on selecting a full
        install like other steps such as the statusline"). The INTERACTIVE default is
        True (2026-08-04 user feedback) - recommended, matching statusline's own default.
        An unattended `--yes` run still skips it (False) rather than inheriting that
        recommendation, same established pattern as docx/citations/split elsewhere in
        this file: a human physically present to see the per-file preview gets the
        inviting default, a silent/CI run gets the conservative one, since this edits the
        user's OWN shell rc file(s) (~/.bashrc/~/.zshrc/a PowerShell profile) - a bigger
        surprise than writing into Claude settings if nobody's watching. run_setup_alias
        does its own per-file preview + confirm regardless; this is only the outer "do
        you want this at all" gate."""
        self.step_intro(
            "Optional: the 'virt-surv' alias lets you launch this installer from any "
            "folder and run 'virt-surv configure'/'engage'/'onboard'/'archive'/"
            "'list-engagements' scoped to wherever you are."
        )
        if self.args.yes:
            wanted = False  # opt-in only - never touch shell rc files on an unattended run
        elif self.subset == "full" and self.quick_defaults:
            # 2026-08-07 user request: chose "go with defaults" at quick_setup_choice -
            # no further question, just do it. run_setup_alias still runs its own
            # per-file preview + confirm below (unaffected by this change).
            wanted = True
        else:
            # "Manually configure" chosen (or a subset other than "full"): the original
            # per-step question, unchanged - a REAL live terminal gets the inviting True
            # default; a non-tty, non-`--yes` run (piped input, a script) gets False
            # regardless - confirm() itself would otherwise silently take the True
            # default with no human actually there to see it (live-caught by
            # test_demo_mode_executes_nothing_and_writes_nothing, 2026-08-04).
            wanted = confirm(
                "  Shall I also set up the 'virt-surv' alias?",
                default=True if sys.stdin.isatty() else False,
                assume_yes=False,
                style=self.style,
            )
        if not wanted:
            self.step_skip(
                "Alias setup", "skipped - python install_helper.py --setup-alias any time"
            )
            return
        rc = run_setup_alias(self.style, self.marks, self.args.yes, self.demo, self.args.repo)
        if rc == 0:
            self.step_ok("Alias setup", "see above for what was added")
        else:
            self.step_fail("Alias setup", "see above for detail", fatal=False)

    def format_preferences_step(self) -> None:
        """Standalone, easily re-runnable: change a project's preferences any time (menu
        option 6) - most users install once and never re-run the full flow, so these
        need a path that isn't buried inside first-time project enablement (2026-07-30
        user feedback). Both preferences here are PROJECT-WIDE (team-preferences.json),
        not per-engagement - a deliberate simplification over an earlier per-engagement
        design for regulatory citations.

        TWO STAGES, kept visibly separate (2026-08-04 user feedback: "project settings
        and can also set the machine's defaults is confusing wording and flow" /
        "are we changing project or machine defaults" - the old flow answered several
        questions that read as project-scoped, then bolted on an abstract "your default
        for new/unconfigured projects" question at the end with no restated values).
        Stage 1 sets ONE named project's preferences (this step's main purpose). Stage 2,
        clearly announced and framed as optional/separate, offers to ALSO apply the SAME
        already-chosen values as this machine's default for OTHER, future new projects -
        restated concretely (not "your default") so it's unambiguous which target is
        being changed at each moment."""
        self.step_intro(
            "Sets ONE project's preferences: whether controlled documents (BRD, FSD, "
            "etc.) also get a Word (.docx) copy, whether detection-logic work cites "
            "regulatory obligations by default, and whether to turn any of the seven "
            "supported analysers (ruff, mypy, bandit, black, sqlfluff, shfmt, gitleaks) "
            "on or off for this project. At the end, a separate, clearly optional "
            "question offers to also make these THIS MACHINE's default for other new "
            "projects you configure later."
        )
        project = self.pick_project("Which project?", "  Which project directory?")
        if project is None:
            self.step_skip("Project preferences", "nothing chosen")
            return
        if not project.is_dir():
            self.step_fail("Project preferences", f"not a directory: {project}")
            return
        # HAND OVER to the launcher's settings screen, which edits this same file and
        # edits it better: sixteen rows with every value visible at once, grouped, with an
        # explanation pane - against a handful of blocking questions in a fixed order with
        # no way to skip forward or go back (2026-08-28 UX review, owner decision).
        #
        # The point is not presentation. The two ask DIFFERENT questions about the same
        # team-preferences.json: this step's own intro used to admit it, listing the
        # preferences it does not cover and telling the reader to go somewhere else for
        # them. That is the drift _editor_rows was written to prevent, reappearing across
        # the entry-point boundary. Handing over is what removes it - one screen, one
        # question set, one file - where adding the missing questions here would only have
        # made two longer lists to keep in sync.
        #
        # None means the launcher could not be run at all, and only then do the prompts
        # below take over: a user must never be left with nothing.
        if not self.demo:
            handed = _run_launcher_settings(project, self.style)
            if handed is not None:
                self.step_ok("Project preferences", "edited in the team's own settings screen")
                return
        prefs_path = project / ".claude" / "team-preferences.json"
        existing = _read_json_dict(prefs_path)
        (
            docx_current,
            citations_current,
            review_tools_current,
            _map_skeleton_current,
            _statusline_show_map_current,
        ) = _project_preference_defaults(existing, self.cfg)
        self.say(self.style.bold(f"\n  For {project.name}:"))
        self.say(
            self.style.dim(
                f"    currently: docx by default = {'on' if docx_current else 'off'}, "
                f"regulatory citations = {'on' if citations_current else 'off'}"
            )
        )
        docx_wanted = self.agree(
            title="Document formats",
            facts=[
                ("head", "  Produce .docx by default?\n"),
                ("dim", f"  for {project.name}\n"),
                ("dim", f"  currently {'on' if docx_current else 'off'}\n"),
            ],
            detail=[
                ("head", "What this changes"),
                (
                    "dim",
                    "Controlled documents in this project are also written as .docx "
                    "alongside the markdown and HTML. It is per-project: other projects "
                    "keep their own answer, and nothing already written is changed.",
                ),
            ],
            yes="yes, produce .docx",
            no="no, markdown and HTML only",
            prompt="  Produce .docx by default for controlled documents in this project?",
            default=docx_current,
        )
        citations_wanted = self.agree(
            title="Regulatory citations",
            facts=[
                ("head", "  Cite regulatory obligations by default?\n"),
                ("dim", f"  for {project.name}\n"),
                ("dim", f"  currently {'on' if citations_current else 'off'}\n"),
            ],
            detail=[
                ("head", "What this changes"),
                (
                    "dim",
                    "Detection-logic work in this project names the specific obligation "
                    "each rule serves. Leave it on unless this project's work is not "
                    "regulatory.",
                ),
            ],
            yes="yes, cite obligations",
            no="no, leave them out",
            prompt="  Detection-logic work in this project cites regulatory obligations by "
            "default - keep that on?",
            default=citations_current,
        )
        review_tools_wanted = _ask_review_tool_overrides(self.style, False, review_tools_current)
        # Read-only against a throwaway synthetic file - runs even in demo mode, same as
        # run_configure's identical check, so a hanging/network-blocked tool (the
        # semgrep/pip-audit shape) is caught before it's ever written as "on".
        review_tools_wanted = _apply_forced_on_validation(
            self.style, self.marks, review_tools_wanted, review_tools_current
        )
        summary = (
            f"docx={'on' if docx_wanted else 'off'}, "
            f"citations={'on' if citations_wanted else 'off'}, "
            f"review-tools={_format_review_tools(review_tools_wanted)}"
        )
        self.say(self.style.bold("\n  Separately - this machine's default:"))
        save_as_default = self.agree(
            title="Also this machine's default?",
            facts=[
                ("head", "  Reuse these choices for future projects?\n"),
                ("dim", f"  you just set {summary}\n"),
                ("dim", f"  for {project.name}\n"),
            ],
            detail=[
                ("head", "What this changes"),
                (
                    "dim",
                    "Only what a DIFFERENT, new project starts with when you configure one "
                    "later. This project is already set either way, and no existing project "
                    "is touched.",
                ),
            ],
            yes="yes, make them the default",
            no=f"no, just {project.name}",
            prompt=f"  You just set {summary} for {project.name}. Also make THESE SAME "
            "choices this machine's default whenever you configure a DIFFERENT, new "
            "project later (not this one, which is already set above)?",
            default=False,
        )
        if self.demo:
            self.step_ok(
                "Project preferences",
                f"would set {summary} for {project.name}"
                + (" (and save as this machine's new-project default)" if save_as_default else ""),
            )
            return
        if save_as_default:
            self.cfg["default_docx"] = docx_wanted
            self.cfg["default_regulatory_citations"] = citations_wanted
            self.cfg["default_review_tools"] = review_tools_wanted
            save_config(self.cfg_path, self.cfg)
        if (
            docx_wanted == docx_current
            and citations_wanted == citations_current
            and review_tools_wanted == review_tools_current
        ):
            self.step_ok(
                "Project preferences",
                f"{project.name} unchanged"
                + (" (this machine's new-project default saved)" if save_as_default else ""),
            )
            return
        write_team_preferences(
            project,
            extra_formats=["docx"] if docx_wanted else [],
            regulatory_citations=citations_wanted,
            review_tools=review_tools_wanted,
        )
        self.step_ok(
            "Project preferences",
            f"{summary} for {project.name} ({prefs_path})"
            + (" - also saved as this machine's new-project default" if save_as_default else ""),
        )

    def dashboard_step(self) -> None:
        """Standalone (Advanced submenu option 7, subset="dashboard"): rebuild the local
        team dashboard on demand. 2026-08-09: originally added as a full-install/update
        closing step (a fresh dashboard link right after setup, nothing extra to
        remember). 2026-08-11 user request: pulled back out of the default full-install
        path - a rebuild is a one-off action to reach for, not something every
        install/update should pay for unconditionally; `/dashboard` and this menu item
        cover the same ground on demand. Never fatal (fatal=False throughout) - no Node,
        no network for a first `npm install`, or a build failure all just skip with a
        plain reason; the plugin itself works fully without this ever succeeding.
        `run_cmd` is already swapped for the dry-run stand-in in --demo (see
        make_demo_runner) - no separate demo branch
        needed here, same as every other step in this class."""
        self.step_intro(
            "Rebuilds the local team dashboard (dashboard-ui/) so there's a fresh link as "
            "soon as setup finishes - the same thing /dashboard does later, run once now."
        )
        if not self.repo:
            self.step_skip("Dashboard", "no usable clone found - run a full install first")
            return
        ui_dir = self.repo / "dashboard-ui"
        if not ui_dir.is_dir():
            self.step_skip("Dashboard", "dashboard-ui/ not present in this checkout")
            return
        node = _find_node()
        npm = shutil.which("npm.cmd") or shutil.which("npm")
        if not node or not npm:
            self.step_skip(
                "Dashboard", "Node/npm not found - run /dashboard later once Node is set up"
            )
            return
        if not (ui_dir / "node_modules").is_dir():
            proc = run_cmd([npm, "install"], cwd=ui_dir, timeout=600)
            if proc.returncode != 0:
                self.step_fail(
                    "Dashboard", "npm install failed - run /dashboard later to retry", fatal=False
                )
                return
        proc = run_cmd([npm, "run", "dashboard"], cwd=ui_dir, timeout=300)
        if proc.returncode != 0:
            self.step_fail("Dashboard", "build failed - run /dashboard later to retry", fatal=False)
            return
        out = ui_dir / "dist" / "index.html"
        self.step_ok("Dashboard " + self.did("rebuilt", "would be rebuilt"), str(out))

    def fixbashrc_step(self) -> None:
        """Standalone (Advanced submenu option 8, subset="fixbashrc"): checks whether
        ~/.bashrc is slow to source non-interactively (the same check --check-env's
        '.bashrc source time' row runs) and, ONLY if it finds a real issue, applies the
        fix automatically - no separate 'run --fix-bashrc after you see the warning'
        round trip, since choosing this menu item IS the consent (2026-08-14 user
        request: 'check if there is an issue with bash then auto apply if there is').
        Reuses run_fix_bashrc's own backup + idempotency-check + atomic-write path
        unchanged (assume_yes=True here is what skips its interactive 'Add it?' prompt -
        the write itself is exactly as safe as the standalone --fix-bashrc flag)."""
        self.step_intro(
            "Checks whether ~/.bashrc is slow to source non-interactively - the same cost "
            "Claude Code's Bash tool pays on every call - and fixes it automatically if so."
        )
        bash_path = find_bash()
        status, detail = _check_shell_startup_time(bash_path)
        if status in ("OK", "SKIP"):
            self.step_ok("Bash startup", detail)
            return
        print(f"  {self.style.yellow('!')} Bash startup: {detail}")
        # 2026-08-14 user request: describe what's about to happen BEFORE it happens -
        # this path has no interactive "Add it?" pause to convey that at write-time (see
        # docstring above), so state it explicitly here instead. run_fix_bashrc's own
        # preview (the exact snippet + the "guards everything below" risk note) still
        # prints too, right after this - this is the what/why, that's the literal diff.
        print(
            self.style.dim(
                f"  About to modify: {Path.home() / '.bashrc'}\n"
                "  What: prepends a 2-line guard that skips the rest of the file for "
                "non-interactive shells (like Claude Code's Bash tool calls), so slow "
                "startup steps stop running on every call. Your interactive terminal use "
                "is unaffected.\n"
                "  Safety: the existing file is backed up first (dated, never overwritten); "
                "nothing runs or is removed, only prepended."
            )
        )
        rc = run_fix_bashrc(self.style, self.marks, assume_yes=True, demo=self.demo)
        if rc == 0:
            self.step_ok("~/.bashrc " + self.did("fixed", "would be fixed"))
        else:
            self.step_fail("~/.bashrc fix", "see output above", fatal=False)

    def clean_plugin_cache_step(self) -> None:
        """Standalone (Advanced submenu option 9, subset="cleanplugincache"): lists every
        cached install of this plugin and offers to remove the stale ones - never the
        currently-active install. Unlike fixbashrc_step, this does NOT auto-apply
        (assume_yes stays whatever args.yes already was, via run_clean_plugin_cache's own
        default=assume_yes confirm() call): removing a directory is not backed-up-and-
        reversible the way a text-file edit is, so it keeps the normal interactive
        confirmation unless the user already passed --yes to the whole run."""
        self.step_intro(
            "Lists every cached install of this plugin under ~/.claude/plugins/ and offers "
            "to remove the stale ones - never the one actually in use."
        )
        rc = run_clean_plugin_cache(self.style, self.marks, self.args.yes, self.demo)
        if rc == 0:
            self.step_ok("Plugin cache " + self.did("cleaned", "would be cleaned"))
        else:
            self.step_fail("Plugin cache cleanup", "see output above", fatal=False)

    def machine_defaults_offer(self) -> None:
        """Last of the optional post-install steps for a full install/update (2026-08-07
        user request: "we are missing an option to be able to modify settings on install
        too" - project-level setup moved entirely to virt-surv configure/engage, but
        THIS MACHINE's own defaults deserve a way back in during install instead of only
        being reachable via the separate Advanced -> Machine defaults menu item). Under
        quick_defaults, auto-skips rather than asking (2026-08-12 user request extending
        "go with defaults" to mean zero further questions everywhere) - its own default
        answer is already "no, don't walk through it", so respecting that without asking
        is skipping, never an auto-APPLIED machine-wide change; still asks otherwise,
        unless --yes, matching machine_defaults_step's own interactive-only nature."""
        if self.args.yes:
            self.step_skip(
                "Machine defaults",
                "non-interactive - Advanced -> Machine defaults any time, or edit "
                f"{self.cfg_path} directly",
            )
            return
        if self.subset == "full" and self.quick_defaults:
            self.step_skip(
                "Machine defaults",
                "go-with-defaults chosen - unchanged, Advanced -> Machine defaults any time",
            )
            return
        if not confirm(
            "  Shall I also walk through this machine's default settings now (citations, "
            "review-tools, codebase-map skeleton, Morgan's model)?",
            default=False,
            assume_yes=False,
            style=self.style,
        ):
            self.step_skip("Machine defaults", "unchanged - Advanced -> Machine defaults any time")
            return
        self.machine_defaults_step()

    def _machine_defaults_grid(self):
        """The grid tier of machine_defaults_step, or None when it cannot run.

        Isolated behind an explicit import helper rather than a bare `import` in a try:
        this file sits at the clone root and scripts/ is a sibling, so a bare import
        raises ImportError and an `except Exception` would leave the tier permanently and
        silently off. That shape has been found three times in two days."""
        try:
            installer_app = _import_from_scripts("installer_app")
            if installer_app is None:
                return None
            return _tiered_installer_screen(
                "grid_screen",
                _machine_rows,
                _machine_apply,
                _machine_help,
                _this_module(),
                title="This machine's defaults",
                repo=self.repo,
            )
        except Exception:
            if os.environ.get("VIRT_SURV_DEBUG_APP"):
                raise
            return None

    def machine_defaults_step(self) -> None:
        """View/edit THIS MACHINE's defaults directly, no project needed (Advanced menu
        option 6, 2026-08-04 user request: "let's just have a clearer view and edit of
        the machine's defaults too" / "so these can be viewed and edited"). Previously
        the ONLY way to see or change docx/citations/review-tools was as a side effect
        of configuring one specific project (Project preferences' "also save as
        default" question) - no direct view, and no way to change them without
        touching a project. Writes the exact same installer.json keys that side effect
        does (default_docx/default_regulatory_citations/default_review_tools), so the
        two paths stay interchangeable - this is just the direct route.

        Morgan's default model is included too (2026-08-05 user request: "Morgan's
        model too should be machine default") - a DIFFERENT storage location
        (~/.claude/settings.json, Claude Code's own user-level settings, which Claude
        Code itself layers under any project's own `model` key with no extra plumbing
        needed on our side) but shown/edited here alongside the installer.json-backed
        settings since all four are "this machine's defaults" from the user's point of
        view."""
        self.step_intro(
            "This machine's defaults - what any NEW/unconfigured project inherits until "
            "it sets its own preferences. Does not touch any project's own settings - a "
            "project's own choice (team-preferences.json, or its own settings.json "
            "`model` key) always overrides these."
        )
        # GRID first, prompts wherever it cannot run (2026-08-28). Same _machine_rows /
        # _machine_apply underneath either way, so the two tiers cannot disagree about what
        # a change does - the pattern the launcher settled on after its own two tiers
        # drifted apart. None means the screen could not start; False means it ran and
        # nothing was changed, which is a decision and must NOT fall through to the
        # prompts (the launcher conflated exactly those two once, and cancelling dumped
        # the user into the tier they had just declined).
        if not self.demo:
            outcome = self._machine_defaults_grid()
            if outcome is not None:
                self.step_ok(
                    "Machine defaults " + ("updated" if outcome else "unchanged"),
                    "" if outcome else "nothing was changed",
                )
                return
        docx_current = bool(self.cfg.get("default_docx", False))
        citations_current = bool(self.cfg.get("default_regulatory_citations", False))
        review_tools_current = self.cfg.get("default_review_tools") or {}
        map_skeleton_current = bool(self.cfg.get("default_map_skeleton", True))
        statusline_show_map_current = bool(self.cfg.get("default_statusline_show_map", False))
        model_current = _read_json_dict(user_settings_path()).get("model")
        launch_cmd_current = self.cfg.get(_CLAUDE_LAUNCH_CMD_KEY) or ""
        self.say(
            self.style.dim(
                f"    currently: docx by default = {'on' if docx_current else 'off'}, "
                f"regulatory citations = {'on' if citations_current else 'off'}, "
                f"review-tools = {review_tools_current or '(all auto)'}, "
                f"codebase-skeleton drift checking = {'on' if map_skeleton_current else 'off'}, "
                f"statusline map indicator = {'on' if statusline_show_map_current else 'off'}, "
                f"Morgan's model = {model_current or f'(unset - {ORCHESTRATOR_MODEL_DEFAULT} applies)'}, "
                "'virt-surv go' launch command = "
                f"{launch_cmd_current or '(unset - prompted on first virt-surv alias setup)'}"
            )
        )
        docx_wanted = confirm(
            "  Produce .docx by default for new projects?",
            default=docx_current,
            assume_yes=False,
            style=self.style,
        )
        citations_wanted = confirm(
            "  New projects cite regulatory obligations by default - keep that on?",
            default=citations_current,
            assume_yes=False,
            style=self.style,
        )
        map_skeleton_wanted = confirm(
            "  New projects get codebase-skeleton drift checking by default - flags when "
            "the codebase-map docs go stale (a mapped area's code changed since it was "
            "last verified, or a cited file:line no longer exists), useful if the team "
            "relies on the map to brief new work accurately. Experimental, ADR-007 Phase 1?",
            default=map_skeleton_current,
            assume_yes=False,
            style=self.style,
        )
        statusline_show_map_wanted = confirm(
            "  New projects show map-skeleton status (map:on/off) in the statusline too - "
            "off by default, keeps the line short unless wanted?",
            default=statusline_show_map_current,
            assume_yes=False,
            style=self.style,
        )
        review_tools_wanted = _ask_review_tool_overrides(self.style, False, review_tools_current)
        # Read-only against a throwaway synthetic file - runs even in demo mode, same
        # rationale as the identical check in format_preferences_step/run_configure.
        review_tools_wanted = _apply_forced_on_validation(
            self.style, self.marks, review_tools_wanted, review_tools_current
        )
        picked = (
            ask(
                "  Morgan's default model - opus / sonnet / sonnet-4-6 / default (clear), "
                "blank to leave unchanged",
                "",
                False,
                style=self.style,
            )
            .strip()
            .lower()
        )
        model_changing = picked != ""
        if picked in ("default", "reset", "clear"):
            model_wanted: Optional[str] = None
        elif picked in ORCHESTRATOR_MODELS:
            model_wanted = picked
        elif picked == "":
            model_wanted = model_current
        else:
            self.say(
                self.style.yellow(
                    f"    expected opus/sonnet/sonnet-4-6/default, got {picked!r} - left unchanged"
                )
            )
            model_wanted = model_current
            model_changing = False
        if model_wanted == "opus":
            self.say(self.style.yellow(f"    {ORCHESTRATOR_OPUS_NOTE}"))
        launch_cmd_picked = ask(
            "  'virt-surv go's Claude Code launch command (e.g. 'claude' or your own alias "
            "like 'cc') - blank to leave unchanged",
            "",
            False,
            style=self.style,
        ).strip()
        launch_cmd_wanted = launch_cmd_picked or launch_cmd_current
        summary = (
            f"docx={'on' if docx_wanted else 'off'}, "
            f"citations={'on' if citations_wanted else 'off'}, "
            f"review-tools={_format_review_tools(review_tools_wanted)}, "
            f"map-skeleton={'on' if map_skeleton_wanted else 'off'}, "
            f"statusline-map={'on' if statusline_show_map_wanted else 'off'}, "
            f"model={model_wanted or 'default'}, "
            f"'virt-surv go' launch command={launch_cmd_wanted or '(unset)'}"
        )
        if self.demo:
            self.step_ok("Machine defaults", f"would set {summary}")
            return
        if model_changing:
            model_ok, model_message = write_orchestrator_model_default(model_wanted)
            if not model_ok:
                self.step_fail("Machine defaults", model_message, fatal=False)
                return
        if (
            docx_wanted == docx_current
            and citations_wanted == citations_current
            and review_tools_wanted == review_tools_current
            and map_skeleton_wanted == map_skeleton_current
            and statusline_show_map_wanted == statusline_show_map_current
            and not model_changing
            and launch_cmd_wanted == launch_cmd_current
        ):
            self.step_ok("Machine defaults", "unchanged")
            return
        self.cfg["default_docx"] = docx_wanted
        self.cfg["default_regulatory_citations"] = citations_wanted
        self.cfg["default_review_tools"] = review_tools_wanted
        self.cfg["default_map_skeleton"] = map_skeleton_wanted
        self.cfg["default_statusline_show_map"] = statusline_show_map_wanted
        if launch_cmd_wanted:
            self.cfg[_CLAUDE_LAUNCH_CMD_KEY] = launch_cmd_wanted
        save_config(self.cfg_path, self.cfg)
        self.step_ok("Machine defaults", f"{summary} ({self.cfg_path})")
        if launch_cmd_wanted != launch_cmd_current:
            # A v5 alias reads this config at every 'go', so the change is already
            # live for it. The refresh offer stays for machines whose installed alias
            # predates v5 (those still have a command BAKED in - the 2026-08-16
            # "doesn't seem to stick" report); on v5 it's a no-op skip.
            if confirm(
                "  Refresh the 'virt-surv' shell alias too? (needed once if it was "
                "installed before v5 - a current alias picks the change up on the "
                "next 'go' automatically)",
                default=True,
                assume_yes=False,
                style=self.style,
            ):
                if run_setup_alias(self.style, self.marks, assume_yes=True) == 0:
                    # run_setup_alias prints the same reminder when it writes; repeat
                    # it here anyway - THIS flow's last screen is the machine-defaults
                    # summary, and the reload is the one step only the user can do (a
                    # child process cannot touch its parent shell).
                    self.say(
                        f"  {self.style.yellow('->')} Run "
                        f"{self.style.yellow('. $PROFILE')} (PowerShell) or "
                        f"{self.style.yellow('source ~/.bashrc')} (bash), or open a "
                        "new terminal, before the next 'virt-surv go' - this session "
                        "still holds the old alias until then."
                    )

    def model_step(self) -> None:
        """Standalone, easily re-runnable (menu option 8): change or reset Morgan's (the
        orchestrator's) own model for one project - PER PROJECT ONLY, matching this
        item's own menu label (fable UX review, 2026-08-05: the flow used to ALSO ask
        "make this the default for new projects too?", contradicting that label - the
        Advanced -> "Machine defaults" item is the direct, non-contradictory path for
        the global default now). Only Morgan is exposed here - the 16 specialist
        subagents each have their own `model:` frontmatter in `.claude/agents/*.md`,
        edited directly; that's a bigger, separate change this option doesn't attempt yet."""
        self.step_intro(
            "Morgan's own model for this project - sonnet is the documented default "
            "(testing to date has not yielded any better results from opus for "
            "orchestration); opus remains available for critical/high-stakes engagements "
            "if you want the extra margin, and sonnet-4-6 pins the previous generation "
            "explicitly if you want that instead of the current one. All three are written "
            "as an exact model ID, never a bare alias - Claude Code's generic 'sonnet' "
            "alias resolves to a different actual model depending on API provider. Or "
            "reset back to sonnet. (This machine's own default model lives under "
            "Advanced -> Machine defaults instead.)"
        )
        project = self.pick_project("Which project?", "  Which project directory?")
        if project is None:
            self.step_skip("Morgan's model", "nothing chosen")
            return
        if not project.is_dir():
            self.step_fail("Morgan's model", f"not a directory: {project}")
            return
        settings_path = project / ".claude" / "settings.json"
        current = _read_json_dict(settings_path).get("model") or "(unset - account default)"
        self.say(self.style.dim(f"    currently: {current}"))
        ok, message = ask_and_set_model(
            project, self.style, self.args.yes, self.demo, offer_global_scope=False
        )
        if not ok:
            self.step_fail("Morgan's model", message)
            return
        self.step_ok("Morgan's model", message)

    def tool_check_step(self) -> None:
        """Standalone, easily re-runnable (menu option 9): verifies code-reviewer's
        analysers actually produce clean, undecorated output on THIS machine - see the
        module comment above run_tool_check for why this is a per-environment check, not
        a documentation claim (terminal/color detection is not guaranteed uniform,
        especially on Git Bash/Windows)."""
        self.step_intro(
            "Runs each installed analyser (gitleaks, bandit, mypy, ruff) against a "
            "trivial clean file with the flags code-reviewer is told to use, and checks "
            "whether the output actually comes back clean here. (semgrep and pip-audit "
            "are deliberately excluded - see code-reviewer.md for why.)"
        )
        if run_tool_check(self.style, self.marks) == 0:
            self.step_ok("Analyser output cleanliness", "all installed analysers clean")
        else:
            self.step_fail(
                "Analyser output cleanliness",
                "see detail above - informational, reviews still work",
                fatal=False,
            )

    def env_check_step(self) -> None:
        """Standalone, easily re-runnable (menu option 10): comprehensive environment
        report - interpreter resolution, guard hooks, encoding, the plugin-root bootstrap,
        bash, and analyser output cleanliness - covers the OTHER Windows-specific issues
        this repo has independently hit, beyond analyser output alone (menu option 9)."""
        self.step_intro(
            "Runs interpreter resolution, guard hooks, an encoding round-trip, the "
            "plugin-root bootstrap, bash availability and analyser output cleanliness - "
            "one report instead of debugging blind from a bare hook error."
        )
        if run_env_check(self.style, self.marks, self.args.repo) == 0:
            self.step_ok("Comprehensive environment check", "environment looks clean")
        else:
            self.step_fail(
                "Comprehensive environment check",
                "see detail above - informational, not a blocker",
                fatal=False,
            )

    def selftest_step(self) -> None:
        """Standalone, easily re-runnable (menu option 11): a throwaway synthetic
        'review this code' engagement - guard hooks, real analyser detection, and the
        engagement-state lifecycle end to end. No LLM involved; see run_selftest's own
        docstring for the full rationale."""
        self.step_intro(
            "A throwaway synthetic engagement: guard hooks, real analyser detection on "
            "a planted issue, and the engagement-state lifecycle (init/findings/render/"
            "close-gate/archive) end to end - no LLM invocation, no network."
        )
        if run_selftest(self.style, self.marks, self.args.repo) == 0:
            self.step_ok("Self-test", "the engagement substrate works on this machine")
        else:
            self.step_fail(
                "Self-test",
                "see detail above and the debug bundle - informational, not a blocker",
                fatal=False,
            )

    def hook_latency_step(self) -> None:
        """Standalone, easily re-runnable (menu option 5 under Diagnostics): measures real
        PreToolUse hook latency on THIS machine - repeated cold starts, the real
        guard-launcher end to end, and a concurrent fan-out simulation - and always writes
        the full numbers to a file, feeding the ADR-014 persistent-daemon decision with
        actual evidence instead of guesswork. Slower than the other diagnostics on
        purpose - say so up front."""
        self.step_intro(
            "Measures real hook latency: repeated interpreter cold starts, the real "
            "guard-launcher end to end, and a genuinely concurrent fan-out simulation - "
            "the evidence docs/adr/ADR-014 calls for before deciding whether a persistent "
            "guard daemon is worth building. Slower than the other checks (repeated + "
            "concurrent measurement) - always writes the full numbers to a file, pass or "
            "fail, since the data is the point here."
        )
        if run_hook_latency_diagnostic(self.style, self.marks, self.args.repo) == 0:
            self.step_ok("Hook latency diagnostic", "measured - see the data file for full numbers")
        else:
            self.step_fail(
                "Hook latency diagnostic",
                "see detail above and the data file - informational, not a blocker",
                fatal=False,
            )

    def adr014_smoke_step(self) -> None:
        """Standalone (Diagnostics menu option 6, subset="adr014smoke"): thin wrapper
        around run_adr014_smoke_test, same shape as hook_latency_step around
        run_hook_latency_diagnostic - keeps the CLI flag (--check-adr014-spike) and the
        menu path sharing one implementation instead of two."""
        self.step_intro(
            "ADR-014 spike: starts a REAL guard-daemon prototype process, sends it real "
            "concurrent requests, and measures actual daemon-vs-cold-start latency - "
            "prototype code, not production, not wired into any live hook path (see "
            "docs/internal/adr-014-spike/README.md for exactly what this does and doesn't "
            "answer). Takes under a minute; output prints in full once it finishes."
        )
        rc = run_adr014_smoke_test(self.style, self.marks, self.args.repo)
        if rc == 0:
            self.step_ok(
                "ADR-014 spike smoke test", "all checks passed - see output above for the numbers"
            )
        elif rc is None:
            self.step_skip(
                "ADR-014 spike smoke test", "docs/internal/adr-014-spike/smoke_test.py not found"
            )
        else:
            self.step_fail(
                "ADR-014 spike smoke test",
                "one or more checks failed - see output above; this is prototype code, a "
                "failure here is real evidence for ADR-014, not a plugin defect",
                fatal=False,
            )

    def daemon_start_step(self) -> None:
        """Standalone (Diagnostics menu option 7, subset="daemonstart"): thin wrapper
        around run_daemon_start_diagnostic, same shape as adr014_smoke_step - keeps the
        CLI flag (--check-daemon-start) and the menu path sharing one implementation."""
        self.step_intro(
            "Actually starts the real guard daemon (foreground AND the exact detached "
            "spawn production uses) in a throwaway temp directory, and reports exactly "
            "what happens - built because a failed detached spawn is silent by design "
            "in production (must never brick a hook call), which makes 'why isn't the "
            "daemon starting' otherwise impossible to debug from the outside."
        )
        rc = run_daemon_start_diagnostic(self.style, self.marks, self.args.repo)
        if rc == 0:
            self.step_ok("Guard daemon start diagnostic", "both checks passed - see output above")
        else:
            self.step_fail(
                "Guard daemon start diagnostic",
                "see output above and the data file - this is the actual production spawn "
                "failure, hand the file back whole",
                fatal=False,
            )

    def enable_step(self) -> None:
        """Optional: enable the team for a project right now. Interactive only - non-
        interactive runs use the --enable-project / --permissions flags. Delegates to
        run_configure() for everything after "which directory" (2026-08-12 consolidation -
        an onboarding UX audit found this method had grown its own ~180-line copy of
        run_configure's permissions/env-tuning/betas/docx/model questions, with wording
        that had drifted from it, six of run_configure's thirteen preferences never asked
        at all here (citations/split/workflow-dispatch/standards-critique/map-skeleton/
        statusline-map), and a model-scope bug reproduced from before it was fixed at the
        other "set the model" call site (model_step, 2026-08-05: asking a project-scoped
        question then silently offering to also change the GLOBAL default). One call into
        run_configure now means exactly one place that knows what "project enablement"
        means - see run_configure's own docstring for the full question list, its own
        quick-defaults gate, and its demo-mode support (this method no longer needs its
        own separate demo branch at all)."""
        self.step_intro("Switching the team on per project - that keeps your token cost down.")
        if self.args.yes:
            self.step_skip(
                "Project enablement",
                "non-interactive - use --enable-project <dir> (and --permissions <dir>)",
            )
            return
        if self.subset != "enable":  # the menu's enable-only choice skips the re-ask
            wanted = confirm(
                "  Shall I enable the team for a project now (per-project scope)?",
                default=False,
                assume_yes=False,
                style=self.style,
            )
            if not wanted:
                # No follow-up "still set Morgan's model?" question here (removed
                # 2026-08-05 user report: it fired on EVERY full run/update, even for a
                # project already enabled and already configured - not something the
                # average user should be asked about on every routine update. It was
                # added 2026-08-03 because there was no other way to reach the model
                # question after declining enablement; that's no longer true - Advanced
                # -> "Morgan's model" (per project) and Advanced -> "Machine defaults"
                # (this machine's default) are both directly reachable any time.
                self.step_skip(
                    "Project enablement",
                    "later: run /plugin inside Claude Code from the project, or "
                    "`virt-surv configure`",
                )
                return
        raw = ask(
            f"  Which project directory? (blank = {Path.cwd()})", ".", False, style=self.style
        )
        target = Path(raw)
        # quick_defaults only ever means anything on the "full" install/update plan (set
        # by quick_setup_choice, which only that plan runs) - the standalone "enable"
        # subset always walks through run_configure's own questions individually,
        # matching this method's pre-2026-08-12 behavior exactly (belt-and-braces even if
        # quick_defaults were ever set True out of band here, same guard the old inline
        # implementation used throughout).
        run_configure(
            target,
            self.style,
            self.marks,
            assume_yes=(self.subset == "full" and self.quick_defaults),
            demo=self.demo,
        )

    # ---- orchestration

    def build_plan(self) -> list:
        """(title, step) rows for the chosen subset; titles may be lazy callables so
        they can reflect choices made by earlier steps (branch, mode)."""
        if self.subset == "setup":
            return [
                ("Preflight checks", self.preflight),
                ("Locate existing clone", self.locate_clone_asis),
                ("Guard interpreter cache", self.prewarm_guard_cache),
                ("Pending hook fixes", self.check_pending_hook_fixes),
                ("Claude Code marketplace", self.marketplace),
                (
                    lambda: "Plugin " + ("update" if self.mode == "update" else "install"),
                    self.plugin,
                ),
                ("Status line (optional)", self.statusline_step),
                ("Enable for a project (optional)", self.enable_step),
            ]
        if self.subset == "update":
            # JUST the update (2026-08-25 user request: "the only way to update the plugin is
            # via option 1 and that executes a full cycle, pip the lot - how can we safely
            # allow a quick update without the full 13-step process where the user needs to
            # confirm everything again").
            #
            # Six steps, and the omissions are the point. Status line, alias, permissions,
            # preferences, model, machine defaults and pip are all things the human already
            # decided; re-asking them is not thoroughness, it is a reason not to update. What
            # remains is exactly what makes new code take effect: pull it, then refresh the
            # installed copy Claude Code actually loads.
            #
            # The branch is NOT re-asked either - it is whatever this machine is already
            # tracking. An update that silently changed channel would be a different thing
            # wearing an update's name.
            return [
                ("Preflight checks", self.preflight_lite),
                ("Local clone", self.resolve_repo),
                (lambda: f"Sync to origin/{self.branch}", self.sync_branch),
                ("Guard interpreter cache", self.prewarm_guard_cache),
                ("Pending hook fixes", self.check_pending_hook_fixes),
                ("Claude Code marketplace", self.marketplace),
                (
                    lambda: "Plugin " + ("update" if self.mode == "update" else "install"),
                    self.plugin,
                ),
            ]
        if self.subset == "statusline":
            return [
                ("Locate existing clone", self.locate_clone_asis),
                ("Status line", self.statusline_step),
            ]
        if self.subset == "enable":
            return [
                ("Preflight checks", self.preflight),
                ("Enable for a project", self.enable_step),
            ]
        if self.subset == "check":
            return [
                ("Preflight checks", self.preflight_lite),
                ("Check for updates", self.check_updates_step),
            ]
        if self.subset == "formats":
            return [
                ("Project preferences", self.format_preferences_step),
            ]
        if self.subset == "model":
            return [
                ("Morgan's model", self.model_step),
            ]
        if self.subset == "machinedefaults":
            return [
                ("Machine defaults", self.machine_defaults_step),
            ]
        if self.subset == "dashboard":
            return [
                ("Locate existing clone", self.locate_clone_asis),
                ("Dashboard", self.dashboard_step),
            ]
        if self.subset == "fixbashrc":
            return [
                ("Fix ~/.bashrc", self.fixbashrc_step),
            ]
        if self.subset == "cleanplugincache":
            return [
                ("Clean plugin cache", self.clean_plugin_cache_step),
            ]
        if self.subset == "toolcheck":
            return [
                ("Analyser output cleanliness", self.tool_check_step),
            ]
        if self.subset == "envcheck":
            return [
                ("Comprehensive environment check", self.env_check_step),
            ]
        if self.subset == "selftest":
            return [
                ("Self-test", self.selftest_step),
            ]
        if self.subset == "hooklatency":
            return [
                ("Hook latency diagnostic", self.hook_latency_step),
            ]
        if self.subset == "adr014smoke":
            return [
                ("ADR-014 spike smoke test", self.adr014_smoke_step),
            ]
        if self.subset == "daemonstart":
            return [
                ("Guard daemon start diagnostic", self.daemon_start_step),
            ]
        if self.subset == "codeintel":
            # Standalone so it can be tested and re-run on its own, rather than only as
            # step 8 of a full install. On a machine where the install failed once - no
            # network at the time, a proxy, a Python that has since changed - this is the
            # retry, and it is also the honest way to CHECK the outcome: it reports
            # "already available" without doing anything when the library is present.
            return [
                ("Code intelligence", self.code_intel_step),
            ]
        return [
            ("Preflight checks", self.preflight),
            ("Release channel", self.choose_branch),
            ("Local clone", self.resolve_repo),
            (lambda: f"Sync to origin/{self.branch}", self.sync_branch),
            ("Guard interpreter cache", self.prewarm_guard_cache),
            ("Pending hook fixes", self.check_pending_hook_fixes),
            ("Quick setup or manual?", self.quick_setup_choice),
            ("Optional pip requirements", self.optional_pip),
            ("Code intelligence (optional)", self.code_intel_step),
            ("Claude Code marketplace", self.marketplace),
            (lambda: "Plugin " + ("update" if self.mode == "update" else "install"), self.plugin),
            ("Status line", self.statusline_step),
            ("Alias setup", self.alias_step),
            ("Machine defaults (optional)", self.machine_defaults_offer),
        ]

    def run(self) -> int:
        s = self.style
        if self.subset in ("full", "setup"):
            self.mode = decide_mode(self.args.mode, self.cfg)
            self.say(s.dim(f"Mode: {self.mode} (config: {self.cfg_path})"))
        elif self.subset == "update":
            # An update run that thinks it is installing takes the slower path and mislabels
            # itself: the step rendered as "Plugin install" inside a screen titled "Updating
            # the team" (seen on screen, 2026-08-29). decide_mode answers "update" whenever
            # the configured clone exists, which is exactly the case this subset is for.
            # Both marketplace() and plugin() then try their update fast path first and fall
            # back to the remove-and-add they were already doing, so this is strictly the
            # better route, not a different one.
            self.mode = decide_mode(self.args.mode, self.cfg)
        plan = self.build_plan()
        aborted = False
        cancelled = False
        try:
            for number, (title, step) in enumerate(plan, 1):
                self.step_header(number, len(plan), title() if callable(title) else title)
                step()
            if self.subset in ("full", "setup"):
                previous = self.cfg.get("last_version")
                self.persist()
                self.whats_new(previous)
        except InstallAbort:
            aborted = True
        except KeyboardInterrupt:
            # Ctrl-C at a prompt or mid-subprocess: clean note, summary, exit 130.
            self.say("")
            self.say(self.style.yellow("Cancelled."))
            self.tracker.record("Cancelled", "fail", "interrupted (Ctrl-C)")
            aborted = True
            cancelled = True
        except subprocess.TimeoutExpired as exc:
            self.tracker.record("Command timed out", "fail", str(exc.cmd))
            aborted = True
        except OSError as exc:
            # A command that failed to launch or a filesystem surprise mid-step:
            # a clear FAIL row and the summary, never a traceback.
            self.tracker.record("Step failed", "fail", str(exc))
            aborted = True
        self.print_summary(aborted)
        if cancelled:
            return 130
        return 1 if aborted else 0


# ------------------------------------------------------------------ permissions merge


def workspace_is_trusted(project_dir: Path, home: Optional[Path] = None) -> Optional[bool]:
    """Has this workspace been trusted in Claude Code? None when it cannot be determined.

    This matters far more than it looks. Claude Code IGNORES the allow rules in a project's
    settings until the workspace is trusted, and says so only on stderr - "Ignoring 12
    permissions.allow entries ... this workspace has not been trusted". So every rule this
    installer writes can be silently inert: the user is told permissions are configured and
    then gets prompted anyway (found on a fresh Windows machine, 2026-08-26). In an
    UNATTENDED run those are not prompts at all, they are denials, and the run quietly does
    less than it was asked to.

    Trust is recorded per project in the user-level Claude config, under
    projects.<path>.hasTrustDialogAccepted."""
    config = (home or Path.home()) / ".claude.json"
    try:
        data = json.loads(config.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    projects = data.get("projects")
    if not isinstance(projects, dict):
        return None
    try:
        wanted = str(Path(project_dir).expanduser().resolve())
    except (OSError, ValueError):
        return None
    for key, entry in projects.items():
        try:
            if str(Path(key).expanduser().resolve()) != wanted:
                continue
        except (OSError, ValueError):
            continue
        return bool(entry.get("hasTrustDialogAccepted")) if isinstance(entry, dict) else None
    return False  # config exists, no entry for this project - not trusted yet


def warn_if_untrusted(project_dir: Path, style: Style, mark_map: dict) -> None:
    """Say plainly when the allow rules will be ignored. Never writes trust itself.

    Trusting a workspace is a security decision Claude Code asks its own question about, and
    setting it from here would answer that question on the user's behalf without them ever
    seeing it. So this reports and points; it does not decide."""
    if workspace_is_trusted(project_dir) is not False:
        return  # trusted, or genuinely unknown - do not cry wolf
    warn = mark_map.get("warn") or "!"
    print("")
    print(
        style.yellow(
            f"  {warn} This project has not been TRUSTED in Claude Code yet, so it will "
            "IGNORE every allow entry above."
        )
    )
    print(
        style.dim(
            "      Open Claude Code in this folder once and accept the trust prompt. Until "
            "then you will still be asked for permission, and an unattended run will simply "
            "be refused."
        )
    )


def run_permissions(project_dir: Path, style: Style, mark_map: dict) -> int:
    """Standalone opt-in step: merge RECOMMENDED_ALLOW into <project>/.claude/settings.json.

    Add-only with a dated backup of any existing file; refuses on unparseable JSON rather
    than clobbering. Human-run by definition (this script is a terminal tool)."""
    ok, fail = mark_map["ok"], mark_map["fail"]
    project = project_dir.expanduser().resolve()
    if not project.is_dir():
        print(f"{fail} not a directory: {project}")
        return 1
    target = project / ".claude" / "settings.json"
    settings: dict = {}
    if target.is_file():
        try:
            settings = json.loads(target.read_text(encoding="utf-8-sig"))
            if not isinstance(settings, dict):
                raise ValueError("settings root is not an object")
        except (OSError, ValueError) as exc:
            print(f"{fail} {target} is not readable JSON ({exc}) - refusing to touch it")
            return 1
    # The team's own files get Read rules too, resolved for this machine. Without them the
    # first action of every engagement prompts (2026-08-25).
    reads = team_read_entries() + team_script_entries()
    try:
        settings, added = merge_allow(settings, RECOMMENDED_ALLOW + reads)
    except InstallAbort as exc:
        print(f"{fail} {exc}")
        return 1
    if not added:
        total = len(RECOMMENDED_ALLOW) + len(reads)
        print(f"{ok} {target}: all {total} recommended entries already present")
        warn_if_untrusted(project, style, mark_map)
        return 0
    if target.is_file():
        today = datetime.now().strftime("%Y-%m-%d")
        backup = target.with_name(f"settings.json.bak-{today}")
        n = 1
        while backup.exists():
            n += 1
            backup = target.with_name(f"settings.json.bak-{today}.{n}")
        backup.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"{ok} backed up existing settings to {backup.name}")
    target.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(target, json.dumps(settings, indent=2) + "\n")
    print(
        f"{ok} {target}: added {len(added)} allow entr{'y' if len(added) == 1 else 'ies'} (add-only; deny rules and hooks untouched)"
    )
    warn_if_untrusted(project, style, mark_map)
    print(style.dim("    Inspect any time with /permissions inside Claude Code."))
    return 0


def _run_env_upsert(
    project_dir: Path, style: Style, mark_map: dict, entries: dict, label: str
) -> int:
    """Shared upsert-into-settings.json "env" block implementation for run_env_tuning and
    run_env_tuning_betas - only the entries dict and the log label differ. Project-level
    only. Feasible and sufficient: Claude Code layers a settings-file "env" value over the
    shell's own (Environment variables doc, "Precedence"), so writing it once at project
    level covers both Linux and PowerShell shells without a platform-specific shell-profile
    edit; there is deliberately no user-level equivalent here (unlike the model-default
    flow) since these are per-project values, not an account-wide preference.

    Upsert, not add-only (unlike run_permissions): a key already present with a DIFFERENT
    value is corrected; any other env var already in the file, and every other top-level
    key (permissions, hooks, model, ...), is left untouched. Dated backup of any existing
    file before writing, same as run_permissions; refuses on unparseable JSON rather than
    clobbering."""
    ok, fail = mark_map["ok"], mark_map["fail"]
    project = project_dir.expanduser().resolve()
    if not project.is_dir():
        print(f"{fail} not a directory: {project}")
        return 1
    target = project / ".claude" / "settings.json"
    settings: dict = {}
    if target.is_file():
        try:
            settings = json.loads(target.read_text(encoding="utf-8-sig"))
            if not isinstance(settings, dict):
                raise ValueError("settings root is not an object")
        except (OSError, ValueError) as exc:
            print(f"{fail} {target} is not readable JSON ({exc}) - refusing to touch it")
            return 1
    try:
        settings, added, updated = merge_env(settings, entries=entries)
    except InstallAbort as exc:
        print(f"{fail} {exc}")
        return 1
    if not added and not updated:
        print(f"{ok} {target}: all {len(entries)} {label} env vars already set correctly")
        return 0
    if target.is_file():
        today = datetime.now().strftime("%Y-%m-%d")
        backup = target.with_name(f"settings.json.bak-{today}")
        n = 1
        while backup.exists():
            n += 1
            backup = target.with_name(f"settings.json.bak-{today}.{n}")
        backup.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"{ok} backed up existing settings to {backup.name}")
    target.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(target, json.dumps(settings, indent=2) + "\n")
    bits = []
    if added:
        bits.append(f"added {len(added)}")
    if updated:
        bits.append(f"updated {len(updated)}")
    total = len(added) + len(updated)
    print(
        f"{ok} {target}: {', '.join(bits)} {label} env var{'s' if total != 1 else ''} "
        "(other env vars and settings untouched)"
    )
    return 0


def run_env_tuning(project_dir: Path, style: Style, mark_map: dict) -> int:
    """Standalone opt-in step (on by default during --configure/--engage): upsert
    RECOMMENDED_ENV - API-timeout/stream-idle/output-size tuning - into
    <project>/.claude/settings.json's "env" block. See _run_env_upsert for the mechanics."""
    return _run_env_upsert(project_dir, style, mark_map, RECOMMENDED_ENV, "tuning")


def run_env_tuning_betas(project_dir: Path, style: Style, mark_map: dict) -> int:
    """Standalone opt-in step (OFF by default, unlike run_env_tuning): upsert
    EXPERIMENTAL_BETAS_ENV (CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1) into
    <project>/.claude/settings.json's "env" block - a workaround for an LLM gateway that
    rejects Anthropic's beta tool-schema fields (2026-08-07 live report: a haiku-tier
    subagent call - review-scorer is the only agent in this roster pinned to model: haiku -
    failed with "tools.0.custom.eager_input_streaming: Extra inputs are not permitted").
    Only worth turning on if you're actually hitting this - see EXPERIMENTAL_BETAS_ENV's
    own comment for the tradeoff (MCP tool search disabled, every MCP tool loads upfront)."""
    return _run_env_upsert(
        project_dir, style, mark_map, EXPERIMENTAL_BETAS_ENV, "beta-fields-workaround"
    )


def run_orchestrator_model(
    project_dir: Path, model: Optional[str], style: Style, mark_map: dict
) -> int:
    """Standalone opt-in step: set or reset Morgan's model for one project. Human-run by
    definition (this script is a terminal tool) - Claude Code itself blocks the model from
    writing settings.json (ADR-002)."""
    ok, fail = mark_map["ok"], mark_map["fail"]
    project = project_dir.expanduser().resolve()
    if not project.is_dir():
        print(f"{fail} not a directory: {project}")
        return 1
    if model is not None and model not in ORCHESTRATOR_MODELS:
        print(
            f"{fail} model must be one of {ORCHESTRATOR_MODELS} or omitted (reset), not {model!r}"
        )
        return 1
    if model == "opus":
        print(style.yellow(f"    {ORCHESTRATOR_OPUS_NOTE}"))
    success, message = write_orchestrator_model(project, model)
    if not success:
        print(f"{fail} {message}")
        return 1
    print(f"{ok} {message}")
    return 0


def run_orchestrator_model_default(model: Optional[str], style: Style, mark_map: dict) -> int:
    """Standalone opt-in step: set (or clear) the DEFAULT model for new/unconfigured
    projects, at Claude Code's user-level settings. Human-run by definition."""
    ok, fail = mark_map["ok"], mark_map["fail"]
    if model is not None and model not in ORCHESTRATOR_MODELS:
        print(
            f"{fail} model must be one of {ORCHESTRATOR_MODELS} or omitted (clear), not {model!r}"
        )
        return 1
    if model == "opus":
        print(style.yellow(f"    {ORCHESTRATOR_OPUS_NOTE}"))
    success, message = write_orchestrator_model_default(model)
    if not success:
        print(f"{fail} {message}")
        return 1
    print(f"{ok} {message}")
    return 0


# The officially supported, individually configurable code-review analysers (2026-08-04) -
# every other analyser scripts/check-review-tools.sh probes stays best-effort/presence-only;
# these seven are the ones a human can force on/off per project, because these seven have
# ALSO been proven (via _TOOL_OUTPUT_CHECKS further below) to run single-file, dependency-
# free and network-free - the same bar semgrep/pip-audit failed. Keep in sync with
# _TOOL_OUTPUT_CHECKS and scripts/check-review-tools.sh's own REVIEW_TOOLS array (a test
# enforces all three match).
_REVIEW_TOOLS = ("ruff", "mypy", "bandit", "gitleaks", "sqlfluff", "black", "shfmt")
_REVIEW_TOOL_STATES = ("auto", "on", "off")


# THIS MACHINE's defaults as a grid, in the shape the launcher's settings screen already
# speaks: rows carry a stable KEY, and dispatch resolves through it rather than through a
# screen position. Both of this repo's positional-dispatch bugs came from the other choice
# (a renumbered Advanced menu redirecting an action, and a grouped settings screen toggling
# the wrong row), so the pattern is copied deliberately, not incidentally.
#
# Grouped by the decision being made, not by where the value is stored - most of these live
# in installer.json and one in the user-level Claude settings, which is true and of no
# interest to someone deciding what new projects should produce.
_MACHINE_GROUPS = (
    ("What new projects produce", ("default_docx", "default_regulatory_citations")),
    ("Codebase map", ("default_map_skeleton", "default_statusline_show_map")),
    ("Morgan's model", ("model",)),
    ("Review tools", tuple(f"review_tools.{name}" for name in _REVIEW_TOOLS)),
)

_MACHINE_LABELS = {
    "default_docx": "controlled-document export",
    "default_regulatory_citations": "regulatory citations",
    "default_map_skeleton": "codebase-map drift checking",
    "default_statusline_show_map": "statusline map indicator",
    "model": "Morgan's model",
}

_MACHINE_HELP = {
    "default_docx": (
        "New projects also produce the Word format alongside .md and .html for controlled "
        "documents."
    ),
    "default_regulatory_citations": (
        "Detections cite the specific obligation they serve, by default, in new projects."
    ),
    "default_map_skeleton": (
        "Flags when the codebase map goes stale - a mapped area's code changed since it was "
        "last verified, or a cited file:line no longer exists. Experimental (ADR-007)."
    ),
    "default_statusline_show_map": ("Adds map:on/off to the statusline. Off keeps the line short."),
}


def _machine_rows(cfg=None):
    """[(group, label, value, on, key)] for this machine's defaults.

    ONE snapshot, shared by the grid and by anything printing a summary, so the two can
    never disagree about what is currently set - the failure the launcher's _editor_rows
    exists to prevent, and which this file reproduced across the entry-point boundary."""
    cfg = load_config(config_path()) if cfg is None else cfg
    tools = cfg.get("default_review_tools") or {}
    model = _read_json_dict(user_settings_path()).get("model") or ""
    values = {
        "default_docx": bool(cfg.get("default_docx", False)),
        "default_regulatory_citations": bool(cfg.get("default_regulatory_citations", False)),
        "default_map_skeleton": bool(cfg.get("default_map_skeleton", True)),
        "default_statusline_show_map": bool(cfg.get("default_statusline_show_map", False)),
    }
    rows = []
    for title, keys in _MACHINE_GROUPS:
        first = True
        for key in keys:
            group = title if first else ""
            first = False
            if key == "model":
                # Just "default": the value column is narrow and "default (sonnet)"
                # clipped mid-word against the divider. Which model that means is in the
                # pane, where there is room to say it.
                shown = model or "default"
                rows.append((group, _MACHINE_LABELS[key], shown, bool(model), key))
            elif key.startswith("review_tools."):
                tool = key.split(".", 1)[1]
                state = tools.get(tool, "auto")
                rows.append((group, tool, state, state != "auto", key))
            else:
                on = values[key]
                rows.append((group, _MACHINE_LABELS[key], "on" if on else "off", on, key))
    return rows


def _machine_help(key: str) -> str:
    """The explanation pane's text for one row."""
    if key.startswith("review_tools."):
        tool = key.split(".", 1)[1]
        return (
            f"Whether reviews run {tool}. auto: use it when it is installed. on: require it "
            "and report when it is missing. off: never run it."
        )
    if key == "model":
        return (
            "The model Morgan the orchestrator runs on. A project's own settings always wins "
            f"over this; unset means {ORCHESTRATOR_MODEL_DEFAULT}."
        )
    return _MACHINE_HELP.get(key, "")


def _machine_apply(key: str) -> str:
    """Toggle or cycle one machine default by KEY. Returns a short note, "" when silent.

    Writes the same installer.json keys the project-configure path writes, so the two
    routes stay interchangeable - this is only the direct one."""
    cfg = load_config(config_path())
    if key == "model":
        order = ("",) + ORCHESTRATOR_MODELS
        settings_path = user_settings_path()
        settings = _read_json_dict(settings_path)
        current = settings.get("model") or ""
        nxt = order[(order.index(current) + 1) % len(order)] if current in order else order[1]
        if nxt:
            settings["model"] = nxt
        else:
            settings.pop("model", None)
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(
            json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        return ORCHESTRATOR_OPUS_NOTE if nxt == "opus" else ""
    if key.startswith("review_tools."):
        tool = key.split(".", 1)[1]
        tools = dict(cfg.get("default_review_tools") or {})
        current = tools.get(tool, "auto")
        at = _REVIEW_TOOL_STATES.index(current) if current in _REVIEW_TOOL_STATES else 0
        nxt = _REVIEW_TOOL_STATES[(at + 1) % len(_REVIEW_TOOL_STATES)]
        if nxt == "auto":
            tools.pop(tool, None)  # absent IS auto - never store the default as an override
        else:
            tools[tool] = nxt
        cfg["default_review_tools"] = tools
        save_config(config_path(), cfg)
        return ""
    if key in ("default_docx", "default_regulatory_citations", "default_statusline_show_map"):
        cfg[key] = not bool(cfg.get(key, False))
    elif key == "default_map_skeleton":
        cfg[key] = not bool(cfg.get(key, True))
    else:
        return ""
    save_config(config_path(), cfg)
    return ""


def _parse_review_tool_overrides(raw: str) -> tuple:
    """'ruff=off, mypy=on' -> ({"ruff": "off", "mypy": "on"}, []). Unknown tool names,
    unknown states and blank/malformed chunks never crash the caller - they're returned
    separately as `rejected` (the original chunk text) instead, so the caller can WARN
    on them rather than silently dropping (fable UX review, 2026-08-05: entering
    'mypy=off, semgrep=on' resulted in review-tools={'mypy': 'off'} with zero mention of
    semgrep - readable as "I turned semgrep on" when nothing happened, worse than a
    plain typo since semgrep is deliberately unsupported here, not just misspelled)."""
    overrides = {}
    rejected = []
    for raw_chunk in raw.split(","):
        chunk = raw_chunk.strip()
        if not chunk:
            continue
        name, _, state = chunk.partition("=")
        name, state = name.strip().lower(), state.strip().lower()
        if name in _REVIEW_TOOLS and state in _REVIEW_TOOL_STATES:
            overrides[name] = state
        else:
            rejected.append(chunk)
    return overrides, rejected


_REVIEW_TOOL_STATES = ("auto", "on", "off")


def _review_tool_grid(current: dict):
    """The seven analyser overrides on a grid. The resulting dict, or None if no screen.

    None and an unchanged dict are different answers and the caller must not conflate
    them: None means fall back to the prompt, while "ran and changed nothing" is a
    decision. The launcher merged those two once and cancelling dumped the user into the
    tier they had just declined.
    """
    state = dict(current)

    def rows_fn():
        return [
            (
                "Analysers" if index == 0 else "",
                tool,
                state.get(tool, "auto"),
                state.get(tool, "auto") != "auto",
                tool,
            )
            for index, tool in enumerate(_REVIEW_TOOLS)
        ]

    def apply_fn(key):
        # Dispatch by KEY, never by row position - this repo has shipped that bug twice.
        nxt = _REVIEW_TOOL_STATES[
            (_REVIEW_TOOL_STATES.index(state.get(key, "auto")) + 1) % len(_REVIEW_TOOL_STATES)
        ]
        if nxt == "auto":
            state.pop(key, None)
        else:
            state[key] = nxt
        return f"{key}={nxt}"

    def help_fn(key):
        # The machine screen's own words, so what auto/on/off mean cannot drift between
        # the two places this is set.
        return _machine_help(f"review_tools.{key}")

    changed = _tiered_installer_screen(
        "grid_screen",
        rows_fn,
        apply_fn,
        help_fn,
        _this_module(),
        title="Review-tool overrides",
        repo=_repo_hint(),
    )
    return None if changed is None else state


def _ask_review_tool_overrides(style: Style, assume_yes: bool, current: dict) -> dict:
    """One compact prompt for the seven-tool on/off/auto overrides instead of seven
    separate confirm()s - most sessions change zero or one tool, not all seven. Returns
    the full resulting {tool: state} dict (existing overrides plus this prompt's changes,
    with any tool explicitly reset to "auto" removed) - callers write the return value
    straight back via write_team_preferences(review_tools=...)."""
    if not assume_yes:
        # GRID first, the prompt wherever it cannot run. Same states and the same help
        # text underneath either way.
        picked = _review_tool_grid(current)
        if picked is not None:
            return picked
    shown = ", ".join(f"{t}={current.get(t, 'auto')}" for t in _REVIEW_TOOLS)
    raw = ask(
        f"  Review-tool overrides (currently: {shown}) - e.g. 'mypy=off,black=on', "
        "blank for no change",
        "",
        assume_yes,
        style=style,
    )
    parsed, rejected = _parse_review_tool_overrides(raw)
    for chunk in rejected:
        print(
            style.yellow(
                f"    ignored '{chunk}' - not one of {'/'.join(_REVIEW_TOOLS)}=auto|on|off"
            )
        )
    merged = dict(current)
    for name, state in parsed.items():
        if state == "auto":
            merged.pop(name, None)
        else:
            merged[name] = state
    return merged


def _format_review_tools(overrides: dict) -> str:
    """{"mypy": "off", "black": "on"} -> "mypy=off,black=on" - matches the exact
    'tool=state' syntax the override prompt accepts, instead of Python's dict repr
    (fable UX review, 2026-08-05: summary lines showed review-tools={'mypy': 'off'})."""
    if not overrides:
        return "(all auto)"
    return ",".join(f"{name}={state}" for name, state in overrides.items())


def _apply_forced_on_validation(style: Style, mark_map: dict, wanted: dict, current: dict) -> dict:
    """Wraps _validate_forced_on_tools for the two call sites (run_configure,
    format_preferences_step): finds tools newly set to "on" this pass (not already "on"
    before), live-validates just those, and REMOVES the ones that failed validation from
    `wanted` - a plain dict.update() with the validator's result would be a no-op for the
    failures, since removed keys aren't present in the update source to overwrite anything
    with."""
    newly_forced_on = {t: s for t, s in wanted.items() if s == "on" and current.get(t) != "on"}
    if not newly_forced_on:
        return wanted
    validated = _validate_forced_on_tools(style, mark_map, newly_forced_on)
    for tool in newly_forced_on:
        if tool not in validated:
            wanted.pop(tool, None)
    return wanted


def _validate_forced_on_tools(style: Style, mark_map: dict, overrides: dict) -> dict:
    """Before accepting an "on" override, live-probes that ONE tool the same way
    --check-tools does - the exact check that would have caught semgrep/pip-audit's
    corp-proxy hang before either was ever relied on for real. A tool whose probe comes
    back NOISY or ERROR (including a timeout - the network-blocked shape) is downgraded
    back to "auto" instead of silently honoured, with a clear warning; SKIP (not
    installed yet) is left as "on" untouched - that is a real choice the human just
    made, no different from any other tool being missing under "auto"."""
    forced_on = [t for t, state in overrides.items() if state == "on"]
    if not forced_on:
        return overrides
    ok, fail = mark_map["ok"], mark_map["fail"]
    validated = dict(overrides)
    with tempfile.TemporaryDirectory(prefix="virt-surv-it-toolcheck-") as tmp:
        for name, status, detail in probe_analyser_output(Path(tmp), only=set(forced_on)):
            if status in ("NOISY", "ERROR"):
                print(
                    style.yellow(
                        f"  {fail} {name}: {status} - {detail} - not forcing 'on', "
                        "leaving at auto instead"
                    )
                )
                validated.pop(name, None)
            elif status == "OK":
                print(style.dim(f"    {ok} {name}: verified clean, forcing 'on'"))
    return validated


def write_team_preferences(
    project: Path,
    extra_formats: Optional[list] = None,
    regulatory_citations: Optional[bool] = None,
    large_context_review_split: Optional[bool] = None,
    parallel_dispatch_via_workflow: Optional[bool] = None,
    standards_critique: Optional[bool] = None,
    map_skeleton: Optional[bool] = None,
    statusline_show_map: Optional[bool] = None,
    review_tools: Optional[dict] = None,
    guard_daemon: Optional[bool] = None,
) -> bool:
    """Project-scoped preferences (`.claude/team-preferences.json`), merge-only (a
    pre-existing file's other keys, and any key not passed here, are preserved) and
    best-effort (never raises):

    - extra_formats: which EXTRA output formats controlled documents get automatically,
      beyond the always-required .md + .html. Currently the only valid extra is "docx"
      (scripts/render_docx.py). Never changes the .md/.html requirement - additive only.
    - regulatory_citations: whether detection-logic work cites the specific regulatory
      obligation it serves (CLAUDE.md §2 / ADR-001). Defaults to True (on) whenever the
      key is absent - only an explicit False turns it off project-wide.
    - large_context_review_split: whether a large, multi-component review is split by
      component from the start instead of discovering the need for it from a failed
      review call (docs/team-operating-guide.md's orchestration-discipline section).
      Defaults to False (off) whenever the key is absent.
    - parallel_dispatch_via_workflow: whether independent review-pass fan-outs go through
      the Claude Code Workflow tool when it is available (deterministic concurrency;
      docs/team-operating-guide.md's dispatch rule). Defaults to True (on) whenever the
      key is absent - only an explicit False turns it off. Like large_context_review_split,
      deliberately no machine-wide tier.
    - standards_critique: whether the DoD "Critiqued against the named standard" pass runs -
      a second, independent agent re-reading a finished review against its profession's named
      criteria (BABOK / ISO 29119 / SR 11-7-shaped, per docs/review/output-format.md; a full
      extra review pass, not a section of the review it checks). Defaults to False (off)
      whenever the key is absent - an explicit True turns it on project-wide. Like
      large_context_review_split, deliberately no machine-wide tier.
    - map_skeleton: whether check_map() runs MAP-DRIFT/MAP-DEAD-POINTER for a codebase map
      with a Paths column (ADR-007 Phase 1 Chunk C/D). Defaults to False (off) whenever the
      key is absent - unlike large_context_review_split, this one DOES have a machine-wide
      default tier (installer.json default_map_skeleton), same as docx/citations.
    - statusline_show_map: whether scripts/statusline.sh's render includes a `map:on/off`
      field. Defaults to False (off) whenever the key is absent, same machine-wide default
      tier as map_skeleton (installer.json default_statusline_show_map) - separate from
      map_skeleton itself so a project can have drift-checking on without a longer
      statusline, or vice versa.
    - review_tools: {tool: "on"|"off"} overrides for the _REVIEW_TOOLS set; "auto" (the
      implicit default for any tool not listed) means "use it if present, skip silently
      if not" - never stored literally, so the file only ever records actual overrides.
    - guard_daemon: whether run-guard.sh's PreToolUse guards route through the persistent
      ADR-014 daemon instead of a fresh interpreter per call (this preference alone does
      nothing on a project that hasn't applied the daemon files - see
      scripts/apply-guard-daemon.sh - since run-guard.sh checks `[ -f "$DAEMON_CLIENT" ]`
      before ever using it). **Unlike every other preference in this function, absence of
      this key does NOT mean "off"** - run-guard.sh's own check (`grep -q '"guard_daemon"
      *: *true'`) only ever matches an explicit `true`; there is no "default true when
      absent" logic at the shell level to lean on. 2026-08-12 user request: "should be on
      by default" - the caller (run_configure) is responsible for actively passing
      `True` during configuration so the key gets WRITTEN, not for relying on any implicit
      default here. Deliberately no machine-wide tier, same precedent as
      large_context_review_split/standards_critique.

    Pass only the preference(s) you want to change; omitted arguments leave the
    corresponding key untouched (or unset, which reads as the default)."""
    try:
        target = project / ".claude" / "team-preferences.json"
        prefs = _read_json_dict(target)
        if extra_formats is not None:
            prefs["extra_formats"] = sorted(set(extra_formats))
        if regulatory_citations is not None:
            prefs["regulatory_citations"] = bool(regulatory_citations)
        if large_context_review_split is not None:
            prefs["large_context_review_split"] = bool(large_context_review_split)
        if parallel_dispatch_via_workflow is not None:
            prefs["parallel_dispatch_via_workflow"] = bool(parallel_dispatch_via_workflow)
        if standards_critique is not None:
            prefs["standards_critique"] = bool(standards_critique)
        if map_skeleton is not None:
            prefs["map_skeleton"] = bool(map_skeleton)
        if statusline_show_map is not None:
            prefs["statusline_show_map"] = bool(statusline_show_map)
        if guard_daemon is not None:
            prefs["guard_daemon"] = bool(guard_daemon)
        if review_tools is not None:
            cleaned = {k: v for k, v in review_tools.items() if v != "auto"}
            if cleaned:
                prefs["review_tools"] = dict(sorted(cleaned.items()))
            else:
                prefs.pop("review_tools", None)
        _write_json_backup(target, prefs)
        return True
    except OSError:
        return False


# Short, human-typed tokens map to EXACT model IDs, never a bare alias like "sonnet" -
# 2026-08-06: found live that Claude Code's "sonnet" alias resolves to a DIFFERENT actual
# model depending on API provider (Sonnet 5 on the direct Anthropic API, Sonnet 4.6 on
# Claude Platform on AWS, Sonnet 4.5 on Bedrock/other platforms) - a project pinned to the
# alias could silently run an older model than intended, with no error and no visible
# signal beyond the statusline's display_name. Pinning to the exact ID (the documented fix,
# https://code.claude.com/docs/en/model-config.md) makes the written value unambiguous and
# provider-independent. "sonnet-4-6" is offered as its own explicit choice (not just
# reachable by luck of provider) for anyone who deliberately wants that generation pinned.
ORCHESTRATOR_MODEL_IDS = {
    "opus": "claude-opus-5",
    "sonnet": "claude-sonnet-5",
    "sonnet-4-6": "claude-sonnet-4-6",
}
ORCHESTRATOR_MODELS = tuple(ORCHESTRATOR_MODEL_IDS)  # ("opus", "sonnet", "sonnet-4-6")
# Testing to date has not yielded any better results from opus for orchestration than
# sonnet, so sonnet is the default. This is the token "reset to default" resolves to
# (ORCHESTRATOR_MODEL_IDS["sonnet"] = "claude-sonnet-5" is the value actually written).
ORCHESTRATOR_MODEL_DEFAULT = "sonnet"
# Shown when a human picks opus explicitly - it remains available, it just isn't the
# default, since nothing observed so far justifies the extra cost for the orchestrator
# role specifically (unlike the four specialist agents that keep their own opus tier on
# independent grounds - docs/agent-design.md).
ORCHESTRATOR_OPUS_NOTE = (
    "Testing to date has not yielded any better results from opus for orchestration than "
    "sonnet, which is why sonnet is the default. Opus remains available if you want the "
    "extra margin for critical or high-stakes engagements."
)


def _write_model_to_settings_file(target: Path, model: Optional[str]) -> tuple[bool, str]:
    """Shared core for write_orchestrator_model (per-project) and
    write_orchestrator_model_default (user-level, ~/.claude/settings.json) - same file
    schema, same safety bar, different target path. Merge-only (every other settings.json
    key preserved) and REFUSES on unparseable JSON rather than risk clobbering
    hooks/permissions already wired there - same safety bar as run_permissions, since this
    touches the same shared, higher-stakes file (unlike the looser team-preferences.json
    helper above). Returns (ok, message)."""
    if model is not None and model not in ORCHESTRATOR_MODELS:
        raise ValueError(f"model must be one of {ORCHESTRATOR_MODELS} or None, not {model!r}")
    settings: dict = {}
    if target.is_file():
        try:
            settings = json.loads(target.read_text(encoding="utf-8-sig"))
            if not isinstance(settings, dict):
                raise ValueError("settings root is not an object")
        except (OSError, ValueError) as exc:
            return False, f"{target} is not readable JSON ({exc}) - refusing to touch it"
    settings["model"] = ORCHESTRATOR_MODEL_IDS[model or ORCHESTRATOR_MODEL_DEFAULT]
    try:
        if target.is_file():
            backup = target.with_suffix(target.suffix + ".bak")
            backup.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
        target.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_text(target, json.dumps(settings, indent=2) + "\n")
    except OSError as exc:
        return False, f"could not write {target} ({exc})"
    return True, f"{target}: model -> {settings['model']}"


def ask_and_set_model(
    project: Path,
    style: Style,
    assume_yes: bool,
    demo: bool = False,
    offer_global_scope: bool = True,
) -> tuple[bool, str]:
    """Ask scope, then opus/sonnet/default, and apply it (or report what a demo run
    would do). Free function (extracted 2026-08-04 from the Installer method of the same
    name, for reuse by run_configure - a standalone scripting-path flow with no Installer
    instance) so the questions and the disclaimer stay in exactly one place rather than
    drifting between copies.

    Scope is asked first: THIS project (write_orchestrator_model) or the DEFAULT for
    every new/unconfigured project (write_orchestrator_model_default, user-level
    ~/.claude/settings.json - Claude Code layers project settings over user settings,
    so this is a genuine global default, not something this script has to re-apply
    per project).

    offer_global_scope=False skips that question entirely (always per-project) - used
    by model_step specifically (fable UX review, 2026-08-05: the Advanced menu labels
    that item "Morgan's model (per project only)", but the flow asked the global-scope
    question regardless, contradicting its own label; Advanced -> "Machine defaults"
    now covers the global case directly, so duplicating it here just to have a "no, per
    project" answer available adds a needless extra question). run_configure keeps the
    default True - it has no separate machine-defaults entry point of its own."""
    if not offer_global_scope or assume_yes:
        # Unchanged under --yes: confirm() returned its default here, which was False.
        # An unattended run has never opted into the wider scope and must not start now.
        global_default = False
    else:
        global_default = _agreed(
            style,
            title="Which projects?",
            facts=[
                ("head", "  Also make this the default for new projects?\n"),
                ("dim", f"  you are setting {project.name}\n"),
            ],
            detail=[
                ("head", "What the wider scope changes"),
                (
                    "dim",
                    "Every new or unconfigured project starts with this model, written to "
                    "your user-level settings. A project that sets its own model still "
                    "wins, and no existing configured project is touched.",
                ),
            ],
            yes="this project and future ones",
            no=f"just {project.name}",
            assume_yes=False,
            prompt="  Also make this the default for new/unconfigured projects, not just this one?",
            default=False,
        )

    if assume_yes:
        picked = "default"  # unchanged: ask() with assume_yes returned its default
    else:
        # A CHOOSER, not a free-text answer.
        answer = _ask().choose(
            f"Morgan's model for {project.name}",
            [
                (
                    "default",
                    "sonnet (the documented default)",
                    "resets to sonnet - testing to date has not shown better orchestration "
                    "from opus",
                ),
                ("opus", "opus", "the extra margin for critical or high-stakes engagements"),
                (
                    "sonnet",
                    "sonnet, pinned explicitly",
                    "the current generation, written as an exact model ID rather than the "
                    "'sonnet' alias, which resolves differently per API provider",
                ),
                ("sonnet-4-6", "sonnet-4-6", "pins the PREVIOUS generation explicitly"),
            ],
        )
        if answer.cancelled:
            return False, "nothing chosen - the model is unchanged"
        picked = str(answer.value)
    if picked in ("default", "reset", ""):
        model: Optional[str] = None
    elif picked in ORCHESTRATOR_MODELS:
        model = picked
    else:
        return False, f"expected opus/sonnet/sonnet-4-6/default, got {picked!r}"
    if model == "opus":
        print(style.yellow(f"    {ORCHESTRATOR_OPUS_NOTE}"))
    if demo:
        scope = "the new-project default" if global_default else str(project)
        return True, f"would set -> {model or ORCHESTRATOR_MODEL_DEFAULT} ({scope})"
    if global_default:
        return write_orchestrator_model_default(model)
    return write_orchestrator_model(project, model)


def write_orchestrator_model(project: Path, model: Optional[str]) -> tuple[bool, str]:
    """Set Morgan's (the orchestrator's) model in <project>/.claude/settings.json's
    top-level `model` key - the Claude Code setting that fixes a project's default
    session model, overridable per-session via /model.

    model=None resets to ORCHESTRATOR_MODEL_DEFAULT explicitly, rather than deleting the
    key: an absent key falls back to whatever's in play at the next scope up (the
    user-level settings written by write_orchestrator_model_default, or otherwise Claude
    Code's own account/CLI default) - that could silently reintroduce the exact quality
    risk this option exists to let a human accept knowingly, under a label ("reset") that
    reads as safe.

    Only the 16 named specialist subagents have their own `model:` frontmatter
    (`.claude/agents/*.md`, edited directly); Morgan is the top-level session itself, so
    this is the only lever for the orchestrator's own tier."""
    return _write_model_to_settings_file(project / ".claude" / "settings.json", model)


def write_orchestrator_model_default(model: Optional[str]) -> tuple[bool, str]:
    """Set the DEFAULT model for new/unconfigured projects, at Claude Code's user-level
    settings (~/.claude/settings.json, same file the statusline step already wires into).
    Claude Code itself layers project settings over user settings, so this is a genuine
    global default - any project without its own `model` override (write_orchestrator_model)
    inherits this one automatically, no extra plumbing needed on our side. Unlike the
    per-project write, model=None here REMOVES the key rather than forcing sonnet: a human
    who never asked for a global override should get Claude Code's own default back, not
    have one silently imposed by a "reset" they didn't ask for at this scope."""
    target = user_settings_path()
    if model is None:
        settings = _read_json_dict(target)
        if "model" not in settings:
            return True, f"{target}: no default model was set"
        del settings["model"]
        try:
            _write_json_backup(target, settings)
        except OSError as exc:
            return False, f"could not write {target} ({exc})"
        return True, f"{target}: default model cleared"
    return _write_model_to_settings_file(target, model)


def write_guard_interpreter_cache(project: Path) -> None:
    """Pre-seed the project's guard-launcher interpreter cache with the interpreter
    running THIS installer (sys.executable) - a known-good, already-version-checked
    absolute path. run-guard.sh (fired by every PreToolUse hook) otherwise has to
    discover this itself on first use, by EXECUTING each of python3/python/py to
    version-check it; on a Windows box where python3.exe is the Microsoft Store
    execution-alias stub, that first discovery costs a multi-second Store-redirect
    hang (live corporate report 2026-07-30). Writing it here means even that one
    hang never happens. Best-effort: never fails project enablement.

    Written with forward slashes (PureWindowsPath(...).as_posix() on Windows, a no-op
    everywhere else) - live corporate report, 2026-08-12: sys.executable on Windows is
    always backslash-separated (e.g. "C:\\Program Files\\PSF\\Python312\\python.EXE"),
    and every consumer of this cache (run-guard.sh, the engage-open.md bootstrap) reads
    it into a POSIX-shell variable and tests it with `command -v "$cached"` under Git
    Bash/MSYS - a context where backslash is the shell's own escape character and
    forward-slash absolute paths (MSYS's own native representation of a Windows drive
    path) are the well-established reliable form. A cached path this installer itself
    can always exec fine (sys.executable is definitionally a real, running interpreter)
    was still observed falling through to the full discovery loop on a real Windows
    box even after the word-splitting bug (2026-08-12, this same report) was fixed -
    the backslash form is the leading suspect, since it's the one difference between
    "this path resolves" and "this path silently doesn't" between a plain Python
    process and a POSIX shell's own path handling."""
    try:
        cache = _guard_interpreter_cache(project)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(PureWindowsPath(sys.executable).as_posix(), encoding="utf-8")
    except OSError:
        pass


def run_enable_project(project_dir: Path, style: Style, mark_map: dict, runner=None) -> int:
    """Enable the plugin for one project (claude plugin enable --scope project, run from
    that project's directory). Human-run; per-project scope is the token-economy rule."""
    runner = runner or run_cmd
    ok, fail = mark_map["ok"], mark_map["fail"]
    project = project_dir.expanduser().resolve()
    if not project.is_dir():
        print(f"{fail} not a directory: {project}")
        return 1
    write_guard_interpreter_cache(project)
    blocked = None
    try:
        proc = runner(["claude", "plugin", "enable", "--scope", "project", PLUGIN_ID], cwd=project)
    except subprocess.TimeoutExpired as exc:
        print(f"{fail} enable failed for {project}: {exc}")
        return 1
    except OSError as exc:
        blocked = str(exc)  # CLI binary itself refused (e.g. group policy)
    if blocked is None:
        if proc.returncode == 0:
            print(f"{ok} enabled for {project}")
            return 0
        stderr = (proc.stderr or "").strip()
        stdout = (proc.stdout or "").strip()
        combined = stderr or stdout
        lowered = combined.lower()
        if "already enabled" in lowered:
            # Already at the desired end state - informational, not a failure (same
            # 2026-08-07 fix as the plugin-install "already installed" case above).
            print(f"{ok} already enabled for {project}")
            return 0
        if "group policy" not in combined.lower() and "blocked" not in combined.lower():
            if combined:
                print(f"{fail} enable failed for {project} (exit {proc.returncode}): {combined}")
            else:
                # Both streams empty - the previous message here was just "unknown error",
                # which is the exact "the only error is 'failed'" complaint (live report,
                # 2026-08-04): nothing to debug from. Print the one fact we DO have (the exit
                # code) and the exact command to re-run by hand, matching the "retry by hand"
                # pattern used elsewhere in this repo (e.g. the step-0 probe's PROBE_FAILED).
                print(
                    f"{fail} enable failed for {project} (exit {proc.returncode}, no output "
                    "on stdout or stderr) - run this by hand to see the real error: "
                    f"claude plugin enable --scope project {PLUGIN_ID}"
                )
            return 1
        blocked = combined
    # The CLI is only writing enabledPlugins into the project settings - do it directly.
    # Refuse on unparseable JSON rather than clobbering, same safety bar as
    # run_permissions/_write_model_to_settings_file for this exact file (found in review,
    # 2026-08-13: this fallback used _read_json_dict, whose garbage-becomes-{} fallback
    # would have silently overwritten a corrupt settings.json instead of refusing).
    target = project / ".claude" / "settings.json"
    if target.is_file():
        try:
            settings = json.loads(target.read_text(encoding="utf-8-sig"))
            if not isinstance(settings, dict):
                raise ValueError("settings root is not an object")
        except (OSError, ValueError) as exc:
            print(f"{fail} {target} is not readable JSON ({exc}) - refusing to touch it")
            return 1
    else:
        settings = {}
    try:
        enabled = settings.get("enabledPlugins")
        if not isinstance(enabled, dict):
            enabled = {}
            settings["enabledPlugins"] = enabled
        enabled[PLUGIN_ID] = True
        _write_json_backup(target, settings)
        print(f"{ok} enabled for {project} (written directly; claude CLI blocked: {blocked})")
        return 0
    except OSError as exc:
        print(f"{fail} enable failed for {project}: {exc}")
        return 1


def _project_preference_defaults(existing: dict, machine_defaults: dict) -> tuple:
    """(docx_current, citations_current, review_tools_current, map_skeleton_current,
    statusline_show_map_current) - the project's own explicit choice (the key is PRESENT in
    its team-preferences.json, even if falsy/empty) always wins; otherwise falls back to
    THIS MACHINE's default; otherwise the built-in CONFIGURE-recommended default (docx off,
    citations off, review-tools all auto, map_skeleton on, statusline_show_map off - 2026-08-07
    user request: "set the defaults to be citations off, split on, docx off, map on").
    Shared by run_configure and format_preferences_step so the two never suggest different
    values for the same project.
    2026-08-05 user request: a "sensible defaults" fast path must respect machine-level
    overrides - e.g. ruff disabled at machine level must stay disabled by default for a
    brand-new project, not silently re-enabled; a project's own prior choice always
    overrides the machine default regardless.
    2026-08-06 (ADR-007 Phase 1 Chunk D): map_skeleton follows the exact same 3-tier
    precedence, added as a 4th value rather than a new function so the "shared, cannot
    drift" property extends to it automatically.
    2026-08-06 (statusline): statusline_show_map (whether scripts/statusline.sh's render
    grows a `map:on/off` field at all) follows the identical 3-tier precedence, added as a
    5th value for the same reason - off by default, since not every project wants a longer
    statusline just because map_skeleton itself might be on.
    2026-08-07: citations/map_skeleton's built-in fallback changed (on->off, off->on).
    Deliberately scoped to CONFIGURE's own suggested/written default only - `scripts/
    engage_probe.py` keeps its own independent, unchanged built-in fallback for a project
    that has NEVER run configure/preferences at all (no key, no machine default either); that
    is a much larger-blast-radius runtime default the user did not ask to change, so the two
    are now intentionally decoupled rather than "mirrored" as the docstring used to claim."""
    if "extra_formats" in existing:
        docx_current = "docx" in (existing.get("extra_formats") or [])
    else:
        docx_current = bool(machine_defaults.get("default_docx", False))
    citations_current = existing.get(
        "regulatory_citations", machine_defaults.get("default_regulatory_citations", False)
    )
    if "review_tools" in existing:
        review_tools_current = existing.get("review_tools") or {}
    else:
        review_tools_current = machine_defaults.get("default_review_tools") or {}
    map_skeleton_current = existing.get(
        "map_skeleton", machine_defaults.get("default_map_skeleton", True)
    )
    statusline_show_map_current = existing.get(
        "statusline_show_map", machine_defaults.get("default_statusline_show_map", False)
    )
    return (
        docx_current,
        citations_current,
        review_tools_current,
        map_skeleton_current,
        statusline_show_map_current,
    )


def run_configure(
    target: Path, style: Style, mark_map: dict, assume_yes: bool = False, demo: bool = False
) -> int:
    """Standalone, one-shot project setup (--configure [DIR], or `virt-surv configure` via
    the alias from run_setup_alias): enable + permissions + preferences + model, scoped to
    ONE folder, in one guided pass. 2026-08-04 user request: "navigate to a project folder,
    run one command, answer a few questions" instead of hunting through several separate
    menu options for the same first-time setup. Interactive by design (each step confirm()s)
    unless assume_yes forces safe defaults, matching --yes semantics used elsewhere here.

    2026-08-07 user request: "always run check-review-tools.sh --refresh when configuring" -
    run_tool_cache_refresh runs unconditionally near the end (after preferences are written,
    so the probe reflects any review_tools override just set), no confirm() gate, since the
    user's own word was "always" rather than "offer".

    demo=True previews every step and writes NOTHING - live-tested gap, 2026-08-04: this
    function originally had no demo support at all, so `--demo` combined with configure
    silently wrote real files. Each step below is therefore branched explicitly rather
    than relying on a run_cmd swap (the existing Installer demo pattern) - run_permissions/
    write_team_preferences do direct file I/O with no subprocess involved at all, so
    swapping run_cmd alone would not have protected them either.

    Deliberately does NOT include the "save as default for new projects" nuance
    format_preferences_step offers (that needs the Installer's own persisted CLI config,
    self.cfg/self.cfg_path) - this is the fast common path; that finer option stays
    reachable via the interactive menu for whoever wants it.

    Opens with a one-click "use the recommended settings?" question (2026-08-05 user
    request: "option to go with recommended settings as a one click option ... gets the
    user quickly up and running") - answering yes reuses the EXISTING assume_yes
    machinery for the rest of this call (every confirm()/ask() below already short-
    circuits to its default under assume_yes), so this adds zero new per-question logic,
    just skips the walk. The "recommended" defaults themselves respect this machine's
    own configured defaults (_project_preference_defaults), not just the original
    built-in ones - a tool disabled at machine level stays disabled for a new project."""
    ok, fail = mark_map["ok"], mark_map["fail"]
    project = target.expanduser().resolve()
    if not project.is_dir():
        print(f"{fail} not a directory: {project}")
        return 1
    print(
        style.bold(f"Configuring {project}" + (" (DEMO - nothing will be written)" if demo else ""))
    )
    if not assume_yes and confirm(
        "  Use the recommended settings (enable + permission allow-list + this "
        "machine's defaults) - the fastest way to get running? 'No' walks through each "
        "choice instead.",
        default=True,
        assume_yes=False,
        style=style,
    ):
        assume_yes = True
    rc = 0
    skip = mark_map["skip"]
    # 2026-08-12 onboarding UX audit: this flow had no progress indicator at all (unlike
    # every Installer-driven flow, which shows "Step N of M" throughout) and declined
    # answers produced no visible feedback until the closing summary table, well after
    # the fact - both fixed here by reusing rule_header (already a free function) for
    # numbered headers and printing an immediate ok/skip mark after every yes/no
    # decision, matching the Installer class's own step_ok/step_skip format exactly
    # (this is a free function with no Installer instance/tracker to call those on
    # directly, so the print format is replicated rather than shared).
    TOTAL_STEPS = 7

    def _mark(accepted: bool, label: str, detail: str = "") -> None:
        suffix = f" {style.dim('(' + detail + ')')}" if detail else ""
        glyph = style.green(ok) if accepted else style.yellow(skip)
        print(f"  {glyph} {label}{suffix}")

    print("")
    print(rule_header(1, TOTAL_STEPS, "Enable the plugin", style))
    if demo:
        print(style.dim(f"    would enable for {project}"))
        enabled_ok = True
    else:
        enable_rc = run_enable_project(project, style, mark_map)
        rc = max(rc, enable_rc)
        enabled_ok = enable_rc == 0

    print("")
    print(rule_header(2, TOTAL_STEPS, "Permission allow-list", style))
    permissions_wanted = confirm(
        "  Add the recommended permission allow-list (fewer prompts)?",
        default=True,
        assume_yes=assume_yes,
        style=style,
    )
    if permissions_wanted:
        if demo:
            print(style.dim(f"    would add up to {len(RECOMMENDED_ALLOW)} allow entries"))
        else:
            rc = max(rc, run_permissions(project, style, mark_map))
    else:
        _mark(False, "Permission allow-list", "declined")

    print("")
    print(rule_header(3, TOTAL_STEPS, "API/env tuning", style))
    env_tuning_wanted = confirm(
        "  Tune API timeout / stream-idle / output-size env vars and the 1-hour "
        "prompt-cache TTL (helps on slow networks or behind a corporate proxy, and "
        "makes stop-start sessions markedly cheaper on API billing; trade-off: "
        "transient API/throttling errors then retry quietly for up to hours instead "
        "of failing fast)?",
        default=True,
        assume_yes=assume_yes,
        style=style,
    )
    if env_tuning_wanted:
        if demo:
            print(style.dim(f"    would upsert {len(RECOMMENDED_ENV)} tuning env vars"))
        else:
            rc = max(rc, run_env_tuning(project, style, mark_map))
    else:
        _mark(False, "API/env tuning", "declined")

    print("")
    print(rule_header(4, TOTAL_STEPS, "LLM-gateway workaround", style))
    betas_wanted = confirm(
        "  Work around an LLM-gateway compatibility issue (a subagent call fails with "
        "'tools.0.custom.eager_input_streaming: Extra inputs are not permitted', most "
        "often on a haiku-tier call)? Recommended default is ON (most corporate LLM-gateway "
        "setups hit this) - it has a real cost, MCP tool search turns off, so say no if you "
        "rely on MCP tool search and aren't seeing this error.",
        default=True,
        assume_yes=assume_yes,
        style=style,
    )
    if betas_wanted:
        if demo:
            print(
                style.dim(
                    f"    would upsert {len(EXPERIMENTAL_BETAS_ENV)} beta-fields-workaround env var(s)"
                )
            )
        else:
            rc = max(rc, run_env_tuning_betas(project, style, mark_map))
    else:
        _mark(False, "LLM-gateway workaround", "declined")

    print("")
    print(rule_header(5, TOTAL_STEPS, "Project preferences", style))
    existing = _read_json_dict(project / ".claude" / "team-preferences.json")
    machine_defaults = load_config(config_path())
    (
        docx_current,
        citations_current,
        review_tools_current,
        map_skeleton_current,
        statusline_show_map_current,
    ) = _project_preference_defaults(existing, machine_defaults)
    # Built-in default False (2026-08-12 user request, reversing the 2026-08-07 "split on"
    # decision) - large_context_review_split deliberately has no machine-wide tier (see
    # write_team_preferences' own docstring), so this literal is its only fallback. This now
    # matches what was already true everywhere else (write_team_preferences' own docstring,
    # .claude/skills/preferences/SKILL.md, and engage_probe.py's actual runtime resolution
    # all already said "defaults to False/off when absent") - only this interactive
    # pre-filled prompt default was still out of sync with them, silently nudging anyone who
    # ran Configure-a-project toward writing "true" even though the true baseline was off.
    split_current = existing.get("large_context_review_split", False)
    # Built-in default True - same no-machine-wide-tier precedent as
    # large_context_review_split above; this literal is its only fallback.
    workflow_dispatch_current = existing.get("parallel_dispatch_via_workflow", True)
    # Built-in default False (2026-08-11 user request: "off by default") -
    # standards_critique deliberately has no machine-wide tier, same as
    # large_context_review_split above; this literal is its only fallback.
    standards_critique_current = existing.get("standards_critique", False)
    # Built-in default True (2026-08-12 user request: "should be on by default") - the one
    # preference in this whole block that defaults ON. No machine-wide tier, same
    # precedent as the two above; this literal is its only fallback. Harmless to write
    # True on a project that hasn't applied the ADR-014 daemon files yet - run-guard.sh
    # checks the files exist before ever using the flag (write_team_preferences' own
    # docstring), so this just pre-seeds the preference for whenever they are applied.
    guard_daemon_current = existing.get("guard_daemon", True)
    docx_wanted = confirm(
        "  Produce .docx by default for controlled documents?",
        default=docx_current,
        assume_yes=assume_yes,
        style=style,
    )
    citations_wanted = confirm(
        "  Cite regulatory obligations by default?",
        default=citations_current,
        assume_yes=assume_yes,
        style=style,
    )
    # EIGHT blocking confirms used to run here, unconditionally, during a first install.
    # Two of them are genuinely first-run decisions - what the team produces, and whether
    # it cites obligations. The other six have sensible defaults, are per-project tuning
    # rather than setup, and are all editable at any time from `virt-surv go` -> [c],
    # which is a grid showing every value at once rather than a fixed interrogation with
    # no way to skip forward or go back.
    #
    # That length is also where the drift came from: this list and the settings screen
    # both write team-preferences.json and asked DIFFERENT questions about it - this one
    # asks about statusline_show_map, which the screen has no row for; the screen covers
    # seven settings this never mentions. Two question sets over one file is exactly what
    # _editor_rows was written to prevent, reappearing across the entry-point boundary
    # (2026-08-28 UX review, owner decision: shrink the wizard).
    #
    # Not REMOVED, gated: an opt-in keeps every question reachable in place for anyone who
    # wants to answer them now, and defaults to no because a first run is the worst moment
    # to be asked about evidence rooms and daemon latencies.
    tune_now = confirm(
        "  Set up the finer preferences now (review splitting, parallel dispatch, "
        "standards critique, map drift, guard daemon, review tools)? You can change "
        "these any time from 'virt-surv go' -> [c], which shows them all at once",
        default=False,
        assume_yes=assume_yes,
        style=style,
    )
    if not tune_now:
        style_note = style.dim(
            "    keeping the current values for those - 'virt-surv go' then [c] to change them"
        )
        print(style_note)
        split_wanted = split_current
        workflow_dispatch_wanted = workflow_dispatch_current
        standards_critique_wanted = standards_critique_current
        map_skeleton_wanted = map_skeleton_current
        statusline_show_map_wanted = statusline_show_map_current
        guard_daemon_wanted = guard_daemon_current
        review_tools_wanted = review_tools_current
    else:
        split_wanted = confirm(
            "  Split large, multi-component reviews by component from the start (useful "
            "behind a corporate proxy that times out on large requests)?",
            default=split_current,
            assume_yes=assume_yes,
            style=style,
        )
        workflow_dispatch_wanted = confirm(
            "  Dispatch independent review passes via the Claude Code Workflow tool when "
            "available (guaranteed concurrent execution; runs in the background and reports "
            "back when done)?",
            default=workflow_dispatch_current,
            assume_yes=assume_yes,
            style=style,
        )
        standards_critique_wanted = confirm(
            "  Run the independent standards-critique pass (a second agent checking a "
            "finished review against its profession's named criteria) - off by default, "
            "since it is a full extra review pass on top of the review itself?",
            default=standards_critique_current,
            assume_yes=assume_yes,
            style=style,
        )
        map_skeleton_wanted = confirm(
            "  Enable codebase-skeleton drift checking for a codebase map with a Paths "
            "column - flags when the map docs go stale (a mapped area's code changed since "
            "it was last verified, or a cited file:line no longer exists), useful if the "
            "team relies on the map to brief new work accurately. Experimental, ADR-007 "
            "Phase 1, off by default?",
            default=map_skeleton_current,
            assume_yes=assume_yes,
            style=style,
        )
        statusline_show_map_wanted = confirm(
            "  Show map-skeleton status (map:on/off) in the statusline too - off by default, "
            "keeps the line short unless you want it?",
            default=statusline_show_map_current,
            assume_yes=assume_yes,
            style=style,
        )
        guard_daemon_wanted = confirm(
            "  Route the safety guards through the persistent ADR-014 daemon instead of a "
            "fresh interpreter per call, once its files are applied (measured ~12ms "
            "daemon-backed vs. ~300ms cold-start median) - on by default?",
            default=guard_daemon_current,
            assume_yes=assume_yes,
            style=style,
        )
        review_tools_wanted = _ask_review_tool_overrides(style, assume_yes, review_tools_current)
    # Live-validates every newly forced-"on" tool even in demo mode - read-only against a
    # throwaway synthetic file, nothing project-related is touched, and the whole point is
    # to catch a hanging/network-blocked tool (the semgrep/pip-audit shape) BEFORE it is
    # ever written as "on", which matters just as much during a demo walkthrough.
    review_tools_wanted = _apply_forced_on_validation(
        style, mark_map, review_tools_wanted, review_tools_current
    )
    summary = (
        f"docx={'on' if docx_wanted else 'off'}, "
        f"citations={'on' if citations_wanted else 'off'}, "
        f"review-split={'on' if split_wanted else 'off'}, "
        f"workflow-dispatch={'on' if workflow_dispatch_wanted else 'off'}, "
        f"standards-critique={'on' if standards_critique_wanted else 'off'}, "
        f"map-skeleton={'on' if map_skeleton_wanted else 'off'}, "
        f"statusline-map={'on' if statusline_show_map_wanted else 'off'}, "
        f"guard-daemon={'on' if guard_daemon_wanted else 'off'}, "
        f"review-tools={_format_review_tools(review_tools_wanted)}"
    )
    if demo:
        print(style.dim(f"    would write preferences: {summary}"))
    elif write_team_preferences(
        project,
        extra_formats=["docx"] if docx_wanted else [],
        regulatory_citations=citations_wanted,
        large_context_review_split=split_wanted,
        parallel_dispatch_via_workflow=workflow_dispatch_wanted,
        standards_critique=standards_critique_wanted,
        map_skeleton=map_skeleton_wanted,
        statusline_show_map=statusline_show_map_wanted,
        guard_daemon=guard_daemon_wanted,
        review_tools=review_tools_wanted,
    ):
        print(f"  {ok} preferences: {summary}")
    else:
        print(f"  {fail} could not write team-preferences.json")
        rc = 1

    print("")
    print(rule_header(6, TOTAL_STEPS, "Refreshing the analyser-availability cache", style))
    rc = max(rc, run_tool_cache_refresh(project, style, mark_map, demo=demo))

    # 2026-08-12 user request: "recommended should set the model to sonnet" - under the
    # recommended-defaults path (assume_yes True here) this now explicitly PINS sonnet in
    # the project's .claude/settings.json rather than silently skipping the question and
    # leaving `model` unset. ask_and_set_model already resolves to exactly that under
    # assume_yes (its own confirm/ask calls short-circuit to their defaults - global scope
    # declined, model picker returns "default" -> None -> ORCHESTRATOR_MODEL_DEFAULT), so
    # bypassing the outer confirm's own default=False (which means "no, leave unset") is
    # the only change needed; the manual walkthrough (assume_yes False) is untouched -
    # still asks, still declines by default, matching every other "set the model"
    # question's deliberately-opt-in posture.
    print("")
    print(rule_header(7, TOTAL_STEPS, "Morgan's model", style))
    model_requested = assume_yes or confirm(
        "  Set Morgan's model for this project (default: sonnet)?",
        default=False,
        assume_yes=assume_yes,
        style=style,
    )
    model_display = "not requested (unset - inherits account/global default)"
    if not model_requested:
        _mark(False, "Morgan's model", "declined")
    if model_requested:
        # offer_global_scope=False (2026-08-12 fix, onboarding UX audit): without it, a
        # "for this project" question was silently followed by an unscoped "also make
        # this the default for new/unconfigured projects?" - the exact contradiction
        # model_step was already fixed for (2026-08-05, "fable UX review": a menu item
        # labeled "per project only" was asking a global-scope question). This call had
        # the identical bug, just not caught at the time.
        ok_model, message = ask_and_set_model(
            project, style, assume_yes, demo=demo, offer_global_scope=False
        )
        print(f"  {ok if ok_model else fail} {message}")
        rc = max(rc, 0 if ok_model else 1)
        model_display = message.split("-> ", 1)[1] if ok_model and "-> " in message else message

    # 2026-08-12 user request: "display a nice table after configuring to explain to the
    # user what's set" - every step above already prints its own real-time confirmation
    # (counts, backup filenames, etc.), but nothing previously showed the FULL picture -
    # enable + permissions/env-tuning/betas + all seven preferences + review-tool
    # overrides + model - in one scannable place. Built from the same variables already
    # driving the steps above, so it can't drift from what was actually asked/applied.
    summary_rows = [
        ("Plugin enabled", "yes" if enabled_ok else "failed - see above", enabled_ok),
        (
            "Permission allow-list",
            f"on ({len(RECOMMENDED_ALLOW)} entries)" if permissions_wanted else "off",
            permissions_wanted,
        ),
        (
            "API/env tuning",
            f"on ({len(RECOMMENDED_ENV)} vars)" if env_tuning_wanted else "off",
            env_tuning_wanted,
        ),
        ("LLM-gateway workaround", "on" if betas_wanted else "off", betas_wanted),
        ("Docx output", "on" if docx_wanted else "off", docx_wanted),
        ("Regulatory citations", "on" if citations_wanted else "off", citations_wanted),
        ("Review split by component", "on" if split_wanted else "off", split_wanted),
        (
            "Workflow-tool dispatch",
            "on" if workflow_dispatch_wanted else "off",
            workflow_dispatch_wanted,
        ),
        (
            "Standards-critique pass",
            "on" if standards_critique_wanted else "off",
            standards_critique_wanted,
        ),
        ("Codebase map-skeleton", "on" if map_skeleton_wanted else "off", map_skeleton_wanted),
        (
            "Statusline shows map",
            "on" if statusline_show_map_wanted else "off",
            statusline_show_map_wanted,
        ),
        (
            "Guard daemon (ADR-014)",
            "on" if guard_daemon_wanted else "off",
            guard_daemon_wanted,
        ),
        ("Review-tool overrides", _format_review_tools(review_tools_wanted), None),
        ("Morgan's model", model_display, None),
    ]
    print(style.dim("\n  Summary:" + (" (preview - nothing written)" if demo else "")))
    for line in render_kv_table(summary_rows, style):
        print("  " + line)

    print("")
    if rc == 0:
        print(style.dim(f"Configuration complete for {project}."))
    else:
        print(style.yellow("Configuration finished with issues - see above."))
    return rc


def clone_asset(*parts) -> Path:
    """A path to something inside the REAL clone - scripts/x.py, docs/templates/y.md.

    Never Path(__file__).parent. _relocate_if_running_inside_target_repo copies this file
    into a bare temp directory and re-execs from there for the rest of the session, so
    that a git checkout can overwrite the original safely. From that moment __file__'s
    parent holds exactly one .py file and none of the siblings anything here wants.

    Three separate features shipped broken because of that and each failed silently: the
    new installer screens never ran, the brand banner fell back to a plain box, and
    scripts/ imports returned None which callers read as "unavailable" (all 2026-08-28).
    The pattern is not that any one of them was careless - it is that a path derived from
    __file__ is WRONG AT RUNTIME here, and wrong quietly.

    Falls back to __file__'s parent, which is correct for a checkout being run in place
    and for the single-file curl bootstrap before any clone exists."""
    root = None
    try:
        root = _resolve_repo_root(None)
    except Exception:
        root = None
    base = root if root else Path(__file__).resolve().parent
    for part in parts:
        base = base / part
    return base


def _engagement_state_script() -> Optional[Path]:
    """Locates scripts/engagement_state.py relative to THIS clone - install_helper.py
    always sits at the clone's own repo root, next to scripts/, so no plugin-root
    discovery is needed here (unlike find_plugin_root.py's problem, which is specifically
    about locating things from an ARBITRARY foreign project directory)."""
    candidate = clone_asset("scripts", "engagement_state.py")
    return candidate if candidate.is_file() else None


def _review_tools_script() -> Optional[Path]:
    """Locates scripts/check-review-tools.sh relative to THIS clone - same rationale as
    _engagement_state_script()."""
    candidate = clone_asset("scripts", "check-review-tools.sh")
    return candidate if candidate.is_file() else None


def run_tool_cache_refresh(
    project_dir: Path, style: Style, mark_map: dict, demo: bool = False
) -> int:
    """Run automatically at the end of every --configure pass (2026-08-07 user request:
    "always run check-review-tools.sh --refresh when configuring via virt-surv configure") -
    forces a fresh analyser-availability probe for the TARGET project instead of leaving it to
    serve a stale (up to 7-day) cache, or - on a brand-new project - having no cache at all
    until the first /engage open. Runs LAST in run_configure, after review-tool preferences are
    written, so the probe's "effective state per tool" (which already reads the project's
    team-preferences.json review_tools override) reflects what was just configured, not what
    was there before this pass started.

    Bridges to the script with cwd set to the project - same cwd-redirection pattern as
    run_list_engagements/run_archive_engagements bridging to engagement_state.py - so the
    script's relative `.claude/.tool-availability` cache path resolves in the TARGET project,
    not this clone. Soft-fail throughout (bash missing, script missing, non-zero exit): all
    reported, none block configure - matching the script's own documented "report, not a gate,
    always exits 0" contract; a probe failure here is informational only."""
    ok, fail = mark_map["ok"], mark_map["fail"]
    project = project_dir.expanduser().resolve()
    if not project.is_dir():
        print(f"{fail} not a directory: {project}")
        return 1
    script = _review_tools_script()
    if script is None:
        print(f"{fail} scripts/check-review-tools.sh not found next to install_helper.py - skipped")
        return 1
    bash = find_bash()
    if bash is None:
        print(
            f"{fail} no bash found (needed for check-review-tools.sh) - analyser-cache refresh skipped"
        )
        return 1
    if demo:
        print(style.dim(f"    would run: bash {script} --refresh (in {project})"))
        return 0
    try:
        proc = run_cmd([bash, str(script), "--refresh"], cwd=project)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"{fail} check-review-tools.sh --refresh failed to run: {exc}")
        return 1
    if proc.returncode != 0:
        print(f"{fail} check-review-tools.sh --refresh exited {proc.returncode}")
        return 1
    print(
        f"{ok} analyser-availability cache refreshed ({project / '.claude' / '.tool-availability'})"
    )
    return 0


def run_archive_engagements(target: Path, style: Style, mark_map: dict, demo: bool = False) -> int:
    """Standalone (--archive [DIR]): archives every closed, unarchived engagement under
    DIR/artifacts - bridges to `engagement_state.py archive --all-closed`, run with its
    cwd set to DIR so it resolves artifacts/ relative to the TARGET project, not this
    clone (engagement_state.py's own workspace resolution defaults to Path.cwd() when no
    --dir is given, confirmed via its source - so setting cwd is sufficient, no extra
    flag needed). demo=True skips the real call entirely - engagement_state.py has no
    dry-run flag of its own, and run_manage_engagements' preceding list step already
    shows what's there before this would be offered."""
    ok, fail = mark_map["ok"], mark_map["fail"]
    project = target.expanduser().resolve()
    if not project.is_dir():
        print(f"{fail} not a directory: {project}")
        return 1
    if demo:
        print(style.dim(f"    would archive every closed engagement under {project / 'artifacts'}"))
        return 0
    script = _engagement_state_script()
    if script is None:
        print(f"{fail} scripts/engagement_state.py not found next to this clone")
        return 1
    try:
        proc = subprocess.run(
            [sys.executable, str(script), "archive", "--all-closed"],
            cwd=project,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"{fail} archive failed: {exc}")
        return 1
    if proc.stdout.strip():
        print(proc.stdout.strip())
    if proc.returncode != 0:
        print(f"{fail} archive exited {proc.returncode}: {(proc.stderr or '').strip()[:300]}")
        return 1
    print(f"{ok} archived every closed engagement under {project / 'artifacts'}")
    return 0


def run_list_engagements(target: Path, style: Style, mark_map: dict) -> int:
    """Standalone (--list-engagements [DIR]): lists DIR's engagements - bridges to
    `engagement_state.py list`, cwd set to DIR (same resolution note as
    run_archive_engagements above)."""
    fail = mark_map["fail"]
    project = target.expanduser().resolve()
    if not project.is_dir():
        print(f"{fail} not a directory: {project}")
        return 1
    script = _engagement_state_script()
    if script is None:
        print(f"{fail} scripts/engagement_state.py not found next to this clone")
        return 1
    try:
        proc = subprocess.run(
            [sys.executable, str(script), "list"],
            cwd=project,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"{fail} list failed: {exc}")
        return 1
    print(proc.stdout.strip() or "(no engagements found)")
    if proc.returncode != 0:
        print(f"{fail} list exited {proc.returncode}: {(proc.stderr or '').strip()[:300]}")
        return 1
    return 0


def run_manage_engagements(
    target: Path, style: Style, mark_map: dict, assume_yes: bool = False, demo: bool = False
) -> int:
    """Interactive combined flow (menu: 'Manage engagements'): list, then offer to
    archive closed ones - one guided step instead of a third menu level for what's really
    a single "let me see what's here, and tidy it up" task. list is already read-only, so
    demo mode only changes the archive half."""
    project = target.expanduser().resolve()
    rc = run_list_engagements(project, style, mark_map)
    if rc != 0:
        return rc
    if confirm(
        "\n  Archive every closed engagement (excludes them from future scans)?",
        default=False,
        assume_yes=assume_yes,
        style=style,
    ):
        return run_archive_engagements(project, style, mark_map, demo=demo)
    print(f"{style.dim('-')} nothing archived")
    return 0


# ------------------------------------------------------------------ shell alias setup
#
# 2026-08-04 user request: run this clone from any folder via a short alias, so
# "cd my-project && virt-surv configure" works without remembering a full path. Opt-in,
# confirm-gated, add-only (never overwrites or removes anything already in a shell rc
# file), and idempotent (checks for an existing "virt-surv" line first).

_ALIAS_MARKER = "virt-surv"

# The alias template's version stamp, embedded in every written line as a trailing
# comment (valid end-of-line comment syntax in POSIX shells and PowerShell alike).
# run_setup_alias treats an existing entry WITHOUT the current stamp as an older
# template and upgrades it (appends the new definition below; never edits the old
# line). Bump _ALIAS_VERSION every time either template changes IN ANY WAY: twice a
# template fix shipped that installed profiles could never receive, because the
# staleness check only recognised the previous era's shape - a pre-'go' plain alias
# (upgrade added 2026-08-15, commit 65648ec) and then a go-era function missing the
# "/engage" prefix (f53e907; live Windows report 2026-08-16: claude errored with
# "unknown option '--new'" because the profile still held the unprefixed line and
# the 'go'-signature check judged it current). The stamp makes staleness
# shape-agnostic: any future template change upgrades automatically.
# v1 plain alias · v2 'go' function · v3 'go' + baked "/engage" prefix · v4 the prefix
# moved INTO the launcher (run-mode-dependent: bare /engage only exists repo-as-project;
# a plugin install needs /compliance-surveillance-team:engage - live report 2026-08-16:
# the baked bare form was an unknown command on every real plugin install), so the
# shell function now passes the launcher's stdout through verbatim as one argument.
# v5 the LAUNCH COMMAND is no longer baked either: the function asks the launcher
# (`--launch-command`) at every 'go' and word-splits the answer (live report
# 2026-08-17: a launch command reset in the config kept launching the old baked value
# even after closing PowerShell, because the profile function still carried it - and a
# multi-word command like 'cc --debug' was baked as ONE quoted word, unresolvable).
# Config changes now take effect on the next 'go' with no alias refresh and no profile
# reload. Trade-off, stated: a launch command that is a single path WITH SPACES no
# longer works word-split - wrap it in your own alias/function and configure that name.
# v6 (2026-08-19): the shell fast path matches 'engage' as well as 'go' - `virt-surv
# engage` now LAUNCHES (it used to be project setup, which read as the opposite of
# /engage in-session). heal_stale_aliases rewrites v5 definitions at the next launch.
_ALIAS_VERSION = 7
_ALIAS_STAMP = f"# {_ALIAS_MARKER}-alias-v{_ALIAS_VERSION}"

# Any version's stamp - the removal marker for _strip_stamped_definitions.
_ALIAS_STAMP_ANY_RE = re.compile(rf"#\s*{re.escape(_ALIAS_MARKER)}-alias-v\d+\s*$")
_ALIAS_ADDED_BY_RE = re.compile(r"^\s*# Added by install_helper\.py\b")


def _alias_line_for(rc_path: Path, interpreter: str, launcher_path, script_path) -> str:
    """The current alias definition for one rc/profile file - the single source both
    run_setup_alias and heal_stale_aliases write, so the two can never drift.

    v5: NOTHING config-dependent is baked into either line - the launcher answers
    `--launch-command` from the machine config at every 'go', and the function
    word-splits it (multi-word commands like 'cc --resume' work; a bare path with
    spaces does not - configure a wrapper alias instead)."""
    if rc_path.suffix == ".ps1":
        return (
            f"function {_ALIAS_MARKER} {{ "
            f'if ($args.Count -gt 0 -and ($args[0] -eq "go" -or $args[0] -eq "engage")) {{ '
            f"$__vtRest = @(); if ($args.Count -gt 1) {{ $__vtRest = $args[1..($args.Count-1)] }}; "
            f'$__vtCmd = @((& "{interpreter}" "{launcher_path}" --launch-command) -split " +"); '
            f'if (-not $__vtCmd) {{ $__vtCmd = @("claude") }}; '
            f"$__vtCmdArgs = @($__vtCmd | Select-Object -Skip 1); "
            f"$__vtF = [System.IO.Path]::GetTempFileName(); "
            f"$env:VIRT_SURV_CD_FILE = $__vtF; "
            f'$__vtDecision = & "{interpreter}" "{launcher_path}"; '
            f"$__vtRc = $LASTEXITCODE; "
            f"Remove-Item Env:\\VIRT_SURV_CD_FILE -ErrorAction SilentlyContinue; "
            f"$__vtGo = (Get-Content $__vtF -Raw -ErrorAction SilentlyContinue); "
            f"Remove-Item $__vtF -ErrorAction SilentlyContinue; "
            f"if ($__vtGo -and $__vtGo.Trim()) {{ Set-Location $__vtGo.Trim() }}; "
            f"if ($__vtRc -ne 97) {{ "
            f'if ($__vtDecision) {{ & $__vtCmd[0] @__vtCmdArgs "$__vtDecision" @__vtRest }} '
            f"else {{ & $__vtCmd[0] @__vtCmdArgs @__vtRest }} }} "
            f"}} else {{ "
            f'& "{interpreter}" "{script_path}" @args '
            f"}} }} {_ALIAS_STAMP}"
        )
    return (
        f"{_ALIAS_MARKER}() {{ "
        f'if [ "$1" = "go" ] || [ "$1" = "engage" ]; then shift; local __vt_c __vt_d __vt_f __vt_r; '
        f'__vt_c="$("{interpreter}" "{launcher_path}" --launch-command)"; '
        f'[ -n "$__vt_c" ] || __vt_c=claude; '
        f'__vt_f="$(mktemp 2>/dev/null || echo "${{TMPDIR:-/tmp}}/virt-surv-cd.$$")"; '
        f'__vt_d="$(VIRT_SURV_CD_FILE="$__vt_f" "{interpreter}" "{launcher_path}")"; '
        f"__vt_r=$?; "
        f'if [ -s "$__vt_f" ]; then cd "$(cat "$__vt_f")" || true; fi; '
        f'rm -f "$__vt_f"; '
        f'if [ "$__vt_r" -ne 97 ]; then $__vt_c ${{__vt_d:+"$__vt_d"}} "$@"; fi; '
        f'else "{interpreter}" "{script_path}" "$@"; fi; }} {_ALIAS_STAMP}'
    )


def heal_stale_aliases() -> list:
    """Self-resolution for a stale installed alias (2026-08-17 user requirement: after a
    plugin update "it should self-resolve" - a profile still carrying an old definition,
    e.g. the v4 one with 'cc --debug' baked in, must not wait for a manual
    re-register). Called by `virt-surv go`'s launcher once per machine per alias
    version: every rc/profile that ALREADY HAS a virt-surv entry but not the current
    line is upgraded in place - old stamped definitions removed
    (_strip_stamped_definitions), current line appended. Files with NO entry are never
    touched: installing the alias somewhere new stays a consented setup action, this
    only keeps an existing consent current. Returns [(path, removed_count), ...] of
    files actually rewritten; every failure is skipped silently (best-effort - the
    launch must never break on this)."""
    _, interpreter = _check_interpreters(
        ["python", "py", "python3"] if sys.platform == "win32" else ["python3", "python", "py"]
    )
    if not interpreter:
        return []
    resolved = _resolve_repo_root(None)
    script_path = (resolved / "install_helper.py") if resolved else Path(__file__).resolve()
    launcher_path = (
        (resolved / "scripts" / "virt_team_launcher.py")
        if resolved
        else Path(__file__).resolve().parent / "scripts" / "virt_team_launcher.py"
    )
    healed = []
    for _label, rc_path in list(_posix_shell_rc_candidates()) + _powershell_profile_candidates():
        try:
            if not rc_path.is_file():
                continue
            existing = rc_path.read_text(encoding="utf-8", errors="replace")
            if _ALIAS_MARKER not in existing:
                continue  # never installed here - not ours to add
            line = _alias_line_for(rc_path, interpreter, launcher_path, script_path)
            if line in existing:
                continue  # current already
            stripped, removed = _strip_stamped_definitions(existing)
            if rc_path.suffix != ".ps1" and _ALIAS_MARKER in stripped:
                line = f"unalias {_ALIAS_MARKER} 2>/dev/null; {line}"
            addition = f"\n# Added by install_helper.py --setup-alias (2026-08-04)\n{line}\n"
            rc_path.write_text(stripped + addition, encoding="utf-8")
            healed.append((rc_path, len(removed)))
        except OSError:
            continue
    return healed


def _strip_stamped_definitions(existing: str) -> tuple:
    """Remove every alias definition THIS tool wrote earlier - identified by the
    version stamp, which makes a line provably machine-written and safe to delete
    (live report 2026-08-17: upgrades only ever appended, so a corp profile carried 5
    dead definitions, one still baking the abandoned 'cc --debug'; dead lines are not
    just clutter - a parse failure in the newest line falls back to stale baked code).
    Each removed definition also takes its own '# Added by install_helper.py' comment
    (and the spacer blank above it) with it. UNSTAMPED content mentioning the marker
    is never touched, even when it looks like ours - a pre-stamp-era line and a
    user-customised one are indistinguishable, and blind surgery on someone's shell rc
    is the risk this file avoids everywhere else. Returns (stripped_text, removed)."""
    out = []
    removed = []
    for raw in existing.splitlines():
        if _ALIAS_STAMP_ANY_RE.search(raw):
            removed.append(raw)
            if out and _ALIAS_ADDED_BY_RE.match(out[-1]):
                out.pop()
                if out and not out[-1].strip():
                    out.pop()
            continue
        out.append(raw)
    text = "\n".join(out)
    if text and not text.endswith("\n"):
        text += "\n"
    return text, removed


def _posix_shell_rc_candidates() -> list:
    """(label, path) for POSIX shell rc files that already EXIST - doesn't guess which
    shell is "the" shell (a corp Windows user may have both Git Bash and PowerShell), it
    just offers whatever's actually there."""
    home = Path.home()
    candidates = []
    for label, name in (("bash", ".bashrc"), ("zsh", ".zshrc")):
        path = home / name
        if path.is_file():
            candidates.append((label, path))
    return candidates


def _powershell_profile_candidates() -> list:
    """Both standard PowerShell profile paths - they are NOT the same file and this
    matters: Windows PowerShell 5.1 (the version built into every Windows machine,
    verified live 2026-08-04) uses Documents/WindowsPowerShell/..., while PowerShell 7+
    (a separate, opt-in install) uses Documents/PowerShell/... - "changes you make to
    $PROFILE in a Windows PowerShell session only affect that host" per Microsoft's own
    docs. Offering only the 7+ path would silently miss most corp Windows machines, which
    typically only have the built-in 5.1.

    Prefers actually QUERYING each host's own $PROFILE (one extra process per host found
    on PATH, spent only when setting up the alias, not on every diagnostic run) over the
    hardcoded Documents-based guess - live report, 2026-08-04: a corporate machine with
    folder redirection has "Documents" resolve to a NETWORK path (\\\\server\\share\\...),
    so the local Documents/WindowsPowerShell/... guess writes somewhere that host's
    PowerShell never actually reads $PROFILE from. Falls back to the static guess (still
    gated on the Documents parent existing) only when that host's binary isn't on PATH or
    the query itself fails - never silently drops a candidate outright, since the
    original static guess is still correct on the (common) machine with no redirection."""
    if sys.platform != "win32":
        return []
    docs = Path.home() / "Documents"
    candidates = []
    for label, exe, subdir in (
        ("PowerShell 5.1", "powershell.exe", "WindowsPowerShell"),
        ("PowerShell 7+", "pwsh.exe", "PowerShell"),
    ):
        queried = None
        found = shutil.which(exe)
        if found:
            try:
                proc = subprocess.run(
                    [found, "-NoProfile", "-NonInteractive", "-Command", "Write-Output $PROFILE"],
                    capture_output=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=10,
                )
                stdout = proc.stdout.strip() if proc.stdout else ""
                if proc.returncode == 0 and stdout:
                    queried = Path(stdout)
            except (OSError, subprocess.TimeoutExpired):
                pass
        if queried is not None:
            candidates.append((label, queried))
        elif docs.is_dir():
            candidates.append((label, docs / subdir / "Microsoft.PowerShell_profile.ps1"))
    return candidates


def _resolve_repo_root(repo_hint: Optional[str] = None) -> Optional[Path]:
    """Best-known real clone root, tried in order: an explicit hint (almost always
    args.repo), THIS machine's installer-wide config (installer.json's repo_path), then
    __file__'s own parent. Returns None if nothing looks like a real repo.

    The hint matters because __file__ alone is unreliable in two DIFFERENT ways found
    live, 2026-08-04: (1) the curl-bootstrap flow briefly runs a single-file copy from a
    temp extraction dir before the real clone exists, and (2)
    _relocate_if_running_inside_target_repo re-execs from ANOTHER temp copy (to let git
    checkout safely overwrite the running .py file) for the rest of that session's
    life - it passes the real clone through as --repo precisely so callers don't have to
    trust __file__ after that point. A diagnostic or alias-setup step run later in that
    SAME relocated session was misreporting "not installed yet" before args.repo was
    threaded through as this hint."""
    for candidate in (repo_hint, load_config(config_path()).get("repo_path")):
        if isinstance(candidate, str) and candidate:
            path = Path(candidate).expanduser().resolve()
            if looks_like_repo(path):
                return path
    fallback = Path(__file__).resolve().parent
    return fallback if looks_like_repo(fallback) else None


def _verify_alias_line(label: str, rc_path: Path, line: str, marker: str = _ALIAS_MARKER) -> tuple:
    """Runs the JUST-WRITTEN alias/function definition in isolation - not the whole rc
    file, whose unrelated content is out of scope and risky to execute - and confirms
    `marker` actually resolves. Catches a syntax/quoting mistake (or, on Windows, an
    execution-policy block) immediately instead of only when the user opens a new
    terminal and it silently doesn't work (2026-08-04 user request: "harden the alias
    creation ... include test of the alias"). Best-effort: if the shell needed to verify
    isn't itself available, that's reported as a note, not a failure - the line was
    still written correctly as far as this process can tell.

    `marker` defaults to `_ALIAS_MARKER` ('virt-surv') so every existing call site is
    unaffected. Added after a live bug (2026-08-15 corp Windows report): an earlier
    iteration of this file had a SEPARATE alias (virt-team) reuse this function
    unchanged, hardcoded to check 'virt-surv' regardless of what was actually just
    written - a correctly-written line still reported "verification failed: virt-surv:
    not found". That separate alias was later folded into virt-surv itself as a `go`
    subcommand (single alias, per user request), but the parameter stays generalised in
    case a future caller ever needs it again."""
    if rc_path.suffix == ".ps1":
        exe = "powershell.exe" if "5.1" in label else "pwsh.exe"
        found = shutil.which(exe)
        if not found:
            return (True, f"{exe} not on PATH here - could not verify, but the line was written")
        cmd = [
            found,
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            f"{line}; Get-Command {marker} -ErrorAction Stop | Out-Null",
        ]
    else:
        bash = find_bash()
        if not bash:
            return (True, "bash not found - could not verify, but the line was written")
        # expand_aliases is OFF by default in non-interactive bash (bash -c), so a plain
        # `alias virt-surv=...; type virt-surv` would falsely report "not found" even for
        # a perfectly correct alias line - must be enabled explicitly first.
        cmd = [bash, "-c", f"shopt -s expand_aliases\n{line}\ntype {marker} >/dev/null"]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=10
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return (False, f"verification failed to run: {exc}")
    if proc.returncode == 0:
        return (True, "resolves cleanly")
    detail = (proc.stderr or proc.stdout or "").strip()[:150]
    return (False, f"was written but does not resolve cleanly: {detail}")


def run_setup_alias(
    style: Style,
    mark_map: dict,
    assume_yes: bool = False,
    demo: bool = False,
    repo_hint: Optional[str] = None,
) -> int:
    """Standalone (--setup-alias / menu): offers to add a 'virt-surv' alias/function to
    whichever shell rc file(s) actually exist on this machine, pointing at THIS clone.
    Never silent - previews the exact line before writing, confirm-gated per file, skips
    (not duplicates) a file that already has one. demo=True previews everything and
    writes nothing (2026-08-04: demo mode must cover every menu option, not just the
    main install flow). repo_hint: see _resolve_repo_root - pass args.repo when calling
    from anywhere that might run post-relocation (the interactive menu, the full-install
    alias_step).

    'virt-surv go' (2026-08-15 user request: "only one alias, separate parameter to
    launch" - a separate virt-team alias existed for one turn of this same feature and
    was explicitly rejected as confusing) - pre-warms the review-tool cache, resolves
    the /engage resume-vs-new decision outside the LLM entirely
    (scripts/virt_team_launcher.py, unchanged - still the same tested decision engine,
    just invoked from this alias now instead of its own), then launches Claude Code via
    whichever command detect_or_configure_claude_launch_command resolved. This is WHY
    the POSIX form below is now a shell FUNCTION, not a plain `alias`: a POSIX alias is
    pure text substitution with no way to branch on `$1` - `go` needs real conditional
    logic, which only a function can express. `type`/`Get-Command` (what
    _verify_alias_line checks) resolve a function exactly the same as an alias, so
    verification is unaffected by the change."""
    ok, fail = mark_map["ok"], mark_map["fail"]
    rows, interpreter = _check_interpreters(
        ["python", "py", "python3"] if sys.platform == "win32" else ["python3", "python", "py"]
    )
    if not interpreter:
        print(f"{fail} no working Python interpreter found - cannot set up the alias")
        for name, status, detail in rows:
            print(f"    {name}: {status} - {detail}")
        return 1
    resolved = _resolve_repo_root(repo_hint)
    script_path = (resolved / "install_helper.py") if resolved else Path(__file__).resolve()
    launcher_path = (
        (resolved / "scripts" / "virt_team_launcher.py")
        if resolved
        else Path(__file__).resolve().parent / "scripts" / "virt_team_launcher.py"
    )
    if not resolved:
        print(
            style.yellow(
                f"  ! no real clone found - the alias would point at {script_path}, "
                "which may be temporary and stop working once it's cleaned up. Run a "
                "full install (menu option 1) first, then re-run --setup-alias from "
                "inside the clone."
            )
        )
    targets = list(_posix_shell_rc_candidates()) + _powershell_profile_candidates()
    if not targets:
        print(
            f"{fail} no shell config file found (~/.bashrc, ~/.zshrc, or a PowerShell "
            "profile) - nothing to add the alias to"
        )
        return 1
    # Still asked/persisted HERE on first setup (the config must exist for the launcher
    # to answer --launch-command later), but since v5 the value never enters the line
    # templates below - the shell function resolves it at every 'go'. The binding is
    # kept for the surrounding messages that name the configured command.
    launch_cmd = detect_or_configure_claude_launch_command(style, mark_map, assume_yes)
    wrote_any = False
    had_error = False
    for label, rc_path in targets:
        # Changing either line template below? Bump _ALIAS_VERSION (see its comment) -
        # the trailing stamp is the only thing that lets an already-installed profile
        # pick the change up on a re-run.
        line = _alias_line_for(rc_path, interpreter, launcher_path, script_path)
        existing = (
            rc_path.read_text(encoding="utf-8", errors="replace") if rc_path.is_file() else ""
        )
        # Staleness is EXACT-LINE: skip only when the rc already contains the exact
        # line this run would write. Any difference upgrades - a changed template
        # (which is what the version stamp marks), but equally a changed baked-in
        # value: a different interpreter or a moved clone path. (The launch command
        # left this list at v5 - it is resolved at run time now, precisely because
        # baking it produced the 2026-08-16 "doesn't seem to stick" report and then
        # the 2026-08-17 one where even a config RESET kept launching the old value.)
        stale = _ALIAS_MARKER in existing and line not in existing
        if _ALIAS_MARKER in existing and not stale:
            print(
                f"{style.dim('-')} {label} ({rc_path}): a '{_ALIAS_MARKER}' entry already exists, skipped"
            )
            continue
        stripped, removed_lines = existing, []
        if stale:
            # Upgrade path: any existing entry without the CURRENT version stamp is an
            # older template (see _ALIAS_VERSION's comment for the two live reports
            # where shape-specific staleness checks left fixed code unreachable on
            # machines that had already run setup-alias).
            #
            # Two tiers (2026-08-17 live report: append-only upgrades left 5 dead
            # definitions in a corp profile, one still baking 'cc --debug'):
            # STAMPED old definitions are provably ours - removed, previewed below.
            # UNSTAMPED marker content may be user-written or customised - left as-is,
            # the new definition simply appended after it. POSIX additionally needs
            # `unalias` first when unstamped content remains: shell ALIAS expansion
            # happens before function lookup, so an old `alias virt-surv=...` earlier
            # in the same file would keep shadowing a same-named function defined
            # later, even though function redefinition alone is enough in PowerShell
            # (last definition wins there, no alias/function precedence quirk).
            stripped, removed_lines = _strip_stamped_definitions(existing)
            if rc_path.suffix != ".ps1" and _ALIAS_MARKER in stripped:
                line = f"unalias {_ALIAS_MARKER} 2>/dev/null; {line}"
            print(
                style.yellow(
                    f"  ! {label} ({rc_path}): the existing '{_ALIAS_MARKER}' entry is out "
                    "of date (the alias template, interpreter or clone path has "
                    "changed) - replacing it with the current definition."
                )
            )
            for old in removed_lines:
                print(style.dim(f"    would remove: {old.strip()}"))
            if _ALIAS_MARKER in stripped:
                print(
                    style.dim(
                        "    (an unstamped '" + _ALIAS_MARKER + "' line stays untouched - "
                        "not written by this tool, or customised; the new definition "
                        "below it wins)"
                    )
                )
        print(f"  Would add to {label} ({rc_path}):")
        print(style.dim(f"    {line}"))
        if demo:
            print(style.dim("    (demo mode - nothing written)"))
            continue
        # Defaults to declining when the warning above just said this target "may be
        # temporary" - live-caught (fable UX review, 2026-08-05): the confirm defaulted
        # to Yes regardless, so pressing Enter wrote exactly the alias the warning had
        # just advised against.
        if not _agreed(
            style,
            title="Register the 'virt-surv' alias",
            facts=[
                ("head", f"  Add the alias to {label}?\n"),
                ("dim", f"  {rc_path}\n"),
            ],
            detail=[
                ("head", "What gets added"),
                ("plain", line),
                *(
                    [
                        (
                            "warn",
                            "This shell startup file may be temporary on this machine, so "
                            "the alias could vanish. Declining is the default here.",
                        )
                    ]
                    if not resolved
                    else []
                ),
                (
                    "dim",
                    "Only this one line, at the end of the file. Nothing else in it is "
                    "read or changed.",
                ),
            ],
            yes="add the alias",
            no=f"leave {label} alone",
            assume_yes=assume_yes,
            prompt="  Add it?",
            # Unchanged, and the part most worth keeping: it declines by default when the
            # warning above has just said this target may be temporary (2026-08-05).
            default=bool(resolved),
        ):
            print(f"{style.dim('-')} {label}: skipped")
            continue
        try:
            rc_path.parent.mkdir(parents=True, exist_ok=True)
            addition = f"\n# Added by install_helper.py --setup-alias (2026-08-04)\n{line}\n"
            if removed_lines:
                # Removal means a full rewrite of the rc: stripped content + the new
                # definition. Plain append everywhere else, same as always.
                rc_path.write_text(stripped + addition, encoding="utf-8")
                print(
                    f"{ok} removed {len(removed_lines)} outdated definition(s), added to {rc_path}"
                )
            else:
                with rc_path.open("a", encoding="utf-8") as fh:
                    if existing and not existing.endswith("\n"):
                        fh.write("\n")
                    fh.write(addition)
                print(f"{ok} added to {rc_path}")
            wrote_any = True
        except OSError as exc:
            print(f"{fail} could not write {rc_path}: {exc}")
            had_error = True
            continue
        verified, note = _verify_alias_line(label, rc_path, line)
        if verified:
            print(f"  {ok} verified: {note}")
        else:
            print(f"  {fail} verification failed: {note}")
            had_error = True
    if wrote_any:
        # A child process can never modify its parent shell, so the reload HAS to be
        # the user's own action - lead with it, unmissable, not buried mid-paragraph
        # (2026-08-16 user request).
        print(
            f"\n{style.yellow('->')} Now run "
            f"{style.yellow('. $PROFILE')} (PowerShell) or "
            f"{style.yellow('source ~/.bashrc')} (bash; ~/.zshrc for zsh), "
            "or just open a new terminal - the updated alias is not live in THIS "
            "session until you do (no shell auto-reloads its profile mid-session)."
        )
        print(
            style.dim(
                "Then: cd into your PROJECT's root folder (the "
                "same folder you'll run `claude` from) and run 'virt-surv configure' "
                "(asks, recommended defaults pre-filled), 'virt-surv engage' or 'virt-surv "
                "onboard' (same thing - applies every default with zero prompts, then "
                "tells you to launch claude), 'virt-surv archive', 'virt-surv "
                f"list-engagements', or 'virt-surv go' to actually launch ('{launch_cmd}') "
                "with the resume-or-new decision already made for you, in the terminal, "
                "before Claude Code even starts."
            )
        )
    elif not had_error:
        # Nothing was WRITTEN, because the alias is already there - and the reload notice
        # above is skipped, which leaves the one person who most needs it with silence.
        # A shell only reads its rc file at startup, so a terminal opened BEFORE the alias
        # landed does not have it however correct the file is (live report 2026-08-25:
        # "virt-surv isn't added to path after I ran the installer ... command not found").
        # Say it whenever the alias exists, not only when we just wrote it.
        print(
            f"\n{style.dim('The alias is already installed.')} If "
            f"{style.yellow('virt-surv')} is not found in THIS terminal, it started before "
            f"the alias did - run {style.yellow('source ~/.bashrc')} "
            f"({style.yellow('. $PROFILE')} in PowerShell), or open a new terminal."
        )
    return 1 if had_error else 0


_CLAUDE_LAUNCH_CMD_KEY = "claude_launch_command"
# Where the human told us the CLI actually is, when nothing we search could run one.
# Distinct from claude_launch_command, which is what `virt-surv go` execs to start an
# interactive session and may be a shell alias that is not a path at all.
_CLAUDE_CLI_PATH_KEY = "claude_cli_path"


_GITBASH_PERF_MARKER = "# --gitbash-perf: Claude Code completion unload v1"
_GITBASH_PERF_SNIPPET = (
    f"\n{_GITBASH_PERF_MARKER} (added by install_helper.py)\n"
    "# Git Bash's system profile loads ~84 git completion functions; Claude Code's shell\n"
    "# snapshot re-encodes and replays them through subprocess pipelines (~37ms per spawn\n"
    "# on Windows), measured at ~6s of overhead PER Bash call. Under Claude Code only\n"
    "# ($CLAUDECODE is set) the completions are unset - interactive terminals keep them.\n"
    'if [ -n "$CLAUDECODE" ]; then\n'
    "    for _cc_fn in $(compgen -A function 2>/dev/null | grep '^_'); do\n"
    '        unset -f "$_cc_fn" 2>/dev/null\n'
    "    done\n"
    "    unset _cc_fn\n"
    "    complete -r 2>/dev/null\n"
    "fi\n"
)

# Per-repo git settings that speed the git subprocesses everything here spawns (probe
# branch/log reads, statusline) - all long-documented Windows performance flags.
_GIT_PERF_SETTINGS = (
    ("core.fscache", "true"),
    ("core.preloadindex", "true"),
    ("core.untrackedcache", "true"),
)


def _agreed(
    style: Style,
    *,
    title: str,
    facts: list,
    detail: list,
    yes: str,
    no: str,
    assume_yes: bool = False,
    prompt: str,
    default: bool = True,
) -> bool:
    """A yes/no decision on a screen, with what it would do beside it. True to go ahead.

    NOT questions.confirm, and the difference is the pane. These decisions carry content
    someone should read first - a snippet about to be appended to their shell profile,
    the exact git keys about to be written - and a chooser's one-line help cannot hold it.
    decision_screen can, so the thing being agreed to is on screen while the answer is
    given rather than having scrolled past above the question.

    BOTH ANSWERS ARE NAMED. "add it" / "leave the profile alone" is a decision someone can
    make at a glance, where "Add it? [Y/n]" is one they make by guessing which way round
    the default reads - and the default here was yes, on a question that edits a file they
    own.

    Falls back to the typed confirm when no screen can draw, and honours assume_yes first
    so scripted runs never meet a screen at all.

    `default` is for that fallback ONLY, and it is not decoration: a screen names both
    answers, so which one is "the default" is a question nobody is asked. A typed [Y/n] is
    the opposite - the default IS the answer for anyone pressing Enter - so a caller whose
    question overwrites something the user configured themselves must be able to say no is
    the safe side. Hardcoding True here made the status-line conflict question default to
    replacing an existing status line (introduced and caught 2026-08-31).
    """
    if assume_yes:
        return bool(default)
    answer = _tiered_installer_screen(
        "decision_screen",
        [("yes", yes), ("no", no)],
        facts,
        detail,
        _this_module(),
        title=title,
        repo=_repo_hint(),
    )
    if answer is None:  # no screen anywhere - the typed question it has always had
        return bool(confirm(prompt, default=default, assume_yes=False, style=style))
    return answer == "yes"


def run_gitbash_perf(
    style: Style, mark_map: dict, assume_yes: bool = False, demo: bool = False
) -> int:
    """Advanced item 11 (2026-08-18, from a corp live diagnosis: Claude Code taking 1-2
    minutes to a first prompt on Windows Git Bash, ~6s per Bash call): two mechanical
    fixes plus printed advice for what needs IT.

    1. The $CLAUDECODE-gated completion unload into the bash profile - the measured
       ~15x fix (snapshot ~6,196ms -> ~261ms). Gated so interactive terminals keep
       their completions; versioned marker keeps it idempotent. Appends to the first
       existing of ~/.bash_profile / ~/.profile; creating a NEW .bash_profile sources
       ~/.profile first so an existing profile chain is never silently shadowed.
    2. Per-repo git performance flags on the CURRENT directory's repo when it is one
       (core.fscache/preloadindex/untrackedcache).
    3. Advice only (admin/IT territory): antivirus exclusions for the project dir,
       short local paths over deep/network ones, WSL2 as the structural alternative."""
    ok = mark_map["ok"]
    s = style
    print("")
    print(s.bold("Git Bash performance fix (Claude Code on Windows)"))
    home = Path.home()
    profile = None
    for name in (".bash_profile", ".profile"):
        if (home / name).is_file():
            profile = home / name
            break
    create_new = profile is None
    if create_new:
        profile = home / ".bash_profile"
    existing = profile.read_text(encoding="utf-8", errors="replace") if profile.is_file() else ""
    if _GITBASH_PERF_MARKER in existing:
        print(f"{s.dim('-')} {profile}: the completion-unload fix is already installed")
    else:
        print(f"  Would append to {profile}:")
        print(s.dim("    " + _GITBASH_PERF_SNIPPET.strip().replace("\n", "\n    ")))
        if demo:
            print(s.dim("    (demo mode - nothing written)"))
        elif _agreed(
            style,
            title="Git Bash performance fix",
            facts=[
                ("head", f"  Append the fix to {profile.name}?\n"),
                ("dim", f"  {profile}\n"),
            ],
            detail=[
                ("head", "What gets appended"),
                ("plain", _GITBASH_PERF_SNIPPET.strip()),
                (
                    "dim",
                    "Gated on $CLAUDECODE, so your interactive terminals keep their "
                    "completions. Measured on the box this came from: a Bash snapshot "
                    "went from ~6,200ms to ~261ms.",
                ),
            ],
            yes="add it",
            no="leave the profile alone",
            assume_yes=assume_yes,
            prompt="  Add it?",
        ):
            try:
                with profile.open("a", encoding="utf-8") as fh:
                    if create_new:
                        fh.write("[ -f ~/.profile ] && . ~/.profile\n")
                    fh.write(_GITBASH_PERF_SNIPPET)
                print(f"{ok} appended to {profile} - new Claude Code sessions get fast Bash calls")
            except OSError as exc:
                print(s.yellow(f"  ! could not write {profile}: {exc}"))
    repo = Path.cwd()
    if (repo / ".git").exists():
        if demo:
            print(
                s.dim(
                    f"    would set git perf flags on {repo} (fscache/preloadindex/untrackedcache)"
                )
            )
        elif _agreed(
            style,
            title="Git performance flags",
            facts=[
                ("head", f"  Set git performance flags on {repo.name}?\n"),
                ("dim", f"  {repo}\n"),
            ],
            detail=[
                ("head", "What gets set"),
                *[("plain", f"{key} = {val}") for key, val in _GIT_PERF_SETTINGS],
                (
                    "dim",
                    "Per-repository git config on this repo only. Nothing global, and "
                    "nothing outside it.",
                ),
            ],
            yes="set them",
            no="leave this repo's config alone",
            assume_yes=assume_yes,
            prompt=f"  Also set git performance flags on this repo ({repo.name})?",
        ):
            for key, val in _GIT_PERF_SETTINGS:
                run_cmd(["git", "-C", str(repo), "config", key, val])
            print(f"{ok} git perf flags set ({', '.join(k for k, _ in _GIT_PERF_SETTINGS)})")
    print(
        s.dim(
            "  Needs IT/admin (advice only): antivirus exclusions for the project folder and\n"
            "  the Git Bash install; prefer short local paths (C:/dev/...) over deep or\n"
            "  network-homed ones; WSL2 avoids the Windows process-spawn overhead entirely."
        )
    )
    return 0


def run_howto(style: Style) -> int:
    """Menu item 5 (2026-08-18 user request): Morgan explains, in plain words, how to
    actually use the plugin day to day. Narrative, not a reference - the README and
    quick-start PDF carry the detail; this is the 60-second version a new user reads
    once from inside the installer."""
    s = style
    hat = "🎩 " if _can_encode("🎩") else ""
    print("")
    print(s.bold(f"{hat}Morgan (PM) here - I'm an AI agent with Virtual Surveillance IT."))
    print("Here's how working with the team goes, start to finish:")
    print("")
    print(s.bold("  Starting a session"))
    print(
        "  cd into your project folder and type " + s.cyan("virt-surv go") + ". You'll see\n"
        "  your project's team settings at a glance, then a menu: resume an open piece of\n"
        "  work, start something new, or just launch. Pick with the arrow keys (or the\n"
        "  hotkeys) and Claude Code starts with your choice already typed in. If a project\n"
        "  isn't set up yet, go walks you through it first."
    )
    print("")
    print(s.bold("  Working with me"))
    print(
        "  Describe whatever you've got in plain English - a problem to solve, code to\n"
        "  review, something to build, data to analyse. I classify it, ask what I genuinely\n"
        "  need to know (batched, one screen), tell you how many specialists I intend to\n"
        "  use and roughly what it will cost, and wait for your go-ahead. Then I run the\n"
        "  work in small stages and come back to you at each gate. You only invoke the team\n"
        "  once per piece of work - after that, just reply normally."
    )
    print("")
    print(s.bold("  What you get back"))
    print(
        "  Everything lands in your project under artifacts/<engagement>/ - the brief, the\n"
        "  work itself, reviews with evidence, and a closing summary email, each as .md and\n"
        "  rendered .html. A START-HERE.md index shows where any engagement stands."
    )
    print("")
    print(s.bold("  The standing safety rules"))
    print(
        "  I never read data/raw/ (hard-blocked), never run the code under review without\n"
        "  your explicit consent (you create the marker; my asking is not the grant), and\n"
        "  treat all real-looking data as sensitive - synthetic or masked only. Outside an\n"
        "  engagement the plugin is dormant: a normal session is just ordinary Claude Code."
    )
    print("")
    print(
        s.dim(
            "  More detail: README.md · docs/quick-start.pdf (one page) · /meet-the-team\n"
            "  inside a session introduces the 13 specialists."
        )
    )
    return 0


def run_alias_manage(
    style: Style,
    mark_map: dict,
    assume_yes: bool = False,
    demo: bool = False,
    repo_hint: Optional[str] = None,
) -> int:
    """Advanced-menu alias manager (2026-08-17 user request): the two things a human
    ever needs here in one place - register/update the 'virt-surv' alias, or change the
    command 'virt-surv go' launches Claude Code with (previously buried in Machine
    defaults - the "no obvious setting" live report). Since alias v5 the command is
    resolved from this config at every 'go' (pre-v5 aliases had it BAKED into the
    shell function - the "doesn't stick" live bug, and its 2026-08-17 sequel where
    even a config reset kept launching the old value); the refresh offer below exists
    to carry pre-v5 installs over."""
    s = style
    print("")
    print(s.bold("Manage the 'virt-surv' alias"))
    # Through the framework, which retires the trap this exact screen fell into on
    # 2026-08-30: blank input at a "[1]" prompt means TAKE THE DEFAULT, while "" from a
    # screen means the human left. Identical as strings, opposite in meaning, and folding
    # them together made blank-Enter back out instead of registering the alias. An Answer
    # cannot be ambiguous that way: cancelled is a flag, not a value, so there is no
    # string for the two meanings to collide in.
    answer = _ask().choose(
        "Manage the 'virt-surv' alias",
        [
            ("1", "Register or update the alias", "recommended after a plugin update"),
            ("2", "Change the launch command", "what 'virt-surv go' runs to start Claude Code"),
        ],
    )
    if answer.cancelled:
        return 0
    if answer.value == "1":
        return run_setup_alias(style, mark_map, assume_yes, demo, repo_hint)
    cfg = load_config(config_path())
    current = cfg.get(_CLAUDE_LAUNCH_CMD_KEY) or ""
    picked = ask(
        f"  Launch command (currently: {current or 'unset, launches `claude`'}) - blank to keep",
        "",
        False,
        style=style,
    ).strip()
    if not picked or picked == current:
        print(f"{s.dim('-')} unchanged")
        return 0
    if demo:
        print(s.dim(f"    would set launch command = {picked}"))
        return 0
    cfg[_CLAUDE_LAUNCH_CMD_KEY] = picked
    save_config(config_path(), cfg)
    print(f"  saved: 'virt-surv go' will launch via {picked!r}")
    # A v5 alias reads this config at every 'go', so the change is already live - but
    # an OLDER installed alias still has a command baked in and needs one refresh to
    # reach v5. Offer it once; on v5 the refresh is a no-op skip, so this stays cheap.
    if confirm(
        "  Refresh the alias too? (needed once if it was installed before v5 - a "
        "current alias picks the change up on the next 'go' automatically)",
        default=True,
        assume_yes=assume_yes,
        style=s,
    ):
        return run_setup_alias(style, mark_map, assume_yes=True)
    return 0


def detect_or_configure_claude_launch_command(
    style: Style, mark_map: dict, assume_yes: bool = False
) -> str:
    """The command `virt-surv go` execs to actually start Claude Code - not necessarily
    `claude` itself (2026-08-14 user request): a user may already have their own
    alias/function (e.g. `cc`) that wraps `claude` with default flags, and `go` must
    launch THAT, not bypass it. Machine-wide config (installer.json's
    claude_launch_command key), same storage tier as default_review_tools - detected/
    prompted ONCE, as part of virt-surv's own alias setup; every later call returns the
    stored value silently, no reprompt (explicit 2026-08-14 user request). Change it
    later via machine_defaults_step without re-running the whole alias setup.

    Detection is a hint, not a verification: `shutil.which("claude")` only ever suggests
    a DEFAULT for the prompt - it cannot detect a shell alias/function (those aren't on
    PATH, they only exist inside a running shell), which is exactly the case this exists
    to support. The human confirms either way."""
    ok = mark_map["ok"]
    cfg = load_config(config_path())
    existing = cfg.get(_CLAUDE_LAUNCH_CMD_KEY)
    if isinstance(existing, str) and existing:
        return existing
    default = "claude"
    if not shutil.which("claude"):
        print(
            style.dim(
                "  ('claude' not found on PATH here - if you launch Claude Code via your own "
                "alias/function, type it below.)"
            )
        )
    cmd = ""
    if not assume_yes:
        # WHAT IS ACTUALLY HERE, offered by name. _claude_candidates walks the same
        # discovery tiers the launcher uses, so this is the machine's own answer rather
        # than a guess the human has to spell.
        options = []
        seen = set()
        for found, how in _claude_candidates():
            if found in seen:
                continue
            seen.add(found)
            options.append((found, found, f"found on this machine ({how})"))
            if len(options) >= 3:
                break
        options.append(
            (
                "",
                "something else",
                "your own alias or function that wraps claude, e.g. 'cc' - type it next",
            )
        )
        answer = _ask().choose("What launches Claude Code here?", options)
        if answer.cancelled:
            # A CANCEL AND "NOBODY WAS THERE" ARRIVE THE SAME WAY and mean different
            # things. With a terminal, the human looked and left: remember nothing, ask
            # again next time. Without one - piped, scripted, no tty - there was nobody to
            # leave, and the old behaviour applies: fall through to the typed question,
            # which takes its own default and persists it exactly as it always did.
            try:
                left_deliberately = sys.stdin.isatty()
            except Exception:
                left_deliberately = False
            if left_deliberately:
                return default
        cmd = str(answer.value or "")
    if not cmd:
        cmd = (
            ask(
                "  What command launches Claude Code on this machine? (your own "
                "alias/function is fine, e.g. 'cc')",
                default,
                assume_yes,
                style=style,
            ).strip()
            or default
        )
    cfg[_CLAUDE_LAUNCH_CMD_KEY] = cmd
    if save_config(config_path(), cfg):
        print(f"{ok} remembered '{cmd}' as the Claude Code launch command for this machine")
    return cmd


_BASHRC_GUARD_MARKER = "# --fix-bashrc: non-interactive shell guard"
_BASHRC_GUARD_SNIPPET = (
    f"{_BASHRC_GUARD_MARKER} (added by install_helper.py)\n"
    "# Claude Code's Bash tool sources this file non-interactively before every call, so a\n"
    "# slow .bashrc costs every single tool call - and past a certain point (Claude Code's\n"
    "# own shell-snapshot timeout) can make it silently lose shell state (cwd, PATH,\n"
    "# functions) between calls entirely. This line skips everything below for\n"
    "# non-interactive shells; normal interactive terminal use is unaffected. If a Bash\n"
    "# tool call later seems to be missing a PATH entry or env var this file used to set,\n"
    "# narrow this to wrap just the slow block (nvm/pyenv/conda init, cloud-auth checks,\n"
    "# etc.) in `if [[ $- == *i* ]]; then ... fi` instead of this blanket early return.\n"
    "[[ $- == *i* ]] || return\n"
)


def run_fix_bashrc(
    style: Style, mark_map: dict, assume_yes: bool = False, demo: bool = False
) -> int:
    """Standalone (--fix-bashrc / menu): offers to add a non-interactive-shell early-return
    guard to ~/.bashrc, so slow interactive-only setup (nvm/pyenv/conda init, cloud-auth
    checks, network calls) doesn't run on every Claude Code Bash tool call - the root cause
    traced in a live corp-Windows dogfooding session (2026-08-14) where a .bashrc taking
    >10s to source non-interactively made Claude Code's shell-snapshot process hit its own
    timeout and get killed, dropping shell state between calls.

    `--check-env`'s `_check_shell_startup_time` only detects and warns (that check must stay
    non-blocking/informational); this is the explicit, consent-gated, opt-in counterpart -
    never silent, previews the exact snippet before writing, backs up the existing file
    first (dated, collision-safe - same pattern the settings.json writers use), and is
    idempotent (skips, doesn't duplicate, if the marker is already present). demo=True
    previews and writes nothing. Deliberately does NOT try to guess which specific lines in
    an unseen .bashrc are the slow ones - a blanket early-return is the only thing that can
    be offered without reading the file's actual content, so the preview says so plainly and
    the snippet's own comment tells the user how to narrow it by hand if it turns out to be
    too broad (some non-interactive tool calls may need PATH/env vars this file sets)."""
    ok, fail = mark_map["ok"], mark_map["fail"]
    bashrc = Path.home() / ".bashrc"
    if not bashrc.is_file():
        print(f"{fail} no ~/.bashrc found - nothing to fix")
        return 1
    existing = bashrc.read_text(encoding="utf-8", errors="replace")
    if _BASHRC_GUARD_MARKER in existing:
        print(f"{style.dim('-')} ~/.bashrc: guard already present, skipped")
        return 0
    print(f"  Would prepend to {bashrc}:")
    for line in _BASHRC_GUARD_SNIPPET.splitlines():
        print(style.dim(f"    {line}"))
    print(
        style.yellow(
            "  ! this guards EVERYTHING below it for non-interactive shells - if this file "
            "sets PATH/env vars a Bash tool call genuinely needs (not just interactive "
            "conveniences), narrow the guard by hand afterwards (see the comment in the "
            "snippet above)"
        )
    )
    if demo:
        print(style.dim("    (demo mode - nothing written)"))
        return 0
    # default=assume_yes (not a hardcoded False): an explicit --yes IS the consent for a
    # flag the user named on purpose, so it should proceed, not silently decline via
    # confirm()'s assume_yes-shortcuts-to-default path. A genuinely interactive session
    # (assume_yes=False, real TTY) still shows the prompt and defaults to declining if the
    # user just presses Enter - the write is consequential enough to want an explicit yes.
    if not _agreed(
        style,
        title="Fix a slow ~/.bashrc",
        facts=[
            ("head", "  Add the guard to ~/.bashrc?\n"),
            ("dim", f"  {bashrc}\n"),
        ],
        detail=[
            ("head", "What gets added"),
            ("plain", _BASHRC_GUARD_SNIPPET.strip()),
            (
                "dim",
                "A dated backup of ~/.bashrc is written first. Your interactive shells are "
                "unaffected - the guard only short-circuits the non-interactive shells "
                "Claude Code spawns for every Bash call.",
            ),
        ],
        yes="add the guard",
        no="leave ~/.bashrc alone",
        assume_yes=assume_yes,
        prompt="  Add it?",
        # An explicit --yes IS consent for a flag the user named on purpose; a bare Enter
        # at the typed prompt is not, because the write is consequential.
        default=assume_yes,
    ):
        print(f"{style.dim('-')} ~/.bashrc: skipped")
        return 0
    today = datetime.now().strftime("%Y-%m-%d")
    backup = bashrc.with_name(f".bashrc.bak-{today}")
    n = 1
    while backup.exists():
        n += 1
        backup = bashrc.with_name(f".bashrc.bak-{today}.{n}")
    try:
        backup.write_text(existing, encoding="utf-8")
        _atomic_write_text(bashrc, _BASHRC_GUARD_SNIPPET + "\n" + existing)
    except OSError as exc:
        print(f"{fail} could not write {bashrc}: {exc}")
        return 1
    print(f"{ok} guard added to {bashrc} (backup: {backup})")
    print(style.dim("  Verify: time bash -c 'source ~/.bashrc' - should now be near-instant."))
    return 0


# --------------------------------------------------------------- stale plugin cache cleanup
#
# Live report (2026-08-14, corp Windows box): a bootstrap failure traced to the plugin cache
# being stuck on a 0.22.0 install while the registry/current release had long since moved to
# 0.33.62 - the stale directory was pure dead weight, never cleaned up by any update path.
# _PLUGIN_CACHE_MARKER must match scripts/find_plugin_root.py's own _TEAM_NAME constant -
# both identify a genuine install of THIS plugin the same way (a docs/team-operating-guide.md
# file under a path segment with this literal name), so a stale-cache scan can never mistake
# an unrelated cached plugin for one of this one's old versions. Duplicated rather than
# imported: install_helper.py can run standalone (a curl-bootstrap temp copy with no
# scripts/ sibling), so it must not depend on find_plugin_root.py being importable.

_PLUGIN_CACHE_MARKER = "compliance-surveillance-team"


def _plugin_cache_version_dirs(home: Path) -> list:
    """Every version directory for this plugin under ~/.claude/plugins/{cache,marketplaces} -
    same discovery rule as find_plugin_root.py's filesystem fallback (see module comment
    above; depth-bounded like it since 2026-08-17, same AV-scan rationale)."""
    bases = (home / ".claude" / "plugins" / "cache", home / ".claude" / "plugins" / "marketplaces")
    patterns = (
        "*/docs/team-operating-guide.md",
        "*/*/docs/team-operating-guide.md",
        "*/*/*/docs/team-operating-guide.md",
        "*/*/*/*/docs/team-operating-guide.md",
    )
    found: list = []
    for base in bases:
        if not base.is_dir():
            continue
        for pattern in patterns:
            for marker in base.glob(pattern):
                if _PLUGIN_CACHE_MARKER in marker.parts:
                    version_dir = marker.parent.parent
                    if version_dir not in found:
                        found.append(version_dir)
    return found


# Registry filenames drift across Claude Code versions - same set find_plugin_root.py
# consults (2026-08-17 corp debug session).
_PLUGIN_REGISTRY_NAMES = ("installed_plugins.json", "config.json", "plugins.json")


def _registry_install_paths(home: Path) -> list:
    """Every installPath string any known registry file names, schema-agnostic (the same
    walk _active_plugin_install_path always did, shared out so the cleaner can
    cross-reference the registry against what the marker scan found - the 2026-08-17
    corp debug session's finding 2: a partial install without the operating-guide marker
    was invisible to the cleaner while the registry kept pointing at it, causing probe
    failures with no cleanup path)."""
    paths: list = []

    def _walk(obj) -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key == "installPath" and isinstance(value, str):
                    if value not in paths:
                        paths.append(value)
                else:
                    _walk(value)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    for name in _PLUGIN_REGISTRY_NAMES:
        try:
            data = json.loads((home / ".claude" / "plugins" / name).read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        _walk(data)
    return paths


def _looks_like_this_plugin(path: Path) -> bool:
    """Manifest names this plugin, or the path itself carries a recognisable token - the
    second test exists because a PARTIAL install may have lost its manifest too, and a
    ghost we cannot attribute must never be offered for deletion (it could belong to any
    other plugin)."""
    try:
        text = (path / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8-sig")
        if _PLUGIN_CACHE_MARKER in text:
            return True
    except OSError:
        pass
    lowered = str(path).lower()
    return _PLUGIN_CACHE_MARKER in lowered or "virtual-surv" in lowered


def _active_plugin_install_path(home: Path) -> Optional[Path]:
    """The install path the registry currently points at for this plugin - the ONE version
    directory that must never be removed, whatever it looks like, since it's what Claude
    Code is actually configured to use right now. None if the registry is missing/unreadable/
    silent on this plugin - callers must treat that as "don't know", never as "safe to
    remove everything" (see run_clean_plugin_cache's own newest-wins fallback for that case,
    which is deliberately more conservative than 'nothing is active')."""
    for raw_path in _registry_install_paths(home):
        candidate = Path(raw_path)
        manifest = candidate / ".claude-plugin" / "plugin.json"
        try:
            text = manifest.read_text(encoding="utf-8-sig")
        except OSError:
            continue  # this candidate doesn't actually exist on disk - not the active one
        if _PLUGIN_CACHE_MARKER in text:
            return candidate
    return None


_CACHE_VERSION_SORT_RE = re.compile(r"(\d+)|(\D+)")


def _cache_version_sort_key(path: Path) -> list:
    """Same `sort -V`-approximating split find_plugin_root.py's _sort_key uses (digit runs
    compare numerically) - only reached when the registry can't confirm which install is
    active, to pick "the newest looking" one as the conservative thing to keep."""
    parts = _CACHE_VERSION_SORT_RE.findall(str(path))
    return [(int(d), "") if d else (-1, s) for d, s in parts]


def _dir_size(path: Path) -> int:
    total = 0
    for p in path.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            continue
    return total


def _human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}GB"


def _purge_stale_registry_entries(home: Path, bad_paths: list) -> list:
    """Remove registry entries whose installPath is one of `bad_paths` - THIS plugin's
    entries pointing at nothing on disk (2026-08-18 user decision: the cleaner used to
    report these and refuse to touch Claude Code's own file; now it repairs them, with
    the same care the settings writers get: .bak of the original, atomic replace,
    surgical removal of ONLY the matched nodes). A dict node carrying a bad installPath
    is dropped from its parent list, or its parent dict key is removed when the node is
    a direct value; a bare string installPath in a list is dropped likewise. Returns
    [(file, removed_count)] for the files actually modified."""
    bad = {str(p) for p in bad_paths}
    results = []
    for name in _PLUGIN_REGISTRY_NAMES:
        path = home / ".claude" / "plugins" / name
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        removed = 0

        def _is_bad_node(node) -> bool:
            return isinstance(node, dict) and str(node.get("installPath") or "") in bad

        def _prune(obj):
            nonlocal removed
            if isinstance(obj, dict):
                for key in list(obj.keys()):
                    val = obj[key]
                    if _is_bad_node(val):
                        del obj[key]
                        removed += 1
                    elif isinstance(val, str) and key == "installPath" and val in bad:
                        # a dict whose own installPath is bad but which the parent must
                        # decide about - handled by the parent pass; leave here
                        continue
                    else:
                        _prune(val)
            elif isinstance(obj, list):
                keep = []
                for item in obj:
                    if _is_bad_node(item) or (isinstance(item, str) and item in bad):
                        removed += 1
                        continue
                    _prune(item)
                    keep.append(item)
                obj[:] = keep

        _prune(data)
        # top-level dict entries whose VALUE is a bad node (e.g. {"team@mkt": {...}})
        if removed:
            _write_json_backup(path, data)
            results.append((path, removed))
    return results


def _offer_registry_repair(
    home: Path, stale_entries: list, style: Style, mark_map: dict, assume_yes: bool, demo: bool
) -> None:
    """List the dead entries and, on confirm, remove them from the registry files
    (2026-08-18 user decision - the report-only stance left an out-of-date registry the
    user could see but the tool refused to fix). Each modified file keeps a .bak; the
    write is atomic; only entries matching the ALREADY-identified this-plugin dead paths
    are touched."""
    ok = mark_map["ok"]
    for rp in stale_entries:
        print(f"    {rp} (does not exist)")
    if demo:
        print(style.dim("    (demo mode - the registry would be repaired, .bak kept)"))
        return
    if not _agreed(
        style,
        title="Repair the plugin registry",
        facts=[
            ("head", f"  Remove {len(stale_entries)} dead entr(y/ies)?\n"),
            ("dim", "  they point at installs that no longer exist\n"),
        ],
        detail=[
            ("head", "What would be removed"),
            *[("plain", str(rp)) for rp in stale_entries],
            ("dim", "A .bak of each registry file is kept, so this one does undo."),
        ],
        yes="repair the registry",
        no="leave the registry as it is",
        assume_yes=assume_yes,
        prompt="  Repair the registry now (remove those dead entries; a .bak of each "
        "file is kept)?",
        default=assume_yes,
    ):
        print(
            style.dim("  - left as-is. Manual fix: reinstall (option 1) or /plugin in Claude Code.")
        )
        return
    results = _purge_stale_registry_entries(home, stale_entries)
    if not results:
        print(style.yellow("  nothing matched in the registry files - no changes made"))
        return
    for path, removed in results:
        print(
            f"{ok} {path.name}: removed {removed} dead entr{'y' if removed == 1 else 'ies'} (backup: {path.name}.bak)"
        )
    print(
        style.dim(
            "  Restart Claude Code. If the plugin should still be installed here, run a "
            "full install (option 1) to re-register it cleanly."
        )
    )


def run_clean_plugin_cache(
    style: Style, mark_map: dict, assume_yes: bool = False, demo: bool = False
) -> int:
    """Standalone (--clean-plugin-cache / menu): removes STALE cached install directories
    for this plugin - old versions an update left behind under
    ~/.claude/plugins/{cache,marketplaces}, never cleaned up by any existing path. Live
    report (2026-08-14): a Windows box's bootstrap broke tracing to exactly this - a cached
    0.22.0 install still sitting on disk, dozens of releases behind current.

    Never removes the version the registry currently points at (`_active_plugin_install_path`),
    even if something else made that install look broken - it is still the one Claude Code
    is configured to use, and this tool's job is disk hygiene, not fixing that separately.
    If the registry can't confirm an active install at all (missing/corrupt/silent on this
    plugin), falls back to keeping only the newest-looking version and flags that this is a
    guess, not a confirmed answer. Preview-first (every directory listed with its size before
    anything is touched), confirm-gated (same pattern as --fix-bashrc: an explicit --yes IS
    the consent, a real interactive prompt still defaults to declining on a bare Enter).
    demo=True lists what would be removed and deletes nothing."""
    ok, fail = mark_map["ok"], mark_map["fail"]
    home = Path.home()
    version_dirs = _plugin_cache_version_dirs(home)
    # Registry cross-reference (2026-08-17 corp debug session, finding 2): the marker
    # scan alone cannot see a PARTIAL install (no operating-guide marker), yet the
    # registry can keep pointing at one forever, breaking every probe with no cleanup
    # path. Ghosts = registry paths attributable to this plugin, on disk, that the
    # marker scan missed; stale entries = registry paths for this plugin with nothing
    # on disk at all (report-only - the registry is Claude Code's file, repaired by a
    # reinstall or /plugin, never edited here).
    marker_resolved = {d.resolve() for d in version_dirs}
    ghosts: list = []
    stale_entries: list = []
    for raw in _registry_install_paths(home):
        rp = Path(raw)
        if not _looks_like_this_plugin(rp):
            continue
        if rp.is_dir():
            if rp.resolve() not in marker_resolved:
                ghosts.append(rp)
        else:
            stale_entries.append(rp)
    if not version_dirs and not ghosts:
        if stale_entries:
            print(
                style.yellow(
                    f"  ! nothing on disk to clean, but the registry still names "
                    f"{len(stale_entries)} missing install path(s) for this plugin:"
                )
            )
            _offer_registry_repair(home, stale_entries, style, mark_map, assume_yes, demo)
            return 0
        print(
            f"{style.dim('-')} no cached installs found under "
            f"{home / '.claude' / 'plugins'} - nothing to clean"
        )
        return 0
    active = _active_plugin_install_path(home)
    print(f"  Found {len(version_dirs)} cached install(s) under {home / '.claude' / 'plugins'}:")
    for d in version_dirs:
        is_active = active is not None and d.resolve() == active.resolve()
        tag = style.green(" (ACTIVE - kept)") if is_active else ""
        print(f"    {d} - {_human_size(_dir_size(d))}{tag}")
    for g in ghosts:
        is_active = active is not None and g.resolve() == active.resolve()
        tag = (
            style.yellow(" (ACTIVE but PARTIAL - kept; repair with a reinstall)")
            if is_active
            else style.yellow(" (ghost: in the registry, no operating-guide marker - removable)")
        )
        print(f"    {g} - {_human_size(_dir_size(g))}{tag}")
    if stale_entries:
        print(
            style.yellow(
                f"  ! the registry also names {len(stale_entries)} install path(s) that no "
                "longer exist on disk:"
            )
        )
        _offer_registry_repair(home, stale_entries, style, mark_map, assume_yes, demo)
    removable_ghosts = [
        g for g in ghosts if not (active is not None and g.resolve() == active.resolve())
    ]
    if active is not None:
        stale = [d for d in version_dirs if d.resolve() != active.resolve()] + removable_ghosts
    elif not version_dirs:
        stale = removable_ghosts
    else:
        print(
            style.yellow(
                "  ! could not confirm which install is active (registry missing/unreadable/"
                "silent on this plugin) - keeping only the newest-looking version as a "
                "conservative guess, not a confirmed answer"
            )
        )
        newest = max(version_dirs, key=_cache_version_sort_key)
        stale = [d for d in version_dirs if d != newest] + removable_ghosts
    if not stale:
        print(f"{style.dim('-')} nothing stale - only the active install is present")
        return 0
    total = sum(_dir_size(d) for d in stale)
    print(f"  Would remove {len(stale)} stale install(s), freeing {_human_size(total)}.")
    if demo:
        print(style.dim("    (demo mode - nothing removed)"))
        return 0
    if not _agreed(
        style,
        title="Clean stale plugin cache",
        facts=[
            ("head", f"  Remove {len(stale)} stale install(s)?\n"),
            ("dim", f"  frees {_human_size(total)}\n"),
        ],
        detail=[
            ("head", "What would be deleted"),
            *[("plain", str(d)) for d in stale],
            (
                "dim",
                "The active install is not in that list and is not touched. These are "
                "deleted outright rather than moved, so this one does not undo.",
            ),
        ],
        yes=f"remove {len(stale)} install(s)",
        no="keep them all",
        assume_yes=assume_yes,
        prompt="  Remove them?",
        default=assume_yes,  # deleting outright: a bare Enter must not do it
    ):
        print(f"{style.dim('-')} skipped")
        return 0
    removed = 0
    for d in stale:
        try:
            shutil.rmtree(d)
            print(f"{ok} removed {d}")
            removed += 1
        except OSError as exc:
            print(f"{fail} could not remove {d}: {exc}")
    return 0 if removed == len(stale) else 1


# ------------------------------------------------------------------ analyser output check
#
# 2026-08-04: code-reviewer's own analysers (gitleaks, bandit, mypy) were found to leak
# decorative overhead into their captured output by default - some of it (gitleaks'
# banner) is unconditional, some of it (mypy's ANSI color, bandit's animated progress
# spinner) turned out to depend on the environment's FORCE_COLOR/terminal-detection state,
# which live research showed is NOT reliably uniform across platforms: rich (bandit's
# spinner library) has a documented, unresolved detection mismatch specifically on Git
# Bash/mintty - the terminal Claude Code actually uses on Windows - since mintty doesn't
# present as a native Win32 console the way rich/colorama's detection expects. Rather than
# assert the fix works everywhere, this makes it checkable: runs each analyser with its
# recommended flags against a trivial, clean throwaway file and reports whether the
# captured output actually came back clean IN THIS environment.
#
# semgrep and pip-audit are deliberately NOT checked here at all (removed 2026-08-04,
# after their own suppression-flag fixes still weren't enough): both make network calls
# with no reliable offline mode found - pip-audit refreshes its vulnerability index on
# every run even against zero packages and doesn't fail fast when that network is blocked;
# semgrep makes an unconditional version-check ping regardless of --config, and --config
# auto additionally re-fetches its ruleset over the network on every run with no local
# caching observed. Both caused repeated live corp-proxy hangs, in this check and in real
# reviews. See code-reviewer.md for the full removal rationale - this probe simply no
# longer names them, so they're never invoked even if installed.

_TOOL_CHECK_CLEAN_PY = "def add(a: int, b: int) -> int:\n    return a + b\n"
# Deliberately multi-line with each select target on its own line - sqlfluff's default
# layout.select_targets rule (LT09) fails a single-line "SELECT id, name" even though
# nothing is actually wrong with it, so a naive "obviously clean" fixture isn't (live-
# tested 2026-08-04 against a real sqlfluff install before trusting this).
_TOOL_CHECK_CLEAN_SQL = "SELECT\n    id,\n    name\nFROM users\nWHERE id = 1;\n"
_TOOL_CHECK_CLEAN_SH = '#!/bin/sh\necho "hello"\n'

# The officially supported, on/off/auto-configurable review-tool set (_REVIEW_TOOLS below)
# - every name here MUST also appear in _REVIEW_TOOLS, and vice versa, enforced by a test.
# (binary, recommended-flags, fixture kind, per-call timeout)
_TOOL_OUTPUT_CHECKS = (
    ("ruff", ["check", "--quiet"], "py-file", 20),
    ("mypy", ["--no-color-output", "--no-error-summary"], "py-file", 20),
    ("bandit", ["-q"], "py-file", 20),
    ("black", ["--check", "--quiet"], "py-file", 20),
    ("sqlfluff", ["lint", "--dialect", "ansi"], "sql-file", 20),
    ("shfmt", ["-d"], "sh-file", 20),
    (
        "gitleaks",
        ["detect", "--no-git", "--no-banner", "--log-level", "error", "--source"],
        "dir",
        20,
    ),
)


def probe_analyser_output(tmpdir: Path, runner=None, only=None):
    """Runs each known-noisy analyser, with its recommended suppression flags, against a
    trivial clean throwaway file - a run with zero real findings should come back empty or
    near-empty. A GENERATOR, not a batch return: yields (name, status, detail) as each tool
    finishes, specifically so a caller can print progress live - an earlier batched version
    ran every tool before printing anything, which on a slow or network-blocked tool
    looked exactly like a hang (live report, 2026-08-04). Status is one of SKIP (not
    installed), OK (clean), NOISY (leaked decoration - an escape code, or unexpectedly
    large output for a trivial clean file), ERROR (crashed, timed out, or a flag wasn't
    recognised - a version-pin mismatch is exactly this shape; a timeout specifically means
    "network-blocked", the exact semgrep/pip-audit failure shape this now exists to catch
    before a tool is ever forced 'on').

    `only`, if given, restricts the run to those tool names - used to live-validate a
    single tool at config time (see _ask_review_tool_overrides) without re-running the
    other six."""
    runner = runner or subprocess.run
    targets = {
        "py-file": tmpdir / "probe.py",
        "sql-file": tmpdir / "probe.sql",
        "sh-file": tmpdir / "probe.sh",
    }
    # newline="\n" (not write_text's default universal-newline translation) forces LF
    # regardless of platform - on Windows, write_text's default would turn every \n into
    # \r\n, and shfmt -d's diff is byte-sensitive enough to report that as "the whole file
    # would change" (live report, 2026-08-04: shfmt NOISY on this exact trivial fixture).
    for kind, content in (
        ("py-file", _TOOL_CHECK_CLEAN_PY),
        ("sql-file", _TOOL_CHECK_CLEAN_SQL),
        ("sh-file", _TOOL_CHECK_CLEAN_SH),
    ):
        with open(targets[kind], "w", encoding="utf-8", newline="\n") as f:
            f.write(content)

    for name, flags, target_kind, per_call_timeout in _TOOL_OUTPUT_CHECKS:
        if only is not None and name not in only:
            continue
        if not shutil.which(name):
            yield (name, "SKIP", "not installed")
            continue
        arg_target = str(tmpdir) if target_kind == "dir" else str(targets[target_kind])
        argv = [name, *flags, arg_target]
        try:
            proc = runner(
                argv,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                cwd=tmpdir,
                timeout=per_call_timeout,
            )
        except subprocess.TimeoutExpired:
            yield (
                name,
                "ERROR",
                f"timed out ({per_call_timeout}s) - likely blocked network access; "
                "this analyser needs a config that doesn't require it",
            )
            continue
        except OSError as exc:
            yield (name, "ERROR", f"failed to launch: {exc}")
            continue
        combined = (proc.stdout or "") + (proc.stderr or "")
        # Checked BEFORE the noise heuristics, and independent of output length/ANSI -
        # live-caught (fable UX review, 2026-08-05): a tool that crashed at startup
        # (e.g. ModuleNotFoundError, a short traceback under the 200-byte NOISY
        # threshold) was reported "OK: clean", the exact opposite of true. Every tool
        # here is expected to exit 0 on a genuinely clean, well-formatted trivial file -
        # nonzero is always anomalous (a crash, a misconfiguration, a version mismatch,
        # or a false positive on our own fixture), never a legitimate "clean" result.
        if proc.returncode != 0:
            detail = combined.strip()
            first_line = detail.splitlines()[0] if detail else "(no output)"
            yield (
                name,
                "ERROR",
                f"exit {proc.returncode} on a trivial clean file - crashed or "
                f"misconfigured: {first_line[:150]}",
            )
        elif "\x1b[" in combined:
            yield (name, "NOISY", "ANSI escape codes leaked through the flags")
        elif len(combined.strip()) > 200:
            preview = combined.strip().splitlines()[0][:80]
            yield (name, "NOISY", f"{len(combined)} bytes on a trivial clean file: {preview!r}...")
        else:
            yield (name, "OK", "clean")


def run_tool_check(style: Style, mark_map: dict) -> int:
    """Standalone diagnostic (--check-tools / menu option 9): verifies, in THIS
    environment, that the noise-suppression flags code-reviewer relies on actually work -
    see the module comment above for why this can't just be asserted from documentation.

    Prints as it goes, never batched (live report, 2026-08-04: the previous version
    collected all results before printing anything, which on a slow tool looked exactly
    like a hang). probe_analyser_output is a generator for exactly this reason - each row
    below prints the moment that tool's check actually finishes, with the full tool list
    shown upfront so a wait between lines reads as "still working through the list", not
    "frozen"."""
    ok, fail = mark_map["ok"], mark_map["fail"]
    names = ", ".join(name for name, *_ in _TOOL_OUTPUT_CHECKS)
    print(style.bold("Checking analyser output cleanliness..."))
    print(style.dim(f"  (checking: {names} - each line below prints as that tool finishes)"))
    # flush=True on every line: stdout is fully buffered (not line-buffered) when it isn't
    # a real tty - piped, redirected, or wrapped - so without this, ALL of these lines
    # would still land in one delayed batch at the end, silently defeating the point.
    sys.stdout.flush()
    bad = 0
    with tempfile.TemporaryDirectory(prefix="virt-surv-it-toolcheck-") as tmp:
        for name, status, detail in probe_analyser_output(Path(tmp)):
            if status == "SKIP":
                print(f"  {style.dim('-')} {name}: not installed, skipped", flush=True)
            elif status == "OK":
                print(f"  {ok} {name}: clean", flush=True)
            else:
                bad += 1
                print(f"  {fail} {name}: {status} - {detail}", flush=True)
    print("")
    if bad:
        print(
            style.yellow(
                f"{bad} tool(s) did not come back clean - code-reviewer's output for these "
                "may still carry decoration on this machine. This is informational, not a "
                "blocker: reviews still work, just with extra noise for the affected tools."
            )
        )
        return 1
    print(style.dim("All installed analysers came back clean."))
    return 0


# ------------------------------------------------------------------ comprehensive environment check
#
# 2026-08-04: --check-tools above covers analyser output only - this repo has independently
# hit several OTHER Windows-specific environment issues over its history (interpreter
# resolution hangs, guard hooks failing with no useful detail, cp1252 encoding crashes, the
# plugin-root bootstrap). --check-env runs all of them in one pass - including --check-tools'
# own analyser section - so a corp user debugging a failure gets one report instead of
# guessing which of several unrelated systems is the actual cause. Explicitly NOT included
# (out of scope per user direction, 2026-08-04): claude CLI reachability, GitHub remote
# reachability - both already covered by the full install flow's own preflight checks.


def _check_interpreters(order: list) -> tuple:
    """Probes each candidate interpreter for real - not just presence on PATH, but that it
    launches and meets the >=3.9 version floor the guards require (pathlib.Path.is_relative_to).
    Returns (rows, winner) - winner is the first that actually works, "" if none do."""
    rows = []
    winner = ""
    for name in order:
        path = shutil.which(name)
        if not path:
            rows.append((name, "SKIP", "not on PATH"))
            continue
        try:
            proc = subprocess.run(
                [name, "-c", "import sys; print(sys.version.split()[0])"],
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            rows.append((name, "ERROR", f"failed to launch: {exc}"))
            continue
        if proc.returncode != 0:
            rows.append(
                (name, "ERROR", f"exit {proc.returncode}: {(proc.stderr or '').strip()[:100]}")
            )
            continue
        version = proc.stdout.strip()
        try:
            major, minor = (int(p) for p in version.split(".")[:2])
        except ValueError:
            rows.append((name, "ERROR", f"unparseable version output: {version!r}"))
            continue
        if (major, minor) < (3, 9):
            rows.append(
                (name, "ERROR", f"Python {version} - below the 3.9 floor the guards require")
            )
            continue
        rows.append((name, "OK", f"Python {version} at {path}"))
        if not winner:
            winner = name
    return rows, winner


def _check_shell_startup_time(bash_path: Optional[str]) -> tuple:
    """Times `source ~/.bashrc` non-interactively - the same cost Claude Code's own
    shell-snapshot mechanism pays on every Bash tool call (it captures shell state, cwd
    included, by sourcing the user's rc file). Live corp-Windows report (2026-08-14,
    screenshots): a .bashrc taking >10s to source non-interactively made that snapshot
    process hit Claude Code's own timeout and get SIGTERM-killed, dropping shell state
    between tool calls - the actual root cause behind a chain of symptoms (PROBE_FAILED,
    the cwd silently resetting mid-session, `list --menu` returning different results
    depending on which directory a call happened to land in) that each looked like a
    separate plugin bug until traced back here. Detect-only, matching this project's
    convention of never touching a file it doesn't own: ~/.bashrc is the user's personal
    shell profile, so this warns with the fix rather than auto-editing it."""
    if not bash_path:
        return ("SKIP", "no bash on PATH - nothing to time")
    bashrc = Path.home() / ".bashrc"
    if not bashrc.is_file():
        return ("SKIP", "no ~/.bashrc - nothing to time")
    start = time.monotonic()
    try:
        subprocess.run(
            [bash_path, "-c", "source ~/.bashrc"],
            capture_output=True,
            timeout=20,
            check=False,
        )
    except subprocess.TimeoutExpired:
        elapsed = 20.0
    except OSError as exc:
        return ("ERROR", f"failed to launch {bash_path}: {exc}")
    else:
        elapsed = time.monotonic() - start
    fix = (
        "run `install_helper.py --fix-bashrc` (previews the exact change, asks first, backs "
        "up ~/.bashrc before writing) to guard slow steps (nvm/pyenv/mise/conda init, "
        "cloud-auth checks, network calls) behind `[[ $- == *i* ]] || return` so they're "
        "skipped for non-interactive shells, or profile with `time source ~/.bashrc` to find "
        "the exact culprit line first"
    )
    if elapsed >= 10.0:
        return (
            "ERROR",
            f"{elapsed:.1f}s to source ~/.bashrc non-interactively - at or past Claude "
            f"Code's own shell-snapshot timeout (10s); very likely why Bash tool calls feel "
            f"slow or silently lose shell state (cwd, PATH, functions) between calls on "
            f"this machine - {fix}",
        )
    if elapsed >= 3.0:
        return ("WARN", f"{elapsed:.1f}s to source ~/.bashrc non-interactively - {fix}")
    return ("OK", f"{elapsed:.2f}s")


def _check_encoding_roundtrip(interpreter: str) -> tuple:
    """Writes UTF-8 (including an emoji) through the resolved interpreter with
    PYTHONIOENCODING=utf-8 and decodes the RAW BYTES ourselves - deliberately not relying
    on subprocess.run's own text=True, which decodes using the PARENT's locale-preferred
    encoding (cp1252 on a plain Windows console) and could raise or silently mis-decode
    right here in the checker, the exact class of bug fixed in engage_probe.py's
    _ascii_safe() (2026-08-04)."""
    if not interpreter:
        return ("SKIP", "no working interpreter found")
    marker = "🎩 test ✓"
    try:
        proc = subprocess.run(
            [interpreter, "-c", f"print({marker!r})"],
            capture_output=True,
            timeout=10,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return ("ERROR", f"failed to launch: {exc}")
    if proc.returncode != 0:
        return (
            "ERROR",
            f"exit {proc.returncode}: {(proc.stderr or b'').decode('utf-8', 'replace')[:150]}",
        )
    try:
        stdout_text = proc.stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        return ("ERROR", f"child's stdout was not valid UTF-8: {exc}")
    if marker not in stdout_text:
        return ("ERROR", f"round-trip mismatch: got {stdout_text.strip()!r}")
    return ("OK", "UTF-8 (including emoji) round-trips cleanly through this interpreter")


def _check_runtime_dependencies() -> list:
    """git and the claude CLI - checked in the full install's preflight, but NOT
    previously in --check-env, so a missing/broken one there was invisible to someone
    running the diagnostic on its own (2026-08-04 user request: "if it won't work in
    Claude Code CLI it should show" here too, not just in the full install path)."""
    rows = []
    if shutil.which("git"):
        rows.append(("git", "OK", "found"))
    else:
        rows.append(("git", "ERROR", "not found - required for cloning/updating the team"))
    claude_path, how = find_claude(refresh=True)
    if how == "path":
        rows.append(("claude CLI", "OK", "found on PATH"))
    elif claude_path:
        rows.append(
            (
                "claude CLI",
                "WARN",
                f"found at {claude_path}, not on this terminal's PATH - a new terminal "
                "will see it by name",
            )
        )
    else:
        rows.append(("claude CLI", "ERROR", f"not found - install it first: {CLAUDE_DOCS_URL}"))
    return rows


def _check_repo_py_syntax(interpreter: str, repo_root: Path) -> list:
    """Compiles every .py file under scripts/ and .claude/hooks/, plus install_helper.py
    itself, with the RESOLVED interpreter (2026-08-04 user request: "every single .py
    file... should be tested"). Catches a syntax/version mismatch - e.g. a 3.10+ feature
    landing on this project's documented 3.9 floor, or a file corrupted by a bad
    encoding/line-ending transform on this specific machine - before Claude Code hits it
    live in a real hook or skill invocation, not just "the file exists on disk"."""
    if not interpreter:
        return [("repo script syntax", "SKIP", "no working interpreter found")]
    bootstrap_hint = _bootstrap_only_hint(repo_root)
    if bootstrap_hint:
        return [("repo script syntax", "SKIP", bootstrap_hint)]
    targets = sorted(repo_root.glob("scripts/*.py")) + sorted(repo_root.glob(".claude/hooks/*.py"))
    if (repo_root / "install_helper.py").is_file():
        targets.append(repo_root / "install_helper.py")
    if not targets:
        return [("repo script syntax", "SKIP", "no .py files found to check")]
    checker = (
        "import py_compile, sys, json\n"
        "bad = []\n"
        "for path in sys.argv[1:]:\n"
        "    try:\n"
        "        py_compile.compile(path, doraise=True)\n"
        "    except Exception as exc:\n"
        "        bad.append([path, str(exc)])\n"
        "print(json.dumps(bad))\n"
    )
    try:
        proc = subprocess.run(
            [interpreter, "-c", checker, *[str(t) for t in targets]],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [("repo script syntax", "ERROR", f"failed to run the checker: {exc}")]
    if proc.returncode != 0:
        return [
            (
                "repo script syntax",
                "ERROR",
                f"checker crashed (exit {proc.returncode}): {(proc.stderr or '').strip()[:200]}",
            )
        ]
    try:
        bad = json.loads(proc.stdout.strip() or "[]")
    except ValueError:
        return [
            ("repo script syntax", "ERROR", f"could not parse checker output: {proc.stdout[:200]}")
        ]
    if not bad:
        return [("repo script syntax", "OK", f"{len(targets)} file(s) compile cleanly")]
    rows = [("repo script syntax", "ERROR", f"{len(bad)}/{len(targets)} file(s) fail to compile")]
    for path, err in bad[:8]:  # capped - the count above is the honest total, this is detail
        rows.append((f"    {Path(path).name}", "ERROR", err[:150]))
    return rows


def _bootstrap_only_hint(repo_root: Path) -> Optional[str]:
    """True (as a ready-to-print reason) when install_helper.py is running from a bare
    single-file bootstrap copy rather than a full clone - live report, 2026-08-04: a
    Windows user ran --check-env from exactly this state (the curl-bootstrap temp dir,
    before the full clone existed) and got a confusing raw ImportError/path-not-found
    instead of a clear "not installed yet" - both checks below are expected to come back
    SKIP here, this just makes the *reason* legible instead of technical."""
    if (repo_root / "scripts").is_dir():
        return None
    return (
        "not installed yet - this looks like the single-file bootstrap download, not the "
        "full clone (no scripts/ next to install_helper.py here). Run the full install "
        "(menu option 1, or: python install_helper.py install) first, then re-run this "
        "check from inside the clone."
    )


def _check_plugin_root_bootstrap(repo_root: Path) -> tuple:
    """Runs the SAME find_plugin_root() the engage-open.md heredoc embeds a twin of
    (2026-08-04) - imported directly here since install_helper.py already sits at the repo
    root next to scripts/, no subprocess needed for this one."""
    bootstrap_hint = _bootstrap_only_hint(repo_root)
    if bootstrap_hint:
        return ("SKIP", bootstrap_hint)
    try:
        sys.path.insert(0, str(repo_root))
        from scripts.find_plugin_root import find_plugin_root
    except ImportError as exc:
        return ("SKIP", f"could not import scripts.find_plugin_root: {exc}")
    try:
        result = find_plugin_root(Path.home(), Path.cwd())
    except Exception as exc:  # noqa: BLE001 - reporting, not re-raising, is the whole point
        return ("ERROR", f"crashed: {exc}")
    if result:
        return ("OK", f"resolves to: {result}")
    if (Path.cwd() / "docs" / "team-operating-guide.md").is_file():
        return ("OK", "repo-as-project (this directory IS the team repo)")
    return (
        "WARN",
        "resolved to empty - no plugin install found from this directory/home (expected "
        "if you haven't installed the plugin anywhere yet)",
    )


def _check_guard_hooks(interpreter: str, repo_root: Path, tmpdir: Path) -> list:
    """Feeds harmless, should-always-pass payloads through the REAL production dispatch
    path (bash_hook_dispatcher.py, then locked_menu_guard.py separately - it's wired on
    AskUserQuestion outside the consolidated dispatcher) and confirms a clean pass-through.
    Catches crashes or false-positive blocks specific to THIS Python environment (a missing
    dependency, an unexpected version quirk) that "the guard file exists" can't - a crash on
    a fail-closed guard is itself reported by the dispatcher as blocked with "crashed
    unexpectedly" in stderr, distinguished here from a genuine (wrong) block."""
    if not interpreter:
        return [("guard hooks", "SKIP", "no working interpreter found")]
    bootstrap_hint = _bootstrap_only_hint(repo_root)
    if bootstrap_hint:
        return [("guard hooks", "SKIP", bootstrap_hint)]
    dispatcher = repo_root / "scripts" / "bash_hook_dispatcher.py"
    if not dispatcher.is_file():
        return [("guard hooks", "SKIP", f"dispatcher not found at {dispatcher}")]
    harmless = tmpdir / "env-check-harmless.txt"
    harmless.write_text("harmless\n", encoding="utf-8")
    payloads = (
        (
            "Bash (raw-data/code-exec/redirects)",
            {"tool_name": "Bash", "tool_input": {"command": "echo hello"}, "cwd": str(tmpdir)},
        ),
        (
            "Write (consent-write/findings-pack)",
            {"tool_name": "Write", "tool_input": {"file_path": str(harmless), "content": "hello"}},
        ),
        (
            "Read (raw-data/document-redirect)",
            {"tool_name": "Read", "tool_input": {"file_path": str(harmless)}},
        ),
    )
    rows = []
    for label, payload in payloads:
        try:
            proc = subprocess.run(
                [interpreter, str(dispatcher)],
                input=json.dumps(payload),
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
                cwd=repo_root,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            rows.append((label, "ERROR", f"dispatcher failed to run: {exc}"))
            continue
        if proc.returncode == 0:
            rows.append((label, "OK", "clean pass-through"))
        elif "crashed unexpectedly" in (proc.stderr or ""):
            rows.append((label, "ERROR", f"a guard crashed: {proc.stderr.strip()[:150]}"))
        else:
            rows.append(
                (
                    label,
                    "ERROR",
                    f"blocked a harmless action (exit {proc.returncode}): {(proc.stderr or '').strip()[:150]}",
                )
            )
    locked_menu = repo_root / "scripts" / "locked_menu_guard.py"
    if locked_menu.is_file():
        payload = {
            "tool_name": "AskUserQuestion",
            "tool_input": {
                "questions": [
                    {
                        "header": "Approach",
                        "question": "Which?",
                        "multiSelect": False,
                        "options": [{"label": "A", "description": "A"}],
                    }
                ]
            },
        }
        try:
            proc = subprocess.run(
                [interpreter, str(locked_menu)],
                input=json.dumps(payload),
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
            )
            if proc.returncode == 0:
                rows.append(("AskUserQuestion (locked-menu guard)", "OK", "clean pass-through"))
            else:
                rows.append(
                    (
                        "AskUserQuestion (locked-menu guard)",
                        "ERROR",
                        (proc.stderr or "").strip()[:150],
                    )
                )
        except (OSError, subprocess.TimeoutExpired) as exc:
            rows.append(("AskUserQuestion (locked-menu guard)", "ERROR", f"failed to run: {exc}"))
    return rows


def _print_diagnostic_summary(style: Style, mark_map: dict, rows: list) -> None:
    """Compact 'what passed, what didn't' scoreboard, grouped by status - same shape as
    the full install's own print_summary (Completed/Skipped/Failed). A long diagnostic
    run (--check-env now folds in the synthetic engagement too - 20+ rows) needs one
    legible list at the end, not a scrollback hunt through interleaved live output
    (2026-08-04 user request). Labels only, no repeated detail text - that already
    printed live as each check ran."""
    ok, fail = mark_map["ok"], mark_map["fail"]
    groups = (
        ("Passed", ("OK",), style.green, ok),
        ("Warnings", ("WARN",), style.yellow, style.yellow("!")),
        ("Skipped", ("SKIP",), style.dim, style.dim("-")),
        ("Failed", ("ERROR",), style.red, fail),
    )
    print("")
    print(style.bold("Summary"))
    for title, statuses, paint, mark in groups:
        labels = [label for label, status, _detail in rows if status in statuses]
        if not labels:
            continue
        print(paint(f"  {title} ({len(labels)})"))
        for label in labels:
            print(f"    {mark} {label}")


def run_env_check(style: Style, mark_map: dict, repo_hint: Optional[str] = None) -> int:
    """Standalone diagnostic (--check-env / menu option 10): a comprehensive environment
    report - interpreter resolution, bash and git/claude-CLI availability, encoding, the
    plugin-root bootstrap, every repo .py file's syntax under the resolved interpreter,
    guard hooks, analyser output cleanliness, AND (2026-08-04 user request: "the
    comprehensive test should execute the synthetic test so it's really is
    comprehensive") the same synthetic 'review this code' engagement --selftest runs
    (planted-issue detection + the engagement-state lifecycle) - in one pass. Never
    blocks anything; informational, matching check-review-tools.sh's own "report, not a
    gate" convention. Goal (2026-08-04 user framing): if it won't work when Claude Code
    actually invokes it, this should show it - not just "the file/binary exists".
    repo_hint: see _resolve_repo_root - pass args.repo when calling from anywhere that
    might run post-relocation (the interactive menu's envcheck action). Ends with a
    compact pass/fail summary (_print_diagnostic_summary) - a run this size (20+ rows)
    needs one legible scoreboard, not a scrollback hunt."""
    ok, fail = mark_map["ok"], mark_map["fail"]
    repo_root = _resolve_repo_root(repo_hint) or Path(__file__).resolve().parent
    all_rows = []

    def emit(label: str, status: str, detail: str) -> None:
        all_rows.append((label, status, detail))
        if status == "SKIP":
            print(f"  {style.dim('-')} {label}: {detail}", flush=True)
        elif status == "OK":
            print(f"  {ok} {label}: {detail}", flush=True)
        elif status == "WARN":
            print(f"  {style.yellow('!')} {label}: {detail}", flush=True)
        else:
            print(f"  {fail} {label}: {status} - {detail}", flush=True)

    print(style.bold("Environment check"))

    print(style.dim("\n  Interpreters:"))
    order = ["python", "py", "python3"] if sys.platform == "win32" else ["python3", "python", "py"]
    interp_rows, interpreter = _check_interpreters(order)
    for name, status, detail in interp_rows:
        emit(name, status, detail)

    print(style.dim("\n  Bash:"))
    bash_path = find_bash()
    if bash_path:
        emit("bash", "OK", bash_path)
    else:
        emit("bash", "WARN", "not found (only matters for the review-tools probe script)")

    print(style.dim("\n  Shell startup time (non-interactive):"))
    status, detail = _check_shell_startup_time(bash_path)
    emit(".bashrc source time", status, detail)

    print(style.dim("\n  Runtime dependencies (git, claude CLI):"))
    for label, status, detail in _check_runtime_dependencies():
        emit(label, status, detail)

    print(style.dim("\n  Encoding round-trip:"))
    status, detail = _check_encoding_roundtrip(interpreter)
    emit("UTF-8/emoji", status, detail)

    print(style.dim("\n  Plugin-root bootstrap:"))
    status, detail = _check_plugin_root_bootstrap(repo_root)
    emit("find_plugin_root", status, detail)

    print(style.dim("\n  Repo script syntax (every .py file the team runs, this interpreter):"))
    for label, status, detail in _check_repo_py_syntax(interpreter, repo_root):
        emit(label, status, detail)

    print(style.dim("\n  Guard hooks (harmless payloads, real production dispatch path):"))
    with tempfile.TemporaryDirectory(prefix="virt-surv-it-envcheck-") as tmp:
        for label, status, detail in _check_guard_hooks(interpreter, repo_root, Path(tmp)):
            emit(label, status, detail)

    print(style.dim("\n  Analyser output cleanliness:"))
    with tempfile.TemporaryDirectory(prefix="virt-surv-it-envcheck-") as tmp:
        for name, status, detail in probe_analyser_output(Path(tmp)):
            emit(name, status, detail)

    print(
        style.dim(
            "\n  Synthetic engagement (planted-issue detection, then init -> findings -> "
            "render -> close-gate -> archive):"
        )
    )
    for label, status, detail, _full in _selftest_engagement_probe(repo_root, interpreter):
        emit(label, status, detail)

    _print_diagnostic_summary(style, mark_map, all_rows)
    bad = sum(1 for _label, status, _detail in all_rows if status not in ("OK", "SKIP", "WARN"))
    print("")
    if bad:
        print(style.yellow(f"{bad} issue(s) found - see the ERROR rows above for detail."))
        return 1
    print(style.dim("Environment looks clean."))
    return 0


# ------------------------------------------------------------------ hook-latency diagnostic
#
# 2026-08-11 live corp bug report (Windows debug-log monitoring): 87 slow PreToolUse events,
# 2-9s normal, 25-90s under Workflow-tool fan-out, traced to a fresh Python process per hook
# call plus (hypothesised, not yet confirmed on that specific box) per-process endpoint-
# security scanning. ADR-014 proposes a persistent guard daemon as the real fix but
# explicitly requires real measurement before committing to it - this project's own
# established discipline is "measured live, not reasoned about in the abstract" (every
# other fix in run-guard.sh's history has been a live reproduction, not design-time
# reasoning alone). This diagnostic is that measurement, made repeatable instead of ad hoc.


def _fmt_latency_stats(samples: list) -> str:
    """samples: elapsed seconds per call, or None for a call that errored/timed out -
    excluded from the stats but counted separately so a crash mid-run doesn't silently
    vanish or masquerade as a fast success."""
    good = sorted(s for s in samples if s is not None)
    dropped = len(samples) - len(good)
    if not good:
        return "no successful samples" + (f" ({dropped} failed/timed out)" if dropped else "")
    good_ms = [s * 1000 for s in good]
    n = len(good_ms)
    median = good_ms[n // 2] if n % 2 else (good_ms[n // 2 - 1] + good_ms[n // 2]) / 2
    detail = f"min={good_ms[0]:.0f}ms median={median:.0f}ms max={good_ms[-1]:.0f}ms (n={n})"
    if dropped:
        detail += f", {dropped} failed/timed out"
    return detail


def _resolve_sh() -> Optional[str]:
    """Resolve a POSIX shell to run run-guard.sh with - PATH alone is not enough on
    Windows. Live-confirmed 2026-08-11: a corp Windows box's PowerShell session had no
    `sh` on PATH at all despite Git Bash being installed (PowerShell does not add Git
    Bash's bin/ to PATH by default), which made the guard-launcher and fan-out sections
    of this diagnostic SKIP entirely - exactly the two measurements that matter most.
    Claude Code itself does not have this problem because it does not depend on the
    invoking shell's PATH for this; public bug-tracker discussion around Windows/Git-Bash
    hook execution points at a `CLAUDE_CODE_GIT_BASH_PATH` env var as the mechanism it
    uses instead - not independently verified against Claude Code's own source, so this
    checks it opportunistically (several plausible shapes: the env var pointing straight
    at sh.exe, at bash.exe/git-bash.exe with sh.exe alongside it, or at the containing
    directory) rather than assuming one exact convention. Falls through to shutil.which
    (works everywhere sh genuinely is on PATH), then common Windows Git-Bash install
    locations as a last resort. Returns None if nothing resolves - the caller SKIPs, same
    as before, never guesses at a shell that might not actually be there."""
    override = os.environ.get("CLAUDE_CODE_GIT_BASH_PATH")
    if override:
        p = Path(override)
        candidates = []
        if p.is_file():
            candidates.append(p.parent / "sh.exe")  # bash.exe/git-bash.exe with sh.exe alongside it
            candidates.append(p)  # or it might already BE sh.exe (checked second, so a real
            # sibling sh.exe always wins over treating a bash.exe-named override as sh itself)
        elif p.is_dir():
            candidates.append(p / "sh.exe")
            candidates.append(p / "bin" / "sh.exe")
        for c in candidates:
            if c.is_file():
                return str(c)
    found = shutil.which("sh")
    if found:
        return found
    if sys.platform == "win32":
        for candidate in (
            r"C:\Program Files\Git\bin\sh.exe",
            r"C:\Program Files\Git\usr\bin\sh.exe",
            r"C:\Program Files (x86)\Git\bin\sh.exe",
            r"C:\Program Files (x86)\Git\usr\bin\sh.exe",
        ):
            if Path(candidate).is_file():
                return candidate
    return None


def _measure_repeated(argv_fn, n: int, timeout: float = 20.0) -> list:
    """n separate, FRESH subprocess invocations, one after another - argv_fn() returns
    (argv, kwargs) recomputed each call so a caller can vary the payload if needed. Returns
    elapsed seconds per call; None = that call errored or timed out."""
    samples = []
    for _ in range(n):
        argv, kwargs = argv_fn()
        start = time.monotonic()
        try:
            subprocess.run(argv, capture_output=True, timeout=timeout, **kwargs)
            samples.append(time.monotonic() - start)
        except (OSError, subprocess.TimeoutExpired):
            samples.append(None)
    return samples


def _trend_verdict(good_bare: list) -> tuple:
    """The decision-relevant signal: does repetition help? A sharp drop after the first
    call is consistent with a one-time "this binary is now trusted" AV/EDR cache; a flat
    cost across all samples is consistent with per-process scanning regardless of
    repetition - the daemon only earns its keep in the second case (fewer processes =
    fewer scans; a cache that already makes repeats cheap gets most of that benefit for
    free without one). Pulled out of run_hook_latency_diagnostic as a pure function
    (samples in, verdict out) specifically so it's testable with contrived sample lists -
    the real function's actual timings come from mocked-instant subprocess calls in tests,
    which can't be made to reproduce a genuine first-call-slow pattern through the mock
    alone. Returns (status, detail)."""
    if len(good_bare) < 3:
        return "SKIP", "not enough successful samples to judge a trend"
    first, rest = good_bare[0], good_bare[1:]
    rest_median = sorted(rest)[len(rest) // 2]
    if first > 0 and rest_median < first * 0.5:
        return "OK", (
            f"first call {first * 1000:.0f}ms, later calls ~{rest_median * 1000:.0f}ms - "
            "consistent with a one-time trust/scan cache, NOT per-process scanning. "
            "Worth investigating AV allow-listing or interpreter start-up flags (-S/-I) "
            "before considering the daemon in ADR-014."
        )
    return "WARN", (
        f"first call {first * 1000:.0f}ms, later calls ~{rest_median * 1000:.0f}ms - "
        "no meaningful drop-off, consistent with per-process scanning regardless of "
        "repetition. This is the signal ADR-014's daemon proposal is aimed at - fewer "
        "processes is the only lever that reduces this."
    )


def _measure_concurrent(argv_fn, n: int, timeout: float = 30.0) -> tuple:
    """n GENUINELY concurrent invocations (ThreadPoolExecutor, not a loop - the same
    technique tests/test_run_guard_lock.py::test_concurrent_calls_are_actually_serialized
    already uses) - reproduces the actual reported Workflow-fan-out symptom on demand
    instead of waiting for it to happen organically in a real session. Returns (per-call
    elapsed-seconds list, total wall-clock for the whole batch)."""

    def _one(_i):
        argv, kwargs = argv_fn()
        start = time.monotonic()
        try:
            subprocess.run(argv, capture_output=True, timeout=timeout, **kwargs)
            return time.monotonic() - start
        except (OSError, subprocess.TimeoutExpired):
            return None

    batch_start = time.monotonic()
    with ThreadPoolExecutor(max_workers=n) as pool:
        samples = list(pool.map(_one, range(n)))
    total = time.monotonic() - batch_start
    return samples, total


def run_hook_latency_diagnostic(
    style: Style, mark_map: dict, repo_hint: Optional[str] = None
) -> int:
    """Standalone diagnostic (--check-hook-latency / Diagnostics menu option 5): measures
    real PreToolUse hook latency on THIS machine - repeated bare interpreter cold starts,
    the real guard-launcher end to end, and a genuinely concurrent fan-out simulation -
    feeding the ADR-014 daemon decision with actual numbers instead of guesswork. Slower
    than the other diagnostics on purpose (repeated + concurrent measurement, not a single
    pass) - ALWAYS writes its full numbers to a timestamped file, pass or fail, since the
    data is the point here, not just catching errors (unlike run_selftest's bundle, which
    is failure-only).

    Verdict logic is deliberately conservative: it reports what the numbers are consistent
    with, never a directive - "measured live" evidence for a human decision, matching this
    project's own established discipline for changes of this size (docs/adr/ADR-014)."""
    ok, fail = mark_map["ok"], mark_map["fail"]
    repo_root = _resolve_repo_root(repo_hint) or Path(__file__).resolve().parent
    rows = []
    bundle_lines = []

    def record(label: str, status: str, detail: str) -> None:
        rows.append((label, status, detail))
        bundle_lines.append(f"--- {label} [{status}] ---\n{detail}\n")
        mark = {"OK": ok, "SKIP": style.dim("-"), "WARN": style.yellow("!")}.get(status, fail)
        print(f"  {mark} {label}: {detail}", flush=True)

    print(style.bold("Hook latency diagnostic (feeds the ADR-014 daemon decision)"))
    print(
        style.dim("  Repeated + concurrent measurement - slower than the other checks on purpose.")
    )

    order = ["python", "py", "python3"] if sys.platform == "win32" else ["python3", "python", "py"]
    interp_rows, interpreter = _check_interpreters(order)
    print(style.dim("\n  Interpreter resolution:"))
    for name, status, detail in interp_rows:
        record(name, status, detail)
    if not interpreter:
        record("bare cold start", "SKIP", "no working interpreter found - nothing to measure")
        _print_diagnostic_summary(style, mark_map, rows)
        return 1

    print(style.dim(f"\n  Bare interpreter cold start ({interpreter}, 5 separate fresh calls):"))
    bare = _measure_repeated(lambda: ([interpreter, "-c", "pass"], {}), n=5)
    good_bare = [s for s in bare if s is not None]
    record("bare cold start", "OK" if good_bare else "ERROR", _fmt_latency_stats(bare))

    trend_status, trend_detail = _trend_verdict(good_bare)
    record("repetition trend (daemon-relevant signal)", trend_status, trend_detail)

    launcher = repo_root / ".claude" / "hooks" / "run-guard.sh"
    dispatcher = repo_root / "scripts" / "bash_hook_dispatcher.py"
    sh_path = _resolve_sh()
    guard_good: list = []
    if not (sh_path and launcher.is_file() and dispatcher.is_file()):
        record(
            "real guard-launcher cost",
            "SKIP",
            "sh, run-guard.sh or bash_hook_dispatcher.py not found - can't measure the real path",
        )
    else:
        print(style.dim("\n  Real guard-launcher end to end (harmless payload, 5 separate calls):"))
        payload = json.dumps(
            {"tool_name": "Read", "tool_input": {"file_path": str(repo_root / "README.md")}}
        )
        guard_samples = _measure_repeated(
            lambda: (
                [sh_path, str(launcher), str(dispatcher)],
                {"input": payload, "text": True, "cwd": repo_root},
            ),
            n=5,
        )
        guard_good = [s for s in guard_samples if s is not None]
        record(
            "real guard-launcher cost",
            "OK" if guard_good else "ERROR",
            _fmt_latency_stats(guard_samples),
        )
        if good_bare and guard_good:
            bare_median = sorted(good_bare)[len(good_bare) // 2]
            guard_median = sorted(guard_good)[len(guard_good) // 2]
            record(
                "guard overhead beyond bare interpreter",
                "OK",
                f"~{(guard_median - bare_median) * 1000:.0f}ms (guard imports/logic on top of "
                "interpreter start-up alone)",
            )

        print(style.dim("\n  Concurrent fan-out simulation (8 genuinely concurrent calls):"))
        fanout_samples, fanout_total = _measure_concurrent(
            lambda: (
                [sh_path, str(launcher), str(dispatcher)],
                {"input": payload, "text": True, "cwd": repo_root},
            ),
            n=8,
        )
        fanout_good = [s for s in fanout_samples if s is not None]
        record(
            "concurrent fan-out (8 calls)",
            "OK" if fanout_good else "ERROR",
            f"{_fmt_latency_stats(fanout_samples)}, total wall-clock {fanout_total * 1000:.0f}ms",
        )
        if fanout_good:
            worst_ms = max(fanout_good) * 1000
            record(
                "worst-case single call under fan-out",
                "WARN" if worst_ms > 5000 else "OK",
                f"{worst_ms:.0f}ms - compare against the 25-90s originally reported; this "
                "reproduces the shape of that symptom on demand instead of waiting for it "
                "to happen organically",
            )

    if sys.platform == "win32":
        ps = shutil.which("powershell") or shutil.which("pwsh")
        if ps:
            print(style.dim(f"\n  PowerShell cold start ({ps}, diagnostic signal only, 5 calls):"))
            ps_samples = _measure_repeated(
                lambda: ([ps, "-NoProfile", "-Command", "exit 0"], {}), n=5
            )
            record(
                "PowerShell cold start (diagnostic signal only - not a proposed fix, see ADR-014)",
                "OK" if any(s is not None for s in ps_samples) else "ERROR",
                _fmt_latency_stats(ps_samples),
            )
        else:
            record("PowerShell cold start", "SKIP", "powershell/pwsh not found on PATH")
    else:
        record("PowerShell cold start", "SKIP", "Windows-only diagnostic signal")

    _print_diagnostic_summary(style, mark_map, rows)

    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    bundle_path = Path.cwd() / f"virt-surv-hook-latency-{ts}.txt"
    header = (
        "virt-surv-it hook-latency diagnostic (feeds the ADR-014 daemon decision)\n"
        f"Python: {sys.version}\nPlatform: {sys.platform}\nInterpreter: {interpreter}\n"
        f"Repo root: {repo_root}\n\n"
    )
    try:
        bundle_path.write_text(header + "\n".join(bundle_lines), encoding="utf-8")
        print("")
        print(style.dim(f"Full numbers written to: {bundle_path} - hand this back whole."))
    except OSError as exc:
        print("")
        print(style.yellow(f"Could not write the data file: {exc}"))

    bad = sum(1 for _label, status, _detail in rows if status == "ERROR")
    return 1 if bad else 0


# ------------------------------------------------------------------ ADR-014 spike smoke test wrapper
#
# 2026-08-12 user request: expose the ADR-014 guard-daemon design-spike's own live smoke
# test (docs/internal/adr-014-spike/smoke_test.py) through the same Diagnostics menu /
# --check-* CLI convention as every other check here, for easy access from a remote
# (Windows) session under investigation. PROTOTYPE, not production: this wrapper runs the
# spike's own script unmodified via run_cmd (demo-mode safe, monkeypatchable in tests,
# same as every other check in this file) - it does not duplicate or reimplement the
# spike's logic, and .claude/hooks/run-guard.sh remains untouched regardless of whether
# this is ever run.


def run_adr014_smoke_test(
    style: Style, mark_map: dict, repo_hint: Optional[str] = None
) -> Optional[int]:
    """Runs docs/internal/adr-014-spike/smoke_test.py via run_cmd and relays its captured
    output in full. Returns the smoke test's own exit code (0 = all checks passed, 1 = at
    least one failed), or None if the spike script is not present (a plugin install that
    predates it, or the spike having been removed) - the caller SKIPs on None, same
    "absent prerequisite" posture every other diagnostic in this file already uses."""
    repo_root = _resolve_repo_root(repo_hint) or Path(__file__).resolve().parent
    smoke_test = repo_root / "docs" / "internal" / "adr-014-spike" / "smoke_test.py"
    if not smoke_test.is_file():
        return None
    proc = run_cmd([sys.executable, str(smoke_test)], cwd=repo_root, timeout=180)
    if proc.stdout:
        print(proc.stdout)
    if proc.stderr:
        print(style.dim(proc.stderr))
    return proc.returncode


# ------------------------------------------------------------------ daemon start diagnostic
#
# 2026-08-14 (live report): the daemon still wasn't starting on a real box after the
# module_root/state_root split, CREATE_BREAKAWAY_FROM_JOB and $0 self-location fixes were
# all confirmed applied - and there was no way to find out WHY, because
# scripts/guard_daemon_client.py's _start_daemon_detached() deliberately swallows any
# spawn failure (correct for production: a hook must never brick a tool call over a
# missed optimisation) but that same design means a genuine spawn problem produces zero
# diagnostic trace, just "no port file, no clue why". Built specifically to give that
# trace, on demand, without touching the production fire-and-forget behaviour at all.


def org_extensions_path() -> Path:
    """Where this machine's ORG extensions contract lives.

    Kept in step with scripts/extensions.py::org_file - same machine-config home as the
    machine defaults, honouring XDG_CONFIG_HOME. Duplicated rather than imported because
    install_helper.py must run standalone from a bare clone with nothing on sys.path; a
    test pins the two to the same location."""
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / "virt-surv-it" / "team-extensions.md"


# How long a synced org contract is trusted before a refresh is attempted. Long enough that
# `go` does not hit the source on every launch, short enough that a compliance function's
# edit reaches machines the same day.
_EXTENSIONS_TTL_SECONDS = 12 * 3600


def extensions_source() -> str:
    """The configured source for this machine's org contract, or "".

    Lives in the machine-defaults file beside the other machine-wide settings. A local path,
    a UNC share, or a git URL - the three shapes a compliance function actually has."""
    try:
        base = os.environ.get("XDG_CONFIG_HOME")
        root = Path(base) if base else Path.home() / ".config"
        with open(root / "virt-surv-it" / "installer.json", encoding="utf-8-sig") as fh:
            value = json.load(fh).get("extensions_source")
        return value.strip() if isinstance(value, str) else ""
    except (OSError, ValueError, AttributeError):
        return ""


def sync_org_extensions(force: bool = False, quiet: bool = True) -> tuple:
    """Refresh the org contract from `extensions_source`. Returns (status, detail).

    FAIL-OPEN, ALWAYS. Status is one of: "off" (no source configured), "fresh" (inside the
    TTL, nothing done), "updated", "unchanged", or "failed". A failure NEVER removes or
    invalidates the contract already on disk - stale-but-present beats absent, and absent
    beats a launch that hangs waiting for a share. This runs on the `go` path, so the one
    outcome that must be impossible is blocking.

    The fetched file is DATA, not instructions. It is parsed by a deliberately dumb parser -
    shutil.which only, plain-argv commands, shell metacharacters refused - and nothing
    downstream executes it. That property is what makes syncing a file from elsewhere
    tolerable at all, and it must not be relaxed to make a feature work.
    """
    source = extensions_source()
    if not source:
        return ("off", "")
    target = org_extensions_path()
    if not force and target.is_file():
        try:
            if time.time() - target.stat().st_mtime < _EXTENSIONS_TTL_SECONDS:
                return ("fresh", str(target))
        except OSError:
            pass

    fetched = None
    try:
        candidate = Path(source).expanduser()
        if candidate.is_file():
            # A plain file - a local path or a UNC share. Checked FIRST so a file that
            # happens to be named something.git is read, not cloned.
            fetched = candidate.read_bytes()
        elif _looks_like_git_source(source, candidate):
            fetched = _fetch_extensions_from_git(source)
    except Exception as exc:  # noqa: BLE001 - fail-open is the contract
        return ("failed", f"{type(exc).__name__}: {exc}")
    if fetched is None:
        return ("failed", f"could not read {source}")

    # Validate BEFORE overwriting a working contract. A source that has been emptied or
    # mangled must not silently replace one that works.
    try:
        import tempfile

        with tempfile.NamedTemporaryFile("wb", suffix=".md", delete=False) as fh:
            fh.write(fetched)
            probe = Path(fh.name)
        sections, _problems = _parse_extensions(probe)
        probe.unlink(missing_ok=True)
    except Exception:
        sections = None
    if not sections:
        return ("failed", "fetched contract has no recognised section - keeping the current one")

    try:
        if target.is_file() and target.read_bytes() == fetched:
            os.utime(target, None)  # touch, so the TTL restarts without a rewrite
            return ("unchanged", str(target))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(fetched)
    except OSError as exc:
        return ("failed", str(exc))
    return ("updated", str(target))


def _looks_like_git_source(source: str, candidate: Path) -> bool:
    """Is this a git repo rather than a file to copy?

    Three shapes a compliance function actually has: a remote URL, a local bare repo (a
    DIRECTORY, usually ending .git - missed by a scheme-only check, which is how the first
    version of this silently fell through to "could not read"), and a working clone."""
    if source.startswith(("http://", "https://", "git@", "ssh://", "git://")):
        return True
    try:
        if candidate.is_dir():
            return (candidate / ".git").exists() or (candidate / "HEAD").is_file()
    except OSError:
        return False
    return False


def _fetch_extensions_from_git(url: str):
    """team-extensions.md out of a git repo, without leaving a clone behind.

    A blobless shallow clone into a temp directory: the compliance function versions its
    standard like anything else, and a machine picks up changes without anyone editing files
    by hand. Bounded by a timeout, because this can run on the launch path."""
    import shutil as _shutil
    import tempfile

    tmp = tempfile.mkdtemp(prefix="virt-surv-ext-")
    try:
        proc = run_cmd(
            ["git", "clone", "--depth", "1", "--filter=blob:none", "--quiet", url, tmp],
            timeout=120,
        )
        if proc.returncode != 0:
            return None
        for candidate in (
            Path(tmp) / "team-extensions.md",
            Path(tmp) / "docs" / "team-extensions.md",
        ):
            if candidate.is_file():
                return candidate.read_bytes()
        return None
    finally:
        _shutil.rmtree(tmp, ignore_errors=True)


def _relocation_plan(project: Path) -> list:
    """[(source, destination, label)] for what would move. Empty when nothing needs to.

    Reads the layout rather than assuming it: only entries whose source EXISTS and whose
    destination does NOT are listed, so running this twice is safe and a half-migrated
    project is completed rather than confused."""
    root = Path(project)
    vsit = root / "VSIT"
    candidates = [
        (root / "artifacts", vsit / "engagements", "engagement workspaces"),
        (root / "docs" / "codebase-map.md", vsit / "shared" / "map.md", "codebase map"),
        (root / "docs" / "CODEBASE-MAP.md", vsit / "shared" / "map.md", "codebase map"),
        (root / "docs" / "codebase-map.d", vsit / "shared" / "map.d", "codebase map areas"),
        (
            root / "docs" / "codebase-map.fingerprints.json",
            vsit / "shared" / "derived.json",
            "map fingerprints",
        ),
        (
            root / "docs" / "team-extensions.md",
            vsit / "config" / "extensions.md",
            "extensions contract",
        ),
        (
            root / ".claude" / "team-preferences.json",
            vsit / "config" / "preferences.json",
            "team preferences",
        ),
        (
            root / ".claude" / ".tool-availability",
            vsit / "local" / "tool-availability",
            "tool inventory cache",
        ),
        (
            root / ".claude" / "engage-probe.json",
            vsit / "local" / "engage-probe.json",
            "probe cache",
        ),
        (
            root / ".claude" / ".guard-interpreter",
            vsit / "local" / "guard-interpreter",
            "interpreter cache",
        ),
        (
            root / ".claude" / ".map-fingerprint-probe-cache.json",
            vsit / "local" / "map-fingerprint-cache.json",
            "fingerprint probe cache",
        ),
    ]
    return [(s, d, label) for s, d, label in candidates if s.exists() and not d.exists()]


_VSIT_README = """# VSIT/

Everything the Virtual Surv-IT team keeps about this project lives here, so it is in one
place rather than scattered through your own directories.

    shared/        what every engagement needs: the codebase map, and a derived index of
                   symbols and line ranges. COMMITTED - the next engagement inherits it.
    engagements/   one folder per piece of work. NOT committed.
    reports/       deliverables that belong to the project rather than one engagement.
    config/        this project's team settings and its extensions contract. COMMITTED.
    local/         caches derived from THIS checkout - file timestamps, resolved paths.
                   NOT committed: they are wrong on anyone else's machine.

Safe to delete: `local/` (regenerates), and `engagements/<slug>/` once an engagement is
finished and archived. Not safe to delete: `shared/` and `config/`, which hold decisions
and knowledge nothing can recompute.

Nothing here is required for your project to build or run.
"""


def _pick_project(style: Style, title: str, prompt: str):
    """Which project, asked on a screen. A Path, or None if they left.

    A CHOOSER OVER REAL CANDIDATES rather than a file browser. What someone wants here is
    almost always a project they have already used, so offering those by name is both
    faster and safer than typing a path - and it works on all three tiers for free,
    because questions.choose does. The typed path stays as the escape hatch for the case
    the list cannot cover.
    """
    seen, options = set(), []
    for label, raw in (
        ("this directory", os.getcwd()),
        ("the project Claude Code is in", os.environ.get("CLAUDE_PROJECT_DIR")),
    ):
        if not raw:
            continue
        path = Path(raw).expanduser()
        if path.is_dir() and str(path) not in seen:
            seen.add(str(path))
            options.append((str(path), path.name or str(path), f"{label} - {path}"))
    try:
        for raw in load_config(config_path()).get("recent_projects") or []:
            path = Path(raw).expanduser()
            if path.is_dir() and str(path) not in seen:
                seen.add(str(path))
                options.append((str(path), path.name or str(path), f"recently used - {path}"))
    except Exception:
        pass
    options.append(("", "somewhere else", "type the path instead"))

    answer = _ask().choose(title, options)
    if answer.cancelled:
        return None
    if answer.value:
        return Path(answer.value).resolve()
    typed = ask(prompt, os.getcwd(), assume_yes=False, style=style).strip()
    return Path(typed or os.getcwd()).expanduser().resolve()


def run_relocate_to_vsit(style: Style, mark_map: dict) -> int:
    """Move a project's team files into VSIT/, after showing exactly what would move.

    OFFERED, NEVER AUTOMATIC (plan-project-footprint-2026-08-27). Silently restructuring
    someone's repository is precisely the behaviour that plan exists to stop, so this
    prints the full plan first and does nothing without a yes.

    Nothing depends on it: the resolver reads both layouts, so a project that never runs
    this keeps working indefinitely. It is convenience, not correctness - which is also why
    it refuses rather than guesses whenever anything looks unexpected.
    """
    ok, warn = mark_map.get("ok") or "OK", mark_map.get("warn") or "!"

    # BOTH QUESTIONS INSIDE THE INTERFACE (owner report with screenshot, 2026-08-30:
    # "clicked 12 and 15, both dropped out of the new interface to the terminal-only
    # question prompt"). This screen asked for a path at a bare prompt and then printed
    # its plan into the scrollback, which is exactly the experience the picker replaces.
    project = _pick_project(style, "Which project to restructure?", "  Project to relocate:")
    if project is None:
        return 0  # they left
    if not project.is_dir():
        print(style.yellow(f"  {warn} not a directory: {project}"))
        return 1

    plan = _relocation_plan(project)
    if not plan:
        print(style.dim("  nothing to move - this project is already on the VSIT layout"))
        return 0

    # The plan goes in the pane, where it can be READ before the keypress, rather than
    # scrolling past above the question. Same content either way - that is the point of
    # decision_screen taking roles rather than one tier's colours.
    facts = [
        ("head", f"  Would move {len(plan)} item(s)\n"),
        ("dim", f"  in {project}\n"),
    ]
    detail = [("head", "What would move")]
    for src, dst, label in plan:
        detail.append(("plain", f"- {src.relative_to(project)}"))
        detail.append(("dim", f"    -> {dst.relative_to(project)}  ({label})"))
    detail.append(
        (
            "dim",
            "Nothing else is touched. Your own docs/ keeps everything that is yours, and "
            ".claude/ keeps what Claude Code reads by path. Git history follows a move, so "
            "committed files keep their history.",
        )
    )
    answer = _tiered_installer_screen(
        "decision_screen",
        [("move", f"move {len(plan)} item(s) now"), ("cancel", "leave everything where it is")],
        facts,
        detail,
        _this_module(),
        title="Move team files into VSIT/",
        repo=_repo_hint(),
    )
    if answer is None:
        # No screen available - the printed plan and typed confirm it has always had.
        print("")
        print(style.bold(f"  Would move {len(plan)} item(s) in {project}:"))
        for src, dst, label in plan:
            print(f"    {src.relative_to(project)}")
            print(style.dim(f"      -> {dst.relative_to(project)}   ({label})"))
        print("")
        print(
            style.dim(
                "  Nothing else is touched. Your own docs/ keeps everything that is "
                "yours, and .claude/ keeps what Claude Code reads by path. Git history "
                "follows a move, so committed files keep their history."
            )
        )
        if not confirm("  Move them now?", default=False, assume_yes=False, style=style):
            print(style.dim("  nothing moved."))
            return 0
    elif answer != "move":
        # "" is Esc and "cancel" is the row; both mean the same thing here, and neither
        # is the same as None, which means no screen ran at all.
        print(style.dim("  nothing moved."))
        return 0

    moved = 0
    for src, dst, _label in plan:
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            # shutil.move rather than rename: the destination can be on a different
            # filesystem, and on Windows rename fails across volumes rather than copying.
            shutil.move(str(src), str(dst))
            moved += 1
        except Exception as exc:  # noqa: BLE001 - report and continue; partial is recoverable
            print(style.yellow(f"  {warn} could not move {src.name}: {exc}"))

    readme = project / "VSIT" / "README.md"
    if moved and not readme.exists():
        try:
            readme.parent.mkdir(parents=True, exist_ok=True)
            readme.write_text(_VSIT_README, encoding="utf-8")
        except OSError:
            pass

    print(f"  {ok} moved {moved} of {len(plan)} item(s)")
    if moved:
        print(
            style.dim(
                "      Commit VSIT/shared/ and VSIT/config/; add "
                "VSIT/engagements/ and VSIT/local/ to .gitignore. A README "
                "explaining the folder is in there."
            )
        )
    return 0 if moved == len(plan) else 1


def run_tool_reprobe(style: Style, mark_map: dict) -> int:
    """Force a fresh analyser/tool probe for a project, and show what it found.

    WHY A MANUAL OPTION (2026-08-27 owner request). The probe caches on a 7-day TTL and
    Morgan reads that cache at engagement open. Install a tool and, without this, the team
    keeps reporting it missing until the TTL lapses - the user did exactly what they were
    told and nothing changed. The code-intel step now clears the cache itself, but that
    only covers the tool it installs, in the project it ran from: anyone installing
    ShellCheck, gitleaks or ctags by hand needs a way to say "look again".
    """
    ok, warn = mark_map.get("ok") or "OK", mark_map.get("warn") or "!"
    # The same question relocate asks, asked the same way (owner report, 2026-08-30): a
    # bare prompt here was the other half of "dropped out of the new interface". The probe
    # OUTPUT still streams, deliberately - it is what someone opened this for.
    project = _pick_project(style, "Which project to re-probe?", "  Project to re-probe:")
    if project is None:
        return 0
    if not project.is_dir():
        print(style.yellow(f"  {warn} not a directory: {project}"))
        return 1
    script = _review_tools_script()
    if script is None:
        print(style.yellow(f"  {warn} scripts/check-review-tools.sh not found"))
        return 1
    print(style.dim(f"  re-probing {project} ..."))
    try:
        proc = run_cmd(["bash", str(script), "--refresh"], cwd=str(project), timeout=300)
    except Exception as exc:
        print(style.yellow(f"  {warn} probe failed to run: {exc}"))
        return 1
    body = (proc.stdout or "").strip()
    if body:
        print(body)
    print(f"  {ok} inventory refreshed - the next engagement open reads this")
    return 0


def run_extensions_editor(style: Style, mark_map: dict) -> int:
    """Review the resolved contract, and open a tier for editing.

    DELIBERATELY NOT A FORM (plan-org-extensions-2026-08-27). The contract is markdown with
    a fenced JSON block that people hand-maintain; a TUI that round-tripped it would risk
    mangling a file its author owns. So this REVIEWS richly - showing which tier each entry
    came from, which is the thing you cannot see by opening one file - and delegates editing
    to $EDITOR, validating on save rather than constraining input.
    """
    ok = mark_map.get("ok") or "OK"
    warn = mark_map.get("warn") or "!"
    org = org_extensions_path()

    while True:
        print("")
        print(style.bold("  Org extensions - the standard workflow for THIS MACHINE"))
        print(
            style.dim(
                "  Applies to every project. A project's own docs/team-extensions.md wins "
                "where the two collide."
            )
        )
        print("")
        configured = extensions_source()
        print(f"  Org contract: {org}")
        if configured:
            print(style.dim(f"  source: {configured}"))
        if org.is_file():
            sections, problems = _parse_extensions(org)
            if sections is None:
                print(style.yellow(f"  {warn} present but unparseable - the team would ignore it"))
            else:
                print(style.dim(f"  sections: {', '.join(sections) or '(none recognised)'}"))
                for problem in problems:
                    print(style.yellow(f"  {warn} {problem}"))
        else:
            print(style.dim("  not installed"))
        # Asked through the framework, so there is no fallback to write here and no way
        # for this screen to answer in its own dialect (scripts/questions.py). Back is
        # not a row: leaving is what Esc, q and b already do on every tier, and listing
        # it as well would be two ways to say one thing on one screen.
        answer = _ask().choose(
            "Org extensions",
            [
                ("1", "Review the resolved contract", "org plus this directory's project file"),
                ("2", "Edit the org contract", "opens it in $EDITOR, validates on save"),
                ("3", "Install one from a file", "copies a contract in and validates it"),
                ("4", "Check registry tools", "which analysers are actually on PATH"),
                ("5", "Sync now", "re-pulls from the configured source"),
            ],
        )
        if answer.cancelled:
            return 0
        choice = answer.value

        if choice == "1":
            _show_resolved_extensions(style)
        elif choice == "2":
            rc = _edit_org_extensions(org, style, mark_map)
            if rc == 0:
                print(f"  {ok} saved")
        elif choice == "3":
            path = ask("  Path to the contract file:", "", assume_yes=False, style=style).strip()
            if path:
                run_install_extensions(path, style, mark_map)
        elif choice == "4":
            _run_team_script(["extensions", "check"], style)
        elif choice == "5":
            status, detail = sync_org_extensions(force=True, quiet=False)
            if status == "off":
                print(style.dim("  no extensions_source configured for this machine."))
                print(
                    style.dim(
                        '      Set one: {"extensions_source": "<git URL | path>"} in this '
                        "machine's defaults file."
                    )
                )
            elif status == "failed":
                print(style.yellow(f"  {warn} sync failed: {detail}"))
                print(style.dim("      The contract already on disk is untouched."))
            else:
                print(f"  {ok} {status}: {detail}")
        else:
            return 0


def _show_resolved_extensions(style: Style) -> None:
    """The merged view - the one thing you cannot get by opening either file."""
    print("")
    _run_team_script(["extensions", "show"], style)


def _run_team_script(argv: list, style: Style) -> None:
    """Run one of the team's own scripts and print its output verbatim.

    Consent-free team tooling by design (CLAUDE.md section 7): these are the plugin's own
    scripts, not code under review."""
    try:
        proc = run_cmd([sys.executable, "-m", "scripts." + argv[0], *argv[1:]], timeout=120)
    except Exception as exc:
        print(style.yellow(f"  could not run: {exc}"))
        return
    body = (proc.stdout or "").strip()
    print(body if body else style.dim("  (no output - no extensions resolved)"))
    if proc.stderr.strip():
        print(style.dim("  " + proc.stderr.strip().splitlines()[-1]))


def _edit_org_extensions(target: Path, style: Style, mark_map: dict) -> int:
    """Open the org contract in $EDITOR, seeding the template if there is none, and
    validate what comes back.

    Validation REPORTS, it does not revert: the file belongs to whoever maintains it, and
    silently undoing someone's edit because a parser disliked one entry would be worse than
    telling them. The parser skips bad entries by design, so a partly-valid contract still
    works for everything else in it."""
    warn = mark_map.get("warn") or "!"
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR")
    if not editor:
        print(style.yellow(f"  {warn} no $EDITOR or $VISUAL set - cannot open an editor."))
        print(style.dim(f"      Edit it directly: {target}"))
        return 1
    if not target.is_file():
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            template = clone_asset("docs", "templates", "team-extensions.md")
            target.write_text(
                template.read_text(encoding="utf-8") if template.is_file() else _MINIMAL_ORG,
                encoding="utf-8",
            )
            print(style.dim(f"  seeded a starting contract at {target}"))
        except OSError as exc:
            print(style.yellow(f"  {warn} could not create it: {exc}"))
            return 1
    try:
        subprocess.call([*editor.split(), str(target)])  # noqa: S603 - user's own $EDITOR
    except Exception as exc:
        print(style.yellow(f"  {warn} editor failed: {exc}"))
        return 1
    sections, problems = _parse_extensions(target)
    if sections is None:
        print(style.yellow(f"  {warn} the file no longer parses - the team would ignore it"))
        return 1
    if not sections:
        print(style.yellow(f"  {warn} no recognised section - nothing in it would apply"))
    for problem in problems:
        print(style.yellow(f"  {warn} {problem}"))
    return 0


_MINIMAL_ORG = """# Team extensions - <YOUR ORGANISATION>

## Standing instructions

- <e.g. "Cite our internal control IDs (CTRL-xxx) wherever a finding maps to one.">

## Close actions

- <e.g. "Write a Confluence page in space SURV summarising what was achieved.">

## Analyser registry

```json
{"analysers": []}
```
"""


def _guard_interpreter_cache(project: Path) -> Path:
    """Where run-guard.sh looks for the interpreter cache.

    MUST AGREE WITH scripts/staged_hooks/run-guard.sh, which resolves the same two
    locations in shell because it runs before any interpreter is chosen and cannot import
    a Python resolver. Both prefer VSIT/local/, fall back to .claude/, and neither creates
    VSIT/ as a side effect: a cache written where the launcher does not look is worse than
    no cache, because the launcher then pays a cold start on every hook call and nothing
    reports it."""
    new = project / "VSIT" / "local" / "guard-interpreter"
    if new.is_file():
        return new
    legacy = project / ".claude" / ".guard-interpreter"
    if legacy.is_file() or not (project / "VSIT" / "local").is_dir():
        return legacy
    return new


def _vsit_engagements(project: Path) -> Path:
    """Engagement workspaces for a project, via the shared resolver when reachable.

    install_helper is also distributed as a lone curl-bootstrapped file with no scripts/
    sibling, so a missing resolver falls back to the legacy path rather than failing - the
    same posture as its other lazy imports."""
    try:
        import sys as _sys

        _here = clone_asset("scripts")
        if str(_here) not in _sys.path:
            _sys.path.insert(0, str(_here))
        import vsit_paths

        return vsit_paths.engagements_dir(project)
    except Exception:
        return project / "artifacts"


def run_install_extensions(source: str, style: Style, mark_map: dict) -> int:
    """Install an org extensions contract for this machine, or report the current one.

    WHY THIS EXISTS (plan-org-extensions-2026-08-27, step 2). The org tier is only useful
    if a contract can actually get onto a machine. This is the day-one path: it works
    offline, needs no network, and needs no git - which matters because the boxes that most
    need a central standard are the ones that can least reach a server to fetch it.

    VALIDATES BEFORE INSTALLING. A contract that parses to nothing is worse than none: it
    looks installed and does nothing. So the file is parsed first and refused if it yields
    no recognised section, and any registry entry the parser rejects is reported - it is
    still installed in that case, because a partly-valid contract is legitimate and the
    parser skips bad entries by design, but the user is told rather than left to discover
    it at an engagement open.

    NEVER EXECUTES the file, and neither does anything downstream - the parser is
    deliberately dumb (shutil.which only, plain-argv commands, shell metacharacters
    refused). That is what makes installing a file from elsewhere tolerable at all.
    """
    ok = mark_map.get("ok") or "OK"
    warn = mark_map.get("warn") or "!"
    target = org_extensions_path()

    if source == "sync":
        status, detail = sync_org_extensions(force=True, quiet=False)
        if status == "off":
            print(style.dim("  no extensions_source configured for this machine"))
            return 0
        if status == "failed":
            print(style.yellow(f"  {warn} sync failed: {detail}"))
            print(style.dim("      the contract already on disk is untouched"))
            return 1
        print(f"  {ok} {status}: {detail}")
        return 0

    if source == "show":
        print(f"  org extensions contract: {target}")
        if target.is_file():
            print(style.dim(f"  installed, {target.stat().st_size} bytes"))
            _report_extensions_contents(target, style, mark_map)
        else:
            print(style.dim("  not installed - projects use their own docs/team-extensions.md"))
            print(style.dim("  install one with: python install_helper.py --extensions FILE"))
        return 0

    src = Path(source).expanduser()
    if not src.is_file():
        print(style.yellow(f"  {warn} not a file: {src}"))
        return 1

    sections, problems = _parse_extensions(src)
    if sections is None:
        print(style.yellow(f"  {warn} could not read {src}"))
        return 1
    if not sections:
        # The one refusal. Everything else installs with a warning.
        print(style.yellow(f"  {warn} {src} has no recognised section - nothing would apply."))
        print(
            style.dim(
                "      Expected H2 headings: Standing instructions, Close actions, "
                "Analyser registry, Integrations. Template: docs/templates/team-extensions.md"
            )
        )
        return 1

    if target.is_file():
        backup = target.with_suffix(".md.bak")
        try:
            backup.write_bytes(target.read_bytes())
            print(style.dim(f"  previous contract backed up to {backup}"))
        except OSError as exc:
            print(style.yellow(f"  {warn} could not back up the existing contract: {exc}"))
            return 1
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(src.read_bytes())
    except OSError as exc:
        print(style.yellow(f"  {warn} could not install: {exc}"))
        return 1

    print(f"  {ok} org extensions installed: {target}")
    print(style.dim(f"      sections: {', '.join(sections)}"))
    for problem in problems:
        print(style.yellow(f"  {warn} {problem}"))
    print(
        style.dim(
            "      Applies to EVERY project on this machine. A project's own "
            "docs/team-extensions.md still wins where the two collide."
        )
    )
    return 0


def _parse_extensions(path: Path):
    """(recognised section names, problems) via the team's own parser, or (None, []).

    Imported lazily and from the clone, because this runs standalone: a bare
    `python install_helper.py` has nothing on sys.path yet."""
    try:
        scripts_dir = clone_asset("scripts")
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        import extensions as ext_mod

        data = ext_mod.load(path)
    except Exception:
        return None, []
    return [name for name, body in data["sections"].items() if body.strip()], data["problems"]


def _report_extensions_contents(path: Path, style: Style, mark_map: dict) -> None:
    sections, problems = _parse_extensions(path)
    if sections is None:
        print(style.yellow("  could not parse it - the team would ignore it"))
        return
    print(style.dim(f"  sections: {', '.join(sections) or '(none recognised)'}"))
    for problem in problems:
        print(style.yellow(f"  {mark_map.get('warn') or '!'} {problem}"))


def run_daemon_start_diagnostic(
    style: Style, mark_map: dict, repo_hint: Optional[str] = None
) -> int:
    """Standalone diagnostic (--check-daemon-start / Diagnostics menu): actually starts the
    REAL scripts/guard_daemon.py (not the archived docs/internal/adr-014-spike prototype -
    see adr014_smoke_step for that) in a throwaway temp directory and reports exactly what
    happens. Two checks, deliberately separated to isolate WHERE a failure is:

      A. Foreground - runs guard_daemon.py as a plain, fully-captured subprocess. Proves
         the daemon's own code works (imports, binds a port, writes the port file,
         answers a real request) independent of how it gets spawned.
      B. Detached - mirrors the EXACT Popen call production makes (same creationflags on
         Windows: DETACHED_PROCESS | CREATE_NO_WINDOW | CREATE_BREAKAWAY_FROM_JOB), but
         WITHOUT swallowing the exception, so a spawn-specific failure (permissions, a
         flag Windows on THIS host rejects, anything about detached/job-object behaviour
         that differs from a plain foreground run) surfaces instead of silently nothing.

    Kept in sync with _start_daemon_detached() by comment, not code, same trade-off this
    file already accepts elsewhere (see prewarm_guard_cache's own docstring) - this
    diagnostic must never itself become the production spawn path, only mirror it closely
    enough to catch what production's fail-open design can't show.

    Runs entirely in throwaway temp directories - never touches this project's own
    .claude/.guard-daemon-port or any real daemon that might already be running."""
    import socket

    ok, fail = mark_map["ok"], mark_map["fail"]
    repo_root = _resolve_repo_root(repo_hint) or Path(__file__).resolve().parent
    rows = []
    bundle_lines = []

    def record(label: str, status: str, detail: str) -> None:
        rows.append((label, status, detail))
        bundle_lines.append(f"--- {label} [{status}] ---\n{detail}\n")
        mark = {"OK": ok, "SKIP": style.dim("-"), "WARN": style.yellow("!")}.get(status, fail)
        print(f"  {mark} {label}: {detail}", flush=True)

    print(style.bold("Guard daemon start diagnostic (production module, not the archived spike)"))
    print(style.dim(f"  Repo root: {repo_root}"))

    daemon_py = repo_root / "scripts" / "guard_daemon.py"
    if not daemon_py.is_file():
        record("guard_daemon.py present", "ERROR", f"not found at {daemon_py}")
        _print_diagnostic_summary(style, mark_map, rows)
        return 1
    record("guard_daemon.py present", "OK", str(daemon_py))

    prefs_path = repo_root / ".claude" / "team-preferences.json"
    if prefs_path.is_file():
        try:
            prefs_text = prefs_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            # UnicodeDecodeError is NOT an OSError (found in review, 2026-08-13): a
            # non-UTF-8 team-preferences.json used to crash this diagnostic instead of
            # just reporting it as unreadable.
            prefs_text = ""
            record("team-preferences.json readable", "ERROR", str(exc))
        if prefs_text:
            import re as _re

            is_on = bool(_re.search(r'"guard_daemon"\s*:\s*true', prefs_text))
            record(
                "guard_daemon preference",
                "OK" if is_on else "WARN",
                "true - run-guard.sh routes to the daemon"
                if is_on
                else f"not true in {prefs_path} - run-guard.sh never routes to the daemon at "
                "all right now (the checks below still run, to test the mechanism itself "
                "independent of this gate)",
            )
    else:
        record(
            "guard_daemon preference",
            "WARN",
            f"{prefs_path} not found - daemon routing is off (checks below still run)",
        )

    def _poll_for_port_file(port_file: Path, seconds: float) -> bool:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if port_file.is_file():
                return True
            time.sleep(0.1)
        return port_file.is_file()

    # --- Check A: foreground, fully captured - proves the daemon's own code works ---
    print(style.dim("\n  Check A - foreground (plain subprocess, full output captured):"))
    with tempfile.TemporaryDirectory(prefix="virt-surv-it-daemon-diag-fg-") as tmp:
        state_root = Path(tmp)
        port_file = state_root / ".claude" / ".guard-daemon-port"
        proc = None
        try:
            proc = subprocess.Popen(  # nosec B603 - fixed argv, shell=False
                [
                    sys.executable,
                    str(daemon_py),
                    str(repo_root),
                    str(state_root),
                    "--idle-timeout",
                    "5",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                encoding="utf-8",
                errors="replace",
            )
        except OSError as exc:
            record("foreground daemon spawn", "ERROR", f"Popen itself raised: {exc!r}")
        if proc is not None:
            appeared = _poll_for_port_file(port_file, 10)
            if appeared:
                record("foreground daemon spawn", "OK", f"port file appeared at {port_file}")
                try:
                    lines = port_file.read_text(encoding="utf-8").splitlines()
                    port, token = int(lines[0]), lines[1]
                    with socket.create_connection(("127.0.0.1", port), timeout=2) as sock:
                        sock.settimeout(5)
                        payload = json.dumps(
                            {
                                "tool_name": "Read",
                                "tool_input": {"file_path": str(repo_root / "README.md")},
                            }
                        )
                        req = json.dumps({"token": token, "payload": payload}) + "\n"
                        sock.sendall(req.encode("utf-8"))
                        sock.shutdown(socket.SHUT_WR)
                        chunks = []
                        while True:
                            chunk = sock.recv(65536)
                            if not chunk:
                                break
                            chunks.append(chunk)
                    resp = json.loads(b"".join(chunks).decode("utf-8"))
                    record(
                        "foreground daemon responds",
                        "OK" if "exit_code" in resp else "ERROR",
                        str(resp),
                    )
                except (OSError, ValueError, IndexError) as exc:
                    record("foreground daemon responds", "ERROR", f"{type(exc).__name__}: {exc}")
            else:
                try:
                    proc.terminate()
                    out, err = proc.communicate(timeout=5)
                except (OSError, subprocess.TimeoutExpired):
                    out, err = "", ""
                still_running = proc.poll() is None
                record(
                    "foreground daemon spawn",
                    "ERROR",
                    f"no port file after 10s (process {'still running - killed for cleanup' if still_running else f'exited {proc.returncode}'}) "
                    f"stdout={out!r} stderr={err!r}",
                )
            if proc.poll() is None:
                try:
                    proc.kill()
                    proc.wait(timeout=5)
                except (OSError, subprocess.TimeoutExpired):
                    pass

    # --- Check B: the ACTUAL production detached-spawn path, exception surfaced ---
    print(style.dim("\n  Check B - detached spawn (mirrors the real production code path):"))
    with tempfile.TemporaryDirectory(prefix="virt-surv-it-daemon-diag-bg-") as tmp2:
        state_root2 = Path(tmp2)
        port_file2 = state_root2 / ".claude" / ".guard-daemon-port"
        kwargs = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = (
                subprocess.DETACHED_PROCESS
                | subprocess.CREATE_NO_WINDOW
                | subprocess.CREATE_BREAKAWAY_FROM_JOB
            )
        else:
            kwargs["start_new_session"] = True
        spawn_error = None
        try:
            subprocess.Popen(  # nosec B603 - fixed argv, shell=False; mirrors
                # scripts/guard_daemon_client.py's own _start_daemon_detached exactly,
                # WITHOUT its exception-swallowing, so a spawn failure surfaces here.
                [
                    sys.executable,
                    str(daemon_py),
                    str(repo_root),
                    str(state_root2),
                    "--idle-timeout",
                    "5",
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                **kwargs,
            )
        except OSError as exc:
            spawn_error = exc
        if spawn_error is not None:
            record(
                "detached daemon spawn",
                "ERROR",
                f"{type(spawn_error).__name__}: {spawn_error} "
                f"(errno={getattr(spawn_error, 'errno', None)}, "
                f"winerror={getattr(spawn_error, 'winerror', None)}) - THIS is the production "
                "code path; an error here is exactly why the daemon never starts for real "
                "hook calls",
            )
        else:
            appeared = _poll_for_port_file(port_file2, 10)
            if appeared:
                record("detached daemon spawn", "OK", f"port file appeared at {port_file2}")
            else:
                record(
                    "detached daemon spawn",
                    "ERROR",
                    "Popen succeeded (no exception) but no port file appeared within 10s - the "
                    "process may have started and crashed immediately with no visible output "
                    "(stdout/stderr are DEVNULL here, matching production exactly - this is "
                    "the actual blind spot; Check A above captures output for the same code, "
                    "just not spawned the detached way, so compare the two results)",
                )

    _print_diagnostic_summary(style, mark_map, rows)

    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    bundle_path = Path.cwd() / f"virt-surv-daemon-start-diagnostic-{ts}.txt"
    header = (
        "virt-surv-it guard daemon start diagnostic\n"
        f"Python: {sys.version}\nPlatform: {sys.platform}\nRepo root: {repo_root}\n\n"
    )
    try:
        bundle_path.write_text(header + "\n".join(bundle_lines), encoding="utf-8")
        print("")
        print(style.dim(f"Full detail written to: {bundle_path} - hand this back whole."))
    except OSError as exc:
        print("")
        print(style.yellow(f"Could not write the data file: {exc}"))

    bad = sum(1 for _label, status, _detail in rows if status == "ERROR")
    return 1 if bad else 0


# ------------------------------------------------------------------ self-test (mechanical smoke test)
#
# 2026-08-04 user request: a lightweight but MEANINGFUL validation of a "review this code"
# engagement's real mechanical substrate - not another presence probe, but proof the pieces
# actually work together on this machine, with full debug detail captured to a file on any
# failure (so a report can be one attachment instead of a screenshot). Deliberately does NOT
# invoke Claude Code/an LLM - that needs the Agent SDK, a venv, real API tokens and network
# (scripts/eval_engage.py already exists for that heavier, opt-in-at-milestones purpose).

_SELFTEST_PLANTED_ISSUE_PY = 'password = "hunter2"\n'  # bandit B105 - reliably flagged


def _selftest_findings_pack(slug: str) -> dict:
    """A minimal but schema-valid findings pack (docs/review/findings-schema.json) - proves
    render_findings.py's full validate-then-render path, not just that the file parses."""
    return {
        "slug": slug,
        "kind": "review",
        "scope": "selftest_target.py",
        "mode": "change",
        "verdict": "conditional",
        "findings": [
            {
                "id": "SEC-1",
                "title": "Hardcoded credential (planted for selftest - not a real finding)",
                "severity": "critical",
                "location": "selftest_target.py:1",
                "basis": "measured",
                "standard": "CWE-259",
                "problem": "planted for selftest - not a real finding",
                "likely_cause": "n/a (synthetic)",
                "impact": "n/a (synthetic)",
                "fix": {"diff": "n/a (synthetic)", "why": "n/a (synthetic)"},
                "disposition": "open",
            }
        ],
    }


def _selftest_engagement_probe(repo_root: Path, interpreter: str):
    """Generator: yields (label, status, detail, full_detail) for the two parts of
    --selftest NOT already covered by --check-env's own sections (guard hooks/repo
    syntax/runtime deps) - the analyser DETECTING a planted issue, and the
    engagement-state lifecycle end to end. Shared by run_selftest and run_env_check
    (2026-08-04 user request: "the comprehensive [env] test should execute the
    synthetic test so it's really is comprehensive") so neither duplicates the other's
    checks - run_env_check folds this in as one more section instead of re-running
    guard hooks etc a second time under a different heading."""
    with tempfile.TemporaryDirectory(prefix="virt-surv-it-selftest-analyser-") as atmp:
        target = Path(atmp) / "selftest_target.py"
        target.write_text(_SELFTEST_PLANTED_ISSUE_PY, encoding="utf-8")
        if not shutil.which("bandit"):
            yield ("bandit (planted issue)", "SKIP", "bandit not installed", None)
        else:
            try:
                proc = subprocess.run(
                    ["bandit", "-q", str(target)],
                    capture_output=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=20,
                )
                combined = (proc.stdout or "") + (proc.stderr or "")
                found = "hardcoded_password" in combined
                # Distinguishes a genuine crash from "ran fine, missed it" - live-caught
                # (fable UX review, 2026-08-05): both used to be reported identically as
                # "may be misconfigured", even when bandit's own exit code (0=clean,
                # 1=issues found are its ONLY two normal outcomes) showed it never
                # actually completed a real scan.
                if found:
                    yield ("bandit (planted issue)", "OK", "planted issue detected", combined)
                elif proc.returncode not in (0, 1):
                    first_line = (
                        combined.strip().splitlines()[0] if combined.strip() else "(no output)"
                    )
                    yield (
                        "bandit (planted issue)",
                        "ERROR",
                        f"crashed (exit {proc.returncode}), not just missed the issue: "
                        f"{first_line[:150]}",
                        combined,
                    )
                else:
                    yield (
                        "bandit (planted issue)",
                        "ERROR",
                        "planted issue NOT detected - bandit ran but its ruleset/config may be off",
                        combined,
                    )
            except (OSError, subprocess.TimeoutExpired) as exc:
                yield ("bandit (planted issue)", "ERROR", f"failed to run: {exc}", None)

    with tempfile.TemporaryDirectory(prefix="virt-surv-it-selftest-lifecycle-") as ltmp:
        project = Path(ltmp)
        slug = "selftest-demo"
        engagement_state = repo_root / "scripts" / "engagement_state.py"
        render_findings = repo_root / "scripts" / "render_findings.py"

        def run_step(label, argv, extra_check=None):
            try:
                proc = subprocess.run(
                    argv,
                    cwd=project,
                    capture_output=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=30,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                return (label, "ERROR", f"failed to run: {exc}", None)
            combined = (proc.stdout or "") + (proc.stderr or "")
            if extra_check:
                passed, note = extra_check(proc, combined)
            else:
                passed, note = (
                    proc.returncode == 0,
                    ("clean" if proc.returncode == 0 else f"exit {proc.returncode}"),
                )
            return (label, "OK" if passed else "ERROR", note, combined)

        if not (engagement_state.is_file() and render_findings.is_file()):
            yield (
                "engagement-state lifecycle",
                "SKIP",
                _bootstrap_only_hint(repo_root) or "scripts not found",
                None,
            )
            return
        py = interpreter or sys.executable
        yield run_step(
            "init",
            [
                py,
                str(engagement_state),
                "init",
                "--title",
                "Selftest demo",
                "--slug",
                slug,
                "--team-version",
                installed_version(repo_root) or "0.0.0",
            ],
        )
        data_dir = _vsit_engagements(project) / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        pack_path = data_dir / f"findings-{slug}.jsonl"
        pack = _selftest_findings_pack(slug)
        # JSONL (envelope line + one finding per line), matching scripts/findings_pack_io.py's
        # on-disk format - written inline (no import) since this runs against a throwaway temp
        # project dir, not necessarily this repo's own layout.
        envelope = {k: v for k, v in pack.items() if k != "findings"}
        lines = [json.dumps(envelope, ensure_ascii=False)]
        lines += [json.dumps(f, ensure_ascii=False) for f in pack["findings"]]
        pack_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        yield run_step("render findings", [py, str(render_findings), str(pack_path), "--html"])
        yield run_step("set-team", [py, str(engagement_state), "set-team", "Selftest (synthetic)"])
        # The close-gate SHOULD refuse an incomplete close (no AI marker, no summary
        # email) - that refusal IS the pass condition, proving the gate has real teeth
        # rather than assuming it does because a trivially-easy synthetic pack closed.
        yield run_step(
            "close-gate (expect refusal - proves an incomplete close is blocked)",
            [py, str(engagement_state), "set-status", "closed"],
            extra_check=lambda proc, combined: (
                proc.returncode != 0 and "CLOSE-REFUSED" in combined,
                "correctly refused an incomplete close"
                if "CLOSE-REFUSED" in combined
                else f"expected a CLOSE-REFUSED block, got exit {proc.returncode}",
            ),
        )
        yield run_step("set-status closing", [py, str(engagement_state), "set-status", "closing"])
        yield run_step("archive", [py, str(engagement_state), "archive", slug, "--force"])


def run_selftest(style: Style, mark_map: dict, repo_hint: Optional[str] = None) -> int:
    """Standalone diagnostic (--selftest / Diagnostics menu): a throwaway synthetic
    "review this code" engagement, exercising the REAL guard hooks, the REAL analyser
    pipeline (proves DETECTION on a planted issue, not just silence on clean input), and
    the REAL engagement-state lifecycle (init -> findings -> render -> the close-gate
    correctly REFUSING an incomplete close -> archive) end to end. No mocking, no LLM.
    Also folded into --check-env as its final section (see _selftest_engagement_probe).

    On any failure, writes a full debug bundle (every step's complete stdout/stderr, plus
    Python/platform/interpreter/repo-root) to virt-surv-selftest-<timestamp>.txt in the
    CURRENT directory - meant to be attached/pasted whole, replacing a screenshot."""
    ok, fail = mark_map["ok"], mark_map["fail"]
    repo_root = _resolve_repo_root(repo_hint) or Path(__file__).resolve().parent
    order = ["python", "py", "python3"] if sys.platform == "win32" else ["python3", "python", "py"]
    _, interpreter = _check_interpreters(order)

    rows = []
    bundle = []

    def record(label: str, status: str, detail: str, full: Optional[str] = None) -> None:
        rows.append((label, status, detail))
        bundle.append(f"--- {label} [{status}] ---\n{full if full is not None else detail}\n")
        mark = {"OK": ok, "SKIP": style.dim("-"), "WARN": style.yellow("!")}.get(status, fail)
        print(f"  {mark} {label}: {detail}", flush=True)

    print(style.bold("Self-test: a mechanical smoke test of a 'review this code' engagement"))
    print(
        style.dim("  No LLM/Claude Code invocation - stdlib + the team's own scripts, no network.")
    )

    print(style.dim("\n  Guard hooks:"))
    with tempfile.TemporaryDirectory(prefix="virt-surv-it-selftest-guard-") as gtmp:
        for label, status, detail in _check_guard_hooks(interpreter, repo_root, Path(gtmp)):
            record(label, status, detail)

    print(style.dim("\n  Repo script syntax:"))
    for label, status, detail in _check_repo_py_syntax(interpreter, repo_root):
        record(label, status, detail)

    print(style.dim("\n  Runtime dependencies:"))
    for label, status, detail in _check_runtime_dependencies():
        record(label, status, detail)

    print(
        style.dim(
            "\n  Synthetic engagement (planted-issue detection, then init -> findings -> "
            "render -> close-gate -> archive):"
        )
    )
    for label, status, detail, full in _selftest_engagement_probe(repo_root, interpreter):
        record(label, status, detail, full)

    _print_diagnostic_summary(style, mark_map, rows)
    bad = [r for r in rows if r[1] not in ("OK", "SKIP", "WARN")]
    print("")
    if bad:
        ts = datetime.now().strftime("%Y%m%dT%H%M%S")
        bundle_path = Path.cwd() / f"virt-surv-selftest-{ts}.txt"
        header = (
            "virt-surv-it self-test debug bundle\n"
            f"Python: {sys.version}\nPlatform: {sys.platform}\nInterpreter: {interpreter}\n"
            f"Repo root: {repo_root}\n\n"
        )
        try:
            bundle_path.write_text(header + "\n".join(bundle), encoding="utf-8")
            print(
                style.yellow(
                    f"{len(bad)} issue(s) found. Full debug bundle written to: {bundle_path}"
                )
            )
        except OSError as exc:
            print(
                style.yellow(
                    f"{len(bad)} issue(s) found, and the debug bundle could not be written: {exc}"
                )
            )
        return 1
    print(style.dim("Self-test passed - the engagement substrate works on this machine."))
    return 0


# ------------------------------------------------------------------ CLI


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="install_helper",
        description="Install or update the compliance-surveillance-team Claude Code plugin.",
        epilog=(
            "Also (handled before any of the above, not shown in usage above since "
            "argparse doesn't model them as a real subparser): "
            "install_helper.py configure|archive|list-engagements [DIR] [--demo] [--yes] "
            "- folder-scoped, same forms the 'virt-surv' alias (--setup-alias) runs when "
            "you type e.g. 'virt-surv configure' from inside a project folder."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=banner_version_line(),
        help="print the version and exit - cheap way to answer 'what are you running?' "
        "when asking for support (fable UX review, 2026-08-05: no --version existed at all)",
    )
    parser.add_argument(
        "mode",
        nargs="?",
        choices=["install", "update"],
        default=None,
        help="install = fresh clone + plugin install; update = sync an existing clone; "
        "default shows the menu on a terminal, else auto-detects from the saved config",
    )
    parser.add_argument(
        "--branch",
        choices=list(BRANCHES),
        help="release channel (dev = recommended default during this PoC phase, main = stable but can lag)",
    )
    parser.add_argument("--repo", help="path to the clone (overrides the saved location)")
    parser.add_argument("--yes", action="store_true", help="non-interactive, safe defaults")
    parser.add_argument(
        "--pip",
        action="store_true",
        help="with --yes: also pip-install requirements-dev.txt (default: skip)",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="dry-run the real interactive flow: answer the real prompts, every command "
        "prints as 'would run:', nothing is executed or written",
    )
    parser.add_argument(
        "--enable-project",
        metavar="PROJECT_DIR",
        action="append",
        dest="enable_project",
        help="standalone: enable the plugin for PROJECT_DIR (repeatable) and exit; "
        "combine with --permissions to also add the allow-list",
    )
    parser.add_argument(
        "--statusline",
        action="store_true",
        help="with --yes: wire the team status line into your user-level Claude settings "
        "(interactive runs simply ask)",
    )
    parser.add_argument(
        "--extensions",
        metavar="FILE",
        help="standalone: install FILE as this machine's ORG extensions contract "
        "(~/.config/virt-surv-it/team-extensions.md), so a standard workflow is authored "
        "once and applies to every project instead of being set up per repo. Validates "
        "before installing and backs up any existing copy. Pass 'show' instead of a path "
        "to print where the contract lives and whether one is installed, or 'sync' to refresh it from the configured extensions_source",
    )
    parser.add_argument(
        "--permissions",
        metavar="PROJECT_DIR",
        help="standalone: merge the README's recommended permissions.allow entries into "
        "PROJECT_DIR/.claude/settings.json (add-only, backs the file up first) and exit",
    )
    parser.add_argument(
        "--env-tuning",
        metavar="PROJECT_DIR",
        help="standalone: upsert recommended API-timeout/stream-idle/output-size env vars "
        "into PROJECT_DIR/.claude/settings.json's env block (adds missing keys, corrects "
        "keys present with a different value, leaves every other env var and setting "
        "untouched; backs the file up first) and exit",
    )
    parser.add_argument(
        "--env-tuning-betas",
        metavar="PROJECT_DIR",
        help="standalone: upsert CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1 into "
        "PROJECT_DIR/.claude/settings.json's env block - a workaround for an LLM gateway "
        "that rejects Anthropic's beta tool-schema fields (400 'tools.0.custom."
        "eager_input_streaming: Extra inputs are not permitted', most often on a "
        "haiku-tier call). Only worth it if you're actually hitting this - it also "
        "disables MCP tool search. Same upsert/backup mechanics as --env-tuning, and exit",
    )
    parser.add_argument(
        "--model-project",
        metavar="PROJECT_DIR",
        help="standalone, combine with --model: set or reset Morgan's model for "
        "PROJECT_DIR and exit",
    )
    parser.add_argument(
        "--model-default",
        action="store_true",
        help="standalone, combine with --model: set Morgan's DEFAULT model for new/"
        "unconfigured projects (~/.claude/settings.json, user-level - Claude Code layers "
        "project settings over this) and exit; alternative to --model-project",
    )
    parser.add_argument(
        "--model",
        choices=[*ORCHESTRATOR_MODELS, "default"],
        help="with --model-project or --model-default: opus/sonnet/sonnet-4-6 (each "
        "written as an exact model ID, never Claude Code's generic 'sonnet' alias, which "
        "resolves to a different actual model per API provider), or 'default' to reset "
        "to sonnet (the documented default for the orchestrator) - or, with "
        "--model-default only, to clear the global default entirely",
    )
    parser.add_argument(
        "--check-tools",
        action="store_true",
        help="standalone, QUICK: verify code-reviewer's analysers (gitleaks, bandit, "
        "mypy, ruff - semgrep/pip-audit deliberately excluded) actually produce clean "
        "output with their recommended flags on THIS machine, and exit - use this for a "
        "fast recheck after installing/removing an analyser; --check-env below runs this "
        "PLUS a lot more, so use --check-tools when you specifically only want this",
    )
    parser.add_argument(
        "--check-env",
        action="store_true",
        help="standalone, COMPREHENSIVE (includes --check-tools' own check plus "
        "everything else): interpreter resolution, git/claude CLI, guard hooks, "
        "encoding round-trip, the plugin-root bootstrap, every repo .py file's syntax, "
        "analyser output cleanliness, AND the --selftest synthetic engagement - one full "
        "report ending in a pass/fail summary, and exit. The slower, complete diagnostic "
        "- reach for this first when reporting an environment issue",
    )
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="standalone: just the synthetic 'review this code' engagement (planted-"
        "issue detection + the full engagement-state lifecycle) that --check-env also "
        "runs as its final section - no LLM/Claude Code invocation, no network - and "
        "exit; writes a debug bundle on any failure",
    )
    parser.add_argument(
        "--check-hook-latency",
        action="store_true",
        help="standalone: measures real PreToolUse hook latency on this machine - "
        "repeated interpreter cold starts, the real guard-launcher end to end, and a "
        "concurrent fan-out simulation - feeding the docs/adr/ADR-014 persistent-daemon "
        "decision with actual numbers. Slower than the other checks on purpose; always "
        "writes the full numbers to a file, pass or fail, and exit",
    )
    parser.add_argument(
        "--check-adr014-spike",
        action="store_true",
        help="standalone: runs the ADR-014 guard-daemon design-spike's live smoke test "
        "(docs/internal/adr-014-spike/) - starts a REAL prototype daemon process, sends "
        "it real concurrent requests, measures actual daemon-vs-cold-start latency, and "
        "exit. PROTOTYPE, not production - not wired into any live hook path",
    )
    parser.add_argument(
        "--code-intel",
        action="store_true",
        help="standalone: install or refresh the optional code-intelligence extras "
        "(tree-sitter), then report whether they actually load. Reports 'already "
        "available' and changes nothing when present, so it doubles as the check. "
        "Never fatal - without them, codebase orientation uses pattern matching",
    )
    parser.add_argument(
        "--check-daemon-start",
        action="store_true",
        help="standalone: starts the REAL PRODUCTION scripts/guard_daemon.py (foreground, "
        "fully captured, AND the exact detached spawn production uses) in a throwaway "
        "temp directory and reports exactly what happens, and exit. Built because a "
        "failed detached spawn is silent by design in production (must never brick a "
        "hook call) - use this when the daemon simply never starts and there's no other "
        "clue why. Writes a debug bundle either way",
    )
    parser.add_argument(
        "--configure",
        metavar="DIR",
        nargs="?",
        const=".",
        help="standalone: one-shot project setup for DIR (default: current directory) - "
        "enable + permissions + preferences + model in one guided pass, plus an "
        "unconditional analyser-availability cache refresh (check-review-tools.sh "
        "--refresh) at the end, and exit. This is what the 'virt-surv' alias "
        "(--setup-alias) runs when you type 'virt-surv configure' from inside a "
        "project folder",
    )
    parser.add_argument(
        "--archive",
        metavar="DIR",
        nargs="?",
        const=".",
        help="standalone: archive every closed engagement under DIR/artifacts (default: "
        "current directory) and exit - bridges to scripts/engagement_state.py archive "
        "--all-closed, scoped to DIR",
    )
    parser.add_argument(
        "--list-engagements",
        metavar="DIR",
        nargs="?",
        const=".",
        help="standalone: list DIR's engagements (default: current directory) and exit - "
        "bridges to scripts/engagement_state.py list",
    )
    parser.add_argument(
        "--setup-alias",
        action="store_true",
        help="standalone: offer to add a 'virt-surv' shell alias/function pointing at "
        "this clone, so it's runnable from any folder - and exit",
    )
    parser.add_argument(
        "--fix-bashrc",
        action="store_true",
        help="standalone: offer to add a non-interactive-shell guard to ~/.bashrc so slow "
        "interactive-only setup doesn't run on every Claude Code Bash tool call (see "
        "--check-env's '.bashrc source time' row) - and exit",
    )
    parser.add_argument(
        "--clean-plugin-cache",
        action="store_true",
        help="standalone: remove stale cached plugin installs under "
        "~/.claude/plugins/{cache,marketplaces} left behind by prior updates - never "
        "removes the currently-active install - and exit",
    )
    return parser.parse_args(argv)


def _argv_from_args(
    args: argparse.Namespace, repo: Path, branch: str, mode: Optional[str] = None
) -> list:
    """Rebuild an equivalent CLI argv from a parsed Namespace, with repo/branch pinned to
    what THIS run already resolved. Used only for the self-update re-exec
    (Installer._reexec_if_self_updated) - --repo/--branch stop the restarted process from
    re-asking choices already made; --enable-project/--permissions are deliberately
    omitted since that scripting path exits _main() before an Installer ever runs.

    `mode`: the RESOLVED install/update mode (self.mode, always concrete by the time a
    self-update relaunch can fire) - NOT args.mode, which is often still None (the user
    picked "1) Install or update" from the menu rather than passing a positional arg).
    Without this, the relaunched child's args.mode would be None too, so it would land
    back on the interactive menu instead of continuing straight through - live-caught,
    2026-08-04: after a self-update relaunch, "it's not clear to the user that they may
    still have to [pick] a full install again to see the new options" - jumping straight
    into the full flow (matching what the user was already mid-way through doing) is the
    fix, not re-showing a menu they already got past once this run."""
    argv = []
    resolved_mode = mode or args.mode
    if resolved_mode:
        argv.append(resolved_mode)
    argv += ["--branch", branch, "--repo", str(repo)]
    if args.yes:
        argv.append("--yes")
    if args.pip:
        argv.append("--pip")
    if args.demo:
        argv.append("--demo")
    if args.statusline:
        argv.append("--statusline")
    return argv


def _relocate_if_running_inside_target_repo(
    args: argparse.Namespace, argv: Optional[list] = None
) -> None:
    """If this script lives inside the git repo it is about to sync (`git checkout` the
    branch), that checkout can fail to overwrite the currently-executing .py file -
    observed live on a corporate Windows box (2026-07-30), where the workaround was
    copying the script out by hand before every run. Copies itself to a temp file and
    re-execs from there FIRST, passing the original repo location through explicitly, so
    the checkout below can freely replace the original and no manual copy is needed.

    Self-limiting, not marker-based: the relocated copy's own __file__ lives in a plain
    temp dir (never a git repo), so looks_like_repo() is False on the second pass and
    this is a no-op - no infinite loop, no state to track."""
    try:
        here = Path(__file__).resolve()
        repo_dir = here.parent
        if not looks_like_repo(repo_dir):
            return  # not running from inside a clone - nothing at risk
        tmp_dir = Path(tempfile.mkdtemp(prefix="virt-surv-it-installer-"))
        tmp_copy = tmp_dir / here.name
        shutil.copy2(here, tmp_copy)
        # Honour whatever argv THIS invocation actually parsed (explicit argv=[...] in
        # tests/embedding, else the real process argv) - never re-read sys.argv blindly,
        # which would leak an unrelated caller's own CLI args into the child.
        child_argv = list(argv if argv is not None else sys.argv[1:])
        if not args.repo:
            # Preserve "I was found inside this clone" - the copy no longer lives there.
            child_argv += ["--repo", str(repo_dir)]
        proc = subprocess.run(  # fixed argv (sys.executable + our own tmp copy), shell=False  # nosec B603
            [sys.executable, str(tmp_copy), *child_argv]
        )
        sys.exit(proc.returncode)
    except SystemExit:
        raise
    except (
        Exception
    ):  # best-effort: fall through to the normal (possibly failing) run  # nosec B110
        pass


_FOLDER_SUBCOMMANDS = (
    "configure",
    "engage",
    "onboard",
    "archive",
    "list-engagements",
    "evidence",
    "setup-alias",
    "go",
)


def _project_root_warning(target: Path) -> Optional[str]:
    """Non-blocking sanity check for 'virt-surv engage'/'onboard' (2026-08-07 user
    request: "check that the user is running it in the root of the project's folder"):
    catches the two common wrong-directory mistakes without asking a question (these
    commands are zero-prompt by design) - just a warning, never a block, since there is
    no reliable way to KNOW a folder is a project root, only ways to notice it probably
    isn't."""
    resolved = target.expanduser().resolve()
    try:
        home = Path.home().resolve()
    except OSError:
        home = None
    if home is not None and resolved == home:
        return "this is your HOME directory, not a project folder"
    if resolved.parent == resolved:  # filesystem root (/, C:\, ...)
        return "this is a filesystem root, not a project folder"
    return None


def _plugin_enabled_for_configure(target: Path) -> bool:
    """Same 'has this project been set up?' signal the launcher uses (its own
    _plugin_enabled): the repo-as-project marker, or .claude/team-preferences.json,
    which run_configure writes and which exists in plugin mode too. Kept as its own tiny
    function rather than importing the launcher - this decides only which of two setup
    UIs to show, and must never make `virt-surv configure` depend on the launcher being
    importable."""
    try:
        project = target.expanduser().resolve()
    except OSError:
        return False
    return (project / "docs" / "team-operating-guide.md").is_file() or (
        project / ".claude" / "team-preferences.json"
    ).is_file()


def _run_evidence_room(target: Path, style: Style, mark_map: dict) -> int:
    """`virt-surv evidence [DIR]` - render an engagement's Evidence Room.

    DIR may be the workspace itself (artifacts/<slug>, i.e. it holds an
    engagement-state.json) or a project root, in which case the ACTIVE engagement is
    used - the marker `virt-surv go` and `engagement_state init` already maintain, so
    standing in your project root and typing the command does the obvious thing. The
    per-project `evidence_room` gate lives in the renderer, not here: one gate, one
    place, and this subcommand is only a convenient way to reach it."""
    fail, ok = mark_map["fail"], mark_map["ok"]
    project = target.expanduser().resolve()
    workspace = project
    if not (workspace / "engagement-state.json").is_file():
        marker = _vsit_engagements(project) / ".active-engagement.json"
        slug = ""
        try:
            slug = json.loads(marker.read_text(encoding="utf-8")).get("slug") or ""
        except (OSError, ValueError, AttributeError):
            slug = ""
        if not slug:
            print(
                f"{fail} no engagement found in {project} - run this from a project with an "
                "active engagement, or pass the workspace: virt-surv evidence artifacts/<slug>"
            )
            return 1
        workspace = _vsit_engagements(project) / slug
    repo = _resolve_repo_root(None)
    scripts_dir = (repo / "scripts") if repo else Path(__file__).resolve().parent / "scripts"
    renderer = scripts_dir / "render_evidence_room.py"
    if not renderer.is_file():
        print(f"{fail} renderer not found: {renderer}")
        return 1
    _, interpreter = _check_interpreters(
        ["python", "py", "python3"] if sys.platform == "win32" else ["python3", "python", "py"]
    )
    if not interpreter:
        print(f"{fail} no working Python interpreter found")
        return 1
    try:
        proc = subprocess.run(  # fixed argv, shell=False  # nosec B603
            [interpreter, str(renderer), str(workspace)],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"{fail} could not run the renderer: {exc}")
        return 1
    message = (proc.stdout or proc.stderr or "").strip()
    if message:
        # A ✓ means a pack was written. "off for this project" also exits 0 (a normal
        # outcome, not an error) but ticking it read as success when nothing happened.
        wrote = proc.returncode == 0 and message.startswith("evidence room:")
        mark = ok if wrote else (mark_map.get("skip", "-") if proc.returncode == 0 else fail)
        print(f"{mark} {message}")
    return proc.returncode


def _run_launcher_settings(target: Path, style: Style):
    """Hand an already-configured project to the launcher's own settings editor - the
    screen `virt-surv go`'s [c] opens (2026-08-19 user request). Returns the exit code,
    or None when the launcher can't be run at all, in which case the caller falls back
    to the full guided configure pass rather than leaving the user with nothing."""
    repo = _resolve_repo_root(None)
    scripts_dir = (repo / "scripts") if repo else Path(__file__).resolve().parent / "scripts"
    launcher = scripts_dir / "virt_team_launcher.py"
    if not launcher.is_file():
        return None
    _, interpreter = _check_interpreters(
        ["python", "py", "python3"] if sys.platform == "win32" else ["python3", "python", "py"]
    )
    if not interpreter:
        return None
    try:
        # --configure prints nothing to stdout (the launcher reserves stdout for a launch
        # decision), so this is safe to run inline with the user's own terminal attached.
        proc = subprocess.run(  # fixed argv, shell=False  # nosec B603
            [interpreter, str(launcher), "--configure", str(target.expanduser().resolve())],
        )
        return proc.returncode
    except (OSError, subprocess.SubprocessError):
        return None


def _run_go(target: Path, style: Style, mark_map: dict, hat: str, demo: bool = False) -> int:
    """'virt-surv go': the single unified launch command (2026-08-15 user request -
    "only one alias, separate parameter to launch" - a separate virt-team alias existed
    for one turn of this same feature and was explicitly rejected as confusing). Shown
    with the same Morgan-hatted presentation as every other virt-surv subcommand
    (2026-08-15 user request), states the current version, and reuses
    check_for_update_upfront - same 8s-timeout, fails-silently-on-no-network behaviour
    already used right after the interactive menu's own banner, not a new code path.
    Pre-warms the tool-inventory cache and resolves the /engage resume-vs-new decision
    outside the LLM entirely (scripts/virt_team_launcher.py, called directly - no logic
    duplicated), then launches Claude Code via the configured launch command with the
    decision pre-seeded as the initial prompt.

    Launching a shell alias/function (a user's own 'cc', say) is NOT possible from this
    Python process - subprocess/exec can only invoke real executables. When virt-surv's
    OWN shell function is what called `... go` (its "go" branch, written by
    run_setup_alias), the SHELL does the actual launch and this function is never
    reached for the launch step at all - only when 'go' is reached some OTHER way
    (python install_helper.py go directly, or an alias written before the "go" branch
    existed) does this function's own launch attempt matter, and even then only when the
    configured command resolves to a real executable (shutil.which) - otherwise it
    prints the exact command to type rather than failing silently."""
    resolved_target = target.expanduser().resolve()
    repo = _resolve_repo_root(None)
    version = installed_version(repo) if repo else None
    version_note = f" v{version}" if version else ""
    print(style.dim(f"{hat}virt-surv go{version_note} - {resolved_target}"))
    if repo and not demo:
        cfg = load_config(config_path())
        check_for_update_upfront(cfg, style, argparse.Namespace(repo=str(repo)))
    scripts_dir = (repo / "scripts") if repo else Path(__file__).resolve().parent / "scripts"
    launcher = scripts_dir / "virt_team_launcher.py"
    decision = ""
    if launcher.is_file():
        _, interpreter = _check_interpreters(
            ["python", "py", "python3"] if sys.platform == "win32" else ["python3", "python", "py"]
        )
        if interpreter:
            try:
                proc = subprocess.run(
                    [interpreter, str(launcher)],
                    cwd=resolved_target,
                    stdout=subprocess.PIPE,
                    encoding="utf-8",
                    errors="replace",
                    timeout=120,
                )
                decision = (proc.stdout or "").strip()
            except (OSError, subprocess.TimeoutExpired):
                decision = ""
    launch_cmd = detect_or_configure_claude_launch_command(style, mark_map)
    # The launcher's stdout IS the full pre-seeded prompt now, passed through verbatim
    # as one argument. History: 2026-08-15 the prefix was missing entirely (a bare
    # "--new" reached claude as a plain message); the fix hardcoded "/engage" here and
    # in the shell function - but bare /engage only exists in repo-as-project mode, so
    # every real plugin install then got "unknown command /engage" (live report
    # 2026-08-16). The run-mode-dependent spelling lives in the launcher's
    # _engage_command, computed per project at run time - never composed here.
    # Word-split like the v5 shell alias does: 'cc --resume' is a command plus a flag,
    # not one unresolvable word (the pre-split form failed shutil.which on any
    # multi-word command and would have execvp'd a literal 'cc --resume').
    cmd_parts = launch_cmd.split() or ["claude"]
    argv = cmd_parts + ([decision] if decision else [])
    if demo:
        print(style.dim(f"    would launch: {' '.join(argv)} (demo - nothing launched)"))
        return 0
    resolved_cmd = shutil.which(cmd_parts[0])
    if not resolved_cmd:
        print(
            style.yellow(
                f"  '{cmd_parts[0]}' isn't a real executable I can launch directly here "
                "(likely your own shell alias/function, not yet visible to this Python "
                "process) - type this yourself:"
            )
        )
        print(f"    {' '.join(argv)}")
        return 0
    print(style.dim(f"  Launching: {' '.join(argv)}"))
    if sys.platform == "win32":
        proc = subprocess.run([resolved_cmd] + argv[1:], cwd=resolved_target)
        return proc.returncode
    os.chdir(resolved_target)
    os.execvp(resolved_cmd, argv)  # replaces this process; never returns on success


def _dispatch_folder_subcommand(argv: list) -> Optional[int]:
    """Handles the 'virt-surv <subcommand> [dir] [--demo] [--yes]' positional form
    directly, bypassing parse_args() entirely for these words. Deliberately NOT
    folded into the main `mode` positional (install/update) - argparse `choices` there
    drives decide_mode() and the self-update re-exec helper, both already battle-tested;
    adding unrelated subcommands to that same positional risked touching either for no
    real benefit, given these subcommands need nothing parse_args already provides beyond
    an optional trailing path and the two flags handled explicitly below.

    --demo/--yes are scanned for anywhere in the remaining args (not assumed to be in a
    fixed position) - live-tested gap, 2026-08-04: bypassing parse_args() entirely meant
    a trailing '--demo' was previously silently dropped instead of either being honoured
    or erroring, which is exactly the kind of silent-wrong-behaviour this repo's own
    culture treats as a real defect.

    Returns an exit code if argv[0] matched one of these, else None (not a match - fall
    through to the normal parse_args flow)."""
    if not argv or argv[0] not in _FOLDER_SUBCOMMANDS:
        return None
    subcommand = argv[0]
    rest = argv[1:]
    demo = "--demo" in rest
    assume_yes = "--yes" in rest
    paths = [a for a in rest if a not in ("--demo", "--yes")]
    style = Style(supports_color())
    # Any OTHER dash-prefixed token (a typo, or a flag from the main parser that doesn't
    # apply here) used to be silently treated as the target directory - live report
    # (fable UX review, 2026-08-05): 'configure --branch dev' produced "not a directory:
    # <cwd>/--branch" instead of a clear "that flag isn't supported here" error.
    unknown_flags = [p for p in paths if p.startswith("-")]
    if unknown_flags:
        print(
            f"{marks()['fail']} unknown option {unknown_flags[0]!r} for '{subcommand}' "
            f"(supported: [DIR], --demo, --yes)"
        )
        return 1
    # A one-line Morgan strapline, not the full boxed banner - user request, 2026-08-05
    # ("make sure the install helper and virt-surv has a strapline from the Morgan
    # persona"): the interactive menu already opens with print_banner()'s box + Morgan's
    # intro line, but these folder-scoped 'virt-surv <subcommand>' calls went straight
    # into the action with no persona touch at all - a genuinely different, quieter
    # surface that the fast alias path exists specifically to keep quick, so the full
    # banner box would be too heavy here.
    hat = "🎩 " if _can_encode("🎩") else ""
    print(style.dim(f"{hat}Morgan here - virt-surv {subcommand}"))
    if subcommand == "setup-alias":
        return run_setup_alias(style, marks(), assume_yes, demo)
    target = Path(paths[0]) if paths else Path(".")
    if subcommand in ("go", "engage"):
        # 'engage' LAUNCHES, same as 'go' (2026-08-19 user ruling). It used to mean
        # project setup, which read as the exact opposite of /engage in a session and of
        # the go menu's own "start new" - three meanings for one word. Setup keeps the
        # word that actually describes it: 'onboard' (and 'configure').
        return _run_go(target, style, marks(), hat, demo)
    if subcommand == "configure":
        # Already set up? Go straight to the launcher's own settings editor - the same
        # screen `go`'s [c] opens (2026-08-19 user request: "configure should just
        # launch go and auto-select the configure option"). Only a project with no team
        # configuration yet gets the full guided first-time pass below.
        # sys.stdin.isatty(): the editor is an interactive screen, so a scripted or
        # piped `virt-surv configure` (CI, a test, `configure < /dev/null`) keeps the
        # old non-interactive run_configure path instead of spawning a UI that has
        # nobody to talk to - caught by the test suite hanging on exactly that.
        if _plugin_enabled_for_configure(target) and not demo and sys.stdin.isatty():
            rc = _run_launcher_settings(target, style)
            if rc is not None:
                return rc
        return run_configure(target, style, marks(), assume_yes, demo)
    if subcommand == "onboard":
        # 2026-08-07 user request: "applies all the project defaults without prompting
        # the user, tell them what's been set, and then says claude code ready to
        # launch" - assume_yes is ALWAYS True here regardless of whether --yes was
        # passed (that's the entire point of these subcommands over plain 'configure').
        # 'onboard' is a deliberate alias of 'engage', same behaviour, same code path -
        # project setup only (not the machine-level install), added because both names
        # read naturally depending on context ("onboard this project" / "engage").
        # --demo is still honoured, same as every other subcommand here.
        resolved_target = target.expanduser().resolve()
        warning = _project_root_warning(target)
        if warning:
            print(
                style.yellow(
                    f"  ! {resolved_target} - {warning}. If that's not intentional, "
                    "Ctrl-C and cd into your actual project root first."
                )
            )
        print(style.dim(f"  Setting up {resolved_target} as your project."))
        rc = run_configure(target, style, marks(), True, demo)
        if rc == 0 and not demo:
            print("")
            print(
                style.green(
                    f"{hat}Claude Code is ready to launch here - run `claude` from "
                    f"{resolved_target} and say hello."
                )
            )
            print(style.dim("   - Morgan"))
        return rc
    if subcommand == "evidence":
        # `virt-surv evidence [<workspace>]` - the Evidence Room without remembering a
        # module path. Bare form renders the ACTIVE engagement, which is what someone
        # standing in their project root means (2026-08-20).
        return _run_evidence_room(target, style, marks())
    if subcommand == "archive":
        return run_archive_engagements(target, style, marks(), demo)
    return run_list_engagements(target, style, marks())


def main(argv=None) -> int:
    """Entry point: _main plus the last-resort Ctrl-C net (menu, banner, prompts that
    sit outside an Installer run). Exit code 130 mirrors the shell convention."""
    try:
        dispatched = _dispatch_folder_subcommand(argv if argv is not None else sys.argv[1:])
        if dispatched is not None:
            return dispatched
        return _main(argv)
    except KeyboardInterrupt:
        print("")
        print("Cancelled.")
        return 130


def _main(argv=None) -> int:
    global run_cmd, _REPO_HINT
    args = parse_args(argv)
    # Remembered for every later caller that has no args of its own - chiefly
    # _import_from_scripts, which decides whether any tiered screen can be drawn at all.
    if args.repo:
        _REPO_HINT = str(args.repo)
    style = Style(supports_color())
    # --model only means anything paired with one of these two - live-caught (fable UX
    # review, 2026-08-05): `--model opus` alone was silently DISCARDED and fell through
    # to a full install (nothing in the scripting-path gate below even looks at
    # args.model on its own); and `--model-project DIR` WITHOUT --model silently reset
    # an existing opus setting to sonnet, since a missing args.model (None) and an
    # explicit `--model default` were indistinguishable downstream. Both are now errors
    # instead of a surprise action or a silent write.
    fail = marks()["fail"]
    if args.model is not None and not (args.model_project or args.model_default):
        print(
            f"{fail} --model needs --model-project DIR or --model-default "
            "(on its own it does nothing)"
        )
        return 1
    if (args.model_project or args.model_default) and args.model is None:
        print(
            f"{fail} --model-project/--model-default need --model opus|sonnet|sonnet-4-6|"
            "default (nothing written - say which one explicitly, including 'default' to reset)"
        )
        return 1
    if (
        args.enable_project
        or args.permissions
        or args.env_tuning
        or args.env_tuning_betas
        or args.model_project
        or args.model_default
        or args.check_tools
        or args.check_env
        or args.selftest
        or args.check_hook_latency
        or args.check_adr014_spike
        or args.check_daemon_start
        or args.code_intel
        or args.extensions
        or args.configure
        or args.archive
        or args.list_engagements
        or args.setup_alias
        or args.fix_bashrc
        or args.clean_plugin_cache
    ):
        # Scripting path: no banner, no menu.
        #
        # --demo gap (found in review, 2026-08-13): unlike --configure/--archive/
        # --setup-alias just below (which all thread args.demo through to their run_*
        # function), these six flags' run_* functions take no demo parameter at all, so
        # `--demo --permissions DIR` (etc.) used to silently perform the REAL write -
        # exactly the "nothing executed or written" promise --demo makes everywhere else,
        # broken here. Each is now gated explicitly at the call site instead - a preview
        # line, no write - rather than threading a new demo kwarg through run_permissions/
        # run_enable_project/run_orchestrator_model* (a larger change to those shared
        # functions' signatures for no behavioural gain here).
        rc = 0
        for target in args.enable_project or []:
            if args.demo:
                print(
                    style.dim(f"    would enable the plugin for {target} (demo - nothing written)")
                )
            else:
                rc = max(rc, run_enable_project(Path(target), style, marks()))
        if args.permissions:
            if args.demo:
                print(
                    style.dim(
                        f"    would add the recommended permission allow-list to "
                        f"{args.permissions} (demo - nothing written)"
                    )
                )
            else:
                rc = max(rc, run_permissions(Path(args.permissions), style, marks()))
        if args.env_tuning:
            if args.demo:
                print(
                    style.dim(
                        f"    would upsert the recommended tuning env vars into "
                        f"{args.env_tuning} (demo - nothing written)"
                    )
                )
            else:
                rc = max(rc, run_env_tuning(Path(args.env_tuning), style, marks()))
        if args.env_tuning_betas:
            if args.demo:
                print(
                    style.dim(
                        f"    would upsert the beta-fields-workaround env var into "
                        f"{args.env_tuning_betas} (demo - nothing written)"
                    )
                )
            else:
                rc = max(rc, run_env_tuning_betas(Path(args.env_tuning_betas), style, marks()))
        if args.model_project:
            if args.demo:
                print(
                    style.dim(
                        f"    would set Morgan's model for {args.model_project} "
                        "(demo - nothing written)"
                    )
                )
            else:
                wanted = None if (args.model or "default") == "default" else args.model
                rc = max(
                    rc, run_orchestrator_model(Path(args.model_project), wanted, style, marks())
                )
        if args.model_default:
            if args.demo:
                print(
                    style.dim(
                        "    would set Morgan's default model for new/unconfigured projects "
                        "(demo - nothing written)"
                    )
                )
            else:
                wanted = None if (args.model or "default") == "default" else args.model
                rc = max(rc, run_orchestrator_model_default(wanted, style, marks()))
        if args.check_tools:
            rc = max(rc, run_tool_check(style, marks()))
        if args.check_env:
            rc = max(rc, run_env_check(style, marks(), args.repo))
        if args.selftest:
            rc = max(rc, run_selftest(style, marks(), args.repo))
        if args.check_hook_latency:
            rc = max(rc, run_hook_latency_diagnostic(style, marks(), args.repo))
        if args.check_adr014_spike:
            spike_rc = run_adr014_smoke_test(style, marks(), args.repo)
            rc = max(rc, spike_rc if spike_rc is not None else 0)
        if args.check_daemon_start:
            rc = max(rc, run_daemon_start_diagnostic(style, marks(), args.repo))
        if args.code_intel:
            rc = max(rc, Installer(args, style, marks(), subset="codeintel").run() or 0)
        if args.extensions:
            rc = max(rc, run_install_extensions(args.extensions, style, marks()))
        if args.configure:
            rc = max(rc, run_configure(Path(args.configure), style, marks(), args.yes, args.demo))
        if args.archive:
            rc = max(rc, run_archive_engagements(Path(args.archive), style, marks(), args.demo))
        if args.list_engagements:
            rc = max(rc, run_list_engagements(Path(args.list_engagements), style, marks()))
        if args.setup_alias:
            rc = max(rc, run_setup_alias(style, marks(), args.yes, args.demo, args.repo))
        if args.fix_bashrc:
            rc = max(rc, run_fix_bashrc(style, marks(), args.yes, args.demo))
        if args.clean_plugin_cache:
            rc = max(rc, run_clean_plugin_cache(style, marks(), args.yes, args.demo))
        return rc

    if not args.demo:
        _relocate_if_running_inside_target_repo(args, argv)

    # The interactive menu draws the brand in its own frame, so printing it here as well
    # would put it somewhere the alternate screen immediately hides. Every other path -
    # --yes, a piped run, a direct --mode - has no frame and still gets it here.
    _menu_coming = args.mode is None and not args.yes and sys.stdin.isatty()
    if not (_menu_coming and app_tier_available()):
        print_banner(style)
    # Deliberately NOT gated on `not args.demo` (2026-08-04 fix, live-tested gap: --demo
    # used to skip straight to a fixed full-flow preview, never showing the menu at all -
    # so none of the newer options, including "Configure", could be previewed. Demo mode
    # now stays a property that flows THROUGH whichever menu choice is made, rather than
    # a separate mode that bypasses the menu entirely.
    if args.mode is None and not args.yes and sys.stdin.isatty():
        cfg = load_config(config_path())
        check_for_update_upfront(cfg, style, args)
        # Loops back to the top-level menu after EVERY action instead of exiting (user
        # request, 2026-08-04: "don't just quit, always return to main menu") - a real
        # terminal's input() blocks until the user types something, so this never spins;
        # see _menu_session's own docstring for why a SCRIPTED test fixture needs to feed
        # "q" once exhausted rather than an infinite "".
        # Tracked so quitting after a real action doesn't claim "nothing changed" -
        # live-caught (fable UX review, 2026-08-05): running Configure (which really
        # enabled the plugin and wrote files) then quitting printed exactly that,
        # readable as "your configuration was discarded". Never set for the one-shot
        # "demo" preview or a session-wide --demo run, both of which genuinely write
        # nothing regardless of which action was picked.
        did_anything = False
        # The worst status any action in this loop returned. The three actions that report
        # one used `rc` - the name the NON-INTERACTIVE flag block above uses, where it is
        # initialised - and inside this loop it is not, so picking any of them raised
        # UnboundLocalError before their function was even called (live report 2026-08-28,
        # against the Org extensions item). Named differently on purpose, so the two
        # scopes cannot be confused again.
        menu_rc = 0
        while True:
            action = choose_action(style)
            if action == "quit":
                if did_anything:
                    print("See you next time.")
                else:
                    print("No problem - nothing changed. See you next time.")
                return menu_rc
            # ONE MENU ITEM MUST NOT TAKE THE INSTALLER WITH IT.
            #
            # Nothing wrapped this dispatch and main() catches only Ctrl-C, so any
            # unhandled error in any action ended the whole session with a traceback -
            # someone who picked the wrong thing lost the menu, not just the action.
            # That was survivable while every action was old and well-worn; it stopped
            # being so when two of them started routing through a new module
            # (scripts/questions.py, 2026-08-30), which is a lot more new code in the
            # path than the five-line print/input fallback it replaced.
            #
            # CONTAINED, NOT CONCEALED, and the difference is the whole point. The
            # traceback is printed in full rather than swallowed, the exit code carries
            # the failure, and the user is told plainly which action broke. A quiet
            # `except Exception: pass` here would turn a crash into a menu item that
            # silently does nothing - which is the same "broken looks unavailable"
            # failure that hid the launcher's screens for a week, one level up.
            try:
                if action == "configure":
                    # Free-function flow with no need for Installer's clone-management
                    # state - handled directly here rather than added as an Installer subset.
                    target = _pick_project(style, "Which project?", "  Which project directory?")
                    if target is None:
                        continue  # they left - not "configure the current directory"
                    # THE SAME HANDOVER `virt-surv configure` DOES (2026-08-19), which this
                    # door skipped: an already-configured project gets the launcher's
                    # settings editor, and only a project with no team configuration yet
                    # gets the guided first-time pass. Same words and same intent on both
                    # doors, so they should not be two different experiences.
                    handed = None
                    if (
                        _plugin_enabled_for_configure(target)
                        and not args.demo
                        and sys.stdin.isatty()
                    ):
                        handed = _run_launcher_settings(target, style)
                    if handed is None:
                        run_configure(target, style, marks(), args.yes, args.demo)
                    did_anything = did_anything or not args.demo
                elif action == "aliasmanage":
                    run_alias_manage(style, marks(), args.yes, args.demo, args.repo)
                    did_anything = did_anything or not args.demo
                elif action == "howto":
                    run_howto(style)  # read-only narrative - never counts as "did anything"
                elif action == "extensions":
                    menu_rc = max(menu_rc, run_extensions_editor(style, marks()) or 0)
                    did_anything = did_anything or not args.demo
                elif action == "reprobe":
                    menu_rc = max(menu_rc, run_tool_reprobe(style, marks()) or 0)
                    did_anything = did_anything or not args.demo
                elif action == "relocate":
                    menu_rc = max(menu_rc, run_relocate_to_vsit(style, marks()) or 0)
                    did_anything = did_anything or not args.demo
                elif action == "gitbashperf":
                    run_gitbash_perf(style, marks(), args.yes, args.demo)
                    did_anything = did_anything or not args.demo
                elif action == "demo":
                    # A one-shot preview of the full flow, not a persistent toggle - restored
                    # afterward so picking "Demo" once doesn't silently keep every LATER menu
                    # choice in demo mode too, which would be a confusing sticky side effect.
                    print(
                        style.yellow(
                            "DEMO MODE - the full interactive run; nothing is executed or written."
                        )
                    )
                    saved_demo, args.demo = args.demo, True
                    saved_run_cmd = run_cmd
                    run_cmd = make_demo_runner(style)
                    try:
                        Installer(args, style, marks(), subset="full").run()
                    finally:
                        run_cmd = saved_run_cmd
                        args.demo = saved_demo
                else:
                    subset = "full" if action == "full" else action
                    if subset == "update" and not args.demo:
                        # In-app first (2026-08-29): picking update used to drop straight out
                        # of the picker into a scrolling step log - the interface the picker
                        # exists to replace. None means the screen could not run, and only
                        # then does the streaming Installer below take over.
                        in_app = run_update_in_app(args, style)
                        if in_app is not None:
                            did_anything = True
                            continue
                    elif subset in _IN_APP_SUBSETS and not args.demo:
                        # Same complaint, same fix (owner report + screenshot,
                        # 2026-08-30): picking Code intelligence from the picker dropped
                        # straight out to a scrolling step log, which is the interface
                        # the picker exists to replace.
                        in_app = run_subset_in_app(args, style, subset, _IN_APP_SUBSETS[subset])
                        if in_app is not None:
                            menu_rc = max(menu_rc, in_app or 0)
                            did_anything = True
                            continue
                    if args.demo:
                        print(
                            style.yellow(
                                "DEMO MODE - the full interactive run; nothing is executed or written."
                            )
                        )
                        saved_run_cmd = run_cmd
                        run_cmd = make_demo_runner(style)
                        try:
                            Installer(args, style, marks(), subset=subset).run()
                        finally:
                            run_cmd = saved_run_cmd
                    else:
                        Installer(args, style, marks(), subset=subset).run()
                    # Read-only diagnostics never change anything regardless of demo -
                    # "nothing changed" stays true after running one of these, unlike the
                    # write-capable subsets.
                    if subset not in (
                        "check",
                        "toolcheck",
                        "envcheck",
                        "selftest",
                        "hooklatency",
                        "adr014smoke",
                        "daemonstart",
                    ):
                        did_anything = did_anything or not args.demo
            except (KeyboardInterrupt, InstallAbort, SystemExit):
                raise  # these already mean something specific further up
            except Exception:
                import traceback

                print("")
                print(style.red(f"  That action failed: {action}"))
                print(style.dim("  The full error follows. Everything else still works -"))
                print(style.dim("  you are back at the menu, and nothing was half-done by"))
                print(style.dim("  this failure that was not already done before it."))
                print("")
                traceback.print_exc()
                print("")
                menu_rc = max(menu_rc, 1)

    subset = "full"
    if args.demo:
        print(style.yellow("DEMO MODE - the full interactive run; nothing is executed or written."))
        saved = run_cmd
        run_cmd = make_demo_runner(style)
        try:
            return Installer(args, style, marks(), subset=subset).run()
        finally:
            run_cmd = saved
    return Installer(args, style, marks(), subset=subset).run()


if __name__ == "__main__":
    sys.exit(main())
