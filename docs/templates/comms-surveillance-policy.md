# Comms Surveillance Policy & Coverage — <SCOPE / BUSINESS LINE>

> Produced by `business-analyst` with `comms-surveillance-sme`. Defines what comms are monitored,
> for whom, how they are retained, and confirms every in-scope channel is actually captured.
> Examples and population data use **synthetic/masked data only** (§5). Authored in `.md`,
> rendered to `.html`. Policy/coverage document — channel-capture engineering is built by
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
The obligation to **record** relevant communications and retain them.
- **MiFID II Art 16(7)** — recording of communications relating to transactions.
- **SEC Rule 17a-4 / FINRA** recordkeeping where the entity is in scope (US).
State retention periods, immutability/WORM requirements, and the system of record per channel.

## 4. Off-channel comms risk & controls
The biggest comms blind spot: business conducted on **unapproved channels** (personal
WhatsApp/SMS, personal email) that are never captured. State the prohibition, attestation
regime, detection/leakage controls, monitoring of approved-channel usage, and disciplinary path.

## 5. Coverage assessment
Confirm **every in-scope channel for every in-scope person is actually captured** — an
un-onboarded channel or starter/leaver gap is undetected-comms exposure (the data-gap lesson,
FCA Market Watch 79).

| In-scope channel | Capture confirmed? | Population coverage (joiners/movers/leavers) | Gap / exposure | Route to |
|---|---|---|---|---|

Capture/onboarding gaps → `platform-engineer`; population/data gaps → `data-quality-reviewer`.

## 6. Review cadence & next steps
Owner, review frequency, out-of-cycle triggers (new channel, new joiners, reg change), and the
prioritised actions to close any gaps — with a recommendation. Never end at the gap list.
