# Historian v0 — CLOSED 2026-08-23

    STRUCTURAL FREEZE            2026-08-22    179 tests
    POST-FREEZE SANCTIONED DELTA 2026-08-22    188 tests
    BEHAVIOURAL CONTRACT + GATE  2026-08-23    208 tests
    CLOSURE-REVIEW FIXES         2026-08-23    220 tests   <- v0 RELEASE GATE
    REAL-CORPUS CANARY           2026-08-23    +42 tests   <- NON-BLOCKING
    FULL SUITE                                 262 tests

The freeze is recorded at the number it was taken at. Later totals are stated separately
rather than overwriting it, for the same reason the RAG v1 canary baseline was not redefined
by a better post-recovery run.

## What v0 accepts on, and what it does not

**v0 accepts on a deterministic behavioural contract.** Independent human adjudication was
**not performed** and is **not a v0 release requirement**. That is a deliberate weakening of
the original acceptance model, taken under the solo-operator constraint, and it is recorded
as a weakening rather than presented as equivalent.

    RELEASE GATE      structural invariants ST1-ST5      188 tests   ENFORCED
                      behavioural contract B1-B8          22 tests   ENFORCED
                      adjudicator persistence path         6 tests   ENFORCED
                      contract coverage gate               4 tests   ENFORCED
                                                         --------
                                                          220 tests

    NON-BLOCKING      real-corpus canary HD-01..HD-20     42 tests   SIGNAL ONLY

    OPTIONAL          independently adjudicated gold       0 cases   NOT AVAILABLE
                      (machinery retained, unmodified)                NOT A RELEASE GATE

### Why a synthetic contract can gate a release

The blocker was never that the rules were unknown. B1-B8 are *stated* — the missing thing
was a mechanism that could demonstrate the engine follows them. Human adjudication of real
corpus cases was one such mechanism; it is not the only one.

Purpose-built evidence whose expected resolution, evidence selection, frame, epistemic class
and abstention behaviour are **known by construction** can assert those outcomes
mechanically. No LLM judges the result and no human is asked to agree with it: each fixture
asserts machine-checkable fields — `resolution.outcome`, `frame`, `authority_refs`,
`considered_refs`, `silent_refs`, `conflict` — against values fixed when the fixture was
written.

Every invariant has **two independent fixtures**, and coverage is **derived from the node
ids pytest actually collected**, not from a hand-written table. A fixture that is deleted or
renamed out of the `test_B<n>_` pattern stops counting the moment it stops running.

### Why the gate is credible: it can fail

A gate that has never failed is decoration. Six mutations were introduced into the engine
and the gate, one at a time, and every one was caught:

    B7  add a recency tie-break (newest wins)          ->  4 failed / 12 passed
    B8  ignore the authority policy                    ->  3 failed / 13 passed
    B1  treat silence as a competing negative claim    ->  2 failed / 14 passed
    B6  adopt an unrecognised frame                    ->  1 failed / 15 passed
    --  rename a B3 fixture out of the pattern         ->  gate refused
    --  lower MIN_CONTRACT_FIXTURES from 2 to 1        ->  gate refused (after fix)

The last one is worth stating plainly because it initially **passed**. The gate test read
its threshold from the same constant the gate read, so weakening the constant weakened the
test with it and nothing failed. This is the tenth instance of the defect that has recurred
through this entire build — *a pointer bound while its payload stays independently
writable* — appearing this time in the acceptance machinery itself. Fixed by asserting
against a duplicated literal `2` and pinning the constant separately.

### What the contract does NOT establish

    it proves    the adjudication RULES are correct on evidence built to have a known answer
    it does not  prove the Historian survives messy, ambiguous, real-world evidence

These are clean constructed cases. Real corpus material is contradictory, partially
irrelevant, and rarely arrives with a determinable answer — which is precisely why grading
it needs an independent adjudicator, and why that path is retained rather than deleted.
**Passing the contract is evidence about the rules, not about the corpus.**

## The real-corpus canary (HD-01..HD-20)

The v3 queue is preserved in full and reframed. It is **not** human-gold acceptance and
contributes **zero** gold coverage.

    20 cases · 24 evidence documents · 29 assignments · 14 families

What it verifies automatically, on every run:

1. every evidence document still resolves and reads from the RAG v1 corpus
2. the adjudicator executes over real corpus evidence and produces a well-formed decision
3. an unrouted real-evidence case degrades to `UNKNOWN` frame rather than inventing one
4. the queue shape has not silently drifted (case, document, assignment, family counts)
5. `AUDIT-V3.py` still passes as a gate rather than a one-off report

What it deliberately does **not** verify: whether any decision is *correct*. Nobody has
established the answers, so nothing here grades a conclusion. Marked `canary` and excluded
from the release gate — a failure is a signal to investigate, not a release blocker.

## Human gold: retained, optional, still honest

`require_complete([])` still raises `SuiteIncomplete`. That is correct and was left alone.
It answers "is there adjudicated gold coverage", and at v0 the honest answer is **no**.

The whole gold path — blind adjudication, derived identity binding, prior-verdict isolation,
packet finalization, `PACKET_INSUFFICIENT`, synthetic-principal exclusion, gold derivation,
coverage from real seed ids — is retained, tested, and unmodified. If an independent
adjudicator ever becomes available, the machinery to consume their verdicts already exists
and already passes its tests. v0 simply does not wait on it.

Neither Claude nor Charles can supply that adjudication: both have seen the designer
material, so any verdict from either is `HUMAN_REVIEWED_PROPOSAL` and permanently
`gold_eligible = false`. That constraint is unchanged by this closure.

## Scope boundary

**RAG v1 is untouched.** No file under `data/ragflow-production/` or `data/ragflow-canary/`
was modified. RAG v1 remains closed at 2,492 documents / 26,127 chunks, integrity 23/23,
valid acceptance 12/12.

## Verification

    python3 -m pytest -q -m 'not canary'    220 passed   (v0 release gate)
    python3 -m pytest -q                    262 passed   (gate + canary)

Release gate: 5 consecutive clean runs post-fix. Full suite: 3 consecutive clean runs
post-fix. (The pre-fix suite ran 8 and 4 clean respectively, which is exactly why the
section below exists: a green suite is evidence about what it tests, not about what it
does not.)

## Closure review — three defects, found after the suite was green

The first closure claim was premature. A review of the newly added adjudicator found three
real defects that 250 passing tests did not catch, because every one of them lived in a
behaviour no fixture exercised. They are recorded here rather than quietly fixed.

**1. A PROPOSED relation could settle a conflict.** `_resolves()` took an untyped tuple and
duck-typed on `.relation_type`, `.subject_ref`, `.object_ref` — the fields `ProposedRelation`
also carries. A model could therefore propose `A CORRECTS B` and its own claim would win.
That is promotion of a proposal to an assertion by the back door, and it defeats the oldest
guarantee in the design. Fixed with a runtime `isinstance` split, not a type hint; an object
that merely looks like a relation now raises rather than being silently ignored.

**2. One resolved pair erased unrelated unresolved conflicts.** The conflict loop set
`winner` from any single settled pair and then discarded every other claim. With claims
X/Y/Z from A/B/C and one asserted `A CORRECTS B`, the untouched A-vs-C conflict vanished and
the engine reported RESOLVED X. A relation settles the pair it names; it says nothing about a
third source. A winner must now dominate **every** claim it disagrees with, or the outcome
stays UNRESOLVED — with a reason that distinguishes partial resolution from no resolution,
because the two need different remedies.

**3. The engine's output was not persistable.** It synthesised `claim:<evidence_id>` strings
and wrote them into `Resolution.proposed_relation_refs`, whose PostgreSQL counterpart is
`resolution_proposed_dep.proposal_id REFERENCES proposed_relation(id)`. Nothing objected,
because nothing had ever tried to persist a Resolution — there is no SQL-backed
`ResolutionStore`, only a Protocol. **A type that is only ever held in memory cannot discover
that it is unpersistable.** Claims are now first-class `ClaimProposal` objects with their own
table and their own dependency edge; source roles and routing travel as `SourceRoleProposal`
and `RoutingProposal` rather than as a bare dict and a bare string, so a Resolution can say
whose inference it rests on. `tests/test_adjudicator_persistence.py` writes real output to
real tables under the real runtime role, and proves the old shape is rejected by the FK.

### Two further defects found while fixing those

Both were found by the new fixtures, not by inspection:

- **My own dominance gate was wrong first.** I gated the outcome on a list of unsettled
  pairs, but a *losing* candidate always leaves pairs unsettled, so the legitimate
  two-source case would have been rejected. Winner-hood was already the complete test.
- **`_settles()` returned the first match.** With both `A CORRECTS B` and `B SUPERSEDES A`
  asserted, scan order silently decided the conflict — document order wearing a different
  hat, which is precisely what B2 forbids. A pair asserted in both directions is a
  contradictory record and now settles nothing.

### Mutation evidence for the fixes

    D1  let a PROPOSED relation settle           -> contract suite failed
    D2  winner from any single settled pair      -> contract suite failed
    D3  fabricate claim:<id> into relation refs  -> 3 persistence tests failed on real FKs

D3 is the one worth noting: it fails against PostgreSQL with foreign-key violations, which
is what makes "the old shape was genuinely unpersistable" a demonstrated fact rather than a
reading of the schema.

### What this says about the acceptance model

The synthetic contract did its job and also showed its edge. It proved the rules it
encoded, and was silent on three behaviours nobody had written a fixture for. That is not
an argument against the contract — it is the reason the limitation paragraph above is
stated in the present tense and should stay there.
