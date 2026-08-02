# ADR-012: The persona layer - named specialists, their cost, and the identity requirement underneath (proposed)

> Architecture Decision Record (Nygard format). One file per significant decision, so the
> *why* is auditable later. Authored in `.md`, rendered to `.html`.

> **Document control** · ID `ADR-012` · Version `0.3` · Status `Proposed`
> · Classification `Internal` · Owner 🤖 Morgan (PM), Virtual Surveillance IT · As-of `2026-08-02`
>
> | Version | Date | Author | Change |
> |---|---|---|---|
> | 0.1 | 2026-08-01 | 2026-08-01 framework audit, persona-layer finding | Initial proposal: the cost of the named roster stated in full, three options put to the human approver, no decision taken |
> | 0.2 | 2026-08-02 | human approver (proposed in review) | **Option D added**: the model writes the ROLE and the display name is resolved mechanically. Dominates A-C by treating the name as derived presentation rather than authored content, the pattern ADR-006 already set for engagement state. Largely pre-built: `_ROLE_TO_NAME` and the render/auto-fix steps already exist |
> | 0.3 | 2026-08-02 | measurement correction | Option D's token-saving claim MEASURED and **retracted**: the shipped anchor is ~222 tokens and carries no name map, so D saves ~$0.04 across a $62.48 eval slice (0.07%). D's case is correctness and maintenance, not cost |

| | |
|---|---|
| **Status** | **Proposed** - the decision belongs to the human approver. Nothing changes until that ruling; the roster ships exactly as it is today |
| **Date** | 2026-08-01 |
| **Deciders** | Human approver (sole decider on this one); 🤖 Morgan (PM) drafts and implements whichever option is chosen |
| **Traceability** | ADR-005 (persona re-anchoring hook, `scripts/persona_anchor.py`); README "Known issues" (persona decay + name drift); `docs/team-operating-guide.md` §"Voice, names & console" and §"Roster & routing"; `scripts/check_artifacts.py` (roster and identity gates); `tests/test_docs_consistency.py::test_roster_gate_matches_operating_guide`; CLAUDE.md §6 |

## Context

The framework ships a **persona layer**: the PM is **Morgan**, and the 16 specialist subagents
carry human first names - Amara (`business-analyst`), Mateo (`rules-developer`), Ana
(`data-analyst`), Theo (`tuning-analyst`), Mei (`ml-engineer`), Kenji (`platform-engineer`),
Linh (`qa-engineer`), Hassan (`tm-sme`), Camila (`trade-surveillance-sme`), Cleo
(`comms-surveillance-sme`), Viktor (`model-validator`), Ravi (`code-reviewer`), Thabo
(`performance-reviewer`), Layla (`compliance-reviewer`), Yuki (`data-quality-reviewer`), Pip
(`review-scorer`). The names are presentation over a technical routing table: delegation always
targets the `subagent_type` slug, never the name.

**What the layer buys.** The names are not decoration, and the argument for them is real:

- **Comprehensibility.** "Amara specs it, Mateo builds it, Ravi reviews it, Linh tests it, Layla
  signs it off" tells a non-technical stakeholder what a multi-agent chain did in one line. The
  slug-only equivalent reads as machine plumbing.
- **Independence made legible.** Separation of duties is the point of the review chain
  (`model-validator` independent of `ml-engineer`, `qa-engineer` independent of the builder).
  Distinct named actors make that separation visible in a delivery report in a way that repeated
  role labels do not.
- **Warmth and adoption.** The team is a delivery experience, not only a pipeline. Users engage
  with a named PM; the persona carries the plain-speaking, "yes, here's how" voice the operating
  guide asks for.
- **A stable vocabulary.** A name is a shorter, more memorable handle in conversation than
  `comms-surveillance-sme`.

**What the layer costs.** Three costs were confirmed on disk in the 2026-08-01 audit:

1. **The persona decays, and needed its own hook to survive.** ADR-005 records a live report that
   on a long engagement the voice faded, responses reverted toward default Claude Code, and
   concurrent subagents showed generic labels. Root cause: the persona lives **only in the
   conversation history** (the plugin is dormant-by-default, so the roster loads once at
   `/engage`), and context compaction erodes it. The fix was a **per-turn `UserPromptSubmit`
   re-anchoring hook** (`scripts/persona_anchor.py`), re-injecting the roster and standing rules
   every turn while an engagement is live. That is a permanent per-turn token cost during an
   engagement and a hook that fires in every session of every project the plugin is installed in.
2. **Name drift is a tracked known issue.** The PM has been observed narrating off-roster names
   ("Isla", "Jordan") for a real specialist. The name-to-role map is exactly the sort of
   low-salience lookup that fades first. *(Accuracy note, measured 2026-08-02: ADR-005 PROPOSED
   injecting the full name-to-role map every turn, but the shipped `_ANCHOR` does not - it is
   ~222 tokens and simply points at the operating guide's roster line. The drift is therefore
   managed by the gate and its auto-fix, not by injection.)*
3. **A class of defect codes exists purely to police the persona.** `scripts/check_artifacts.py`
   carries four (plus an email-scoped variant):
   - `ROSTER-UNKNOWN` - an artifact attributes work to a name that is not on the roster;
   - `ROSTER-ROLE-MISMATCH` - a roster name attached to the wrong role;
   - `AGENT-UNMARKED` (and `EMAIL-AGENT-UNMARKED`) - a persona attribution with no 🤖 marker;
   - `AGENT-HUMAN-COMBINED` - a roster name joined to a human on one sign-off line.

   `tests/test_docs_consistency.py::test_roster_gate_matches_operating_guide` exists to stop the
   hardcoded roster in the gate drifting from the operating guide's roster line. Every added or
   renamed specialist touches all of it.

**The requirement genuinely underneath the last two codes is not the names.** It is
**AI-identity marking**: in a compliance context, an agent's check must **never read as a human
sign-off**, and must **never share an approval line with a human**, because only the human grant
carries authority. That requirement is correct, is what a governance reviewer of these artifacts
will actually test, and stands whether or not a single first name survives. `AGENT-UNMARKED` and
`AGENT-HUMAN-COMBINED` serve it. `ROSTER-UNKNOWN` and `ROSTER-ROLE-MISMATCH` serve only the
free-form-name problem: they exist because a name can be invented, whereas a role slug is drawn
from a closed set that already exists on disk.

## Decision

**None taken.** This ADR states the trade-off and puts four options to the human approver. The
constraint on all of them:

> **Any option must preserve AI-identity marking in full.** An agent attribution stays
> unmistakably an agent (🤖 + Virtual Surveillance IT), and an agent's check never shares a
> sign-off line with a human. `AGENT-UNMARKED` / `EMAIL-AGENT-UNMARKED` /
> `AGENT-HUMAN-COMBINED` stay armed under every option. Nothing here is a route to softening
> that.

### Option A - keep the named roster, accept the maintenance

Status quo. Morgan plus 16 names, the re-anchoring hook, all four defect codes, the
roster-consistency test.

**Consequences.** The delivery experience and the legibility of separation of duties are
unchanged, and no documentation, skill, template or test has to move. The costs stay: a per-turn
anchor while engaged (small but permanent, and it dents the dormancy-lean posture during an
engagement), name drift remains a live known issue managed by injection plus an auto-fixing gate
rather than eliminated, and every roster change is a multi-file change (operating guide, anchor,
gate, test, `/meet-the-team`). Reviewers who dislike anthropomorphised AI output keep an
objection the framework answers only with a 🤖 prefix.

### Option B - role-based identities, retiring the first names

Specialists are identified by role in every surface: *"Compliance Review (Virtual Surveillance
IT, automated)"*, *"Independent QA (Virtual Surveillance IT, automated)"*. Morgan's fate is a
sub-choice: the orchestrator could stay named (one name, one voice, and the front door is where
warmth pays most) or become "the PM (Virtual Surveillance IT)".

**Consequences.** The role label is **derived from the routing table rather than remembered**, so
the name-drift failure mode disappears at source: there is no invented identity to invent, and a
wrong role label is a routing error that is visible on its own terms. `ROSTER-UNKNOWN` and
`ROSTER-ROLE-MISMATCH` retire (a role-slug check against the agent files on disk replaces them if
one is still wanted); `AGENT-UNMARKED` and `AGENT-HUMAN-COMBINED` stay. The re-anchoring hook
loses its largest payload (the 16-entry name-to-role map) and, if the standing rules are anchored
some other way, may retire with it, taking the per-turn cost with it. Artifacts arguably read as
**more** audit-defensible: "Compliance Review (automated)" cannot be mistaken for a person by a
reader who never saw the legend, which is the failure mode 🤖 marking is defending against.
Against that: real losses. The warmth and the narrative quality of the delivery experience drop,
"Ravi reviewed what Mateo built" becomes "Code Review reviewed what Rules Development built"
(clunkier, and a step toward the machine-plumbing register the team was designed to avoid), and
the change is a wide sweep across the operating guide, skills, templates, evals and README. Any
user habituated to the roster loses a familiar vocabulary.

### Option C - hybrid: names in conversation only, roles in artifacts

The roster survives in the TUI voice (Morgan narrates "Amara is specifying it now"), and **every
written artifact** carries role identities only. Nothing durable, forwardable or auditable
contains a human first name.

**Consequences.** Warmth is kept where it is felt (the live conversation) and removed where it
carries risk (the document a third party reads months later, out of context and without the
legend). The artifact-side gates simplify: the roster codes become a **prohibition** on roster
names in artifacts rather than a name-to-role validation, and the identity codes stay. Costs:
this is the only option that maintains **two** identity vocabularies and a translation rule
between them, which is a new class of drift ("did this name leak into the report?") and one more
thing for a decaying persona to forget. The re-anchoring hook is still needed for the
conversational names, so the per-turn cost stays. The mechanical check is cheap (a roster name
appearing in an artifact is grep-detectable and auto-fixable), so the risk is manageable, but the
rule is genuinely harder to explain than either A or B.

### Option D - the model writes the ROLE, the name is resolved mechanically (human proposal, 2026-08-02)

The model never types a specialist's name. It writes the **role**, which is the
`subagent_type` slug it must already know in order to delegate at all, and a deterministic step
resolves that to the display identity on the way out:

    the model writes   ->   compliance-reviewer
    the reader sees    ->   🤖 Layla, Compliance Review (Virtual Surveillance IT)

**Why this dominates A, B and C.** The three options above all treat the name as something the
model *authors* and the framework then *polices*. This treats the name as **presentation derived
from a source of truth**, which is the pattern the framework already committed to elsewhere:
ADR-006 made the engagement state machine-readable first and `START-HERE.md` a **render** of it
that is never hand-edited, precisely because a hand-maintained copy of a fact rots. The roster is
the same shape of problem and, until now, got the opposite treatment.

- **Name drift stops being unlikely and becomes impossible.** The PM cannot invent "Isla" while
  writing no names at all. Today the map is *remembered*; here it is *looked up*.
- **The warmth survives.** Unlike Option B, the reader still gets "Layla, Compliance Review". The
  cost B pays (clunky machine-register prose) is not paid here.
- **A small anchor simplification, and only that.** *(Corrected 2026-08-02 after measurement:
  an earlier draft of this option claimed the hook "loses its largest payload, the 16-entry
  name-to-role map". That was wrong and is left recorded rather than quietly deleted.* The
  shipped `_ANCHOR` is **887 chars / ~222 tokens and contains no specialist names at all** - it
  says "name specialists by their roster names" and points at the operating guide. ADR-005
  proposed inlining the map; the implementation never did.*) Option D would let the anchor drop
  one clause, worth a handful of tokens. **Do not choose D for cost.**
- **`ROSTER-UNKNOWN` and `ROSTER-ROLE-MISMATCH` change from validation to resolution.** An
  unknown slug fails to resolve loudly at render time rather than reaching an artifact and being
  caught downstream. The identity codes are unaffected and stay armed.

**Most of it already exists.** `scripts/check_artifacts.py` carries `_ROSTER` (17 entries) *and*
`_ROLE_TO_NAME`, its reverse map, already pinned to the operating guide's canonical roster line
by `tests/test_docs_consistency.py::test_roster_gate_matches_operating_guide`. `render_html` and
`render_findings` already process artifacts on the way out, and `check_artifacts --fix` already
auto-corrects an off-roster name to the canonical one. The pieces are in place; what changes is
their direction of use, from detect-and-correct to derive.

**The genuine gap, and it is real.** The live TUI conversation is **not** rendered: Morgan's
turns go straight to the user with no substitution step. So either conversational voice uses role
labels (losing warmth exactly where Option C argues it matters most), or the anchor keeps a small
name map for **voice only**, which preserves a reduced version of the per-turn cost and a reduced
version of the drift risk. Note the asymmetry that makes this acceptable: a drifted name in
conversation is a cosmetic slip in an ephemeral channel, while a drifted name in an artifact is a
durable, forwardable, auditable defect. Option D makes the **artifact** side structurally correct
and leaves only the cheap half of the problem.

**What D is worth, measured.** Not tokens. Across the 12-case 0.33.6 eval slice the anchor
accounted for ~14k input tokens in total, about **$0.04 against a $62.48 run (0.07%)**, and D
barely touches it. The case for D is entirely **correctness and maintenance**: name drift becomes
structurally impossible rather than caught after the fact, the name-to-role map stops being a
fact duplicated across the guide, the gate and the anchor, and adding or renaming a specialist
becomes a one-line change to a single source instead of a multi-file sweep. Any option argued on
token cost here is being argued on noise.

**Other costs.** Every artifact-producing path must go through resolution, so a deliverable
written without it would ship raw slugs (grep-detectable, auto-fixable, and arguably a safer
failure than a wrong name). A placeholder convention has to be chosen and taught. And the model
may still type a name out of habit, so the existing roster check stays as a backstop rather than
retiring, now enforcing "no raw roster name in an authored artifact" instead of "this name maps
to the right role".

## Consequences (of this ADR itself)

- **Deferring is a legitimate outcome**, and deferring is the current state: nothing in the
  framework changes on the strength of this document. What changes is that the cost of the
  persona is now written down and traceable, instead of being rediscovered by each audit.
- **The identity requirement is now stated separately from the naming scheme.** That separation
  is the durable part of this ADR whichever option is chosen: identity marking is a compliance
  control, and the roster is a product decision, and they should not be argued as one thing again.
- Whichever option lands, the **implementation surface is known**: `docs/team-operating-guide.md`
  (roster line and §"Voice, names & console"), `scripts/persona_anchor.py`,
  `scripts/check_artifacts.py`, `tests/test_docs_consistency.py`, the templates' sign-off legends,
  the `/meet-the-team` skill, the eval cases that assert persona behaviour, and the README.

## Status / next step

**Proposed - awaiting the human approver's ruling** (A, B, C, D, or a variant; D is the
strongest on the evidence and the cheapest to build). No implementation
work is queued behind it. If no ruling is made, Option A stands by default, which is a decision
by inaction and is recorded as such here so it is at least a visible one.
