#!/usr/bin/env node
// Portable launcher for `npm run data` (and therefore `npm run dashboard`,
// `dashboard:live`'s own call to it, and install_helper.py's dashboard_step).
//
// The previous version of this script hardcoded `python3` - which does not exist on
// Windows (the interpreter there is `python` or `py`), exactly the same problem this
// plugin's own hook launcher (.claude/hooks/run-guard.sh) already had to solve. npm
// scripts don't run under a POSIX shell on Windows by default, so the fix can't be a
// shell one-liner the way run-guard.sh's is - this does the same OS-aware probing in
// Node instead, which is guaranteed available here (the whole dashboard build depends
// on it already).
//
// Mirrors run-guard.sh's own reasoning: on Windows, `python3.exe` is frequently the App
// Execution Alias stub (present, but not a real interpreter - invoking it triggers a
// Microsoft Store redirect prompt instead of running Python), so try `python`/`py`
// first there and leave `python3` for last; everywhere else, `python3` first.
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const REPO_ROOT = path.resolve(fileURLToPath(import.meta.url), "..", "..", "..");
const CANDIDATES =
  process.platform === "win32" ? ["python", "py", "python3"] : ["python3", "python", "py"];

function worksAndIsRecentEnough(interpreter) {
  const probe = spawnSync(
    interpreter,
    ["-c", "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)"],
    { stdio: "ignore" },
  );
  return probe.status === 0;
}

function resolveInterpreter() {
  for (const candidate of CANDIDATES) {
    if (worksAndIsRecentEnough(candidate)) return candidate;
  }
  return null;
}

const interpreter = resolveInterpreter();
if (!interpreter) {
  console.error(
    `No Python >= 3.9 interpreter found on PATH (tried: ${CANDIDATES.join(", ")}). ` +
      "The dashboard's data step needs Python to run scripts/dashboard.py.",
  );
  process.exit(1);
}

const result = spawnSync(
  interpreter,
  ["-m", "scripts.dashboard", "--json", "dashboard-ui/data/dashboard-data.json"],
  { cwd: REPO_ROOT, stdio: "inherit" },
);
process.exit(result.status ?? 1);
