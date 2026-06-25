# Comms Surveillance Policy & Coverage - <SCOPE / BUSINESS LINE>

> Produced by `business-analyst` with `comms-surveillance-sme`. Defines what comms are monitored,
> for whom, how they are retained, and confirms every in-scope channel is actually captured.
> Examples and population data use **synthetic/masked data only** (§5). Authored in `.md`,
> rendered to `.html`. Policy/coverage document - channel-capture engineering is built by
> `platform-engineer`.

| | |
|---|---|
| **Scope** | <desk / business line> |
| **Jurisdiction(s)** | <applicable regime(s) (CLAUDE.md §2)> |
| **Date / author** | <YYYY-MM-DD> |
| **Headline** | <coverage status / open gaps in one line> |

## 1. Scope & in-scope population
The roles/desks/individuals whose communications are in scope and why (regulated activity,
access to MNPI, client-facing). State the channels in scope: **email, chat/IM, voice,
collaboration tools, social**.

## 2. What is monitored & why
Per channel: what is captured, the conduct risks it covers (insider dealing, collusion,
mis-selling, market sounding), and the lexicon/model applied (ref Lexicon Spec).

| Channel | Captured content | Risk(s) covered | Lexicon / model ref |
|---|---|---|---|

## 3. Recordkeeping & retention
The obligation to **record** relevant communications and retain them. *[Citations verified against
primary sources - ESMA Single Rulebook, EUR-Lex, legislation.gov.uk, SEC, FINRA.]*
- **EU - MiFID II Art 16(7)** (Directive 2014/65/EU): record telephone & electronic comms relating
  to own-account dealing and client-order services (reception/transmission/execution), **including
  comms *intended* to result in a transaction even if none does**. Retain **5 years (up to 7 if the
  competent authority requests)**. Detailed by **CDR (EU) 2017/565 Art 76** - a **written recording
  policy** identifying in-scope comms (incl. relevant **internal** comms), client notification, and
  the retention clock starting at record creation. *(UK: the retained text points to FCA **SYSC 10A**.)*
- **US - Exchange Act Rule 17a-4(b)(4)**: retain business-related comms **≥3 years, first 2 readily
  accessible**; **FINRA Rule 4511(b)**: **6-year** default where no other period applies.
- **Electronic storage** (US): **WORM** *or* the **audit-trail alternative** (SEC Oct-2022
  amendments, eff. 2023) - a system that can recreate an altered/deleted record with a time-stamped
  audit trail. State the system of record, retention and immutability mode per channel.

## 4. Off-channel comms risk & controls
The biggest comms blind spot: business conducted on **unapproved channels** (personal WhatsApp/
SMS/iMessage/Signal, personal email) that are never captured. State the prohibition, attestation
regime, detection/leakage controls, monitoring of approved-channel usage, and disciplinary path.

> **Why this is the headline risk** *(verified - SEC & CFTC primary sources)*: the 2022–2024
> off-channel sweep penalised **failure to preserve and supervise** business comms on personal
> devices, not trading misconduct - SEC actions in **Sep 2022 (16 firms, >$1.1bn)**, **Aug 2023
> (11 firms, $289m)** and **Sep 2023 (10 firms, $79m)**, plus the **CFTC Aug 2023 (4 firms,
> $260m)** order. The failures reached **supervisors and senior executives**. The control
> expectation: capture business comms **regardless of channel/device**, or credibly prohibit and
> monitor for leakage - backed by attestations and discipline.

## 5. Coverage assessment
Confirm **every in-scope channel for every in-scope person is actually captured** - an
un-onboarded channel or starter/leaver gap is undetected-comms exposure (the data-gap lesson,
FCA Market Watch 79).

| In-scope channel | Capture confirmed? | Population coverage (joiners/movers/leavers) | Gap / exposure | Route to |
|---|---|---|---|---|

Capture/onboarding gaps → `platform-engineer`; population/data gaps → `data-quality-reviewer`.

## 6. Review cadence & next steps
Owner, review frequency, out-of-cycle triggers (new channel, new joiners, reg change), and the
prioritised actions to close any gaps - with a recommendation. Never end at the gap list.
