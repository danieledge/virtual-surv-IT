# Domain evidence base - practice-claim verification register

> **What this is.** The provenance record for the surveillance **practice** claims the team ships
> (as distinct from the *regulatory* citations, which were already verified). On 2026-07-06 a Fable 5
> pass inventoried 56 falsifiable practice claims across the four clusters `docs/house-rules.md`
> had marked "STILL UNVERIFIED - treat as foundational", and verified each against primary and
> authoritative sources. This file is the durable register; `house-rules.md` §"Domain evidence
> base" carries the summary and tier.

> **Verdict scale.** **VERIFIED** - a primary/authoritative source supports it. **PARTIAL** - the
> core is supported but a specific number, superlative or transfer is the repo's own (sound)
> construction, not in the source. **INDUSTRY-STANDARD-UNCITED** - clearly common practice with no
> single citable primary source; keep labelled as practice. **UNSUPPORTED** - no source found.

> **Headline:** 33 VERIFIED · 8 PARTIAL · 15 INDUSTRY-STANDARD-UNCITED · **0 UNSUPPORTED** across
> 56 claims. **No claim was found false or fabricated.** The uncited items are legitimate
> practice/operating-model framings, several already self-flagged in-repo (`lexicon-spec.md:30-31`,
> `tuning-analyst.md:57`). Method note: the inventory + verification ran as five subagents (one
> inventory, four cluster verifiers); the full claim inventory index is
> `artifacts/evidence-claim-inventory.md`.

---

## Cross-cutting findings (read these first)

1. **The independence/separation backbone is citable; the named-role RACI is convention.** Every
   role-boundary claim (C50-C56) rests on a genuinely mandated principle - SR 11-7 (model
   development independent of validation), the IIA Three Lines Model (first- vs second-line), FCA
   SYSC 3.2 (segregation of duties), BABOK v3 (the BA specifies, does not build), EARS/Mavin
   (requirements syntax). What is *convention*, not mandate, is the mapping of those principles onto
   this team's specific named roles (data-analyst vs tuning-analyst vs developer). Docs should cite
   the framework for the principle and label the role split as operating-model convention.
2. **FCA Market Watch 79 is a data/model-governance authority, not an e-comms-lexicon authority.**
   MW79 supports surveillance model testing (data comprehensiveness · model logic · model code ·
   parameters), the self-concealing dead-feed dynamic, and formal-review governance. It does **not**
   govern e-comms lexicon design; secondary sources that attribute lexicon guidance to MW79
   overstate it. Cite MW79 only for the governance/testing/coverage points.
3. **The spoofing default thresholds are conservative catch-alls, not case-derived constants.** The
   only PARTIAL with a substantive gap is C41: enforcement statistics are *tighter* than the repo's
   defaults (Coscia large-order fill ~0.08% vs the repo's <=0.10; spoof orders open <500ms vs the
   repo's <=2000ms). The defaults will catch the cases; they are correctly flagged in-repo as
   needing production calibration. Recorded now in `docs/scenarios/spoofing.md`.

---

## Cluster A - communications-surveillance practice (C1-C18)
6 VERIFIED · 3 PARTIAL · 9 INDUSTRY-STANDARD-UNCITED

| id | verdict | anchor | repo action |
|---|---|---|---|
| C1 detection targets | UNCITED | MAR; SEC off-channel initiative; MW79 (collusion language) | keep as field description |
| C2 five language-signal kinds | UNCITED | practitioner framing (SteelEye lexicon methodology) | keep labelled inference/practice |
| C3 lexicon design = categorised terms + match types + scored combination | **VERIFIED** | SteelEye *Lexicon Fundamentals*; Bloomberg *Lexicon surveillance is not dead* | cite a vendor methodology for the design pattern |
| C4 classification/anomaly/topic model families | UNCITED | generic ML taxonomy (Bloomberg) | keep as practice |
| C5 multilingual/slang/obfuscation/channel-mixing challenges | UNCITED (channel-mixing strong) | Chronicle/IPC/NICE MiFID II material | keep; channel-mixing leg citable |
| C6 FP drivers (banter, quoted, automated, idioms, product names, jargon) | UNCITED | Bloomberg/SteelEye (lexicon = high FP, entity noise) | keep as practice |
| C7 exclusions/allow-lists suppress FPs **without creating coverage gaps** | **PARTIAL** | exclusions are standard; the no-gaps qualifier overclaims | **soften** - exclusions trade recall for precision; corrected in `lexicon-spec.md` |
| C8 per-term hit/FP tracking; reject opaque lists | UNCITED | Bloomberg (review lexicons regularly); MW79 (formal review) | keep; MW79 for governance |
| C9 target precision/recall + evaluation set | UNCITED | generic ML evaluation discipline | keep as practice |
| C10 NLP needs negation/context-window/sentiment-intent | **VERIFIED** | negation-detection literature (arXiv 2209.00470, 1810.00967); Bloomberg | keep |
| C11 voice = STT transcription (confidence-scored) before lexicon/NLP | **VERIFIED** | Theta Lake; Verint capture; NICE MiFID II mobile-recording | keep |
| C12 voice = highest-risk & most gap-prone channel | **PARTIAL** | gap-prone leg verified (Chronicle/IPC/NICE; ESMA call-taping); superlative is judgement | keep existing "frequently" hedge |
| C13 NICE Engage / Verint / Theta Lake are real voice-capture platforms | **VERIFIED** | Verint; Theta Lake; NICE (Verint+Theta Lake capture partnership) | correct as-is; keep "e.g." |
| C14 lexicon governance (owner, cadence, change control, triggers) | UNCITED | MW79 (formal documented review procedures) | keep; MW79 for the governance expectation |
| C15 ATL/BTL transferred to lexicon thresholds; BTL "within 10%" | **PARTIAL** | ATL/BTL verified for AML TM (Abrigo; Deloitte); "10%" matches the documented AML tuning convention; the comms-lexicon transfer is the repo's own analogy | keep "e.g. within 10%"; note it's borrowed from AML/TM |
| C16 off-channel control set (prohibit/attest/detect/monitor/discipline) | **VERIFIED** | SEC/CFTC enforcement; Faegre Drinker; ACA Group | cite SEC/CFTC + a compliance-guidance source |
| C17 in-scope population + channel universe | UNCITED | MiFID II CDR 2017/565 Art 76 / SYSC 10A (recording leg) | keep; recording leg already cited in §3 |
| C18 worker-monitoring privacy/proportionality/audit constraints | **VERIFIED** | ICO *Monitoring workers* guidance (2023-10-03); GDPR/DPIA | **add ICO citation** |

## Cluster B - coverage-assurance methodology (C19-C27)
5 VERIFIED · 2 PARTIAL · 2 INDUSTRY-STANDARD-UNCITED

| id | verdict | anchor | repo action |
|---|---|---|---|
| C19 coverage gap is self-concealing until audit/incident | **VERIFIED** | FCA MW79 (news feed never activated -> zero alerts for years) | cite MW79 |
| C20 risk->scenario->feed mapping; missing scenario/feed = blind spot | UNCITED | MW79 four-component testing frame | label as practice operationalising MW79 |
| C21 DQ dimensions (completeness/accuracy/timeliness/reconciliation/integrity) | **VERIFIED** | BCBS 239 Principles 3-5; DAMA-DMBOK | cite BCBS 239 + DMBOK |
| C22 completeness via source->surveillance reconciliation | **VERIFIED** | BCBS 239 Principle 3 (reconcile to sources, breaks measured) | cite BCBS 239 Principle 3 |
| C23 "zero alerts" ambiguous; canary/heartbeat/reconciliation disambiguate | **PARTIAL** | MW79 verifies the trap; the three methods are engineering practice | MW79 for the trap; label methods as practice |
| C24 assurance independent of the builder | **VERIFIED** | IIA Three Lines Model (2020) | cite Three Lines Model |
| C25 re-run triggers (new channel/product/reg change/incident/zero-alert) | UNCITED | MW79 (periodic testing) backs the principle, not the list | present list as recommended practice |
| C26 JML onboarding-to-capture SLA, typically <=1 business day | **PARTIAL** | SYSC 10A / MW79 require capture & oversight; the number is a firm-set target | keep hedge; **label the number an operational target, not a regulator figure** |
| C27 controls evidenced & reproducible (control-of-controls) | **VERIFIED** | BCBS 239 Principle 3 + governance; IIA Three Lines | cite BCBS 239 |

## Cluster C - detection-tuning & typology practice (C28-C49)
18 VERIFIED · 2 PARTIAL · 2 INDUSTRY-STANDARD-UNCITED

| id | verdict | anchor | repo action |
|---|---|---|---|
| C28 risk-based per-segment calibration | **VERIFIED** | FFIEC RBA; Deloitte; Abrigo | cite FFIEC RBA |
| C29 statistical thresholds (percentiles/std-dev/EVT), never round numbers | **VERIFIED** | Sanction Scanner; Flagright; EVT/POT literature | keep; EVT is niche-but-real |
| C30 ATL = sample flagged, label TP/FP, estimate precision | **VERIFIED** | Abrigo; Protiviti | cite; standard AML terminology |
| C31 BTL = sample just-below, estimate FN/gaps | **VERIFIED** | Abrigo; Protiviti | cite |
| C32 dry-run candidate params over history | **VERIFIED** | Hawk; Deloitte | cite methodology |
| C33 post-deployment MI basket + decay monitoring | **VERIFIED** (basket is industry-standard) | SR 11-7 ongoing monitoring; Protiviti/Deloitte | frame the specific list as industry-standard MI |
| C34 peer-group/benchmark comparators | **VERIFIED** | Nasdaq SMARTS; NICE Actimize MSC | cite vendor methodology |
| C35 granular time spine is a tuning prerequisite | **VERIFIED** | MiFID II RTS 25 (CDR 2017/574) clock-sync/granularity | cite RTS 25 as the corollary basis |
| C36 re-tune triggers (X/Y/Z + change-based) | **VERIFIED** (X/Y/Z firm-set) | SR 11-7 (change in products/clients/conditions) | keep X/Y/Z as placeholders |
| C37 append-only change log; satisfies SR 11-7/FFIEC change mgmt | **VERIFIED** | SR 11-7 change management + documentation | the header claim is well-founded |
| C38 record the no-change review | UNCITED | SR 11-7 periodic-review + audit-trail logic | recast as governance practice grounded in SR 11-7 |
| C39 spoofing typology (place large / execute opposite / cancel) | **VERIFIED** | MAR Art 12(1) & Annex I; *US v Coscia*; Sarao | cite |
| C40 implementable spoofing signature (conjunction on lifecycle data) | **VERIFIED** | Coscia CFTC/DOJ record; Sarao CFTC 7156-15 | cite |
| C41 spoofing defaults (>=5x, <=2000ms, <=0.10, within 3000ms) | **PARTIAL** | mechanics verified; numbers are the repo's illustrative defaults, *looser* than cases | keep "plausible defaults, calibrate"; **add enforcement-stat context** |
| C42 genuine-only size baseline (self-masking failure mode) | UNCITED | sound engineering inference; no primary source | present as reasoned design (🧠 inferred) |
| C43 benign FP explanations (MM/hedge/iceberg/IOC/normal cancels) excluded | **VERIFIED** | Nasdaq/NICE; MAR Art 13 accepted practices / Art 5 carve-outs | cite; can add MAR MM distinction |
| C44 layering = multiple orders at successive price levels | **VERIFIED** | Sarao (CFTC 7156-15); FinCrime Intelligence glossary | cite |
| C45 synthetic validation != production calibration | **VERIFIED** | SR 11-7 (representative/production data; ongoing monitoring) | well-founded |
| C46 segmentation/suppression cut FPs but can create gaps | **VERIFIED** | BTL rationale (Abrigo/Protiviti) | cite |
| C47 canonical ML typologies (structuring/rapid-movement/round-trip/mule/TBML) | **VERIFIED** | FATF TBML & professional-ML typology reports | cite specific FATF reports |
| C48 alert->STOR escalation as a tunable, ATL/BTL-tested parameter | **PARTIAL** | MAR Art 16 / RTS 2016/957 verify the trigger; parameterise-and-tune is repo practice | cite MAR Art 16 for the trigger; label the treatment as practice |
| C49 comms tuning (lexicon per-term; NLP score/drift) | **VERIFIED** | SteelEye; Bloomberg | cite |

## Cluster D - DA/BA/role-boundary (C50-C56)
4 VERIFIED · 1 PARTIAL · 2 INDUSTRY-STANDARD-UNCITED

| id | verdict | anchor | repo action |
|---|---|---|---|
| C50 data-analyst vs distinct quant tuning role | **PARTIAL** | tuning-as-distinct-discipline verified (ACAMS/Abrigo/FFIEC); the named-role split is convention | cite the discipline; label the split convention |
| C51 BA specifies, does not build; thresholds are SME/quant | **VERIFIED** | BABOK v3 (Requirements Analysis & Design Definition; Elicitation) | cite BABOK; label threshold-ownership as convention |
| C52 BA-owned deliverables (EARS, RTM, AC, UAT, reg-change impact) | **VERIFIED** | BABOK v3 (RADD + Requirements Life Cycle Mgmt); Mavin EARS | cite BABOK + EARS |
| C53 lexicon design/tune/build three-owner split | UNCITED | SR 11-7 (build vs validation) for the NLP leg only; MW79 (logic/code/data) | cite the NLP leg to SR 11-7; rest as convention |
| C54 trade-scenario design->build->tune->advise pipeline | UNCITED (SoD backbone mandated) | FCA SYSC 3.2 segregation; MW79 component separability | cite SYSC/MW79 for the principle; pipeline is convention |
| C55 analysts recommend, never apply to live logic; independent validation before deploy | **VERIFIED** | SR 11-7 (independent validation before reliance); FFIEC; SYSC | strongest-grounded; cite SR 11-7 + FFIEC |
| C56 independent coverage/DQ assurance != operational DQ | **VERIFIED** | IIA Three Lines Model; MW79 (data coverage) | cite Three Lines; line-placement is org choice |

---

## Repo actions taken from this pass (2026-07-06)

1. `docs/house-rules.md` §"Domain evidence base" - the single `🟡 STILL UNVERIFIED` line replaced
   with a tiered summary (verified-with-source / practice-labelled / partial) pointing here.
2. `docs/templates/lexicon-spec.md` (C7) - softened the exclusion/allow-list claim that overstated
   "without creating coverage gaps".
3. `docs/scenarios/spoofing.md` (C41) - added the enforcement-statistics context (Coscia ~0.08%
   fill, <500ms lifetimes) noting the defaults are deliberately conservative catch-alls.

## Deferred (would strengthen further, not done this pass)

- Add the specific inline citations named in the tables above to each template/agent file (ICO for
  C18, SEC/CFTC for C16, BCBS 239 for C21-C22/C27, SR 11-7 for C55, BABOK/EARS for C51-C52, FATF for
  C47). This pass centralised the provenance here and fixed the two substantive issues; per-file
  citation threading is a mechanical follow-up.
- Re-label the operating-model role splits (C50/C53/C54) in the agent files as "convention" where
  they currently read as mandated.
