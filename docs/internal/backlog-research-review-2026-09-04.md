# Backlog - research-review items not taken (2026-09-04)

From the external research review of 2026-09-02 (full report, untracked, at
`docs/internal/research-review-2026-09-02.md`). Four items were applied on 2026-09-03 and are
not repeated here: blind-first review in `code-reviewer`, the framing-cue row in
`docs/operating-guide.d/untrusted-content.md`, spec-before-builder's-tests in `qa-engineer`, the test-gaming check in
the bugs lens, and the per-spawn pricing that replaced the flat ~15x.

Everything below is parked with the reason. Ordered by value per unit of cost, not by interest.

---

## 0. REJECTED, do not re-propose: relaxing the reviewer reporting posture

The review recommended removing "flag only gaps that affect correctness, safety or the stated
requirements... do not manufacture findings" from the five reviewer prompts, on the vendor
guidance that Opus 5 follows a conservative instruction literally and under-reports, with
filtering left to a separate pass.

**Tested and rejected, 2026-09-03.** A three-case before-pass (`review-seeded-bugs-py`,
`review-sql-injection`, `review-clean-code`, dispatched to `code-reviewer` directly so the
prompt was the only variable) scored **recall 1.0 on both seeded cases**: 4/4 planted found on
one, 2/2 on the other, from 16 and 10 findings respectively on short files. There is no recall
headroom for "report everything" to recover. Both failures were **precision** failures, and one
was real: `review-seeded-bugs-py` tripped forbidden trap FP-1 by flagging `LARGE_ORDER_MULTIPLE`
as lacking rationale when the constant carries `# >=5x trader median = outsized (calibrated
2026-06-18)`.

So the change would push on the axis already passing and worsen the axis already failing. The
after-pass was not run: the before-pass settles it. This is a second datapoint alongside
`docs/agent-design.md:119-129` that more/looser checking scores worse here.

**What would reopen it:** evidence of a real recall miss traceable to the restraint line, on a
case where the planted finding exists and is not reported.

---

## 1. Statistical literacy in the release gate

**What.** In `scripts/release_gate.py` and `scripts/eval_engage.py`: Wilson interval on
per-baseline recall and pass-rate; paired **McNemar** against the previous baseline over the
shared case set (cases are identical across versions, so the pairing is free power); refuse to
call a delta a regression or improvement inside the interval, printing the discordant cases by
name instead; a `judge_samples: 3` option recording median and spread, with a high spread
marking a case `unadjudicated` rather than passed.

**Why.** `evals/README.md:154` sets the minimum baseline slice at 6 distinct cases, scored by a
single-sample judge with pass/fail read off raw counts. At that n a large recall drop is inside
noise, and the release gate is the only mechanical control on prompt drift
(`docs/DEFINITION-OF-DONE.md:108-114`). The review's headline finding.

**Cost.** Judge calls triple; the judge is a small fraction of a case's spend. No pip needed
(Wilson and exact McNemar are a few lines; `scipy` optional). More cases land as
`unadjudicated` and need a human read, which is the intent.

**Blocked on.** Nothing but effort. Owner deprioritised on 2026-09-03 in favour of
execution-edge items.

## 2. Judge sentinels

**What.** `evals/judge-sentinels/`: six to ten hand-labelled review outputs including a
known-good, a known-bad, a paraphrased twin, a verbosity-padded twin and a label-flipped
variant. `/run-evals` grades them first; a misgrade drops that baseline's qualitative scores to
advisory-only.

**Why.** Judges show test-retest reliability above 0.95 while carrying severe systematic bias, so
a repeatable judge is not a valid one. Pairs with item 1: the interval is meaningless if the
measurement is biased.

**Blocked on.** One-off owner labour to author the sentinels. Cannot be delegated to the model
without defeating the point.

## 3. Refutation record on the challenge object

**What.** The agreed optional `challenge` object on `docs/review/findings-schema.json` records
**what disconfirming evidence was sought and whether it was found**, not merely that a finding
survived. Ordering rule for Criticals: the PM reads the `location` source before the finding's
`problem` text. At Audit depth only, each Critical goes to one small fresh-context spawn briefed
with the finding as an **external claim**.

**Why.** A model corrects the same error near-zero when it sits in its own reasoning trace and
far more often when the identical claim is presented as external content. Today the challenge
pass edits the pack only on downgrade or drop (`deep-review/SKILL.md:205-207`), so a Critical
that was attacked and held up is byte-identical to one nobody looked at.

**Cost.** Zero at Deep; one ~5-10k spawn at Audit. Now affordable: the flat ~15x that deterred
small spawns was replaced with per-spawn pricing on 2026-09-03.

**Risk.** Over-pruning true positives if the refuter is briefed to win. Brief it to seek
evidence, not verdicts.

**Deliberately NOT included:** the `CRITICAL-UNCHALLENGED` check in `check_artifacts`. That can
fail a close, so it waits until the record has run unenforced for a while.

## 4. Cross-language security analysis (semgrep)

**What.** Opt-in `semgrep: on` in the review-tools config with vendored rule files,
`SEMGREP_SEND_METRICS=off`, `SEMGREP_ENABLE_VERSION_CHECK=0`, and a 5-second pre-flight probe
that fails fast.

**Why.** `code-reviewer.md:76-86` gives bandit for Python and gitleaks language-agnostic, and
nothing security-side for Scala, Java or TypeScript, against seven advertised languages.

**Blocked on.** `code-reviewer.md:121` records semgrep and pip-audit as deliberately excluded
after the 2026-08-04 measurement that offline flags still hung (semgrep issue #8793 confirms
residual calls). The pip constraint was lifted on 2026-09-02; the **network** constraint was
not. Needs the probe to be proved to fail fast rather than hang, in a real corporate-proxy
environment, before the default changes. Also needs a `_TEAM_SCRIPT_NAMES`-style review of the
tools config per the existing two-tier on/off/auto pattern.

## 5. Dependency-vulnerability coverage (pip-audit or equivalent)

**What.** Same shape as item 4. An entire finding class is currently invisible.

**Blocked on.** Same network constraint. The bank-compatible relaxation is an internal artifact
mirror URL declared in `VSIT/config/extensions.md` (ADR-009, the sanctioned extension surface)
and nothing else. Needs a decision that a declared registry URL is an acceptable exception to
"no runtime network", which is a policy call, not a build one.

## 6. Invisible-character scan on the context surfaces

**What.** A context-file scanner under `scripts/` (not yet built, so deliberately unnamed here:
this repo's reference check refuses a doc that cites a path with no file behind it), wired into
the engage probe: U+E0000-E007F, zero-width and
bidi overrides across `VSIT/config/extensions.md`, `VSIT/shared/map.md` and a foreign project's
`CLAUDE.md`; record the sha256 of `extensions.md` at first honour in `engagement-state.json` and
flag drift.

**Why.** The 10 Feb 2026 Anthropic patch rejects Unicode tag characters in **skills**, not in
arbitrary files the team Reads at operator level. Those three are exactly the memory-file surface
the CSA context-poisoning note describes.

**Blocked on.** A new `scripts/` tool needs its basename added to the guard allow-list
(`_TEAM_SCRIPT_NAMES`), staged by the model and **applied by the human**, or plugin-mode users
get a consent prompt for the team's own tooling. Cheap to build, gated on that human step.

## 7. Regulatory currency: SR 11-7 is rescinded

**What.** SR 11-7 was rescinded on 17 Apr 2026 and replaced by **SR 26-2** / **OCC Bulletin
2026-13** with a parallel FDIC statement (verified by search, 2026-09-02). It excludes
generative and agentic AI from scope, narrows "model" to exclude deterministic rule-based
processes (which changes what `model-validator` may claim about a threshold rule), replaces
prescriptive independence mechanisms with "sufficient independence", and withdraws SR 21-8 /
OCC Bulletin 2021-19 on BSA/AML models alongside it.

**Where.** `CLAUDE.md:150`, `docs/scope-and-stack.md:20,30`,
`docs/WAYS-OF-WORKING.md:106,121,125,201`, `docs/DEFINITION-OF-DONE.md:183`,
`docs/glossary.md:44`, plus the templates that name it.

**Why parked rather than done.** It is a docs-only change with no behaviour effect, and the
BSA/AML withdrawal means the TM model-validation pack's framing needs a considered rewrite
rather than a find-and-replace. Also affects `docs/scope-and-stack.md`, which ships as an
example default users are told to customise.

## 8. Deterministic subagent caps

**What.** `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` (default 20, proposed 8, above the largest
real fan-out on record) and `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` (default 3, proposed 1) in
`.claude/settings.json` `env`.

**Blocked on.** Owner decision, deferred 2026-09-03. `settings.json` is behind the consent-write
gate so this is human-applied regardless. The live tension: these apply to **every** session in
the project, including dormant ones where the team is not engaged, so depth=1 constrains the
owner's own non-team work. Concurrency-only is the lower-friction half.

## 9. `effort:` frontmatter tiering on the reviewers

**What.** Vendor guidance states review accuracy holds at lower effort settings, so
Quick/Deep `code-reviewer` at medium and Audit at high would be a free token cut. No agent
currently carries an `effort` key; frontmatter today is `name`, `description`, `tools`, `model`.

**Blocked on.** Unverified. The claim came via the review and was not independently checked, and
it interacts with the model tiering in `docs/agent-design.md` that would need to stay in sync.
Cheap to test once item 1 makes a before/after measurable.

---

## Open defect found while testing, partially fixed

`scripts/eval_score.py:203` builds its keyword haystack from title + kind + **location**, so a
forbidden trap keyed on a bare identifier fires on any finding whose location merely names that
function. `review-sql-injection` FP-1 (keyword `find_alerts_by_trader`) produced a **false
failure** on 2026-09-03 against a review that had explicitly cited that function's parameterised
query as the correct pattern to copy.

**Fixed at the case level** by adding `min_severity: warning` to that trap, with the reasoning
in the case file: the trap describes a warning-or-worse claim, so a style nitpick sharing the
function name should not trip it.

**Not fixed at the class level.** Any other case using a bare identifier as a trap keyword has
the same exposure. Deliberately not fixed in the matcher: changing the haystack would move every
existing baseline, and the release gate has no interval (item 1) to tell a real move from noise.
Sequence these: item 1 first, then revisit the matcher.

---

## 11. Finding fingerprints, so a disposition survives the next review

**Added 2026-09-10.** Idea taken from CPGuard (https://github.com/KimJeju/cpguard,
Apache-2.0), whose rescans inherit the previous verdict by fingerprint: same rule, same
file, same normalised sink code, therefore same audit state and same note. The scanner
itself is too young to depend on (8 stars, essentially one author, self-reported OWASP
Benchmark accuracy of 0.717 on Python) but the verdict mechanic is right and is ours to
take.

**The problem.** A review finds something, the user accepts it with a reason, and three
months later the next review reports the identical thing as new. The old decision exists
in the previous findings pack and nothing connects the two, so it is re-decided or
re-argued. The carry-over rule added on 2026-09-10
(`docs/operating-guide.d/artifacts-lifecycle.md` §Carry-over at open) has the PM re-read
the prior pack and match findings by eye, which is the manual version of this.

**What to build.** A `fingerprint` field on `docs/review/findings-schema.json`: a short
stable hash of **rule + file + normalised code at the location**. Deliberately NOT the line
number, which moves whenever anything above it is edited. Normalising whitespace and
formatting means a finding that merely moved is recognised as the same one, while a finding
whose code genuinely changed gets a new fingerprint and correctly comes back for a fresh
look.

Then at review time, before findings reach the user: match fingerprints against the
previous pack, carry `disposition` and its note forward on a match, and mark anything
unmatched as new. The user is only asked about what they have not already ruled on.

**Why it fits here.** It makes the carry-over rule mechanical rather than manual, it pairs
with the `challenge` record (item 3) and the `reviewed_by` field, and it is a schema
addition plus a comparison step rather than new machinery. Canonical hashing is already
solved: `rfc8785` plus stdlib `hashlib`, per item 9's provenance note.

**Watch for.** A fingerprint that is too loose silently inherits a decision for a finding
that has actually changed, which is the failure mode that matters: prefer a fingerprint
that changes too often over one that changes too rarely. Renaming a file should be visible
as new rather than silently inherited, at least until there is evidence that is annoying.

**Sequence.** 0.39, alongside the challenge record. Not before item 1: without an interval
on the eval gate there is no way to tell whether the inheritance rule is helping or hiding.
