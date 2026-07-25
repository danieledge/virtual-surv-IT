# Developer Handover - Alert-export de-duplication utility (synthetic)

> **Document control** · ID `DEVH-001` · Version `0.2` · Status `Draft` · Owner `Kenji`
> Last revised: fix cycle 1.

The utility passes **44/44 tests**. Requirements trace to **FSD-001..017, AC-01..20**.

## Applicable obligations

Record-keeping duties under **FCA SYSC 10A (indicative)** - see the FSD's regulatory section.

## Known limitations

BOM-prefixed files produce a misleading error; non-UTF-8 bytes raise an uncaught error;
Python 3.9 vs 3.11 timestamp-parsing divergence is unverified.
