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
  file's env block (every other env var and setting left untouched); `--model-project`/
  `--model-default` set Morgan's model. Each refuses on an unparseable settings file and
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
import os
import shutil
import subprocess  # fixed-argv calls to git/claude/pip, no shell  # nosec B404
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
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
RECOMMENDED_ENV = {
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
    return bool(getattr(stream, "isatty", lambda: False)())


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
    version = installed_version(Path(__file__).resolve().parent)
    if not version:
        repo = load_config(config_path()).get("repo_path")
        if isinstance(repo, str) and repo:
            version = installed_version(Path(repo))
    suffix = f"v{version}" if version else "(version shown after install)"
    return f"compliance-surveillance-team {suffix}"


def print_banner(style: Style, stream=None) -> None:
    """Boxed banner (tool name + version line) and Morgan's intro."""
    for row in render_banner([BANNER_TITLE, banner_version_line()], style, stream):
        print(row)
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
    except OSError:
        pass
    return None


def list_headlines_between(changelog_text, local_version: Optional[str]) -> list:
    """`## [x.y.z] ...` headline lines from the top of a changelog BODY down to (not
    including) the entry for local_version. A local version that never appears (or
    None) yields every headline - the caller caps the display. Pure and total: any
    input coerces via str() and the worst case is an empty list."""
    headlines = []
    for line in str(changelog_text).splitlines():
        if line.startswith("## ["):
            if local_version and line.startswith(f"## [{local_version}]"):
                break
            headlines.append(line[3:].strip())
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


def merge_statusline(settings: dict, command: str):
    """Set statusLine in a settings dict. Returns (settings, verdict):
    'added' (none existed), 'already' (identical command present, nothing to do),
    'ours-moved' (OUR statusline.sh at another path - e.g. an old clone location -
    updated in place without a scare prompt), or 'conflict' (a genuinely foreign
    statusLine - the caller must show it to the user and get explicit confirmation)."""
    current = settings.get("statusLine")
    if isinstance(current, dict) and current.get("command") == command:
        return settings, "already"
    if isinstance(current, dict) and "statusline.sh" in str(current.get("command", "")):
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


def _write_json_backup(path: Path, data: dict) -> None:
    """utf-8, trailing newline, .bak of any existing content first."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        backup = path.with_suffix(path.suffix + ".bak")
        backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


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

    st_path = claude_dir / "settings.json"
    st = _read_json_dict(st_path)
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


def _claude_via_npm_prefix() -> Optional[str]:
    """Ask npm where its prefix is, then look for claude under it. Covers custom
    corporate prefixes no hardcoded candidate list can know. Best-effort: npm absent,
    blocked or slow just returns None."""
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


def find_claude(refresh: bool = False) -> tuple:
    """Locate the Claude CLI even when this session's PATH is stale.

    Returns (absolute_path_or_None, how) with how in "path" | "known-location" |
    "registry" | "". Order: the live PATH, then the documented install locations
    (native installer, npm global), then - Windows only - directories from a fresh
    registry PATH read (catches 'installed a minute ago, terminal opened an hour
    ago'). Never raises."""
    global _claude_cache
    if _claude_cache is not None and not refresh:
        return _claude_cache
    result: tuple = (None, "")
    hit = shutil.which("claude")
    if hit:
        result = (hit, "path")
    else:
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
            try:
                if c.is_file():
                    result = (str(c), "known-location")
                    break
            except OSError:
                continue
        if result[0] is None:
            npm_hit = _claude_via_npm_prefix()
            if npm_hit:
                result = (npm_hit, "npm-prefix")
        if result[0] is None and sys.platform == "win32":
            for d in _windows_registry_path_dirs():
                found = next((p for n in names if (p := Path(d) / n) and _is_file_safe(p)), None)
                if found:
                    result = (str(found), "registry")
                    break
    _claude_cache = result
    return result


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
    log line, never a crash."""
    argv = [str(a) for a in argv]
    prefix = command_argv(argv[0])
    decode = {"encoding": "utf-8", "errors": "replace"}
    if prefix[0] == "cmd":
        # Batch shim: one explicit string, shell=False. This branch is unreachable on
        # POSIX (which() never resolves a bare name to *.cmd/*.bat there).
        return subprocess.run(  # fixed command line built above, shell=False  # nosec B603
            windows_shim_cmdline(prefix[-1], argv[1:]),
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            timeout=timeout,
            **decode,
        )
    return subprocess.run(  # argv is a fixed list built here, shell=False  # nosec B603
        prefix + argv[1:],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        timeout=timeout,
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

    return runner


# ------------------------------------------------------------------ pure git helpers


def validate_branch(branch: str) -> str:
    if branch not in BRANCHES:
        raise ValueError(f"branch must be one of {'/'.join(BRANCHES)}, not {branch!r}")
    return branch


def is_dirty(repo: Path, runner=None) -> bool:
    """True when `git status --porcelain` reports anything (staged, unstaged or untracked)."""
    runner = runner or run_cmd
    proc = runner(["git", "-C", repo, "status", "--porcelain"])
    if proc.returncode != 0:
        raise InstallAbort(f"git status failed in {repo}: {proc.stderr.strip()}")
    return bool(proc.stdout.strip())


def commits_ahead(repo: Path, branch: str, runner=None) -> int:
    """Local commits on HEAD that origin/<branch> does not have (0 on any lookup failure)."""
    runner = runner or run_cmd
    proc = runner(["git", "-C", repo, "rev-list", "--count", f"origin/{branch}..HEAD"])
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
    proc = probe(["git", "-C", repo, "rev-list", "--count", f"HEAD..origin/{branch}"])
    if proc is not None:
        try:
            info["behind"] = int(proc.stdout.strip())
        except (ValueError, TypeError, AttributeError):
            pass
    if info["behind"] is None:
        info["notes"].append("could not count new commits (shallow clone or detached HEAD?)")
    proc = probe(["git", "-C", repo, "show", f"origin/{branch}:.claude-plugin/plugin.json"])
    if proc is not None:
        info["remote_version"] = parse_manifest_version(proc.stdout)
    if info["remote_version"] is None:
        info["notes"].append("could not read the remote manifest")
    proc = probe(["git", "-C", repo, "show", f"origin/{branch}:CHANGELOG.md"])
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
        proc = run_cmd(["git", "-C", repo, "fetch", "origin", branch], timeout=8)
    except (subprocess.TimeoutExpired, OSError):
        return
    if proc is None or proc.returncode != 0:
        return
    local_version = installed_version(repo)
    preview = gather_update_preview(repo, branch, local_version)
    remote = preview.get("remote_version")
    if not remote or not local_version or remote == local_version:
        return
    print(style.yellow(f"📦 A newer version is available: {local_version} -> {remote}"))
    headline = (preview.get("headlines") or [None])[0]
    if headline:
        print(f"   {headline}")
    print(style.dim("   Pick option 1 to update, or Diagnostics (5) -> 1 to preview first."))
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


MENU_ACTIONS = {
    "1": "full",
    "2": "configure",
    "3": "manage",
    "4": "alias",
    "5": "diagnostics",
    "6": "advanced",
    "q": "quit",
}

# Submenus (2026-08-04 reorganisation - the top-level menu had grown to 10 flat numbered
# options and felt clunky; diagnostics/one-off settings now live one level down).
_DIAGNOSTICS_ACTIONS = {
    "1": "check",
    "2": "toolcheck",
    "3": "envcheck",
    "4": "selftest",
    "b": "back",
}
_ADVANCED_ACTIONS = {
    "1": "setup",
    "2": "statusline",
    "3": "formats",
    "4": "model",
    "5": "demo",
    "6": "machinedefaults",
    "b": "back",
}


def _choose_submenu(style: Style, title: str, options: tuple, actions: dict) -> Optional[str]:
    """Shared submenu loop: prints options, returns the resolved action string, or None
    if the user chose 'back' (caller should redraw the top-level menu)."""
    s = style
    print("")
    print(s.bold(title))
    for key, text in options:
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
        print(f"  1-{len(options) - 1} or b, please.")


def choose_action(style: Style) -> str:
    """The interactive front door: pick which subset to run. Callers gate on a tty;
    a closed stdin or empty answer takes the full run. 'diagnostics'/'advanced' open a
    submenu and loop back to this top-level menu on 'back' rather than returning
    directly - the caller only ever sees a final, concrete action."""
    s = style
    while True:
        print("")
        print(s.bold("What can I do for you?"))
        options = (
            ("1", "Install or update the team (this machine - full run, recommended)"),
            ("2", "Configure a project (per project - enable/permissions/preferences/model)"),
            ("3", "Manage engagements (per project - list / archive closed)"),
            ("4", "Set up the 'virt-surv' alias (this machine - run from any folder)"),
            ("5", "Diagnostics..."),
            ("6", "Advanced / one-off settings..."),
            ("q", "Quit"),
        )
        for key, text in options:
            print(f"  {s.cyan(key + ')')} {text}")
        # Redraws the menu on entering/re-entering this loop (fresh session, or back from
        # a submenu) but NOT on a simple invalid keystroke - an inner retry loop just
        # re-asks (2026-08-04 user request: "don't reprint entire menu, just the item
        # that the user is on"), matching how _choose_submenu already behaved.
        while True:
            try:
                answer = input(f"{s.cyan('  What shall it be?')} {s.bold('[1]')}: ").strip().lower()
            except EOFError:
                return "full"
            if not answer:
                return "full"
            if answer in MENU_ACTIONS:
                break
            print("  1-6 or q, please.")
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

    # ---- console helpers

    def say(self, text: str = "") -> None:
        print(text)

    def step_header(self, number: int, total: int, title: str) -> None:
        self.say("")
        self.say(rule_header(number, total, title, self.style))

    def step_ok(self, name: str, detail: str = "") -> None:
        self.tracker.record(name, "ok", detail)
        suffix = f" {self.style.dim('(' + detail + ')')}" if detail else ""
        self.say(f"  {self.style.green(self.marks['ok'])} {name}{suffix}")

    def step_skip(self, name: str, detail: str = "") -> None:
        self.tracker.record(name, "skip", detail)
        suffix = f" {self.style.dim('(' + detail + ')')}" if detail else ""
        self.say(f"  {self.style.yellow(self.marks['skip'])} {name}{suffix}")

    def step_fail(self, name: str, detail: str = "", fatal: bool = True) -> None:
        self.tracker.record(name, "fail", detail)
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
        proc = run_cmd(["git", "-C", repo, "fetch", "origin", self.branch], timeout=300)
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

        proc = run_cmd(["git", "-C", repo, "checkout", "-B", self.branch, f"origin/{self.branch}"])
        if proc.returncode != 0:
            self.step_fail("Checkout branch", proc.stderr.strip() or "git checkout failed")
        head = run_cmd(["git", "-C", repo, "rev-parse", "--short", "HEAD"])
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
            child_argv = _argv_from_args(self.args, repo=self.repo, branch=self.branch, mode=self.mode)
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
        cache = self.repo / ".claude" / ".guard-interpreter"
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
        proc = run_cmd(["git", "-C", repo, "fetch", "origin", branch], timeout=300)
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
        "go with defaults" (fast: dev requirements, status line and the 'virt-surv' alias
        are all wired with no further questions) or "manually configure" (walk through
        each one individually, exactly as this installer did before). --yes always
        implies the fast path (a scripted/CI run can't answer an interactive question),
        matching this installer's `--yes` semantics everywhere else."""
        if self.args.yes:
            self.quick_defaults = True
            return
        self.step_intro(
            "A few more optional bits follow: dev requirements, the status line, the "
            "'virt-surv' shell alias, and this machine's default settings."
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
            register_plugin_directly(self.repo, user_settings_path().parent, version)
        self.direct_registered = True
        self.step_ok(
            "Marketplace + plugin " + self.did("registered directly", "would register directly"),
            "restart Claude Code to load it",
        )

    def marketplace(self) -> None:
        self.step_intro("Pointing Claude Code's marketplace at your clone.")
        self.direct_registered = False
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
            if "group policy" in err.lower() or "blocked" in err.lower():
                self.say_claude_launch_trace()
                self.register_directly("the claude CLI launch is blocked by policy")
                return
            self.say_claude_launch_trace()
            self.step_fail("Add marketplace", err or "claude plugin marketplace add failed")
        self.step_ok(
            f"Marketplace {MARKETPLACE} " + self.did("->", "would point at") + f" {self.repo}"
        )

    def plugin(self) -> None:
        verb = "Updating" if self.mode == "update" else "Installing"
        self.step_intro(f"{verb} the team plugin from that marketplace.")
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
            if "group policy" in lowered or "blocked" in lowered:
                self.say_claude_launch_trace()
                self.register_directly("the claude CLI launch is blocked by policy")
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
            # 2026-08-07 user request: project-level setup is no longer part of this
            # default run - point at `virt-surv configure`, run FROM the project's own
            # root folder (the same folder you'll run `claude` from), instead.
            fallback = f"python {self.repo / 'install_helper.py'} --configure ." if self.repo else "install_helper.py --configure ."
            self.say(
                "  1. Set up a project: cd into its root folder - the same folder you'll "
                f"run `claude` from - and run 'virt-surv configure' (or '{fallback}' if "
                "you skipped the alias above) to review or change the defaults "
                "(citations, review-split, docx, codebase-map skeleton, tuned env vars, "
                "permissions, Morgan's model). Or 'virt-surv engage' (or 'virt-surv "
                "onboard' - same thing) to apply every default with zero prompts and go "
                "straight to launching claude."
            )
            self.say("  2. Restart Claude Code to load the new version.")
        self.say("")
        # The celebratory "summon the team" close is only accurate for a full/setup run
        # that actually finished clean - live-caught (fable UX review, 2026-08-05): a
        # failed-but-non-fatal step (e.g. "no usable clone found" in a diagnostic) still
        # left `aborted` False, so this printed regardless, inviting the user to summon
        # a team that was just reported as not working. Diagnostics/one-off subsets get
        # a plain close instead - they were never "installing the team" to begin with.
        any_failed = any(status == "fail" for _name, status, _detail in self.tracker.steps)
        if self.subset in ("full", "setup") and not any_failed:
            self.say(s.green("Done. Summon the team with /compliance-surveillance-team:engage"))
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
            keep = confirm(
                "  Shall I replace it with the team's status line?",
                default=False,
                assume_yes=self.args.yes,
                style=self.style,
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
        target.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
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
            self.step_skip("Alias setup", "skipped - python install_helper.py --setup-alias any time")
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
            "projects you configure later. (The large-context review-split and "
            "codebase-skeleton drift-checking preferences aren't asked here - they're "
            "set via 'Configure a project' instead.)"
        )
        raw = ask(f"  Which project directory? (blank = {Path.cwd()})", ".", False, style=self.style)
        project = Path(raw).expanduser().resolve()
        if not project.is_dir():
            self.step_fail("Project preferences", f"not a directory: {project}")
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
        docx_wanted = confirm(
            "  Produce .docx by default for controlled documents in this project?",
            default=docx_current,
            assume_yes=False,
            style=self.style,
        )
        citations_wanted = confirm(
            "  Detection-logic work in this project cites regulatory obligations by "
            "default - keep that on?",
            default=citations_current,
            assume_yes=False,
            style=self.style,
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
        save_as_default = confirm(
            f"  You just set {summary} for {project.name}. Also make THESE SAME "
            "choices this machine's default whenever you configure a DIFFERENT, new "
            "project later (not this one, which is already set above)?",
            default=False,
            assume_yes=False,
            style=self.style,
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

    def machine_defaults_offer(self) -> None:
        """Last of the optional post-install steps for a full install/update (2026-08-07
        user request: "we are missing an option to be able to modify settings on install
        too" - project-level setup moved entirely to virt-surv configure/engage, but
        THIS MACHINE's own defaults deserve a way back in during install instead of only
        being reachable via the separate Advanced -> Machine defaults menu item).
        Always asks (never auto-applied by quick_defaults - changing what every future
        project inherits is a deliberate action, not a "no real downside" default like
        the status line or the alias) unless --yes, matching machine_defaults_step's own
        interactive-only nature."""
        if self.args.yes:
            self.step_skip(
                "Machine defaults",
                "non-interactive - Advanced -> Machine defaults any time, or edit "
                f"{self.cfg_path} directly",
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
        docx_current = bool(self.cfg.get("default_docx", False))
        citations_current = bool(self.cfg.get("default_regulatory_citations", False))
        review_tools_current = self.cfg.get("default_review_tools") or {}
        map_skeleton_current = bool(self.cfg.get("default_map_skeleton", True))
        statusline_show_map_current = bool(self.cfg.get("default_statusline_show_map", False))
        model_current = _read_json_dict(user_settings_path()).get("model")
        self.say(
            self.style.dim(
                f"    currently: docx by default = {'on' if docx_current else 'off'}, "
                f"regulatory citations = {'on' if citations_current else 'off'}, "
                f"review-tools = {review_tools_current or '(all auto)'}, "
                f"codebase-skeleton drift checking = {'on' if map_skeleton_current else 'off'}, "
                f"statusline map indicator = {'on' if statusline_show_map_current else 'off'}, "
                f"Morgan's model = {model_current or f'(unset - {ORCHESTRATOR_MODEL_DEFAULT} applies)'}"
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
            "  New projects get codebase-skeleton drift checking (MAP-DRIFT/"
            "MAP-DEAD-POINTER) by default - experimental, ADR-007 Phase 1?",
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
        summary = (
            f"docx={'on' if docx_wanted else 'off'}, "
            f"citations={'on' if citations_wanted else 'off'}, "
            f"review-tools={_format_review_tools(review_tools_wanted)}, "
            f"map-skeleton={'on' if map_skeleton_wanted else 'off'}, "
            f"statusline-map={'on' if statusline_show_map_wanted else 'off'}, "
            f"model={model_wanted or 'default'}"
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
        ):
            self.step_ok("Machine defaults", "unchanged")
            return
        self.cfg["default_docx"] = docx_wanted
        self.cfg["default_regulatory_citations"] = citations_wanted
        self.cfg["default_review_tools"] = review_tools_wanted
        self.cfg["default_map_skeleton"] = map_skeleton_wanted
        self.cfg["default_statusline_show_map"] = statusline_show_map_wanted
        save_config(self.cfg_path, self.cfg)
        self.step_ok("Machine defaults", f"{summary} ({self.cfg_path})")

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
        raw = ask(f"  Which project directory? (blank = {Path.cwd()})", ".", False, style=self.style)
        project = Path(raw).expanduser().resolve()
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

    def enable_step(self) -> None:
        """Optional: enable the team for a project right now, and offer the recommended
        permission allow-list for the same project. Interactive only - non-interactive
        runs use the --enable-project / --permissions flags. In demo the directory check
        stays real but nothing is executed or written."""
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
                    "later: run /plugin inside Claude Code from the project",
                )
                return
        raw = ask(f"  Which project directory? (blank = {Path.cwd()})", ".", False, style=self.style)
        target = Path(raw)
        if self.demo:
            project = target.expanduser().resolve()
            if not project.is_dir():
                self.step_fail("Project enablement", f"not a directory: {project}", fatal=False)
                return
            run_cmd(["claude", "plugin", "enable", "--scope", "project", PLUGIN_ID], cwd=project)
            self.step_ok("Project enablement", f"would enable for {project}")
            if confirm(
                "  Shall I also add the recommended permission allow-list (fewer prompts)?",
                default=True,
                assume_yes=False,
                style=self.style,
            ):
                self._demo_permissions(project)
            if confirm(
                "  Also tune API timeout / stream-idle / output-size env vars for this "
                "project (helps on slow networks or behind a corporate proxy)?",
                default=True,
                assume_yes=False,
                style=self.style,
            ):
                self.say(
                    self.style.dim(
                        f"    would upsert {len(RECOMMENDED_ENV)} env vars into "
                        f"{project / '.claude' / 'settings.json'} (other env vars untouched)"
                    )
                )
            if confirm(
                "  Controlled documents (BRD, FSD, etc.) always get .md + .html - also "
                "produce a Word (.docx) copy by default, for reviewers who redline in Word?",
                default=bool(self.cfg.get("default_docx", False)),
                assume_yes=False,
                style=self.style,
            ):
                self.say(
                    self.style.dim(
                        f"    would write {project / '.claude' / 'team-preferences.json'}"
                    )
                )
            if confirm(
                "  Set Morgan's (the orchestrator's) model for this project too - sonnet is "
                "the documented default (testing to date hasn't shown opus outperforming it "
                "for orchestration); want to set opus instead for this project?",
                default=False,
                assume_yes=False,
                style=self.style,
            ):
                _, message = ask_and_set_model(project, self.style, self.args.yes, self.demo)
                self.say(self.style.dim(f"    {message}"))
            return
        if run_enable_project(target, self.style, self.marks) == 0:
            self.step_ok("Project enablement", str(target.expanduser().resolve()))
            if confirm(
                "  Shall I also add the recommended permission allow-list (fewer prompts)?",
                default=True,
                assume_yes=False,
                style=self.style,
            ):
                run_permissions(target, self.style, self.marks)
            if confirm(
                "  Also tune API timeout / stream-idle / output-size env vars for this "
                "project (helps on slow networks or behind a corporate proxy)?",
                default=True,
                assume_yes=False,
                style=self.style,
            ):
                run_env_tuning(target.expanduser().resolve(), self.style, self.marks)
            if confirm(
                "  Controlled documents (BRD, FSD, etc.) always get .md + .html - also "
                "produce a Word (.docx) copy by default, for reviewers who redline in Word?",
                default=bool(self.cfg.get("default_docx", False)),
                assume_yes=False,
                style=self.style,
            ):
                write_team_preferences(
                    target.expanduser().resolve(),
                    extra_formats=["docx"],
                    regulatory_citations=self.cfg.get("default_regulatory_citations"),
                )
            if confirm(
                "  Set Morgan's (the orchestrator's) model for this project too - sonnet is "
                "the documented default (testing to date hasn't shown opus outperforming it "
                "for orchestration); want to set opus instead for this project?",
                default=False,
                assume_yes=False,
                style=self.style,
            ):
                ok, message = ask_and_set_model(
                    target.expanduser().resolve(), self.style, self.args.yes, self.demo
                )
                if ok:
                    self.say(self.style.dim(f"    {message}"))
                else:
                    self.say(self.style.yellow(f"    {message}"))
        else:
            self.step_fail("Project enablement", "see message above", fatal=False)

    def _demo_permissions(self, project: Path) -> None:
        """Dry-run twin of run_permissions: read the real settings file (read-only) to
        count what a real run would add; on an unreadable file, report the upper bound."""
        target = project / ".claude" / "settings.json"
        count = str(len(RECOMMENDED_ALLOW))
        if target.is_file():
            count = f"up to {len(RECOMMENDED_ALLOW)}"
            try:
                settings = json.loads(target.read_text(encoding="utf-8-sig"))
                if isinstance(settings, dict):
                    _, added = merge_allow(settings)  # throwaway copy, nothing written
                    count = str(len(added))
            except (OSError, ValueError, InstallAbort):
                pass
        self.say(
            self.style.dim(
                f"    would add {count} allow entries to {target} "
                "(add-only; deny rules and hooks untouched)"
            )
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
                ("Claude Code marketplace", self.marketplace),
                (
                    lambda: "Plugin " + ("update" if self.mode == "update" else "install"),
                    self.plugin,
                ),
                ("Status line (optional)", self.statusline_step),
                ("Enable for a project (optional)", self.enable_step),
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
        return [
            ("Preflight checks", self.preflight),
            ("Release channel", self.choose_branch),
            ("Local clone", self.resolve_repo),
            (lambda: f"Sync to origin/{self.branch}", self.sync_branch),
            ("Guard interpreter cache", self.prewarm_guard_cache),
            ("Quick setup or manual?", self.quick_setup_choice),
            ("Optional pip requirements", self.optional_pip),
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
    try:
        settings, added = merge_allow(settings)
    except InstallAbort as exc:
        print(f"{fail} {exc}")
        return 1
    if not added:
        print(f"{ok} {target}: all {len(RECOMMENDED_ALLOW)} recommended entries already present")
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
    target.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    print(
        f"{ok} {target}: added {len(added)} allow entr{'y' if len(added) == 1 else 'ies'} (add-only; deny rules and hooks untouched)"
    )
    print(style.dim("    Inspect any time with /permissions inside Claude Code."))
    return 0


def run_env_tuning(project_dir: Path, style: Style, mark_map: dict) -> int:
    """Standalone opt-in step: upsert RECOMMENDED_ENV into <project>/.claude/settings.json's
    "env" block - project-level only. Feasible and sufficient: Claude Code layers a
    settings-file "env" value over the shell's own (Environment variables doc, "Precedence"),
    so writing it once at project level covers both Linux and PowerShell shells without a
    platform-specific shell-profile edit; there is deliberately no user-level equivalent here
    (unlike the model-default flow) since these are per-project network/output-size tuning
    values, not an account-wide preference.

    Upsert, not add-only (unlike run_permissions): a key in RECOMMENDED_ENV already present
    with a DIFFERENT value is corrected; any other env var already in the file, and every other
    top-level key (permissions, hooks, model, ...), is left untouched. Dated backup of any
    existing file before writing, same as run_permissions; refuses on unparseable JSON rather
    than clobbering."""
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
        settings, added, updated = merge_env(settings)
    except InstallAbort as exc:
        print(f"{fail} {exc}")
        return 1
    if not added and not updated:
        print(f"{ok} {target}: all {len(RECOMMENDED_ENV)} tuning env vars already set correctly")
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
    target.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    bits = []
    if added:
        bits.append(f"added {len(added)}")
    if updated:
        bits.append(f"updated {len(updated)}")
    total = len(added) + len(updated)
    print(
        f"{ok} {target}: {', '.join(bits)} tuning env var{'s' if total != 1 else ''} "
        "(other env vars and settings untouched)"
    )
    return 0


def run_orchestrator_model(project_dir: Path, model: Optional[str], style: Style, mark_map: dict) -> int:
    """Standalone opt-in step: set or reset Morgan's model for one project. Human-run by
    definition (this script is a terminal tool) - Claude Code itself blocks the model from
    writing settings.json (ADR-002)."""
    ok, fail = mark_map["ok"], mark_map["fail"]
    project = project_dir.expanduser().resolve()
    if not project.is_dir():
        print(f"{fail} not a directory: {project}")
        return 1
    if model is not None and model not in ORCHESTRATOR_MODELS:
        print(f"{fail} model must be one of {ORCHESTRATOR_MODELS} or omitted (reset), not {model!r}")
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
        print(f"{fail} model must be one of {ORCHESTRATOR_MODELS} or omitted (clear), not {model!r}")
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


def _ask_review_tool_overrides(style: Style, assume_yes: bool, current: dict) -> dict:
    """One compact prompt for the seven-tool on/off/auto overrides instead of seven
    separate confirm()s - most sessions change zero or one tool, not all seven. Returns
    the full resulting {tool: state} dict (existing overrides plus this prompt's changes,
    with any tool explicitly reset to "auto" removed) - callers write the return value
    straight back via write_team_preferences(review_tools=...)."""
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
    map_skeleton: Optional[bool] = None,
    statusline_show_map: Optional[bool] = None,
    review_tools: Optional[dict] = None,
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
        if map_skeleton is not None:
            prefs["map_skeleton"] = bool(map_skeleton)
        if statusline_show_map is not None:
            prefs["statusline_show_map"] = bool(statusline_show_map)
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
        target.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
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
    global_default = (
        offer_global_scope
        and confirm(
            "  Also make this the default for new/unconfigured projects, not just this one?",
            default=False,
            assume_yes=assume_yes,
            style=style,
        )
    )
    picked = (
        ask(
            "  opus / sonnet / sonnet-4-6 / default (reset to sonnet)?",
            "default",
            assume_yes,
            style=style,
        )
        .strip()
        .lower()
    )
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
    hang never happens. Best-effort: never fails project enablement."""
    try:
        cache = project / ".claude" / ".guard-interpreter"
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(sys.executable, encoding="utf-8")
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
    try:
        target = project / ".claude" / "settings.json"
        settings = _read_json_dict(target)
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
    print(style.bold(f"Configuring {project}" + (" (DEMO - nothing will be written)" if demo else "")))
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

    print(style.dim("\n  Enable the plugin:"))
    if demo:
        print(style.dim(f"    would enable for {project}"))
    else:
        rc = max(rc, run_enable_project(project, style, mark_map))

    if confirm(
        "\n  Add the recommended permission allow-list (fewer prompts)?",
        default=True,
        assume_yes=assume_yes,
        style=style,
    ):
        if demo:
            print(style.dim(f"    would add up to {len(RECOMMENDED_ALLOW)} allow entries"))
        else:
            rc = max(rc, run_permissions(project, style, mark_map))

    if confirm(
        "\n  Tune API timeout / stream-idle / output-size env vars (helps on slow "
        "networks or behind a corporate proxy)?",
        default=True,
        assume_yes=assume_yes,
        style=style,
    ):
        if demo:
            print(style.dim(f"    would upsert {len(RECOMMENDED_ENV)} tuning env vars"))
        else:
            rc = max(rc, run_env_tuning(project, style, mark_map))

    print(style.dim("\n  Project preferences:"))
    existing = _read_json_dict(project / ".claude" / "team-preferences.json")
    machine_defaults = load_config(config_path())
    (
        docx_current,
        citations_current,
        review_tools_current,
        map_skeleton_current,
        statusline_show_map_current,
    ) = _project_preference_defaults(existing, machine_defaults)
    # Built-in default True (2026-08-07 user request: "split on") - large_context_review_split
    # deliberately has no machine-wide tier (see write_team_preferences' own docstring), so this
    # literal is its only fallback.
    split_current = existing.get("large_context_review_split", True)
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
    split_wanted = confirm(
        "  Split large, multi-component reviews by component from the start (useful "
        "behind a corporate proxy that times out on large requests)?",
        default=split_current,
        assume_yes=assume_yes,
        style=style,
    )
    map_skeleton_wanted = confirm(
        "  Enable codebase-skeleton drift checking (MAP-DRIFT/MAP-DEAD-POINTER) for a "
        "codebase map with a Paths column - experimental, ADR-007 Phase 1, off by "
        "default?",
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
        f"map-skeleton={'on' if map_skeleton_wanted else 'off'}, "
        f"statusline-map={'on' if statusline_show_map_wanted else 'off'}, "
        f"review-tools={_format_review_tools(review_tools_wanted)}"
    )
    if demo:
        print(style.dim(f"    would write preferences: {summary}"))
    elif write_team_preferences(
        project,
        extra_formats=["docx"] if docx_wanted else [],
        regulatory_citations=citations_wanted,
        large_context_review_split=split_wanted,
        map_skeleton=map_skeleton_wanted,
        statusline_show_map=statusline_show_map_wanted,
        review_tools=review_tools_wanted,
    ):
        print(f"  {ok} preferences: {summary}")
    else:
        print(f"  {fail} could not write team-preferences.json")
        rc = 1

    print(style.dim("\n  Refreshing the analyser-availability cache:"))
    rc = max(rc, run_tool_cache_refresh(project, style, mark_map, demo=demo))

    if confirm(
        "\n  Set Morgan's model for this project (default: sonnet)?",
        default=False,
        assume_yes=assume_yes,
        style=style,
    ):
        ok_model, message = ask_and_set_model(project, style, assume_yes, demo=demo)
        print(f"  {ok if ok_model else fail} {message}")
        rc = max(rc, 0 if ok_model else 1)

    print("")
    if rc == 0:
        print(style.dim(f"Configuration complete for {project}."))
    else:
        print(style.yellow("Configuration finished with issues - see above."))
    return rc


def _engagement_state_script() -> Optional[Path]:
    """Locates scripts/engagement_state.py relative to THIS clone - install_helper.py
    always sits at the clone's own repo root, next to scripts/, so no plugin-root
    discovery is needed here (unlike find_plugin_root.py's problem, which is specifically
    about locating things from an ARBITRARY foreign project directory)."""
    candidate = Path(__file__).resolve().parent / "scripts" / "engagement_state.py"
    return candidate if candidate.is_file() else None


def _review_tools_script() -> Optional[Path]:
    """Locates scripts/check-review-tools.sh relative to THIS clone - same rationale as
    _engagement_state_script()."""
    candidate = Path(__file__).resolve().parent / "scripts" / "check-review-tools.sh"
    return candidate if candidate.is_file() else None


def run_tool_cache_refresh(project_dir: Path, style: Style, mark_map: dict, demo: bool = False) -> int:
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
        print(f"{fail} no bash found (needed for check-review-tools.sh) - analyser-cache refresh skipped")
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
    print(f"{ok} analyser-availability cache refreshed ({project / '.claude' / '.tool-availability'})")
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
            text=True,
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
            text=True,
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
                    text=True,
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


def _verify_alias_line(label: str, rc_path: Path, line: str) -> tuple:
    """Runs the JUST-WRITTEN alias/function definition in isolation - not the whole rc
    file, whose unrelated content is out of scope and risky to execute - and confirms
    'virt-surv' actually resolves. Catches a syntax/quoting mistake (or, on Windows, an
    execution-policy block) immediately instead of only when the user opens a new
    terminal and it silently doesn't work (2026-08-04 user request: "harden the alias
    creation ... include test of the alias"). Best-effort: if the shell needed to verify
    isn't itself available, that's reported as a note, not a failure - the line was
    still written correctly as far as this process can tell."""
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
            f"{line}; Get-Command {_ALIAS_MARKER} -ErrorAction Stop | Out-Null",
        ]
    else:
        bash = find_bash()
        if not bash:
            return (True, "bash not found - could not verify, but the line was written")
        # expand_aliases is OFF by default in non-interactive bash (bash -c), so a plain
        # `alias virt-surv=...; type virt-surv` would falsely report "not found" even for
        # a perfectly correct alias line - must be enabled explicitly first.
        cmd = [bash, "-c", f"shopt -s expand_aliases\n{line}\ntype {_ALIAS_MARKER} >/dev/null"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
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
    alias_step)."""
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
    wrote_any = False
    had_error = False
    for label, rc_path in targets:
        if rc_path.suffix == ".ps1":
            line = f'function {_ALIAS_MARKER} {{ {interpreter} "{script_path}" @args }}'
        else:
            line = f'alias {_ALIAS_MARKER}=\'{interpreter} "{script_path}"\''
        existing = rc_path.read_text(encoding="utf-8", errors="replace") if rc_path.is_file() else ""
        if _ALIAS_MARKER in existing:
            print(f"{style.dim('-')} {label} ({rc_path}): a '{_ALIAS_MARKER}' entry already exists, skipped")
            continue
        print(f"  Would add to {label} ({rc_path}):")
        print(style.dim(f"    {line}"))
        if demo:
            print(style.dim("    (demo mode - nothing written)"))
            continue
        # Defaults to declining when the warning above just said this target "may be
        # temporary" - live-caught (fable UX review, 2026-08-05): the confirm defaulted
        # to Yes regardless, so pressing Enter wrote exactly the alias the warning had
        # just advised against.
        if not confirm("  Add it?", default=bool(resolved), assume_yes=assume_yes, style=style):
            print(f"{style.dim('-')} {label}: skipped")
            continue
        try:
            rc_path.parent.mkdir(parents=True, exist_ok=True)
            with rc_path.open("a", encoding="utf-8") as fh:
                if existing and not existing.endswith("\n"):
                    fh.write("\n")
                fh.write(f"\n# Added by install_helper.py --setup-alias (2026-08-04)\n{line}\n")
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
        print(
            style.dim(
                "\nA new terminal picks this up automatically. To use it in THIS "
                "session instead: POSIX shells - `source` your rc file (e.g. `source "
                "~/.bashrc`); PowerShell - `. $PROFILE` (PowerShell does not auto-reload "
                "its profile mid-session). Then: cd into your PROJECT's root folder (the "
                "same folder you'll run `claude` from) and run 'virt-surv configure' "
                "(asks, recommended defaults pre-filled), 'virt-surv engage' or 'virt-surv "
                "onboard' (same thing - applies every default with zero prompts, then "
                "tells you to launch claude), 'virt-surv archive', or 'virt-surv "
                "list-engagements'."
            )
        )
    return 1 if had_error else 0


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
    ("gitleaks", ["detect", "--no-git", "--no-banner", "--log-level", "error", "--source"], "dir", 20),
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
            proc = runner(argv, capture_output=True, text=True, cwd=tmpdir, timeout=per_call_timeout)
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
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            rows.append((name, "ERROR", f"failed to launch: {exc}"))
            continue
        if proc.returncode != 0:
            rows.append((name, "ERROR", f"exit {proc.returncode}: {(proc.stderr or '').strip()[:100]}"))
            continue
        version = proc.stdout.strip()
        try:
            major, minor = (int(p) for p in version.split(".")[:2])
        except ValueError:
            rows.append((name, "ERROR", f"unparseable version output: {version!r}"))
            continue
        if (major, minor) < (3, 9):
            rows.append((name, "ERROR", f"Python {version} - below the 3.9 floor the guards require"))
            continue
        rows.append((name, "OK", f"Python {version} at {path}"))
        if not winner:
            winner = name
    return rows, winner


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
        return ("ERROR", f"exit {proc.returncode}: {(proc.stderr or b'').decode('utf-8', 'replace')[:150]}")
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
            text=True,
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
        return [("repo script syntax", "ERROR", f"could not parse checker output: {proc.stdout[:200]}")]
    if not bad:
        return [("repo script syntax", "OK", f"{len(targets)} file(s) compile cleanly")]
    rows = [
        ("repo script syntax", "ERROR", f"{len(bad)}/{len(targets)} file(s) fail to compile")
    ]
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
        ("Bash (raw-data/code-exec/redirects)", {"tool_name": "Bash", "tool_input": {"command": "echo hello"}, "cwd": str(tmpdir)}),
        ("Write (consent-write/findings-pack)", {"tool_name": "Write", "tool_input": {"file_path": str(harmless), "content": "hello"}}),
        ("Read (raw-data/document-redirect)", {"tool_name": "Read", "tool_input": {"file_path": str(harmless)}}),
    )
    rows = []
    for label, payload in payloads:
        try:
            proc = subprocess.run(
                [interpreter, str(dispatcher)],
                input=json.dumps(payload),
                capture_output=True,
                text=True,
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
                (label, "ERROR", f"blocked a harmless action (exit {proc.returncode}): {(proc.stderr or '').strip()[:150]}")
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
                text=True,
                timeout=15,
            )
            if proc.returncode == 0:
                rows.append(("AskUserQuestion (locked-menu guard)", "OK", "clean pass-through"))
            else:
                rows.append(
                    ("AskUserQuestion (locked-menu guard)", "ERROR", (proc.stderr or "").strip()[:150])
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
                    ["bandit", "-q", str(target)], capture_output=True, text=True, timeout=20
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
                    first_line = combined.strip().splitlines()[0] if combined.strip() else "(no output)"
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
                        "planted issue NOT detected - bandit ran but its ruleset/config "
                        "may be off",
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
                proc = subprocess.run(argv, cwd=project, capture_output=True, text=True, timeout=30)
            except (OSError, subprocess.TimeoutExpired) as exc:
                return (label, "ERROR", f"failed to run: {exc}", None)
            combined = (proc.stdout or "") + (proc.stderr or "")
            if extra_check:
                passed, note = extra_check(proc, combined)
            else:
                passed, note = proc.returncode == 0, (
                    "clean" if proc.returncode == 0 else f"exit {proc.returncode}"
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
        data_dir = project / "artifacts" / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        pack_path = data_dir / f"findings-{slug}.json"
        pack_path.write_text(json.dumps(_selftest_findings_pack(slug), indent=2), encoding="utf-8")
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
    print(style.dim("  No LLM/Claude Code invocation - stdlib + the team's own scripts, no network."))

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
            print(style.yellow(f"{len(bad)} issue(s) found, and the debug bundle could not be written: {exc}"))
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
    return parser.parse_args(argv)


def _argv_from_args(args: argparse.Namespace, repo: Path, branch: str, mode: Optional[str] = None) -> list:
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


_FOLDER_SUBCOMMANDS = ("configure", "engage", "onboard", "archive", "list-engagements", "setup-alias")


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
    if subcommand == "configure":
        return run_configure(target, style, marks(), assume_yes, demo)
    if subcommand in ("engage", "onboard"):
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
    global run_cmd
    args = parse_args(argv)
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
        or args.model_project
        or args.model_default
        or args.check_tools
        or args.check_env
        or args.selftest
        or args.configure
        or args.archive
        or args.list_engagements
        or args.setup_alias
    ):
        # Scripting path: no banner, no menu.
        rc = 0
        for target in args.enable_project or []:
            rc = max(rc, run_enable_project(Path(target), style, marks()))
        if args.permissions:
            rc = max(rc, run_permissions(Path(args.permissions), style, marks()))
        if args.env_tuning:
            rc = max(rc, run_env_tuning(Path(args.env_tuning), style, marks()))
        if args.model_project:
            wanted = None if (args.model or "default") == "default" else args.model
            rc = max(rc, run_orchestrator_model(Path(args.model_project), wanted, style, marks()))
        if args.model_default:
            wanted = None if (args.model or "default") == "default" else args.model
            rc = max(rc, run_orchestrator_model_default(wanted, style, marks()))
        if args.check_tools:
            rc = max(rc, run_tool_check(style, marks()))
        if args.check_env:
            rc = max(rc, run_env_check(style, marks(), args.repo))
        if args.selftest:
            rc = max(rc, run_selftest(style, marks(), args.repo))
        if args.configure:
            rc = max(rc, run_configure(Path(args.configure), style, marks(), args.yes, args.demo))
        if args.archive:
            rc = max(rc, run_archive_engagements(Path(args.archive), style, marks(), args.demo))
        if args.list_engagements:
            rc = max(rc, run_list_engagements(Path(args.list_engagements), style, marks()))
        if args.setup_alias:
            rc = max(rc, run_setup_alias(style, marks(), args.yes, args.demo, args.repo))
        return rc

    if not args.demo:
        _relocate_if_running_inside_target_repo(args, argv)

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
        while True:
            action = choose_action(style)
            if action == "quit":
                if did_anything:
                    print("See you next time.")
                else:
                    print("No problem - nothing changed. See you next time.")
                return 0
            if action in ("configure", "manage"):
                # Free-function flows with no need for Installer's clone-management
                # state - handled directly here rather than added as Installer subsets.
                raw = ask("  Which project directory?", ".", False, style=style)
                target = Path(raw)
                if action == "configure":
                    run_configure(target, style, marks(), args.yes, args.demo)
                else:
                    run_manage_engagements(target, style, marks(), args.yes, args.demo)
                did_anything = did_anything or not args.demo
            elif action == "alias":
                run_setup_alias(style, marks(), args.yes, args.demo, args.repo)
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
                if subset not in ("check", "toolcheck", "envcheck", "selftest"):
                    did_anything = did_anything or not args.demo

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
