# Historian invariant matrix — v0

Status: **slots empty, awaiting adjudicated cases.** This document is built before any
implementation, and case allocation is derived FROM it rather than the reverse. Populating
a scenario list first and hoping the invariants get covered is the failure this ordering
exists to prevent.

RAG v1 is **outside this matrix entirely** — a closed dependency, not a component under
re-evaluation. If the Historian needs information RAG v1 does not expose (source role,
authority, relation type), that is an interface requirement for the integration layer,
never a retroactive RAG v1 acceptance failure.

---

## Two assurance classes

Behavioural invariants are properties of what the Historian **decides**. They are proven by
blind, human-adjudicated cases.

Structural invariants are properties of what the system is **capable of representing or
doing**. They cannot be proven by cases at all — they are enforced by schema constraints and
build-time assertions. A behavioural case that merely *mentions* a PROPOSED edge is not
evidence that epistemic immutability is enforced.

Failure states differ, and the distinction is load-bearing:

    BEHAVIOURAL COVERAGE LOST    insufficient evidence of correctness
                                 -> SUITE INCOMPLETE, acceptance cannot be claimed

    STRUCTURAL GATE VIOLATED     implementation violates the architecture
                                 -> BUILD FAILURE, cannot be released

---

## Behavioural invariants — case slots

Minimum assurance: **>=2 independently adjudicated cases from >=2 scenario families.** One
case may defend several invariants, but no invariant may draw all its assurance from a
single case or a single scenario family — otherwise overlap manufactures its own illusion
of coverage.

| ID | Invariant | Slot A | Slot B | Coverage |
|----|-----------|--------|--------|----------|
| B1 | NO_RELATION_BY_ABSENCE | ___ / ___ | ___ / ___ | 0/2 |
| B2 | ORDER_IS_NOT_AUTHORITY | ___ / ___ | ___ / ___ | 0/2 |
| B3 | UNRESOLVED_IS_VALID | ___ / ___ | ___ / ___ | 0/2 |
| B4 | FALSE_ABSTENTION_IS_FAILURE | ___ / ___ | ___ / ___ | 0/2 |
| B5 | ROUTING_IS_INFERENTIAL | ___ / ___ | ___ / ___ | 0/2 |
| B6 | CLOSED_FRAME_SPACE | ___ / ___ | ___ / ___ | 0/2 |
| B7 | NO_RECENCY_AS_AUTHORITY | ___ / ___ | ___ / ___ | 0/2 |
| B8 | QUESTION_RELATIVE_AUTHORITY | ___ / ___ | ___ / ___ | 0/2 |

Candidate labels contribute no human-gold coverage. Public synthetic fixtures exercise
B1–B8 in `tests/test_behavioural_contract.py`; the collected fixture gate requires at
least two tests per invariant. Synthetic queue shape is checked separately and is not gold.

### Synthetic failure examples

| ID | Failure the invariant prevents |
|----|--------------------------------|
| B1 | A missing maintenance entry is mistaken for proof that no maintenance occurred. |
| B2 | A later observation is treated as a correction without an explicit relation. |
| B3 | Conflicting sources are forced into an unsupported answer. |
| B4 | Clear authoritative evidence is ignored in favor of universal abstention. |
| B5 | A proposed route is mistaken for an explicitly supplied question frame. |
| B6 | Agreement in an incomplete frame set is mistaken for convergence. |
| B7 | A newer catalog entry overrides an older local decision based solely on date. |
| B8 | A vendor description is treated as authority for a local operating decision. |

---

## Structural invariants — enforcement, not cases

| ID | Invariant | Gates | Failure action |
|----|-----------|-------|----------------|
| ST1 | EPISTEMIC_CLASS_IS_IMMUTABLE | G-S1, G-S8 | Build/test failure |
| ST2 | MODEL_CONSENSUS_IS_NOT_PROMOTION | G-S2, G-S3 | Build/test failure |
| ST3 | GOLD_IS_HUMAN_ADJUDICATED | G-S6 | Suite-load failure |
| ST4 | GOLD_INDEPENDENT_OF_SYSTEM | G-S4, G-S5 | Suite-load failure |
| ST5 | EVALUATION_COVERAGE_IS_EXPLICIT | G-S9 | Suite-load: INCOMPLETE |

**ST5 was missing from v0.** The rule "retiring a case recomputes coverage immediately;
below minimum => SUITE INCOMPLETE" is mechanically checkable, so it is a structural
invariant needing a gate, not merely a construction convention. Without G-S9 the coverage
rule is a policy reminder — exactly the category this design keeps converting into
enforcement.

### Gates

    G-S1  epistemic-class mutation           PROPOSED -> ASSERTED             MUST FAIL
    G-S2  model-created assertion            asserted_origin = MODEL          MUST FAIL
    G-S3  consensus promotion                asserted_origin = MODEL_CONSENSUS MUST FAIL
    G-S4  reviewed proposal contaminated     derived_from_proposal != null
                                             => acceptance_gold_eligible = false
    G-S5  blind gold required                adjudication_mode != BLIND
                                             => acceptance_gold_eligible = false
    G-S6  human gold provenance required     adjudicator_id missing           SUITE CANNOT LOAD
    G-S7  closed frame taxonomy              frame not in taxonomy_version
                                             => reject / UNKNOWN_OR_AMBIGUOUS
    G-S8  proposal retention                 human review creates a NEW ASSERTED object;
                                             the original PROPOSED object stays immutable
    G-S9  coverage enforcement               any behavioural invariant < 2 cases
                                             or < 2 scenario families => SUITE INCOMPLETE

G-S7 is the structural half of B6: taxonomy closure is mechanical, correct routing behaviour
within the taxonomy is behavioural.

### Assertion origins

    ASSERTED
    +-- TYPED_SOURCE               gold-eligible when independently established
    +-- HUMAN_REVIEWED_PROPOSAL    operationally usable, gold-eligible = FALSE
    +-- HUMAN_BLIND_ADJUDICATION   operationally usable, gold-eligible = TRUE

A human who adjudicates a model's proposal has already seen the model's answer; that
judgement is not independent of it. `derived_from_proposal != null` must make an object
programmatically ineligible for gold, not merely discouraged.

---

## Public case construction

The checked-in queue contains invented observatory and recycling scenarios. Seed,
blind packet, adjudication and evaluation gold remain separate artifacts. Never commit
packets or results generated from operator data. Synthetic examples cannot earn independent
human-gold coverage; all eight human-gold slots above remain unfilled.
