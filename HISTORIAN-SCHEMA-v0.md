> Historical v0 design/closure record. Current installation and storage guidance is in
> [RUNBOOK.md](RUNBOOK.md); the only supported database is libSQL.

# Historian schema — v0 DRAFT (rev 3)

**For review. No persistence, no gates, no write paths implemented.**

Design rule throughout: where a forbidden transition can be made **structurally
unrepresentable**, prefer that over guarding it in application logic. A rule enforced by
shape cannot be forgotten, worked around under deadline, or bypassed by a code path added
later. Each object records *why this shape* where the shape is doing the work.

Rev 3 is the final schema pass before the G-S1..G-S9 mapping review. Rev 2 corrected rev 1's
conflation of *what the evidence is* with *what reasoning was performed over it*. Rev 3
finishes that job by making the evidence-side dimension **derived** rather than stored, and
moves blindness from configuration into capability separation.

---

## 1. Epistemic class is encoded by TYPE, never by a field

    ProposedRelation        distinct object type
    AssertedRelation        distinct object type

No `epistemic_class` field, no shared relation table.

*Why:* a single object with `epistemic_class = PROPOSED | ASSERTED` makes
`UPDATE ... SET epistemic_class='ASSERTED'` syntactically valid and therefore something
every future code path must guard. With separate types there is no mutation to guard — ST1
holds because promotion is not expressible.

### relation_type (closed, 6 values)

    SUPERSEDES | CORRECTS | AUGMENTS | CONTRADICTS | CONFIRMS | NARROWS

`UNRESOLVED_WITH` was **removed** in rev 2. Unresolvedness is a *resolution outcome*, not a
semantic relation between two pieces of evidence. Keeping both would give two incompatible
encodings of the same state — `A --UNRESOLVED_WITH--> B` versus
`Resolution(outcome=UNRESOLVED)` — which will eventually disagree.

### ProposedRelation

    id, subject_ref, relation_type, object_ref
    evidence_refs[]           EvidenceRef
    extractor_id, extraction_run_id, created_at
    disposition               ACTIVE | REJECTED | SUPERSEDED_BY_PROPOSAL
    proposal_support_count    int, default 1

No `CONFIRMED` disposition. `proposal_support_count` records that several extractions
agreed; nothing consumes it as promotion evidence.

### AssertedRelation

    id, subject_ref, relation_type, object_ref, evidence_refs[]
    origin                    TYPED_SOURCE
                              | HUMAN_REVIEWED_PROPOSAL
                              | HUMAN_BLIND_ADJUDICATION
    typed_source_ref          required iff origin = TYPED_SOURCE
    human_adjudicator_id      required iff origin is a HUMAN_* variant
    derived_from_proposal_id  required iff origin = HUMAN_REVIEWED_PROPOSAL
                              MUST BE NULL otherwise
    created_at

    DERIVED, never a writable field:
    gold_eligible = (origin != HUMAN_REVIEWED_PROPOSAL)
                    AND (derived_from_proposal_id IS NULL)

*Why:* the enum has **no MODEL or MODEL_CONSENSUS variant**, so a model-authored assertion
is unrepresentable rather than rejected. `gold_eligible` is derived because a stored boolean
is a field someone can set.

### WHAT "ASSERTED" MEANS — read before using this type

    ASSERTED means: an identifiable source or named human EXPLICITLY asserted this relation.
    ASSERTED does NOT mean: the relation is objectively true.

`AssertedRelation(origin=TYPED_SOURCE, typed_source_ref=<ledger claim>)` deterministically
means *this ledger claim explicitly encodes relation X*. It does not mean X is globally
authoritative. Correspondingly, **absence of a ledger assertion proves nothing** about
whether the relation or event exists — the EVECOR ledger has a documented 35-minute
recording gap during which real work produced no claims on a healthy ledger.

Source *completeness* and assertion *explicitness* are separate concepts and must stay
separate. No completeness score is modelled; UNKNOWN is the safe assumption.

### Human review creates a NEW object (G-S8)

    ProposedRelation P17   stays immutable
              |  human reviews P17
              v
    AssertedRelation A42   origin = HUMAN_REVIEWED_PROPOSAL
                           derived_from_proposal_id = P17
                           gold_eligible = FALSE (derived)

A42 is fully usable operationally, permanently contaminated for evaluation.

### AssertedRelationReview

Retraction is NOT expressed by creating a CONTRADICTS relation. Those mean different things:

    A CONTRADICTS B      a statement about EVIDENCE SEMANTICS
    A is retracted       a statement about the LIFECYCLE of an explicit assertion

    id, asserted_relation_id, created_at
    origin                    TYPED_SOURCE | HUMAN
    typed_source_ref          required iff origin = TYPED_SOURCE
    reviewer_id               required iff origin = HUMAN
    verdict                   AFFIRMED | REJECTED | RETRACTED
    rationale
    replacement_assertion_id  nullable

There is **no MODEL origin**, so a model cannot author an authoritative review — the same
shape that makes ST2 hold for assertions themselves.

The original AssertedRelation stays immutable. A retraction proves *the identified source or
human explicitly retracted that assertion*; it does not rewrite history and does not make
the original assertion cease to have existed. This matters precisely because ASSERTED means
**explicitly asserted**, not **objectively true** — so retraction is a provenance event, not
a correction of fact.

---

## 2. Interpretive properties are proposals, not metadata

### SourceRoleProposal

    id, source_ref, evidence_refs[], extractor_id, created_at
    proposed_role   LOCAL_OPERATIONAL_DECISION | UPSTREAM_VENDOR_MATERIAL
                    | INCIDENT_RECORD | ARCHITECTURAL_ANALYSIS
                    | COMPARATIVE_REVIEW | UNKNOWN

*Why a proposal:* concluding a document is UPSTREAM_VENDOR_MATERIAL is inference even when
obvious. There is deliberately **no AssertedSourceRole type in v0** and **no write path back
into RAG v1 metadata** — writing source role into the ingestion contract would disguise
inference as deterministic metadata and retroactively alter a closed phase.

### RoutingProposal

    id, question_ref, taxonomy_version, extractor_id, created_at
    proposed_frame   member of FrameTaxonomy(taxonomy_version) | UNKNOWN_OR_AMBIGUOUS
    alternates[]     {frame, rationale}   frames considered but not selected

*Why `alternates[]`:* convergence can only be claimed across frames actually considered.
Recording them makes "converged across the frames considered" checkable rather than implied.

### FrameTaxonomy

    version    immutable once published
    frames[]   closed enumeration
    UNKNOWN_OR_AMBIGUOUS   always present, always valid

---

## 3. Deterministic source position (B2)

Rev 1 buried ordering inside an opaque `passage_ref`. B2's own originating failure — canary
S2, where "Root Cause: Disk Full" is followed later in the *same file, same date* by "there's
a second root cause on top of the disk issue" — was therefore awkward to express.

### SourcePosition

    source_id
    source_version_hash

    canonical:
        coordinate_system = LINE     only value in v0
        start, end

    optional_native:
        turn?
        message?

**LINE is canonical for v0.** It exists for every markdown source, is deterministic, and —
paired with `source_version_hash` — is pinned to one immutable version. Crucially it needs
no new parser proven correct before the Historian can cite evidence.

TURN/MESSAGE are optional derived coordinates, populated only after a corpus-wide parser
audit. That audit is worth doing but must not block structural gates: `### User` /
`### Assistant` markers *look* consistent, and "looks consistent across the ones I read" is
exactly the claim this corpus has already falsified three times. CHUNK remains a last resort
— chunk order is a retrieval representation, and using it would make Historian ordering
depend on RAG v1 chunking.

Deterministic helpers operate on canonical LINE coordinates, **no model involved**:

    same_source(A, B) -> bool
    precedes(A, B)    -> bool
    overlaps(A, B)    -> bool

**The boundary this type enforces:** `precedes(A, B)` establishes *B occurs after A*. It
establishes **nothing** about supersession. Any SUPERSEDES/CORRECTS/AUGMENTS relation still
requires explicit textual evidence, a typed link, or it stays unresolved. Order is evidence;
it is not precedence. For canary S2 this is sufficient to say the "second root cause" passage
is later in the same source, without claiming it replaces the disk-full passage.

---

## 4. Resolution: immutable, with independent epistemic dimensions

### Resolution

    id, question_ref, created_at
    outcome                     RESOLVED | UNRESOLVED
    conclusion                  required iff RESOLVED
    unresolved_reason           required iff UNRESOLVED
    evidence_refs[]
    asserted_relation_refs[]
    proposed_relation_refs[]
    source_role_proposal_refs[]
    routing_proposal_ref
    previous_resolution_id      lineage only, nullable
    revision_reason             nullable

    resolution_method   DETERMINISTIC_RULE | MODEL_INFERENCE | HUMAN_ADJUDICATION
                        STORED - describes what actually performed the reasoning

    DERIVED, never writable:
    support_profile     DIRECT_EVIDENCE_ONLY
                        | ASSERTED_RELATION_DEPENDENT
                        | PROPOSED_DEPENDENT
                        | MIXED

        raw evidence only, no relation deps        -> DIRECT_EVIDENCE_ONLY
        asserted relation deps, no proposal deps   -> ASSERTED_RELATION_DEPENDENT
        proposal deps, no asserted relation deps   -> PROPOSED_DEPENDENT
        both                                       -> MIXED

**Two independent dimensions, one stored and one derived.** Rev 1 derived a single
`basis` from whether proposed refs were empty — wrong, because a model can make an
inferential leap over purely asserted evidence. Rev 3 additionally makes `support_profile`
**derived rather than stored**: if it were writable, a model-generated Resolution could cite
proposed relations while declaring ASSERTED_ONLY, which is the same declared-not-enforced
weakness as a self-reported blindness flag. `resolution_method` must stay stored because
nothing in the dependency graph reveals what actually did the reasoning.

The independence is the point:

    support_profile   = ASSERTED_RELATION_DEPENDENT   (derived)
    resolution_method = MODEL_INFERENCE               (stored)

reads as *the supporting relations are explicit assertions, but the conclusion drawn from
them was still model inference* — a state rev 1 could not express.

    HIST-C3-style authority judgement
        support_profile   = PROPOSED_DEPENDENT      (derived)
        resolution_method = MODEL_INFERENCE

    metadata lookup
        support_profile   = DIRECT_EVIDENCE_ONLY    (derived)
        resolution_method = DETERMINISTIC_RULE

    structural abstention — worth noting because it validates the split
        support_profile   = PROPOSED_DEPENDENT
        resolution_method = DETERMINISTIC_RULE
    "two sources conflict and no relation resolves them" is a deterministic rule applied
    over inferential inputs. Under rev 1's single derived field this combination could not
    be expressed at all.

**Immutability.** A Resolution is never updated in place. Reconsideration creates a new
Resolution with `previous_resolution_id` pointing at the old one, which remains
reconstructable.

*Lineage is not evidence supersession.* `R2.previous_resolution_id = R1` means *the
Historian produced a later adjudication of this question*. It does **not** mean the evidence
proves R2 supersedes R1. Keeping these distinct matters because the same word would
otherwise describe both a bookkeeping link and an evidential claim.

### ResolutionReview

    id, resolution_id, reviewer_id, created_at
    verdict                     ACCEPTED | REJECTED
    rationale
    replacement_resolution_id   nullable

    ACCEPTED  -> replacement_resolution_id MUST BE NULL
    REJECTED  -> replacement_resolution_id MAY BE NULL

**A rejected Resolution does not require a replacement.** Rejection establishes only *this
resolution is not accepted*; it does not establish what the correct answer is. `R1 rejected,
no replacement` is a valid terminal state. If a later R2 is produced it carries
`previous_resolution_id = R1`, and the review may then point at it.

Three link types that must never collapse into one another:

    ResolutionReview          a human's judgement about an OUTPUT
    previous_resolution_id    Historian output LINEAGE
    SUPERSEDES                an EVIDENTIAL relationship

R1 is never mutated.

---

## 5. Gold is four artifacts, and blindness is an access boundary

### GoldCaseSeed — internal test-design object, NOT the blind packet

    id, question, evidence_packet[], family, invariant_candidates[]

No field can hold an expected answer. But `family` and `invariant_candidates[]` are
themselves contaminating: telling an adjudicator *family = authority-trap, invariants =
NO_RECENCY_AS_AUTHORITY* effectively hands them the answer without stating it.

### AdjudicationPacket — the ONLY thing a blind adjudicator sees

    id, seed_id, question, evidence_packet[], packet_hash

Deliberately absent: family, invariant candidates, forbidden shortcuts, model proposals,
expected outcome, prior Historian output.

### BlindAdjudication

    id, packet_id, adjudicator_id (REQUIRED), created_at
    adjudication_mode   BLIND    only representable value
    verdict             RESOLVED | UNRESOLVED
    resolution_text, rationale, evidence_used[]

    AUDIT FIELDS ONLY — not the enforcement mechanism:
    proposal_exposure_declared    bool
    system_output_seen_declared   bool

### Blindness is enforced by capability separation, not by self-report

Rev 1 treated `proposal_exposure = false` as establishing blindness. It does not — anything
can write `false`. Rev 2 named the stores an adjudicator must not read, but if one process
can reach them all, that is configuration, not architecture. ST4 needs three components with
**distinct service identities and database credentials**, not three methods in one process:

    A. PACKET BUILDER
         CAN READ    GoldCaseSeed, approved raw source evidence
         CANNOT READ ProposedRelation, SourceRoleProposal, RoutingProposal,
                     Resolution, EvaluationGold
         WRITES      immutable AdjudicationPacket

    B. BLIND ADJUDICATOR
         CAN READ    AdjudicationPacket, evidence referenced by that packet
         CANNOT READ GoldCaseSeed (family / invariant candidates), proposals,
                     Resolution outputs, EvaluationGold
         WRITES      BlindAdjudication

    C. GOLD COMPILER
         CAN READ    GoldCaseSeed, BlindAdjudication
         WRITES      EvaluationGold
         CANNOT ALTER the packet or the adjudication verdict

The declared booleans on BlindAdjudication are retained for audit only. They are never the
enforcement mechanism.

### EvaluationGold

    id, seed_id
    adjudication_id       REQUIRED — no constructor without one
    expected_outcome      RESOLVED | UNRESOLVED
    expected_resolution
    allowed_abstention
    defends_invariants[]
    created_at

*Why `adjudication_id` is required:* EvaluationGold cannot exist without a BlindAdjudication
to descend from, so ST3 holds structurally rather than by policy.

---

## 6. EvidenceRef — versioned and re-verifiable

    source_id             RAG v1 document_id, or ledger claim id
    source_system         RAG_V1 | LEDGER | OTHER
    source_version_hash   REQUIRED
    position              SourcePosition
    passage_hash          REQUIRED
    quote                 verbatim anchor, REQUIRED

*Why version and hash are required:* we already have a live case where a document's indexed
representation differs from the original archive — `2026-07-07-patch-plan-summary.md`, sha
`9d35973e041b7126` original vs `7fdc73f7998c02ec` indexed. Document id plus quote does not
identify **which version** was adjudicated. Re-verifiability needs identity + version +
exact position + passage hash + verbatim anchor.

This also serves B1: distinguishing "no evidence exists" from "evidence we can no longer
locate" is only possible if references remain checkable after the store changes.

---

## 7. What this schema makes impossible

    PROPOSED -> ASSERTED mutation          no such operation (separate types)
    model-authored assertion               no MODEL origin variant
    consensus promotion                    support count consumed by nothing
    unresolvedness expressed two ways      UNRESOLVED_WITH removed
    gold with a pre-set expected answer    GoldCaseSeed has no such field
    gold without blind adjudication        EvaluationGold requires adjudication_id
    non-blind adjudication                 only BLIND is representable
    adjudicator seeing family/invariants   AdjudicationPacket omits them; store unreadable
    settable gold_eligible                 derived, not stored
    evidence type implying reasoning type  support_profile and resolution_method independent
    in-place rewriting of history          Resolution immutable; review is a separate object
    ad-hoc authority frame                 versioned closed taxonomy
    source role written into RAG v1        no write path, no asserted-role type
    order silently implying precedence     precedes() is deterministic and claims only order
    retraction disguised as contradiction  AssertedRelationReview is a distinct object
    model-authored assertion review        no MODEL origin on AssertedRelationReview
    resolution declaring false support     support_profile derived from dependency refs
    blindness by self-declaration          capability separation across service identities
    rejected resolution forced a successor replacement_resolution_id is nullable

## 8. Open questions for review

1. **`routing_proposal_ref` collapses the `support_profile` vocabulary.** If every question
   is routed by a RoutingProposal, then every Resolution carries a proposal dependency, and
   DIRECT_EVIDENCE_ONLY and ASSERTED_RELATION_DEPENDENT become unreachable in practice —
   the derived field would always read PROPOSED_DEPENDENT or MIXED. Two ways out: exclude
   routing from the derivation on the grounds that it selects which authority rules apply
   rather than supporting the conclusion; or allow an explicitly-specified frame (a caller
   stating the frame outright) so routing is not always inferential. This needs a ruling
   before the derivation is implemented, otherwise the vocabulary is decorative.

2. **Turn-marker census still outstanding.** LINE is canonical for v0 so this no longer
   blocks gates, but whether `### User` / `### Assistant` boundaries are unambiguously
   parseable across all 2,492 exports remains unverified and is a prerequisite for
   populating `optional_native.turn`.

3. **Evidence packet assembly still touches the Historian's own read paths.** The Packet
   Builder must read approved raw source evidence, which for this corpus means RAG v1. That
   is fine — RAG v1 exposes no proposals or resolutions — but the boundary should be stated
   as "RAG v1 read-only, Historian stores unreadable" rather than left implicit.

4. **No object yet represents a question.** `question_ref` appears on Resolution and
   RoutingProposal as a bare string. If two Resolutions are to be compared, or a question
   re-asked later, question identity needs to be stable and probably versioned.
