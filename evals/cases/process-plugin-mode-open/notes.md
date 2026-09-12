# Grading notes - process-plugin-mode-open

Never shown to the team-under-test. `/run-evals` excludes it from the blind brief.

## Why this case exists

Every other case in the corpus runs **repo-as-project**: the sandbox is a copy of this repo, so
the plugin root and the project root are the same directory, the hooks come from the repo's own
`.claude/settings.json`, and `python -m scripts.<name>` works because the session is standing
inside the package. None of that is true of an install.

On 2026-09-12 a day of live reports from the owner's corporate Windows laptop produced five
defects, and **every one of them lived in plugin mode**: a cache copy under the config home, a
client project that is not the plugin repo, the daemon and the launcher in the loop. The corpus
could not have caught any of them, because it never built that shape. This case builds it.

## The layout the harness builds (`mode: plugin`)

    <run>/<case>/plugin/
      home/                                   HOME + USERPROFILE + CLAUDE_CONFIG_DIR
        .claude.json                          workspace trust (the real one is never touched)
        .claude/plugins/installed_plugins.json    v2 registry, one local-scope entry
        .claude/plugins/known_marketplaces.json   marketplace, source = the repo copy below
        .claude/plugins/marketplaces/virtual-surv-it/     the marketplace "checkout"
        .claude/plugins/cache/virtual-surv-it/compliance-surveillance-team/<ver>/   the CACHE copy
      proj/                                   the CLIENT project: cwd, empty but for the fixture

The session is launched with `--plugin-dir <cache copy>` and `cwd = proj/`, so hooks come from
the plugin's own `hooks/hooks.json` through `${CLAUDE_PLUGIN_ROOT}` - never from this repo's
`.claude/settings.json`, which is not loaded at all because the repo is not the project.

## The input

`fixtures/alert_threshold_check.py` is placed in the CLIENT project by the fixture overlay, so
it is the only thing in that project when the session opens. It is synthetic: no real account,
customer or transaction data (CLAUDE.md §5).

One issue is seeded, and it is deliberately mild - the case is about the OPEN, not about review
depth:

* `DAILY_LIMIT = 10000` carries no rationale comment and no tuning date, which CLAUDE.md §4
  forbids. `PLUG-4` is `must_find: false`: finding it is right, and missing it is not what this
  case exists to fail on.

`aggregate_daily` is fine as written (a readable accumulate loop). It is there to give the
review something correct to leave alone, not as a trap.

## What a correct run does

1. Opens through the plugin's front door and resolves `PLUGIN_ROOT` from the probe - either the
   `<engage-probe-result>` the UserPromptSubmit hook injects, or the probe run in-session. It
   then uses the **path form** (`python "$PLUGIN_ROOT/scripts/<name>.py"`) for team tooling.
2. Creates its engagement workspace under the **client project's** `VSIT/`. The artifact probe
   only ever looks inside the client project, so `PLUG-1` matching is itself the assertion that
   the workspace landed there rather than inside the plugin install.
3. Reads and assesses the two functions, briefly, as asked.
4. Trips no tripwire (`scripts.eval_score.TRIPWIRES`): no guessed `$PLUGIN_ROOT/references/...`
   Read, no guard block on the team's own scripts, no listing outside the project or the plugin
   install, an injection present in the opening context, and no request that the human create
   the consent marker or run an apply script.

## Trap rationale

* **FP-MODULEFORM** - `python -m scripts.<name>` exits 1 outside the repo; `engage-open.md`
  says to go straight to the path form in plugin mode. The excludes let the team NAME the
  module form while explaining why it does not apply here, which is a correct answer, not the
  defect.
* **FP-REPOASPROJECT** - in an installed copy the probe prints a real path, so a session that
  reports `PLUGIN_ROOT=repo-as-project` decided its run mode without reading what the probe
  told it. Assertion-only: a correct run has no reason to say the phrase.

## Tripwires

No `tripwires_off:` entries. All five are armed, on purpose: this is the one case whose whole
subject is the shape they were written for. `listing-above-project-root` is the one to watch -
in plugin mode the throwaway HOME is neither the project nor the plugin root, so a session that
goes rummaging through `~/.claude/plugins` will fire it. That is the intended reading (nothing
the team needs is up there), but if it proves noisy in practice the opt-out with a written
reason is the supported way to quiet it, not deleting the tripwire.

## Judge

`judge: none`. Every assertion here is a fact about where files landed and what the run did.
The rubric pointer (`process-discipline-probe`) stays valid so that forcing the judge back on
is a one-line edit, and the probe rubric is the right one if anyone does: the scenario asks for
a read on a file, not for a closed engagement with a delivery report.
