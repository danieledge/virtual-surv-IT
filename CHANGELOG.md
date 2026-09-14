# Changelog

All notable changes to the compliance-surveillance-team plugin. Dates are absolute.
This is a proof-of-concept; see `docs/house-rules.md` for the evidence state of domain content.

## [Unreleased]

- **Project setting "claude session debug":** `virt-surv go` starts the session with Claude
  Code's own `--debug` when this project's `claude_debug` preference is on, so hook timings and
  tool-call failures on a slow box are logged where they can be read. Off by default, project
  only, never doubled when the launch command already carries the flag.
- **Launcher:** the first-time setup and update progress screens crashed before their
  subprocess started (a duplicated `errors` keyword in the Popen call); fixed.

## [0.38.0] - 2026-09-14 - Guards applied, plugin mode proven live, a sample engagement shipped

The 2026-09-13 framework review, executed. Why a version bump now: plugin.json's version is what
`claude plugin update` keys on, so with 0.37.0 unchanged every install ran a stale cache while
reporting "updated"; the guard changes below had to ship under a new number. The eval baseline
(`evals/eval-baseline-0.38.0.md`) records one case still failing (`process-review-scorer-delegation`,
run `20260913T130835Z`) and says the release ships with it open. In user terms:

- **Plugin mode proven live:** the install-shaped eval case (marketplace cache copy, client
  project, hooks through `hooks/hooks.json`) passed in 27 turns with no tripwire; the run is the
  first golden replay in CI and its workspace is the shipped sample engagement
  (`examples/engagements/`), opened by `virt-surv try --replay` or `/demo replay` for no tokens.
- **Installer:** `update` compares the installed cache against the marketplace clone and reinstalls
  when the version did not move; preflight and the armed check resolve `sh` the way the hooks do,
  so Git Bash without `sh` on PATH no longer fails an update.
- **Guards, applied:** `validate_findings` runs consent-free; the enumeration redirect says what
  was blocked and the one command to run in two sentences; the DoD stop gate names the pack its
  findings came from; the guard launcher no longer leaks a shell error under a parallel review;
  the persona anchor and the resume brief name `VSIT/engagements/<slug>/`, the workspace projects
  really have.
- **Sessions without TodoWrite** mirror the gates into the state file and say so once; a box with
  no spend telemetry gets a stated pacing rule instead of an invented one.
- **`repo_skeleton` on a non-code repository** rolls symbol-less directories up to one line and
  counts placeholders and archives in a footer, so the inventory fits its budget.
- **CI:** green on Linux and Windows for the first time in the recent history; the Windows leg's
  ten platform failures fixed at their causes.

- **Install:** the five review analysers are downloaded at a pinned version and verified against
  a SHA-256 before install (`config/release-tools.json`); `--no-downloads` or `CST_NO_DOWNLOADS=1`
  fetches nothing; dev requirements install from a hash-pinned lock. The install ends by proving
  the guards fire in your project (`scripts/armed_check.py`), and preflight refuses to continue
  without a POSIX `sh`.
- **Thirteen front doors:** `/review`, `/build`, `/requirements`, `/detection-health` and `/team`
  route by flag to the skills that did the work before; `/engage --light` replaces
  `/engage-light`. The older names still work for one release.
- **Guards** (staged, applied by the owner): a folder name inside an `echo` label, a `--title`
  or an Agent briefing is no longer read as a read; `cat tox.ini` is no longer a build; six
  more wrapper prefixes cannot launder `pytest`; the locked-menu guard runs inside the dispatcher;
  the data-quality reviewer writes its coverage matrix as a findings pack.
- **Evals:** a token-free replay mode for kept golden runs (`--rescore --replay`), three new
  tripwires, a `capped` outcome for runs the harness's own limits ended, a retention-rule
  command, and a spend ledger the release gate checks.
- **Docs:** a quickstart above the fold, a three-step Quick start, `docs/quick-start.md` as the
  one-page reference's source, `docs/README.md` as the documentation index, the FAQ opening with
  what leaves your machine, what it costs, what you need and Windows; house style enforced by
  a test; `SECURITY.md` states every byte that leaves the machine.

The working notes behind each item: `docs/releases/0.38.0.md`.

## [0.37.0] - 2026-08-25 - Data tools, mail formats, and a performance pass that started by finding a hang

### Added
- **`[b]` browse done & archived engagements** in all three launcher tiers, opened
  read-only via `<engage-cmd> --review <slug>`. ARCHIVED-OPEN packs were previously
  findable nowhere. The engage skill validates the slug against
  `engagement_state list --finished` and treats the session as review: no state
  transitions, no ACTIVE marker, no writes into the pack. Data layer:
  `finished_engagements()` - a separate function rather than a widening of
  `scan_engagements`, whose archived-exclusion the DoD checker, stop gate, registry
  and statusline all depend on.

- **`profile_temporal`** - time as a dimension for alert data and similar sets: range,
  **calendar-aware** gaps, freshness, cadence, per-period volumes and peer-subgroup
  breakdowns. Calendar awareness is the point: a naive "gap > 2x the interval" check flags
  every weekend and exchange holiday, which would bury the one real outage.
- **`tag_columns`** + `config/finance-taxonomy.json` - what each column MEANS, from 29
  FIBO-grounded tags across money, banking, loan, security, party, identifier, temporal,
  category and risk. A tag that maps to a published ontology class is defensible to a
  regulator in a way an ad-hoc label is not.
- **`doc_skeleton`** - token-budgeted inventory of a documentation tree. Anthropic's own
  retrieval guidance is that under ~200k tokens you put the corpus in the prompt rather than
  build retrieval infrastructure, so what was missing was **orientation, not RAG**.
- **`.eml` and `.msg`** in `convert_file`. Comms surveillance is one of three pillars, so
  mail was never an edge case - `.msg` was silently skipped. `.eml` needs no dependency;
  `.msg` uses vendored **olefile** and prefers the original RFC822 transport headers so both
  formats parse through the same stdlib path.
- **Two-tier preferences**, machine and project with project winning: `data_profiling`,
  `document_map` and `guard_daemon` - all **on by default**.
- **`[n]` takes the request at the launcher** (`--request`), and **autonomy is no longer
  Jira-only** - a typed request can run unattended too.
- **`[s]` sign-off and `[r]` supersede** on the browse screen: finish a finished engagement
  without ever reopening it.
- **Symbols for Java, C#, SQL, Scala, Kotlin and JS/TS** in `repo_skeleton`. Previously
  anything but Python and Markdown got only its filename - on exactly the languages a bank
  actually runs.

### Safety

- `profile_temporal` and `tag_columns` emit **aggregates only, never a record**, which makes
  them safer than the alternative of an agent reading rows into context. `doc_skeleton` is
  deliberately NOT exempt - headings are content and can name a client - and says so.

### Performance

Measured, not guessed. The review that produced these first found the test suite was not
slow but **hung**, on a screen of mine that blocked waiting for keys a harness never sends.

- State mutators stop re-rendering unchanged HTML: **0.38s -> 0.10s** per mutation.
- Date parsing in `profile_temporal`: **2.34s -> 0.08s** per 100k ISO rows.
- `repo_skeleton`: **15.0s -> 6.5s** - every Python file was parsed twice.
- The engage-probe prefetch is **daemon-served** like the other every-prompt hook, and no
  longer imports `subprocess` just to decide it has nothing to do.
- The guard daemon's idle watchdog no longer outsleeps the timeout it polices.

### Fixed

- The generated START-HERE and review documents never said the team is **AI**.
- A Markdown table written on one line rendered as a paragraph of literal pipes -
  now caught by `TABLE-COLLAPSED` before it reaches a client.
- Developer guidance is no longer **manufactured for deliverables containing no code**.
- The AUTO-* Definition-of-Done gates were **dead code**, then ran only on engagements that
  shipped code. Both fixed; the flag is now recorded by the launcher, not by the run.
- TUI hotkeys say the key you actually press (`[a]` meant a plain letter; the binding was
  Ctrl-A), and the evidence sidecar is `.evidence.json` rather than a second `.report.json`
  that read as just another output.

Entries for 0.36.0 and earlier: `docs/releases/archive-0.36-and-earlier.md` (moved 2026-09-14, verbatim).
