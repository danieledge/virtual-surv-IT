# ADR-012: The persona layer - named specialists, their cost, and the identity requirement underneath (proposed)

> Architecture Decision Record (Nygard format). One file per significant decision, so the
> *why* is auditable later. Authored in `.md`, rendered to `.html`.

> **Document control** · ID `ADR-012` · Version `0.1` · Status `Proposed`
> · Classification `Internal` · Owner 🤖 Morgan (PM), Virtual Surveillance IT · As-of `2026-08-01`
>
> | Version | Date | Author | Change |
> |---|---|---|---|
> | 0.1 | 2026-08-01 | 2026-08-01 framework audit, persona-layer finding | Initial proposal: the cost of the named roster stated in full, three options put to the human approver, no decision taken |

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
   low-salience lookup that fades first, which is why ADR-005 injects the full map rather than a
   reminder to stay in character.
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

**None taken.** This ADR states the trade-off and puts three options to the human approver. The
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

**Proposed - awaiting the human approver's ruling** (A, B, C, or a variant). No implementation
work is queued behind it. If no ruling is made, Option A stands by default, which is a decision
by inaction and is recorded as such here so it is at least a visible one.
