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

**HIST-C3 contributes ZERO coverage.** Its expected judgement already exists in durable
project records (RAG v1 manifest, ledger clm-2026-eb52f4cd), so it cannot be blind-adjudicated
by anyone with access to the EVECOR record and is not gold under ST4. It is retained as a
regression exhibit. B4, B5, B7 and B8 therefore stand at 0/2 and need TWO cases each from
two families — not one apiece. Coverage is counted from adjudicated gold only, never from
specified candidates.

### Originating failures

Each invariant records the observed failure that produced it. This is not decoration — when
someone later proposes relaxing one because it is inconvenient, the entry names the concrete
failure that returns.

| ID | Originating observed failure |
|----|------------------------------|
| B1 | Ledger recording gap: 35 minutes of real work with no claim written on a healthy ledger. Most of the 2,492-conversation corpus carries no typed relations at all. |
| B2 | Canary question S2 (`2026-06-26-system-lockup-investigation.md`) states "Root Cause: Disk Full" then later "there's a second root cause on top of the disk issue" — same file, same date, same conversation. The correction is positional, not chronological. |
| B3 | No similarity threshold separates answerable from unanswerable on this corpus: an unanswerable question scored 0.4387 while genuine answers scored lower. |
| B4 | Inverse risk of B3: structural abstention is cheap and almost always defensible, so a Historian that abstains on everything is safe and useless. |
| B5 | Query-planner classifier reported 8/8 while its few-shot examples WERE its test set. Routing is a model judgement and must be held-out tested. |
| B6 | Convergence across an incomplete frame set is false convergence — absence of a *considered* frame is not absence of a *valid* frame. |
| B7 | RAG v1 acceptance case C3: a filename/date heuristic selected an upstream vendor release review over the local decommissioning decision, then penalised correct retrieval for not returning the wrong document. |
| B8 | The same vendor review is genuinely authoritative for "what changed in v0.8.4?" and not authoritative for "what is our current operational state?" Authority is not a permanent property of a source. |

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

## Anchor case — SEED ONLY

    Case:   HIST-C3
    Family: authority-trap
    Question: "What is the current state/design of Hindsight?"

    Evidence packet:
      2026-07-14-hindsight-v0-8-4-review.md
      2026-07-08-decommissioning-hindsight-memory.md

    Invariant candidates: B4, B5, B7, B8
    Proves: no structural invariant. Those are the build gates' responsibility.

    Forbidden shortcuts the case is designed to expose:
      newest filename wins / newest date wins / highest similarity wins /
      vendor source wins globally

**The expected verdict is deliberately NOT recorded here.** A design artifact that states
the answer contaminates any adjudicator who reads it, violating G-S5 before adjudication
begins. Seed, adjudication and expected-verdict live in three separate artifacts:

    CASE-SEED         question + evidence packet + invariant candidates   (no answer)
    BLIND-ADJUDICATION  adjudicator, blind=true, verdict, rationale
    EVALUATION-GOLD   expected verdict — generated only AFTER adjudication

### HIST-C3 may already be permanently gold-ineligible

Stated plainly because it is easier to discover now than later. The C3 verdict is already
written into durable records — the RAG v1 production manifest and ledger claim
clm-2026-eb52f4cd both contain the reasoning and the conclusion. Anyone with access to the
EVECOR record has seen it. Under ST4:

  * the verdict was produced by a model (me) reading the two sources, so it is PROPOSED;
  * Charles independently agreed, but only AFTER seeing that analysis, which makes the
    resulting assertion HUMAN_REVIEWED_PROPOSAL, and therefore `gold_eligible = false`.

So HIST-C3 is a strong CANDIDATE and a documented failure-mode record, but it is not gold
and cannot become gold through anyone who has read the RAG v1 record. Making it gold
requires blind adjudication by someone who has not. If no such adjudicator is available,
HIST-C3 should be retained as a regression exhibit and its four invariant slots filled by
other cases — B4, B5, B7 and B8 would then have ZERO coverage, not one slot each.

---

## Naming collision to resolve before this is built on

v0 used `S1..S4` for structural invariants while `S1/S2/S3` are also live canary question
IDs (S2 is `system-lockup-investigation`, cited as B2's originating failure in this very
document). Structural invariants are renamed **ST1..ST5** here. Canary question IDs keep
S1/S2/S3.

## Open slots

    B1  2 cases needed, >=2 families
    B2  2 cases needed, >=2 families        candidate family: intra-document (canary S2)
    B3  2 cases needed, >=2 families
    B4  2 cases needed, >=2 families   (HIST-C3 contributes nothing)
    B5  2 cases needed, >=2 families   (HIST-C3 contributes nothing)
    B6  2 cases needed, >=2 families
    B7  2 cases needed, >=2 families   (HIST-C3 contributes nothing)
    B8  2 cases needed, >=2 families   (HIST-C3 contributes nothing)

    Total behavioural slots outstanding: 16
    Cases adjudicated so far: 0 (HIST-C3 is specified, not yet blind-adjudicated)
