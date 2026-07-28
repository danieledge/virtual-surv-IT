# Engagement flow specification - complete diagram brief

Purpose: a complete, diagram-ready description of every hook, guard, gate, step, branch,
loop and artifact in the compliance-surveillance team's engagement workflow (v0.29.0). Written
to be handed to a diagramming assistant. Nothing user-visible is omitted.

**Suggested rendering:** swimlane flowchart with five lanes - **User (human)** · **Morgan
(PM/orchestrator)** · **Specialists (subagents)** · **Hooks & guards (automatic)** · **Artifacts
on disk**. The hook lane fires across all phases (it intercepts tool calls), so draw hooks as a
horizontal always-on band rather than a sequential step. Decision diamonds are marked ◇ below;
loops are marked ⟲; artifact writes are marked 📄. A companion legend node should explain the
state emoji (⏳ in progress · ⛔ blocked · ✅ closed) and evidence tags (📊 observed/measured ·
🧠 inferred · 📄 coded).

---

## Layer 0 - always-on hooks and guards (active even when the team is dormant)

These run on EVERY session in the project, engagement or not. Draw each as: trigger → condition
→ allow / block (with the block message returned to the model).

1. **Permission deny rules** (`.claude/settings.json`): hard-deny Read/Grep/Glob/Write/Edit on
   `data/raw/**` (any depth), and Read on `.env*`, `secrets/**`, `*.pem`, `*.key`.
2. **guard-raw-data.py** (PreToolUse on Read|Grep|Glob|Bash): blocks any tool call that would
   touch `data/raw/` - raw transaction/comms data must never reach the model. Always-on.
3. **guard-code-execution.py** (PreToolUse on Bash): splits the command on `; && || | \n \` $(`,
   then per segment:
   - ◇ segment matches the TEAM ALLOW list (`python -m scripts.*`, `python scripts/...`,
     bundled-copy path invocations of the team script basenames, `bash scripts/*.sh`) → allow
     consent-free (team tooling is not "code under review").
   - ◇ segment matches the execution pattern (python/pytest/node/etc. running other code) →
     ◇ does `.claude/.exec-consent` exist OR `CST_ALLOW_EXEC=1`? → yes: allow; no: BLOCK with
     a message explaining the consent mechanism. Lexical fail-open residual risk is documented
     (ADR-002): it is consent-recording plus a safety net, not a sandbox.
4. **guard-consent-writes.py** (PreToolUse on Write|Edit|MultiEdit|NotebookEdit|Bash): blocks
   any MODEL write to `.claude/.exec-consent`, settings files, or hook files - the model can
   never grant itself execution consent or weaken a guard. Read-only mentions (echo/grep of
   the filename) are allowed; every write path (redirect, touch, cp, sed -i, command
   substitution) blocks.
5. **persona_anchor.py** (UserPromptSubmit): ◇ is the engagement live? State-first (ADR-006):
   a parseable `$CLAUDE_PROJECT_DIR/artifacts/engagement-state.json` is authoritative
   (`in_progress`/`blocked` arms even before START-HERE is rendered; `closed` silences even
   over a stale ⏳ render); fallback: START-HERE.md exists with status ⏳ or ⛔. → yes: inject
   a ≤8-line Morgan persona/discipline anchor into the turn (survives conversation
   compaction); no: silent. Anchored to the session's project root, never the shell's
   wandering cwd.
6. **dod_stop_gate.py** (Stop hook, warn-first): fires when the model tries to end its turn.
   ◇ same state-first liveness check → run the mechanical DoD checker over `artifacts/` →
   ◇ findings? → yes: block the stop ONCE with the finding list framed as a FIX-LIST (auto-fix
   the deterministic ones, escalate judgement calls, or end plainly saying "NOT closed -
   outstanding: ..."); the nudge does not re-fire in the same stop cycle. No open engagement or
   clean check → silent.

## Layer 0b - dormancy switch

◇ Did the user invoke the team? (`/engage`, another team command, or asking in words for "the
team" / "Morgan" / "the PM") → NO: everything below stays inert; the session behaves as plain
Claude Code (only Layer 0 stays armed). → YES: activate Morgan and enter Phase 1.

---

## Phase 1 - open (engage step 0)

1. **Single compound probe call** (one Bash invocation, no narration turns): loads the
   operating guide (repo or resolved `$PLUGIN_ROOT` copy via the install registry, else a
   cache/marketplace find), the Python interpreter (`python3` → `python` → `py`), the run mode
   (repo-as-project vs installed plugin), the plugin version, the analyser inventory
   (`check-review-tools.sh`, 7-day cache), the codebase map header + §3 engagement history
   (§2 bodies stay unread - just-in-time), and the newest CHANGELOG block.
2. **Opening banner** (always the very next output): 🎩 Morgan intro + team version + offer of
   `/meet-the-team` + run mode. ◇ What's-new: loaded version ≠ last map-recorded Team ver →
   one-line "Since last time (vX → vY): ..." · no prior record → "In the current release
   (vY): ..." · versions match → nothing. Changelog unreadable → silently omit (never surface
   probe mechanics).
3. ◇ **Bare `/engage` (no concrete target)?** → YES: banner + ONE question only ("where is the
   code / input?") and wait; the gated questions below are undecidable before a target exists.
   → NO: continue.
4. **Safety gates** (when a target exists and code/data is involved) - two VERBATIM
   disclaimers shown as loud callouts, then a single batched AskUserQuestion call containing
   only the applicable questions (tool limits: ≤4 questions/call, ≤4 options each, short
   headers, "Other" auto-added):
   - **Execution-safety disclaimer** (static-by-default; user responsible for handed-over code
     being safe to run).
   - **Data-safety disclaimer** (everything shared goes to the model provider; `data/raw/`
     hard-blocked; user attests shared data is clean; pseudonymised ≠ anonymous).
   - ◇ **Work-type** (only if genuinely ambiguous): problem / review / build.
   - ◇ **Execution consent - INTENT question** (only when code involved; default No):
     - "Yes - I'll grant consent" → Morgan gives the user the absolute-path command to type
       themselves (`! touch <abs>/.claude/.exec-consent`; PowerShell/cmd variants on Windows);
       the HUMAN creates the marker; Morgan verifies it exists before any execution; if it
       never appears, execution stays blocked and dynamic findings stay 🧠 inferred.
     - "No - static only" → any existing marker is DELETED (fail-safe close).
   - ◇ **Data attestation** (only when data plausibly involved): "Yes - synthetic/masked, no
     prohibited PII" / "No or unsure" → route to `/prepare-data` (masking pipeline: ingest +
     masking-schema + validate_masking, key from MASKING_KEY; prefer fully synthetic) /
     "No data involved" (recorded silently otherwise).
   Answers recorded once - never re-asked per file or command.

## Phase 2 - classify and gather

1. ◇ **Classification**:
   - **Problem / idea** → discovery → requirements (`/write-brd`, `/elicit-requirements`,
     `/brd-to-fsd`) → build (full SDLC).
   - **Review** → the review path (step 1b below) via `/audit-review` mechanics; ◇ when the
     code touches a security-sensitive surface (auth, parsing, DB, external I/O, crypto,
     secrets, PII), offer "review + dedicated `/security-audit`" (recommended) vs review only
     - re-offered at the review's close as a backstop.
   - **Build from requirements** → `/build-solution` (orchestrator-workers).
   - **Phased engagements re-classify per phase**: the moment any phase produces deliverable
     code it runs under the build chain (reviewer + independent QA + DoD) regardless of how the
     engagement started.
   - Deliverable can be ANY surveillance-engineering output: detection rule, pipeline/ETL,
     utility script, reconciliation/reporting job, tooling, review - route by type, never
     assume detection rule.
2. **Inputs first (step 1a)**: ◇ target/spec/data present? → NO: ask where it is (path, repo,
   branch, commit range, paste) and WAIT; verify it exists before proceeding; never invent a
   target. Sub-workflows are chained by READING their SKILL.md and following it in-session
   (dormant skills are not model-invocable).
3. ◇ **Review-type menu (step 1b, LOCKED wording, one call, three single-select questions)**:
   - Q1 Depth: **Quick** (changed code, 🔴/🟠) ⊂ **Deep** (+architecture, 🟡, impact,
     coverage) ⊂ **Audit** (Deep in audit-readiness mode, pre-existing issues in scope) ·
     **None**.
   - Q2 Performance review: Yes (static, findings 🧠/📄, vs target volumes) / No.
   - Q3 Fix-cycle (single source of truth, never re-asked): **Report only** / **Apply fixes** /
     **Fix → re-review loop** ⟲ (repeat until no Criticals or the user stops).
   - ◇ Q1=None AND Q2=No → nothing to run: say so, return to the outcome question.
4. **Clarifications (step 2)**: fold material unknowns (jurisdiction, success criteria) into
   the batched calls; no ceremonial "anything else?" round. ◇ Changing user code needs
   explicit approval (Apply fix? menu) unless Q3 already authorised it.

## Phase 3 - plan and gate

1. ◇ **Artifact menu (step 3, LOCKED two-stage)**: Stage 1 packaging - **Consolidated Delivery
   Report** (default) / Separate artifacts / Both. Stage 2 (only if Separate/Both) - one
   batched call of grouped multi-selects: Spec docs (Brief · BRD · FSD · RTM) · Reviews (Code
   & Compliance · Performance · Model Validation · ADRs) · Handover (Developer · QA · Ops
   Runbook + Release Notes · Change Request); rarer templates via "Other". Every artifact
   ships `.md` + `.html`.
2. 📄 **Engagement Brief** written (decisions, assumptions, open questions, routing plan) and
   📄 **the machine-readable state opened in the same breath** (ADR-006):
   `engagement_state init` creates `artifacts/engagement-state.json` (status ⏳,
   ⚠️-outstanding pre-seeded with the gates ahead: independent QA, DoD) and renders
   📄 **START-HERE.md** + `.html` from it. The state file is authoritative; START-HERE is its
   generated view and is never hand-edited. From here on: every artifact write is recorded
   with `add-artifact` IN THE SAME TURN, which re-renders the index (state leads reality - it
   is the engagement's external memory and survives compaction).
3. ◇ **Go-ahead gate** (question tool): Proceed as briefed / Adjust / Stop.

## Phase 4 - delivery (agile loop) ⟲

1. **Right-sizing, stated out loud** before any fan-out: one line naming how many agents and
   why (multi-agent ≈ 15× tokens; leanest set that fits; 1 agent for fact-finding, 2-4 for
   comparisons, minimal sufficient chain for delivery).
2. **Routing table** (deliverable → owner; roster of Morgan + 16 named specialists):
   spec/requirements → Amara (business-analyst) · detection rules → Mateo (rules-developer) ·
   pipelines/utility scripts/infra → Kenji (platform-engineer) · exploratory/FP/reporting
   analysis → Ana (data-analyst) · threshold calibration → Theo (tuning-analyst) · ML → Mei
   (ml-engineer) with independent validation → Viktor (model-validator) · independent QA →
   Linh (qa-engineer) · code review → Ravi (code-reviewer) · performance → Thabo
   (performance-reviewer) · compliance/audit → Layla (compliance-reviewer) · data-quality /
   coverage assurance → Yuki (data-quality-reviewer) · domain advice → Hassan (tm-sme) /
   Camila (trade-surveillance-sme) / Cleo (comms-surveillance-sme) · mechanical
   scoring/lens-routing → Pip (review-scorer). Model tiers: opus for last-word judgement
   (model-validator, compliance-reviewer, code-reviewer, ml-engineer) and the orchestrator;
   sonnet for build/advisory/static review; haiku for review-scorer.
3. **Agent constraints**: advisory agents (*-sme, model-validator, code-reviewer,
   performance-reviewer, compliance-reviewer, data-quality-reviewer) hold NO Write/Edit - they
   recommend and hand back; build agents implement. Every delegation brief is explicit and
   non-overlapping (objective · scope boundary · inputs · output format · hard return budget
   ≤ ~1,500 tokens - detail goes to the artifact, the "blackboard" coordination medium).
4. **PM challenge (sceptic, not relay)**: spot-check don't re-score - challenge every
   Critical, anything regulated, thin evidence, a sample of the rest AND a sample of the
   filtered set (promote wrongly-filtered findings); verify evidence tags (📊 vs 🧠 vs 📄 -
   never let inference reach the user as fact).
5. **Code chain (no exemptions)**: deliverable code → tests (project's own framework, exact
   command recorded) → code review ⟲ (fix cycles per Q3) → INDEPENDENT QA by Linh ⟲ (test
   cycles append-only, failed verdicts preserved as-found; QA evidence and suites PRESERVED
   under artifacts/, never deleted) → DoD. ◇ Execution consent withheld → static-only path:
   QA verdict stays 🧠, DoD marked PARTIAL, untested code named as residual risk, close offers
   "grant consent → suite runs → verdict upgrades". No hard limit exists on QA/fix cycle
   count - the brakes are the user at each gate (interactive) or budget/turn caps (harness).
6. **Interim naming discipline** 📄: pre-close outputs use pass-scoped names (review-pass-N,
   qa-cycle-N, interim-*) and every content artifact opens with the one-line interim banner;
   `delivery-report.md`, `final-*`, `REVIEW-<slug>.md` and the summary email are CLOSE-ONLY
   names. Iteration history is evidence: iteration log, test-cycles table, clarification
   rounds - append-only, never rewritten.
7. **Every critique names an external standard** (5 C's for findings, BABOK criteria for
   requirements, ISO/IEC 29119 shape for QA evidence, SR 11-7-style expectations for
   validation docs); critic is never the author.

## Phase 4a - blocked path ◇

Turn ends needing user input the team cannot proceed without → `engagement_state set-status
blocked` + `add-outstanding` per item (unanswered questions AND every gate not yet run; each
command re-renders START-HERE to ⛔), end the turn stating plainly "this engagement is NOT
closed - outstanding: ...". No summary email, no delivery report (SUMMARY-BEFORE-CLOSE /
FINAL-BEFORE-CLOSE defects if written). **Resume**: user answers → `set-status in_progress` +
`resolve-outstanding`, log the answer, continue ⟲. **Cold resume** (new session, even after
interruption): the fresh session reads `engagement-state.json` (authoritative; structured
status, outstanding, decisions) with START-HERE + interim artifacts as the human record,
honours recorded decisions/evidence without re-litigating, completes the outstanding list top
to bottom, and closes properly (proven live 2026-07-25, pre-state; state file since ADR-006).

## Phase 5 - close (only path to ✅)

Ordered close checklist:
1. **Citations gate**: run `check_citations`; TO-VERIFY citations ship FLAGGED (never block
   the close, never a close-time verification question) with source permalinks resolved:
   register URL → register header scheme construction → official search / "link to be
   confirmed"; never invent a plausible URL. Standard limitations note added to report +
   one-liner in the email; user later says "mark X verified" → register overlay updated.
2. **Mechanical DoD gate**: `check_artifacts --fix`, treated as a FIX-LIST ⟲ (fix, re-run,
   until only judgement items remain):
   - AUTO-FIX (never handed to the user): MISSING-HTML (render), MISSING-INDEX / STALE-INDEX /
     INDEX-NO-STATUS (fix the living index), STATE-STALE-RENDER (re-render START-HERE from
     `engagement-state.json`, ADR-006; STATE-INVALID / STATE-MISSING are fix-the-state items,
     never auto-fabricated), ROSTER-UNKNOWN / ROSTER-ROLE-MISMATCH (correct
     persona names to the canonical roster), missing interim banner or premature "final",
     FINAL-BEFORE-CLOSE / SUMMARY-BEFORE-CLOSE / SUMMARY-WRONG-EXT, STALE-STATUS (banner
     surviving close), non-portable absolute paths, incomplete source index, missing evidence
     tags, CODE-NO-TESTS / CODE-NO-QA (route to the missing chain step).
   - ESCALATE via the question tool (never self-fix): evidence contradictions ("the email says
     X but the artifact says Y"), sign-off on unverifiable authority, scope/acceptance calls,
     RATIFIED-CLAIM-PENDING (an artifact asserts an approval the state records as pending -
     never self-ratify) and REVIEW-FINGERPRINT-GAP (shipped code no review fingerprinted -
     delta review or explicit DoD disclosure).
   - STALE-DOCSTATUS: document-control Status still Draft/In-review under a ✅ index - close
     it out or state "pending human sign-off" explicitly (judgement item).
3. **Close-time reconciliation sweep** (every produced/touched document, INCLUDING
   code-adjacent README and module docstrings): one authoritative set of counts / ranges /
   findings enumerations everywhere; late-cycle changes propagated into every stale sibling;
   struck citations swept from every file; no prose referencing removed interim state;
   document-control statuses closed out; QA evidence retained on disk (a 📊 measured tag with
   no surviving artifact downgrades to 🧠 inferred).
4. **Codebase map update** (ADR-003, a DoD gate) 📄: durable architecture facts with 📊/🧠
   tags, dates, SHA anchors; corrections/deprecations dated; §3 history row appended; maps the
   CODE never the team's activity; PM-written, ≤~200 lines.
5. **Render everything** 📄: every `.md` artifact gets its `.html` sibling.
6. 📄 **Delivery Report** (close-only, consolidated by default) and 📄 **engagement-summary
   email**: `.txt` in artifacts/ (the one artifact never rendered to HTML), signed as Morgan,
   "Hi," when the requester's name is unknown, states the engagement footprint (approx tokens
   + agent count), repeats the execution/data responsibility notes, NEVER offers a call or
   meeting - next steps are actions. Written only now, at close.
7. **Finalise the state last of all** 📄: `engagement_state set-team ...` +
   `finalise-artifacts` + `set-footprint`, then `set-status closed --verdict "..."` (the
   close refuses on an empty team or any interim artifact row) - sets the close date, clears
   ⚠️-outstanding to "Nothing - closed <date>", and re-renders START-HERE to ✅ CLOSED;
   interim banners stripped from artifacts that became final. The state flip to closed is
   the FINAL state change.
8. **Close with next steps**: short summary + concrete options with a recommendation + offer
   to carry them out; a dead end is a PM failure. Human sign-off remains the one DoD item only
   the user can perform.

## Definition of Done (the gate the close must satisfy)

Traceable (RTM spine BRD → FSD → code → test → regulatory obligation) · tested (known
true/false-positive cases, exact command recorded) · independently QA'd (full cycle history,
evidence preserved) · code-reviewed (no open Criticals, dispositions, developer-guidance
section) · performance-reviewed and compliance-reviewed where routed · critiqued against a
named standard · reconciled at close · dual-format artifacts · summary email · truthful
lifecycle state throughout · human sign-off. Static-only variant: DoD PARTIAL with named
residual risk when execution consent was withheld.

## Artifact inventory (what exists on disk, by phase)

Open: the engagement's WORKSPACE `artifacts/<slug>/` (ADR-008; several engagements may
coexist at independent states - root `engagements.json`/`ENGAGEMENTS.md` is the derived
registry) containing engagement-brief.md/.html · engagement-state.json (authoritative
lifecycle state, ADR-006) · START-HERE.md/.html (rendered from the state on every mutation).
Delivery (as routed): fsd.md · rtm.md · review-pass-N.md · qa-cycle-N/qa-handover.md ·
interim-*.md · the deliverable code + tests + QA suites · analysis packs - each with .html.
Close: delivery-report.md/.html · developer-handover.md/.html (if chosen) ·
engagement-summary-<slug>.txt · docs/codebase-map.md (working project) · finalised
START-HERE. All artifacts/ content is git-ignored by the team repo's own hygiene.

## Sub-workflow index (all 23 commands; each re-enters this flow at the matching phase)

/engage (front door) · /engage-light (explicit low-ceremony profile: same safety gates and
code chain, one-page brief, 2-3 agents, short summary email but no delivery report; refuses
detection logic and upgrades to standard) · /meet-the-team · /prepare-data · /demo · /write-brd ·
/elicit-requirements · /brd-to-fsd · /new-scenario · /build-solution · /analyse-data ·
/tune-thresholds · /validate-tm-model · /assess-coverage · /reg-change-impact · /deep-review ·
/audit-review · /security-audit · /performance-review · /remediate · /handover ·
/beta-assess-quantexa · /run-evals (eval harness; plus scripts.eval_engage for live
orchestration evals with --rescore and --resume-run).

## Cross-cutting rules (annotate as a side panel, they apply everywhere)

- Every clarification/choice via AskUserQuestion (≤4 questions/call, ≤4 options, headers,
  single-select for exclusive axes, multi-select for independent picks, one axis per question).
- 🎩 first line of every Morgan turn; specialists referred to by name; console kept clean
  (detail in artifacts, not the TUI).
- Evidence basis on every data claim: 📊 observed/measured · 🧠 inferred · 📄 coded.
- Memory: general lessons → house rules; engagement-specific → the working project's own
  CLAUDE.md / codebase map; the plugin itself accrues no project memory.
- Compaction resilience: START-HERE as external memory + the persona anchor re-injected each
  user turn while an engagement is open.
- Right-sizing and the ~15× token multiplier stated at every fan-out gate.
