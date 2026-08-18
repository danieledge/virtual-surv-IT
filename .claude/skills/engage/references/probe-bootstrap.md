# The step-0 probe bootstrap (miss-path fallback)

> Read this file ONLY when the open found neither an injected `<engage-probe-result>` block
> nor a usable `.claude/engage-probe.json` cache (the two fast paths in
> `.claude/skills/.shared/engage-open.md` step 0). A steady-state open never reads this file -
> that is the point of its extraction (token plan Phase 2, 2026-08-18): the fallback text is
> paid for only when the fallback runs. It is still fully live and tested, not being retired.

The bootstrap below is a tested Python heredoc - a drift-pinned twin of `scripts/find_plugin_root.py`
(`tests/test_engage_open_bootstrap.py` keeps the two from ever diverging). Run it exactly as
written, character for character - history and full rationale in
`.claude/skills/engage/references/probe-contract.md` if something looks wrong:

```
CACHED=$(cat "${CLAUDE_PROJECT_DIR:-.}/.claude/.guard-interpreter" 2>/dev/null); \
_try() { PYTHONIOENCODING=utf-8 "$1" - "$1" <<'PY'
import sys, json, os, re, subprocess
from pathlib import Path

interp = sys.argv[1]
home = Path.home()
cwd = Path.cwd()

def install_paths(obj):
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "installPath" and isinstance(v, str):
                out.append(v)
            else:
                out += install_paths(v)
    elif isinstance(obj, list):
        for item in obj:
            out += install_paths(item)
    return out

def is_team_root(path):
    try:
        p = Path(path)
        return ("compliance-surveillance-team" in (p / ".claude-plugin/plugin.json").read_text(encoding="utf-8-sig")
                and (p / "scripts/engage_probe.py").is_file())
    except Exception:
        return False

def from_env():
    seed = os.environ.get("CLAUDE_PLUGIN_ROOT") or ""
    return seed if seed and is_team_root(seed) else ""

def from_registry():
    for name in ("installed_plugins.json", "config.json", "plugins.json"):
        try:
            data = json.loads((home / ".claude/plugins" / name).read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        for path in install_paths(data):
            if is_team_root(path):
                return path
    return ""

def from_config():
    base = os.environ.get("XDG_CONFIG_HOME")
    cfg = (Path(base) if base else home / ".config") / "virt-surv-it" / "installer.json"
    try:
        repo_path = json.loads(cfg.read_text(encoding="utf-8-sig")).get("repo_path") or ""
    except Exception:
        return ""
    return repo_path if repo_path and is_team_root(repo_path) else ""

def from_filesystem():
    hits = []
    pats = ("*/docs/team-operating-guide.md", "*/*/docs/team-operating-guide.md",
            "*/*/*/docs/team-operating-guide.md", "*/*/*/*/docs/team-operating-guide.md")
    for base in (home / ".claude/plugins/cache", home / ".claude/plugins/marketplaces"):
        if base.is_dir():
            for pat in pats:
                for marker in base.glob(pat):
                    if "compliance-surveillance-team" in marker.parts:
                        hits.append(marker)
    hits = [h for h in hits if is_team_root(h.parent.parent)]
    if not hits:
        return ""
    def key(p):
        return [(int(d), "") if d else (-1, s) for d, s in re.findall(r"(\d+)|(\D+)", str(p))]
    return str(max(hits, key=key).parent.parent)

root = "" if (cwd / "docs/team-operating-guide.md").is_file() else (from_env() or from_registry() or from_filesystem() or from_config())
script = Path(root, "scripts", "engage_probe.py") if root else Path("scripts/engage_probe.py")
if not script.is_file():
    sys.stderr.write("PROBE-STDERR: no engage_probe.py under resolved root=%r (cwd=%s)\n" % (root, cwd))
    sys.exit(1)
proc = subprocess.run(
    [interp, str(script), "--plugin-root", root, "--interpreter-name", interp],
    capture_output=True, text=True, encoding="utf-8",
)
sys.stdout.write(proc.stdout)
if proc.returncode != 0 or not proc.stdout:
    for line in (proc.stderr or "").strip().splitlines()[-3:]:
        sys.stderr.write("PROBE-STDERR: " + line + "\n")
    sys.exit(1)
sys.exit(0)
PY
}; \
OUT=""; \
if [ -n "$CACHED" ] && command -v "$CACHED" >/dev/null 2>&1; then OUT=$(_try "$CACHED"); fi; \
if [ -z "$OUT" ]; then \
  if [ "${OS:-}" = "Windows_NT" ]; then ORDER="python py python3"; else ORDER="python3 python py"; fi; \
  for I in $ORDER; do \
    OUT=$(_try "$I") && break; \
    OUT=""; \
  done; \
fi; \
if [ -n "$OUT" ]; then echo "$OUT"; else \
echo "PROBE_FAILED - retry this exact block once by hand with your working interpreter to see the real error"; fi
```

The interpreter order (warm cache first, then Windows-aware) and `PYTHONIOENCODING=utf-8` are
still load-bearing, not decoration - the cache key is `CLAUDE_PROJECT_DIR`-scoped, not
plugin-root-scoped (rationale: `.claude/skills/engage/references/probe-contract.md`).

Every rule around RUNNING the block (never prepend `cd`, the Windows forward-slash path rule,
never a substitute probe, `PROBE_FAILED` handling) lives in
`.claude/skills/.shared/engage-open.md` step 0 and applies unchanged - this file holds only
the block itself.
