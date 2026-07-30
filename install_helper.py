#!/usr/bin/env python3
"""
install_helper.py (repo root) - guided install/update for the Claude Code plugin.

Walks a human through the real install path from README "Quick start": clone or update a
local copy of the repo, pick a release channel (main = stable, dev = cutting edge), point
the Claude Code marketplace at the clone, and install or update the
compliance-surveillance-team plugin - with a step-by-step console trail and a closing
summary of the actions that stay manual (per-project enablement, a session restart -
the hooks ship pre-wired; apply-*.sh scripts are maintainer tools, not user steps).

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
  is set, ASCII fallbacks for the check marks when the console encoding cannot carry them.

Usage:
  python install_helper.py                         # auto: update if configured, else install
  python install_helper.py install                 # fresh clone + marketplace + plugin install
  python install_helper.py update          # fetch/reset + marketplace + plugin update
  python install_helper.py --branch dev    # pick the channel up front
  python install_helper.py --yes           # non-interactive, safe defaults
  python install_helper.py --yes --pip     # also install requirements-dev.txt
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess  # fixed-argv calls to git/claude/pip, no shell  # nosec B404
import sys
from pathlib import Path
from typing import Optional

REPO_URL = "https://github.com/danieledge/virtual-surv-IT.git"
MARKETPLACE = "virtual-surv-it"
PLUGIN_ID = "compliance-surveillance-team@virtual-surv-it"
BRANCHES = ("main", "dev")
DEFAULT_CLONE_DIR = Path.home() / "virtual-surv-IT"
CLAUDE_DOCS_URL = "https://claude.com/claude-code"

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
    """Missing or corrupt config is not an error - the run just starts fresh."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_config(path: Path, cfg: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")


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


def marks(stream=None) -> dict:
    """Unicode check marks, with ASCII fallbacks for consoles that cannot encode them."""
    stream = stream if stream is not None else sys.stdout
    encoding = getattr(stream, "encoding", None) or "utf-8"
    try:
        "✓✗".encode(encoding)
        return {"ok": "✓", "fail": "✗", "skip": "~"}
    except (UnicodeEncodeError, LookupError):
        return {"ok": "OK", "fail": "X", "skip": "~"}


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
    """The plugin version in the clone's manifest, or None when unreadable."""
    try:
        manifest = json.loads((repo / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        version = manifest.get("version")
        return version if isinstance(version, str) and version else None
    except (OSError, ValueError):
        return None


def changelog_headline(changelog: Path, version: str) -> Optional[str]:
    """The `## [<version>] - date - title` line from the changelog, cleaned for console."""
    try:
        for line in changelog.read_text(encoding="utf-8").splitlines():
            if line.startswith(f"## [{version}]"):
                return line[3:].strip()
    except OSError:
        pass
    return None


def user_settings_path() -> Path:
    """The user-level Claude Code settings file (~/.claude/settings.json)."""
    return Path.home() / ".claude" / "settings.json"


def statusline_command(repo: Path) -> str:
    """The statusLine command pointing at the clone's script by absolute path, so the
    status line works from every project (dormant ones just show 'team dormant')."""
    return f'bash "{(repo / "scripts" / "statusline.sh").resolve()}"'


def merge_statusline(settings: dict, command: str):
    """Set statusLine in a settings dict. Returns (settings, verdict) where verdict is
    'added', 'already' (identical command present) or 'conflict' (a DIFFERENT statusLine
    exists - the caller must get explicit confirmation before overwriting)."""
    current = settings.get("statusLine")
    if isinstance(current, dict) and current.get("command") == command:
        return settings, "already"
    if current is not None:
        return settings, "conflict"
    settings["statusLine"] = {"type": "command", "command": command}
    return settings, "added"


def command_argv(name: str, resolved: Optional[str] = None) -> list:
    """The argv prefix that actually launches `name` on this platform.

    Windows npm shims are `.cmd`/`.bat` batch files: `shutil.which` finds them but
    CreateProcess cannot launch a batch file by bare name without a shell, so the
    resolved path is routed through `cmd /c`. Everywhere else (and for real
    executables) the resolved absolute path is used directly."""
    resolved = resolved if resolved is not None else (shutil.which(name) or name)
    if str(resolved).lower().endswith((".cmd", ".bat")):
        return ["cmd", "/c", str(resolved)]
    return [str(resolved)]


def run_cmd(argv, cwd: Optional[Path] = None, timeout: int = 300):
    """Fixed-argv runner, output captured. Tests monkeypatch this symbol.

    The first element is resolved via command_argv so Windows `.cmd` shims
    (the npm-installed `claude`) launch correctly."""
    argv = [str(a) for a in argv]
    argv = command_argv(argv[0]) + argv[1:]
    return subprocess.run(  # argv is a fixed list built here, shell=False  # nosec B603
        argv,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


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
    return (path / ".git").exists() and (path / ".claude-plugin" / "plugin.json").exists()


def decide_mode(explicit: Optional[str], cfg: dict) -> str:
    """install | update. Explicit wins; else update when the configured clone still exists."""
    if explicit:
        return explicit
    repo = cfg.get("repo_path")
    if repo and looks_like_repo(Path(repo)):
        return "update"
    return "install"


# ------------------------------------------------------------------ prompts


def ask(prompt: str, default: str, assume_yes: bool) -> str:
    """One-line prompt with a default; --yes or a closed stdin takes the default."""
    if assume_yes or not sys.stdin.isatty():
        return default
    try:
        answer = input(f"{prompt} [{default}]: ").strip()
    except EOFError:
        return default
    return answer or default


def confirm(prompt: str, default: bool, assume_yes: bool) -> bool:
    if assume_yes or not sys.stdin.isatty():
        return default
    hint = "Y/n" if default else "y/N"
    try:
        answer = input(f"{prompt} [{hint}]: ").strip().lower()
    except EOFError:
        return default
    if not answer:
        return default
    return answer in ("y", "yes")


# ------------------------------------------------------------------ the installer


class Installer:
    def __init__(self, args, style: Style, mark_map: dict):
        self.args = args
        self.style = style
        self.marks = mark_map
        self.tracker = StepTracker()
        self.cfg_path = config_path()
        self.cfg = load_config(self.cfg_path)
        self.repo: Optional[Path] = None
        self.branch = "main"
        self.mode = "install"
        self.stashed = False

    # ---- console helpers

    def say(self, text: str = "") -> None:
        print(text)

    def step_header(self, number: int, total: int, title: str) -> None:
        self.say("")
        self.say(self.style.cyan(self.style.bold(f"[{number}/{total}] {title}")))

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

    # ---- steps

    def preflight(self) -> None:
        if sys.version_info >= (3, 9):
            self.step_ok(f"Python {sys.version_info.major}.{sys.version_info.minor}")
        else:
            self.step_fail("Python version", "3.9 or newer required")
        if shutil.which("git"):
            self.step_ok("git found")
        else:
            self.step_fail("git", "git is required - install it and re-run")
        if shutil.which("claude"):
            self.step_ok("claude CLI found")
        else:
            self.step_fail(
                "claude CLI",
                f"Claude Code is not on PATH - install it first: {CLAUDE_DOCS_URL}",
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
        self.say(self.style.dim("  main = stable releases, dev = latest integrated changes"))
        while True:
            picked = ask("  Release channel (main/dev)", default, self.args.yes).lower()
            try:
                self.branch = validate_branch(picked)
                break
            except ValueError as exc:
                if self.args.yes or not sys.stdin.isatty():
                    self.step_fail("Branch choice", str(exc))
                self.say(f"  {exc}")
        self.step_ok(f"Channel: {self.branch}")

    def resolve_repo(self) -> None:
        if self.args.repo:
            candidate = Path(self.args.repo).expanduser().resolve()
        elif self.mode == "update":
            configured = self.cfg.get("repo_path")
            script_root = Path(__file__).resolve().parents[1]
            if configured and looks_like_repo(Path(configured)):
                candidate = Path(configured)
            elif looks_like_repo(script_root):
                candidate = script_root
            else:
                self.step_fail(
                    "Locate clone",
                    "no known clone - run: python install_helper.py install",
                )
                return
        else:
            default = self.cfg.get("repo_path", str(DEFAULT_CLONE_DIR))
            candidate = (
                Path(ask("  Clone directory", default, self.args.yes)).expanduser().resolve()
            )

        if looks_like_repo(candidate):
            self.repo = candidate
            self.step_ok(f"Using existing clone: {candidate}")
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

    def sync_branch(self) -> None:
        repo = self.repo
        proc = run_cmd(["git", "-C", repo, "fetch", "origin", self.branch], timeout=300)
        if proc.returncode != 0:
            self.step_fail("Fetch origin", proc.stderr.strip() or "git fetch failed")
        self.step_ok(f"Fetched origin/{self.branch}")

        if is_dirty(repo):
            self.say(self.style.yellow("  The clone has uncommitted local changes."))
            if self.args.yes or not sys.stdin.isatty():
                self.step_fail(
                    "Working tree",
                    "dirty - refusing to reset; commit or stash your changes, then re-run",
                )
            if confirm("  Stash them and continue?", default=False, assume_yes=False):
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
            if not confirm(f"  {detail}. Discard and match origin?", False, False):
                self.step_fail("Local commits", detail + " - left in place, aborting")

        proc = run_cmd(["git", "-C", repo, "checkout", "-B", self.branch, f"origin/{self.branch}"])
        if proc.returncode != 0:
            self.step_fail("Checkout branch", proc.stderr.strip() or "git checkout failed")
        head = run_cmd(["git", "-C", repo, "rev-parse", "--short", "HEAD"])
        commit = head.stdout.strip() if head.returncode == 0 else "?"
        self.step_ok(f"On {self.branch} at {commit}", f"matches origin/{self.branch}")

    def optional_pip(self) -> None:
        req = self.repo / "requirements-dev.txt"
        if not req.exists():
            self.step_skip("Dev requirements", "requirements-dev.txt not present")
            return
        wanted = (
            self.args.pip
            if self.args.yes
            else confirm(
                "  Install optional dev requirements (pytest, render deps)?",
                default=self.args.pip,
                assume_yes=False,
            )
        )
        if not wanted:
            self.step_skip("Dev requirements", "skipped - the plugin works without them")
            return
        proc = run_cmd([sys.executable, "-m", "pip", "install", "-r", req], timeout=600)
        if proc.returncode == 0:
            self.step_ok("Dev requirements installed")
        else:
            # pip may be absent or blocked in locked-down environments; never fatal.
            self.step_fail(
                "Dev requirements",
                "pip install failed - the plugin itself needs no pip packages",
                fatal=False,
            )

    def marketplace(self) -> None:
        if self.mode == "update":
            proc = run_cmd(["claude", "plugin", "marketplace", "update", MARKETPLACE], timeout=120)
            if proc.returncode == 0:
                self.step_ok(f"Marketplace {MARKETPLACE} refreshed")
                return
        # Fresh add (install mode, or an update where the marketplace was missing/broken).
        run_cmd(["claude", "plugin", "marketplace", "remove", MARKETPLACE], timeout=120)
        proc = run_cmd(["claude", "plugin", "marketplace", "add", self.repo], timeout=120)
        if proc.returncode != 0:
            self.step_fail(
                "Add marketplace",
                (
                    proc.stderr.strip()
                    or proc.stdout.strip()
                    or "claude plugin marketplace add failed"
                ),
            )
        self.step_ok(f"Marketplace {MARKETPLACE} -> {self.repo}")

    def plugin(self) -> None:
        if self.mode == "update":
            proc = run_cmd(["claude", "plugin", "update", PLUGIN_ID], timeout=300)
            if proc.returncode == 0:
                self.step_ok(f"Plugin {PLUGIN_ID} updated")
                return
        run_cmd(["claude", "plugin", "uninstall", PLUGIN_ID], timeout=120)
        proc = run_cmd(["claude", "plugin", "install", PLUGIN_ID], timeout=300)
        if proc.returncode != 0:
            self.step_fail(
                "Install plugin",
                (proc.stderr.strip() or proc.stdout.strip() or "claude plugin install failed"),
            )
        self.step_ok(f"Plugin {PLUGIN_ID} installed")

    def persist(self) -> None:
        self.cfg.update(
            {"repo_path": str(self.repo), "branch": self.branch, "last_run": "2026-07-30"}
        )
        version = installed_version(self.repo) if self.repo else None
        if version:
            self.cfg["last_version"] = version
        save_config(self.cfg_path, self.cfg)
        self.step_ok(f"Settings saved to {self.cfg_path}")

    def whats_new(self, previous: Optional[str]) -> None:
        """After a successful install/update: what did you just get."""
        s = self.style
        version = installed_version(self.repo) if self.repo else None
        if not version:
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
        self.say("")
        self.say(s.bold(s.cyan("Summary " + ("(aborted)" if aborted else ""))))
        for line in self.tracker.summary_lines(self.marks):
            self.say(line)
        if self.stashed:
            self.say(s.yellow("  Your local changes are stashed: git stash pop to restore."))
        if aborted:
            self.say("")
            self.say("Fix the failed step above and re-run - the helper is safe to repeat.")
            return
        self.say("")
        self.say(s.bold("Still yours to do by hand:"))
        self.say(
            "  1. Any FURTHER projects: enable per project via step 9 on a re-run, /plugin\n"
            "     inside Claude Code, or `python install_helper.py --enable-project <dir>`.\n"
            "     (Per-project enablement is the README's token-economy rule - avoid user scope.)"
        )
        self.say("  2. Restart Claude Code so the new plugin version loads.")
        self.say(
            "  (The safety and lifecycle hooks ship pre-wired - nothing to apply. The\n"
            "  optional status line is offered during the run, or later via\n"
            "  bash scripts/apply-statusline.sh.)"
        )
        self.say("")
        self.say(s.green("Done. Summon the team with /compliance-surveillance-team:engage"))

    def statusline_step(self) -> None:
        """Optional: wire the team status line into the USER-level Claude settings so it
        shows in every project. Opt-in (interactive yes, or --statusline with --yes);
        add-only with backup; a DIFFERENT existing statusLine is never overwritten
        without an explicit interactive yes. Windows note: the command runs via bash
        (Git Bash ships with Git for Windows)."""
        wanted = (
            self.args.statusline
            if self.args.yes
            else confirm(
                "  Wire the team status line (shows dormant/engaged + cost, zero tokens)?",
                default=self.args.statusline,
                assume_yes=False,
            )
        )
        if not wanted:
            self.step_skip("Status line", "skipped - bash scripts/apply-statusline.sh any time")
            return
        target = user_settings_path()
        settings = {}
        if target.is_file():
            try:
                settings = json.loads(target.read_text(encoding="utf-8"))
                if not isinstance(settings, dict):
                    raise ValueError("settings root is not an object")
            except (OSError, ValueError) as exc:
                self.step_fail(
                    "Status line", f"{target} unreadable ({exc}) - not touching it", fatal=False
                )
                return
        command = statusline_command(self.repo)
        settings, verdict = merge_statusline(settings, command)
        if verdict == "already":
            self.step_ok("Status line", "already wired to this clone")
            return
        if verdict == "conflict":
            keep = confirm(
                "  A different statusLine is already configured - replace it?",
                default=False,
                assume_yes=self.args.yes,
            )
            if not keep:
                self.step_skip("Status line", "existing statusLine kept")
                return
            settings["statusLine"] = {"type": "command", "command": command}
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

    def enable_step(self) -> None:
        """Optional: enable the team for a project right now, and offer the recommended
        permission allow-list for the same project. Interactive only - non-interactive
        runs use the --enable-project / --permissions flags."""
        if self.args.yes:
            self.step_skip(
                "Project enablement",
                "non-interactive - use --enable-project <dir> (and --permissions <dir>)",
            )
            return
        wanted = confirm(
            "  Enable the team for a project now (per-project scope)?",
            default=False,
            assume_yes=False,
        )
        if not wanted:
            self.step_skip(
                "Project enablement",
                "later: run /plugin inside Claude Code from the project",
            )
            return
        try:
            raw = input("  Project directory [.]: ").strip() or "."
        except EOFError:
            raw = "."
        target = Path(raw)
        if run_enable_project(target, self.style, self.marks) == 0:
            self.step_ok("Project enablement", str(target.expanduser().resolve()))
            if confirm(
                "  Also add the recommended permission allow-list to it (fewer prompts)?",
                default=True,
                assume_yes=False,
            ):
                run_permissions(target, self.style, self.marks)
        else:
            self.step_fail("Project enablement", "see message above", fatal=False)

    # ---- orchestration

    def run(self) -> int:
        s = self.style
        self.say(s.bold(s.cyan("Compliance Surveillance Team - plugin install helper")))
        self.mode = decide_mode(self.args.mode, self.cfg)
        self.say(s.dim(f"Mode: {self.mode} (config: {self.cfg_path})"))
        total = 9
        aborted = False
        try:
            self.step_header(1, total, "Preflight checks")
            self.preflight()
            self.step_header(2, total, "Release channel")
            self.choose_branch()
            self.step_header(3, total, "Local clone")
            self.resolve_repo()
            self.step_header(4, total, f"Sync to origin/{self.branch}")
            self.sync_branch()
            self.step_header(5, total, "Optional pip requirements")
            self.optional_pip()
            self.step_header(6, total, "Claude Code marketplace")
            self.marketplace()
            self.step_header(
                7, total, "Plugin " + ("update" if self.mode == "update" else "install")
            )
            self.plugin()
            self.step_header(8, total, "Status line (optional)")
            self.statusline_step()
            self.step_header(9, total, "Enable for a project (optional)")
            self.enable_step()
            previous = self.cfg.get("last_version")
            self.persist()
            self.whats_new(previous)
        except InstallAbort:
            aborted = True
        except subprocess.TimeoutExpired as exc:
            self.tracker.record("Command timed out", "fail", str(exc.cmd))
            aborted = True
        self.print_summary(aborted)
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
            settings = json.loads(target.read_text(encoding="utf-8"))
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


def run_enable_project(project_dir: Path, style: Style, mark_map: dict, runner=None) -> int:
    """Enable the plugin for one project (claude plugin enable --scope project, run from
    that project's directory). Human-run; per-project scope is the token-economy rule."""
    runner = runner or run_cmd
    ok, fail = mark_map["ok"], mark_map["fail"]
    project = project_dir.expanduser().resolve()
    if not project.is_dir():
        print(f"{fail} not a directory: {project}")
        return 1
    proc = runner(["claude", "plugin", "enable", "--scope", "project", PLUGIN_ID], cwd=project)
    if proc.returncode == 0:
        print(f"{ok} enabled for {project}")
        return 0
    detail = (proc.stderr or proc.stdout or "").strip().splitlines()
    print(f"{fail} enable failed for {project}: {detail[-1] if detail else 'unknown error'}")
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
        "default auto-detects from the saved config",
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


def main(argv=None) -> int:
    args = parse_args(argv)
    style = Style(supports_color())
    if args.enable_project or args.permissions:
        rc = 0
        for target in args.enable_project or []:
            rc = max(rc, run_enable_project(Path(target), style, marks()))
        if args.permissions:
            rc = max(rc, run_permissions(Path(args.permissions), style, marks()))
        return rc
    return Installer(args, style, marks()).run()


if __name__ == "__main__":
    sys.exit(main())
