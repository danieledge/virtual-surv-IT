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
  human actions - the summary lists them as reminders instead). The ONE settings write it
  can do is explicit opt-in: `--permissions <project-dir>` merges the README's recommended
  permissions.allow entries into that project's .claude/settings.json - add-only (nothing
  is removed or overwritten, deny/hooks untouched), the existing file is backed up first,
  and an unparseable settings file makes it refuse. Because you run this helper yourself,
  that write is a human act (ADR-002 rec 5 governs the model, which stays blocked).
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
    "Bash(semgrep *)",
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
    branch = branch if branch in BRANCHES else "main"
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
    print(style.dim("   Pick option 1 to update, or 5 to preview first."))
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
    "2": "setup",
    "3": "statusline",
    "4": "enable",
    "5": "check",
    "6": "formats",
    "7": "demo",
    "q": "quit",
}


def choose_action(style: Style) -> str:
    """The interactive front door: pick which subset to run. Callers gate on a tty;
    a closed stdin or empty answer takes the full run."""
    s = style
    print("")
    print(s.bold("What can I do for you?"))
    options = (
        ("1", "Install or update the team (full run - recommended)"),
        ("2", "Environment setup only (marketplace + plugin + extras; does not pull latest code)"),
        ("3", "Status line only"),
        ("4", "Enable the team for a project (+ optional permission allow-list)"),
        ("5", "Check for updates (read-only - shows what an update would bring)"),
        ("6", "Project preferences (docx export, regulatory citations)"),
        ("7", "Demo - watch the whole run, nothing executed or written"),
        ("q", "Quit"),
    )
    for key, text in options:
        print(f"  {s.cyan(key + ')')} {text}")
    while True:
        try:
            answer = input(f"{s.cyan('  What shall it be?')} {s.bold('[1]')}: ").strip().lower()
        except EOFError:
            return "full"
        if not answer:
            return "full"
        if answer in MENU_ACTIONS:
            return MENU_ACTIONS[answer]
        print("  1-7 or q, please.")


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
        self.branch = "main"
        self.mode = "install"
        self.stashed = False
        self.code_stale = False  # user declined the update: clone used as-is

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
        default = self.args.branch or self.cfg.get("branch", "main")
        self.step_intro("Picking your release channel - main is stable, dev is the latest work.")
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
                        "install_helper 2026-07-29",
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
        branch = branch if branch in BRANCHES else "main"
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
        wanted = (
            self.args.pip
            if self.args.yes
            else confirm(
                "  Shall I install the optional dev requirements (pytest, render deps)?",
                default=self.args.pip,
                assume_yes=False,
                style=self.style,
            )
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
            if "group policy" in err.lower() or "blocked" in err.lower():
                self.say_claude_launch_trace()
                self.register_directly("the claude CLI launch is blocked by policy")
                return
            self.say_claude_launch_trace()
            self.step_fail("Install plugin", err or "claude plugin install failed")
        self.step_ok(f"Plugin {PLUGIN_ID} " + self.did("installed", "would be installed"))

    def persist(self) -> None:
        if self.demo:
            self.say(self.style.dim(f"    would save settings to {self.cfg_path}"))
            return
        self.cfg.update(
            {"repo_path": str(self.repo), "branch": self.branch, "last_run": "2026-07-30"}
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
            self.say(
                "  1. Enable more projects any time: run me again (option 4) "
                "or /plugin inside Claude Code."
            )
            self.say("  2. Restart Claude Code to load the new version.")
        self.say("")
        self.say(s.green("Done. Summon the team with /compliance-surveillance-team:engage"))
        hat = "🎩 " if _can_encode("🎩") else ""
        self.say(f"{hat}I look forward to working with you. - Morgan")
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
            wanted = self.args.statusline
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
            backup = target.with_name("settings.json.bak-2026-07-30")
            n = 1
            while backup.exists():
                n += 1
                backup = target.with_name(f"settings.json.bak-2026-07-30.{n}")
            backup.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
        self.step_ok("Status line", f"wired in {target} (restart to see it)")

    def format_preferences_step(self) -> None:
        """Standalone, easily re-runnable: change a project's preferences any time (menu
        option 6) - most users install once and never re-run the full flow, so these
        need a path that isn't buried inside first-time project enablement (2026-07-30
        user feedback). Both preferences here are PROJECT-WIDE (team-preferences.json),
        not per-engagement - a deliberate simplification over an earlier per-engagement
        design for regulatory citations."""
        self.step_intro(
            "Two project-wide preferences: whether controlled documents (BRD, FSD, etc.) "
            "also get a Word (.docx) copy, and whether detection-logic work cites "
            "regulatory obligations by default."
        )
        raw = ask("  Which project directory?", ".", False, style=self.style)
        project = Path(raw).expanduser().resolve()
        if not project.is_dir():
            self.step_fail("Project preferences", f"not a directory: {project}")
            return
        prefs_path = project / ".claude" / "team-preferences.json"
        existing = _read_json_dict(prefs_path)
        docx_current = "docx" in (existing.get("extra_formats") or [])
        citations_current = existing.get("regulatory_citations", True)  # unset = on
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
            "  Detection-logic work cites regulatory obligations by default - keep that on?",
            default=citations_current,
            assume_yes=False,
            style=self.style,
        )
        if self.demo:
            self.step_ok(
                "Project preferences",
                f"would set docx -> {'on' if docx_wanted else 'off'}, "
                f"citations -> {'on' if citations_wanted else 'off'}",
            )
            return
        if docx_wanted == docx_current and citations_wanted == citations_current:
            self.step_ok("Project preferences", "unchanged")
            return
        write_team_preferences(
            project,
            extra_formats=["docx"] if docx_wanted else [],
            regulatory_citations=citations_wanted,
        )
        self.step_ok(
            "Project preferences",
            f"docx -> {'on' if docx_wanted else 'off'}, "
            f"citations -> {'on' if citations_wanted else 'off'} ({prefs_path})",
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
                self.step_skip(
                    "Project enablement",
                    "later: run /plugin inside Claude Code from the project",
                )
                return
        raw = ask("  Which project directory?", ".", False, style=self.style)
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
                "  Controlled documents (BRD, FSD, etc.) always get .md + .html - also "
                "produce a Word (.docx) copy by default, for reviewers who redline in Word?",
                default=False,
                assume_yes=False,
                style=self.style,
            ):
                self.say(
                    self.style.dim(
                        f"    would write {project / '.claude' / 'team-preferences.json'}"
                    )
                )
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
                "  Controlled documents (BRD, FSD, etc.) always get .md + .html - also "
                "produce a Word (.docx) copy by default, for reviewers who redline in Word?",
                default=False,
                assume_yes=False,
                style=self.style,
            ):
                write_team_preferences(target.expanduser().resolve(), extra_formats=["docx"])
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
        return [
            ("Preflight checks", self.preflight),
            ("Release channel", self.choose_branch),
            ("Local clone", self.resolve_repo),
            (lambda: f"Sync to origin/{self.branch}", self.sync_branch),
            ("Optional pip requirements", self.optional_pip),
            ("Claude Code marketplace", self.marketplace),
            (lambda: "Plugin " + ("update" if self.mode == "update" else "install"), self.plugin),
            ("Status line (optional)", self.statusline_step),
            ("Enable for a project (optional)", self.enable_step),
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
        backup = target.with_name("settings.json.bak-2026-07-30")
        n = 1
        while backup.exists():
            n += 1
            backup = target.with_name(f"settings.json.bak-2026-07-30.{n}")
        backup.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"{ok} backed up existing settings to {backup.name}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    print(
        f"{ok} {target}: added {len(added)} allow entr{'y' if len(added) == 1 else 'ies'} (add-only; deny rules and hooks untouched)"
    )
    print(style.dim("    Inspect any time with /permissions inside Claude Code."))
    return 0


def write_team_preferences(
    project: Path, extra_formats: Optional[list] = None, regulatory_citations: Optional[bool] = None
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

    Pass only the preference(s) you want to change; omitted arguments leave the
    corresponding key untouched (or unset, which reads as the default)."""
    try:
        target = project / ".claude" / "team-preferences.json"
        prefs = _read_json_dict(target)
        if extra_formats is not None:
            prefs["extra_formats"] = sorted(set(extra_formats))
        if regulatory_citations is not None:
            prefs["regulatory_citations"] = bool(regulatory_citations)
        _write_json_backup(target, prefs)
        return True
    except OSError:
        return False


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
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        last = detail[-1] if detail else "unknown error"
        if "group policy" not in last.lower() and "blocked" not in last.lower():
            print(f"{fail} enable failed for {project}: {last}")
            return 1
        blocked = last
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


# ------------------------------------------------------------------ CLI


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="install_helper",
        description="Install or update the compliance-surveillance-team Claude Code plugin.",
    )
    parser.add_argument(
        "mode",
        nargs="?",
        choices=["install", "update"],
        default=None,
        help="install = fresh clone + plugin install; update = sync an existing clone; "
        "default shows the menu on a terminal, else auto-detects from the saved config",
    )
    parser.add_argument("--branch", choices=list(BRANCHES), help="release channel (main = stable)")
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
    return parser.parse_args(argv)


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


def main(argv=None) -> int:
    """Entry point: _main plus the last-resort Ctrl-C net (menu, banner, prompts that
    sit outside an Installer run). Exit code 130 mirrors the shell convention."""
    try:
        return _main(argv)
    except KeyboardInterrupt:
        print("")
        print("Cancelled.")
        return 130


def _main(argv=None) -> int:
    global run_cmd
    args = parse_args(argv)
    style = Style(supports_color())
    if args.enable_project or args.permissions:
        # Scripting path: no banner, no menu.
        rc = 0
        for target in args.enable_project or []:
            rc = max(rc, run_enable_project(Path(target), style, marks()))
        if args.permissions:
            rc = max(rc, run_permissions(Path(args.permissions), style, marks()))
        return rc

    if not args.demo:
        _relocate_if_running_inside_target_repo(args, argv)

    print_banner(style)
    subset = "full"
    if not args.demo and args.mode is None and not args.yes and sys.stdin.isatty():
        cfg = load_config(config_path())
        check_for_update_upfront(cfg, style, args)
        action = choose_action(style)
        if action == "quit":
            print("No problem - nothing changed. See you next time.")
            return 0
        if action == "demo":
            args.demo = True
        elif action != "full":
            subset = action

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
