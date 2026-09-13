> Historical v0 design/closure record. Current installation and storage guidance is in
> [RUNBOOK.md](RUNBOOK.md); the only supported database is libSQL.

# Historian structural layer — FROZEN 2026-08-22

    STRUCTURAL FREEZE            2026-08-22    179 tests
    POST-FREEZE SANCTIONED DELTA 2026-08-22    +3 changes, 188 tests
    BEHAVIOURAL CONTRACT + GATE  2026-08-23    +20 tests,  208 tests
    CLOSURE-REVIEW FIXES         2026-08-23    +12 tests,  220 tests
    CURRENT STATE                revision 4 - HISTORIAN v0 CLOSED

**Historian v0 is CLOSED. See `HISTORIAN-V0-CLOSED.md`.** This file remains the record of
the STRUCTURAL layer and its freeze; it is not restated at the current total.

The freeze happened at **179 tests** after seven review rounds. It is recorded at that
number and not silently restated at the current one, because the point of a freeze is the
moment it was taken — the same discipline applied to the RAG v1 canary baseline.

### Post-freeze sanctioned delta

Three changes were made after the freeze, each authorised and each with a reason that is
not "I found another thing to tidy":

1. **Synthetic-principal gold exclusion.** Required so the pipeline could be exercised
   before real human time is spent on it, with the results *structurally* unable to become
   gold rather than excluded by convention. Adds `adjudicator_principal.is_synthetic`, a
   gold-guard exception and a coverage exclusion.
2. **Snapshot-hash correction.** The real corpus exposed a defect fixtures could not:
   `snapshot_text::bytea` is a *cast* expecting bytea escape format, so it worked on plain
   ASCII fixtures and failed on corpus text containing backslashes. `convert_to()` is
   correct but not immutable and cannot back a generated column, so the hash moved to a
   `BEFORE INSERT` trigger. A supplied value is now **discarded** rather than rejected —
   the same guarantee by a different mechanism.
3. **`PACKET_INSUFFICIENT` verdict.** Adds a distinct `adjudication_verdict` domain so a
   blind adjudicator can reject a packet without that collapsing into `UNRESOLVED`. See
   "the opposite contamination" below.

Current suite: **188 tests, three consecutive clean runs**, of which 26 exercise the
evidence verifier against external source material and the remainder run
against a live PostgreSQL instance under `scram-sha-256` with per-capability credentials.

### The opposite contamination

Shallow seed construction prevents the case designer leaking the answer. It creates the
mirror risk: a mechanically-selected span may simply **omit the material the question
needs** — most obviously for intra-document-correction cases, where the correction may sit
a hundred lines below the opening block. An `UNRESOLVED` verdict would then mean *the
packet was inadequate*, not *the evidence is genuinely unresolved*, and the behavioural
measurement would be contaminated in the opposite direction and just as fatally.

`PACKET_INSUFFICIENT` separates them. It yields no gold, no coverage, and does **not**
count as false abstention; the case returns to `reseed_worklist`, which exposes the
sufficiency rationale and no conclusion — so a reseeder learns what was missing without
learning the answer. The remedy is deliberately *not* curating evidence toward an answer,
which would destroy the shallow construction the queue depends on.

**No more adjacent-mechanism hunting without a demonstrated failure or a failing test.**
Changes to this layer now require a reproducing case first.

## What is closed

    model -> EvidenceRef direct write            CLOSED
    candidate locator cross-wire                 CLOSED
    candidate quote drift                        CLOSED
    verified_by self-report                      CLOSED
    source-system -> adapter binding             CLOSED
    registry key self-declaration                CLOSED
    corpus-root containment                      CLOSED
    gold seed/adjudication cross-wire            CLOSED
    blind-assertion self-certification           REMOVED BY DESIGN (v0)
    adjudicator human identity                   CLOSED (per-human logins, derived)
    prior-verdict isolation                      CLOSED (INSERT without SELECT)
    packet forgery / incompleteness / ordering   CLOSED (finalization)
    seed aggregate mutability                    CLOSED (finalization)
    coverage from caller labels                  CLOSED (derived from real seeds)
    credential leak via statement logging        CLOSED (client-side SCRAM verifiers)
    owner credential in container metadata       CLOSED (ephemeral bootstrap, retired)

## The trusted computing base, stated so it is never overclaimed

    The DATABASE proves:  only the verifier identity can create an EvidenceRef.
    The VERIFIER proves:  the source bytes match what the EvidenceRef records.
    NEITHER ALONE PROVES BOTH.

`historian_evidence_verifier` and its source adapter are inside the TCB. PostgreSQL cannot
independently know whether the verifier really read RAG v1. That is where the boundary sits
absent cryptographic source attestation. It is not a defect; describing the SQL gate as
though it proved source existence would be.

## The defect that recurred, and its two forms

Eight instances across seven rounds at the time of the freeze; **eleven by 2026-08-23**,
the later ones in the acceptance machinery and the adjudicator rather than the structural
layer. All one shape:

> **A pointer was bound while its payload stayed independently writable.**

gold `seed_id`; blind-assertion relation triple; packet question; seed question;
`EvidenceRef` content vs RAG v1; seed aggregate vs its materialisation; candidate locator;
candidate quote.

A variant appeared twice and generalises differently:

> **A structurally correct binding can faithfully propagate an upstream error.**

The six-column candidate FK would have preserved `LEDGER` provenance for RAG bytes. The
source registry would have done the same had its key stayed caller-supplied. *The FK holds*
is not *the value is right*.

Both were found by review, not by me. The pattern in my own work was consistent: **I
verified the mechanism I had just built and not the one adjacent to it.**

## What this layer does NOT establish

Nothing here says the Historian reasons well. It says the evidence chain is
non-forgeable end to end:

    real immutable source
      -> verified evidence      (only a source-reading identity may create it)
      -> frozen seed            (content cannot change after a human answers)
      -> frozen packet          (exact materialisation, order and question bound)
      -> blind human verdict    (identity derived, prior verdicts unreadable)
      -> derived gold           (seed, outcome and resolution followed, not stored)
      -> coverage               (distinct finalized seeds only)

### Status of the behavioural layer (superseded 2026-08-23)

This section previously read: *"Behavioural invariants B1-B8 are at 0/2. `require_complete([])`
raises `SuiteIncomplete`. Historian acceptance cannot be claimed."* That was accurate when
written and the reasoning behind it should not be lost, so it is corrected here rather than
deleted.

What changed is the **acceptance model**, not the evidence. Building this layer surfaced the
fact that `RuntimeResolver.resolve()` only PERSISTED a Resolution somebody else constructed —
nothing in the system adjudicated anything. B1-B8 could not have been at 0/2 or any other
number, because there was no engine to hold them. `historian/adjudicator.py` is that engine:
deterministic rules over typed evidence, reading no documents and consulting no model.

    deterministic facts constrain inference; inference must never manufacture deterministic facts

B1-B8 are now covered **2/2 by deterministic synthetic contract fixtures**, which is the v0
release gate. `require_complete([])` still raises `SuiteIncomplete`, unchanged and correct:
adjudicated human gold remains at **0 cases**, and v0 does not claim otherwise. Independent
human validation was not performed and is not a v0 release requirement.

The distinction that matters and must not be blurred:

    CONTRACT COVERAGE  the RULES are right on evidence with a known answer   2/2  ENFORCED
    GOLD COVERAGE      the Historian survives messy real evidence            0    NOT CLAIMED
