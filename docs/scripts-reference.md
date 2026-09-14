# Scripts reference

> Moved out of README.md on 2026-09-14 (framework review, step 6.8); the README keeps a one-line pointer.


Every file in `scripts/` (97 - counted via `ls scripts/*.py scripts/*.sh`), plus the four
`.claude/hooks/guard-*.py` modules and `install_helper.py` at the repo root, grouped by function.
**model, consent-free** = the team's own tooling, allow-listed in the execution guard and run as
`python -m scripts.<name>`; **run by Claude Code** = hooks fired automatically around tool use;
**human-only** = wiring/consent actions the model is blocked from performing (ADR-002);
**maintainer** = supports releases of this repo, not engagements. Descriptions are taken from
each script's own docstring; a purpose phrase for every file, not a full API reference - `ls
scripts` on a checkout is the authoritative inventory if this table and the tree ever disagree.

**Front-door tools** (model, consent-free unless noted)

| Script | What it does |
|---|---|
| `scripts/convert_file.py` | The single front door for reading/converting source files: Excel/CSV/TSV/PDF/DOCX in, CSV/JSONL/Markdown out, lossless by default, JSON evidence report every run (deps vendored, no pip) |
| `scripts/ingest.py` | The sanctioned path for real data: schema-driven keyed masking, `data/raw/` → `data/masked/` |
| `scripts/gen_synthetic.py` | Synthetic order-flow generator for the spoofing example; deterministic per seed, no real records |
| `scripts/synthesise.py` | Learns the shape of masked order flow and emits fully synthetic sessions sharing no real rows, entities or timestamps |
| `scripts/check_citations.py` | Grounds regulatory citations against the register (ADR-001): retrieve via `lookup()`, mechanically flag unregistered pinpoints |
| `scripts/check_artifacts.py` | The mechanical Definition-of-Done check over an engagement's artifacts - the gate CI can never see because `VSIT/engagements/` is git-ignored |
| `scripts/engagement_state.py` | Reads/writes the machine-readable engagement state (`engagement-state.json`, ADR-006); `START-HERE.md` is a rendered view of it |
| `scripts/calibrate_spoofing.py` | Measured FP/FN evidence for the spoofing rule on a labelled synthetic corpus (precision/recall per segment) |
| `scripts/extensions.py` | Parses and surfaces the company-extensions contract from a working project's `VSIT/config/extensions.md` (ADR-009) |
| `scripts/convert_sarif.py` | Converts SARIF analyser output to the team's findings-pack JSONL so company-tool findings keep 📊 measured status |
| `scripts/engage_probe.py` | The `/engage` step-0 open-time probe, as code |
| `scripts/repo_skeleton.py` | Deterministic, token-budgeted codebase skeleton (inventory, tiered symbols, PageRank importance; placeholders and archives counted in a footer, symbol-less directories rolled up to one line) - the mechanical layer under `/map-codebase` and the sanctioned whole-repo inventory during engagements |
| `scripts/explain_rule.py` | "Why did this NOT alert?" per-condition trace for the spoofing worked example (the `/why-no-alert` step c) |
| `scripts/doc_skeleton.py` | Deterministic, token-budgeted inventory of a documentation tree |
| `scripts/map_fingerprint.py` | Content fingerprinting for codebase-map drift detection (ADR-007 Phase 1) |
| `scripts/tag_columns.py` | Semantic tags for the columns of a dataset - what each field means, not what it holds |
| `scripts/profile_temporal.py` | Temporal profile of a dataset - time as a dimension, in pure stdlib |
| `scripts/check-review-tools.sh` | Probes which analysers are installed (cached), so missing tools are skipped rather than re-invoked |

**Validators** (model, consent-free)

| Script | What it does |
|---|---|
| `scripts/validate_findings.py` | Validates a review findings pack against `docs/review/findings-schema.json`; a missing field is a hard error |
| `scripts/validate_masking.py` | Proves a masking config is safe and useful (residual-PII, detection fidelity, k-anonymity); `--in` scans an actual masked file |
| `scripts/validate_manifest.py` | Asserts every agent/skill/hook declared in the plugin manifest exists on disk |
| `scripts/validate_rtm.py` | Validates a Requirements Traceability Matrix against the code, tests and obligations it claims |
| `scripts/validate_references.py` | Reference checker for the framework's own internals - a link checker pointed inwards |

**Renderers** (model, consent-free)

| Script | What it does |
|---|---|
| `scripts/render_html.py` | Renders a Markdown artifact to a styled, standalone HTML file (inline CSS, shareable as one file) |
| `scripts/render_findings.py` | Renders a validated findings pack to the canonical `REVIEW-<slug>.md`; owns the report layout so finding format cannot drift |
| `scripts/render_docx.py` | Renders a Markdown artifact to a Word (.docx) document |
| `scripts/render_evidence_room.py` | One self-contained HTML pack per engagement, pulling together its artifacts for a single-file handover |

**Hooks and dispatchers** (run by Claude Code)

| Script | What it does | When |
|---|---|---|
| `.claude/hooks/guard-raw-data.py` | Blocks Read/Grep/Glob/Bash tool calls that target `data/raw/` | always on |
| `.claude/hooks/guard-code-execution.py` | Blocks execution of the code under review unless a human has opened the consent gate | team-invoked sessions |
| `.claude/hooks/guard-consent-writes.py` | Blocks model writes of the consent marker, the hook files themselves, git execution config and the session stamp | always on |
| `.claude/hooks/guard-consent-writes.py` (settings tier) | Blocks model writes of `.claude/settings*.json` | team-invoked sessions only |
| `.claude/hooks/guard-findings-pack-write.py` | Scopes the five advisory reviewer agents' Write/Edit to their own findings-pack JSONL only | always on |
| `.claude/hooks/run-guard.sh` | The guard launcher: probes `python3` → `python` → `py` and fails closed on a crash | always on |
| `scripts/bash_hook_dispatcher.py` | Runs the PreToolUse checks above (plus the redirects below) in one process instead of several | always on |
| `scripts/guard_daemon.py` | Persistent guard daemon - eliminates per-call interpreter cold start (ADR-014) | always on, default transport |
| `scripts/guard_daemon_client.py` | Client for `guard_daemon.py`, with a cold-start subprocess fallback | always on |
| `scripts/locked_menu_guard.py` | PreToolUse guard on `AskUserQuestion`: catches drift in the team's two locked menus | always on |
| `scripts/persona_anchor.py` | Per-turn persona + discipline re-anchor while an engagement is live; a no-op when dormant (ADR-005; staged copy in `scripts/staged_hooks/`) | engagement-scoped |
| `scripts/engage_probe_prefetch.py` | UserPromptSubmit hook: pre-runs the `/engage` step-0 probe before the model's turn | engagement-scoped |
| `scripts/prompt_hook_dispatcher.py` | Runs `persona_anchor` and `engage_probe_prefetch` as one `UserPromptSubmit` process | always on |
| `scripts/dod_stop_gate.py` | Warn-first Stop-hook DoD backstop: runs the mechanical check when a turn ends with an engagement still open (staged copy in `scripts/staged_hooks/`) | engagement-scoped |
| `scripts/todo_panel_nudge.py` | Stop-hook nudge: seeds the native task-list gate panel, warn-first and self-suppressing | engagement-scoped |
| `scripts/stop_hook_dispatcher.py` | Runs `dod_stop_gate` and `todo_panel_nudge` as one `Stop` process | always on |
| `scripts/document_input_redirect.py` | PreToolUse redirect: binary document reads route to the vendored converter instead of hand-parsing (staged copy in `scripts/staged_hooks/`) | engagement-scoped, fail-open |
| `scripts/module_form_redirect.py` | PreToolUse(Bash) redirect: rewrites module-form team-script calls in plugin mode | engagement-scoped, fail-open |
| `scripts/enumeration_redirect.py` | Bash PreToolUse cost rule: denies bare full-tree enumeration, naming the sanctioned inventory sources instead | engagement-scoped, fail-open |
| `scripts/exploration_redirect.py` | Read/Grep PreToolUse cost rule: redirects a whole-file Read or unbounded Grep once per target | engagement-scoped, fail-open |
| `scripts/session_resume_brief.py` | SessionStart re-brief after compaction or `--resume`: state and decisions recovered from disk (ADR-011; staged copy in `scripts/staged_hooks/`) | engagement-scoped |
| `scripts/post_edit_lint.py` | PostToolUse lint on Python files written during a live engagement, so defects surface one edit later, not at the gate (staged copy in `scripts/staged_hooks/`) | engagement-scoped |
| `scripts/subagent_return_budget.py` | PostToolUse feedback on Task completion: the condensed-return budget, mechanised | always on |
| `scripts/statusline.sh` | Statusline render: dormant-vs-engaged, active slug/status/phase, at zero context cost | statusline |

**Launcher / installer** (human, pre-session unless noted)

| Script | What it does |
|---|---|
| `scripts/virt_team_launcher.py` | `virt-surv go`'s decision engine, run before Claude Code starts: settings table, resume-or-new menu (arrow keys/mouse via vendored prompt_toolkit, plain fallback), inline settings editor and archiving, cache pre-warm; stdout carries only the pre-seeded prompt |
| `scripts/launcher_app.py` | Full-screen launcher app for `virt-surv go` |
| `scripts/launcher_textual.py` | The Textual rendering tier for the launcher |
| `scripts/launcher_tiers.py` | Textual widgets for the launcher's screens |
| `scripts/launch_terminal.py` | Opens a command in a new terminal window |
| `scripts/installer_app.py` | Full-screen screens for `virt-surv`, the installer/manager menu |
| `install_helper.py` (repo root) | Guided install/update of the plugin from a terminal: channel pick, clone/safe update, marketplace add, plugin install |
| `scripts/preflight.py` | What the launcher knows before it starts an action, in one declared table |
| `scripts/tui_chrome.py` | Shared terminal chrome for both front doors: `virt-surv go` and `virt-surv` |
| `scripts/questions.py` | One way to ask a person something, and one vocabulary for what they answered |
| `scripts/brand_banner.py` | The VSIT brand banner, rendered as terminal art for both front doors |
| `scripts/install-git-hooks.sh` | Installs the opt-in AI-review git hooks (pre-commit / pre-push) | human-only |

**Eval harness** (maintainer)

| Script | What it does |
|---|---|
| `scripts/eval_engage.py` | Headless live-`/engage` eval driver: runs a full engagement in a sandboxed repo copy and scores it |
| `scripts/eval_score.py` | Deterministic scorer for the eval harness: matches team findings against each golden case's ground truth |
| `scripts/headless_run.py` | Builds and reads a headless Claude Code run (`claude -p --output-format stream-json`) for the eval harness |

**Internal** (imported by other scripts/hooks, not invoked directly)

| Script | What it does |
|---|---|
| `scripts/fsutil.py` | Atomic file writes, shared by every script that persists state |
| `scripts/vsit_paths.py` | Where the team's files live in a project - the single source of truth |
| `scripts/findings_pack_io.py` | JSONL read/write for review findings packs |
| `scripts/find_plugin_root.py` | Locates the compliance-surveillance-team plugin root, for the `/engage` step-0 bootstrap |
| `scripts/dlp_guard.py` | Hard-rejects content containing blocked keywords (employer, colleague names, internal hosts); a `git` pre-commit/CI scanner, not a Claude Code hook |
| `scripts/audit_screens.py` | Dev diagnostic: every menu option and screen, and whether each is actually wired |
| `scripts/tier_probe.py` | Dev diagnostic: why did (or didn't) the Textual tier draw |

**Maintainer** (human-only; supports releases of this repo, not engagements)

| Script | What it does |
|---|---|
| `scripts/release_gate.py` | The mechanical dev → main promotion gate: version/badge/CHANGELOG consistency + a current eval baseline |
| `scripts/dashboard.py` | Local observability page: engagement inventory, DoD gate, map hygiene, consent highlight, measured token cost - run `python -m scripts.dashboard` |
| `scripts/try_engagement.py` | `virt-surv try`: one command, one minute, a closed synthetic review engagement in a throwaway project with its evidence room opened in the browser; every step is a team script, no model call (2026-09-13) |
| `scripts/armed_check.py` | Proves the guards fire in a project: synthetic tool calls through the real launcher and dispatcher expecting the raw-data block, the execution gate and the plugin enabled; the installer's last step and `--selftest` print its one line (2026-09-13) |
| `scripts/prune_eval_runs.py` | The eval-run retention rule as a command: keeps cited and recent runs, trims sandboxes from the rest, purges old uncited runs; dry run by default, `--apply` deletes |
| `scripts/keep_golden_run.py` | Copies one passing eval run's scoring inputs and workspace subset into `evals/golden-runs/` for CI's token-free replay; refuses a run the current scorer would fail |
| `scripts/pin_release_tools.py` | Regenerates `config/release-tools.json`, the pinned version and SHA-256 per asset for every binary the installer downloads, from the publisher's release API; human-run at release time, `--check` reports drift |
| `scripts/pin_python_requirements.py` | Regenerates the hash-pinned `requirements-*.lock` files (every file PyPI publishes per pinned version, resolved per platform and unioned); human-run at release time |
| `scripts/sbom.py` | A CycloneDX 1.5 SBOM from `vendor/MANIFEST.md` and `requirements-dev.lock`; CI uploads it as an artifact and a release attaches it |
| `scripts/check_pdf_links.py` | Refuses a tracked PDF whose link annotations point at the author's local filesystem; a CI step |
| `scripts/apply-staged.sh` | The one human-run promotion step (2026-09-13, plan step 3.6): moves every pending file in `scripts/staged_hooks/` to its live path (`guard-*` and `run-guard.sh` to `.claude/hooks/`, the rest to `scripts/`) and deletes the staged copy; `--dry-run` lists. The staging directory is empty at rest and the suite is red while anything is pending. Never run by an agent, per this project's house rules; shipped releases come pre-wired. |

<sub>[↑ Back to top](../README.md#readme-top)</sub>
