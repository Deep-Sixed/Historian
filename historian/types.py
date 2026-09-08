"""Historian domain types.

Epistemic class is encoded by TYPE, never by a mutable field. There is deliberately no
`epistemic_class` attribute and no shared relation base class with a settable kind: a
single object carrying `epistemic_class = PROPOSED | ASSERTED` would make promotion a
syntactically valid update that every future code path must guard. With separate types
there is no mutation to guard.

Every object here is frozen. History is never rewritten in place; reconsideration and
retraction create new objects that reference the old ones.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Sequence


# --------------------------------------------------------------------------- enums


class RelationType(Enum):
    """Semantic relations between pieces of evidence.

    UNRESOLVED_WITH is deliberately ABSENT. Unresolvedness is a resolution OUTCOME, not a
    relation between evidence. Modelling both would give two incompatible encodings of the
    same state, which would eventually disagree.
    """

    SUPERSEDES = "SUPERSEDES"
    CORRECTS = "CORRECTS"
    AUGMENTS = "AUGMENTS"
    CONTRADICTS = "CONTRADICTS"
    CONFIRMS = "CONFIRMS"
    NARROWS = "NARROWS"


class AssertionOrigin(Enum):
    """How an assertion came to be asserted.

    There is NO MODEL or MODEL_CONSENSUS variant. G-S2 and G-S3 hold because a
    model-authored assertion is unrepresentable, not because something rejects it.
    Repetition, confidence and agreement among models never appear here.
    """

    TYPED_SOURCE = "TYPED_SOURCE"
    HUMAN_REVIEWED_PROPOSAL = "HUMAN_REVIEWED_PROPOSAL"
    # HUMAN_BLIND_ADJUDICATION is DELIBERATELY ABSENT in v0. Citing a blind adjudication
    # id proves only that the adjudication EXISTS, never that it established that
    # particular subject/relation/object - the gold cross-wiring bug relocated into the
    # assertion path. An epistemic label the system cannot enforce is worse than no label,
    # so the origin is removed until a structured BlindRelationAdjudication exists whose
    # verdict itself carries the relation triple.


class ReviewOrigin(Enum):
    """Who may review an assertion. No MODEL variant, for the same reason."""

    TYPED_SOURCE = "TYPED_SOURCE"
    HUMAN = "HUMAN"


class ProposalDisposition(Enum):
    """Lifecycle state of a proposal, recorded as an EVENT and never as a field.

    There is NO CONFIRMED value. A proposal never becomes an assertion; human review
    creates a separate AssertedRelation that references it.
    """

    ACTIVE = "ACTIVE"
    REJECTED = "REJECTED"
    SUPERSEDED_BY_PROPOSAL = "SUPERSEDED_BY_PROPOSAL"


class SourceSystem(Enum):
    RAG_V1 = "RAG_V1"
    LEDGER = "LEDGER"
    OTHER = "OTHER"


class CoordinateSystem(Enum):
    """LINE is the only canonical value in v0.

    LINE exists for every markdown source, is deterministic, and — paired with
    source_version_hash — is pinned to one immutable version. It requires no new parser
    proven correct before the Historian can cite evidence. TURN/MESSAGE are optional
    derived coordinates pending a corpus-wide parser audit. CHUNK is a last resort: chunk
    order is a retrieval representation, and using it would make Historian ordering depend
    on RAG v1 chunking.
    """

    LINE = "LINE"


class SourceRole(Enum):
    LOCAL_OPERATIONAL_DECISION = "LOCAL_OPERATIONAL_DECISION"
    UPSTREAM_VENDOR_MATERIAL = "UPSTREAM_VENDOR_MATERIAL"
    INCIDENT_RECORD = "INCIDENT_RECORD"
    ARCHITECTURAL_ANALYSIS = "ARCHITECTURAL_ANALYSIS"
    COMPARATIVE_REVIEW = "COMPARATIVE_REVIEW"
    UNKNOWN = "UNKNOWN"


class Outcome(Enum):
    RESOLVED = "RESOLVED"
    UNRESOLVED = "UNRESOLVED"


class AdjudicationVerdict(Enum):
    """Human packet verdicts are wider than Historian resolution outcomes."""

    RESOLVED = "RESOLVED"
    UNRESOLVED = "UNRESOLVED"
    PACKET_INSUFFICIENT = "PACKET_INSUFFICIENT"


class ResolutionMethod(Enum):
    """What actually performed the reasoning. STORED, because nothing in the dependency
    graph reveals it."""

    DETERMINISTIC_RULE = "DETERMINISTIC_RULE"
    MODEL_INFERENCE = "MODEL_INFERENCE"
    HUMAN_ADJUDICATION = "HUMAN_ADJUDICATION"


class SupportProfile(Enum):
    """What kind of evidence a resolution rests on. DERIVED, never stored — a writable
    field would let a resolution cite proposed relations while declaring otherwise."""

    DIRECT_EVIDENCE_ONLY = "DIRECT_EVIDENCE_ONLY"
    ASSERTED_RELATION_DEPENDENT = "ASSERTED_RELATION_DEPENDENT"
    PROPOSED_DEPENDENT = "PROPOSED_DEPENDENT"
    MIXED = "MIXED"


class ReviewVerdict(Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class AssertionReviewVerdict(Enum):
    AFFIRMED = "AFFIRMED"
    REJECTED = "REJECTED"
    RETRACTED = "RETRACTED"


class AdjudicationMode(Enum):
    """BLIND is the only representable value.

    A NON_BLIND variant would create a legitimate-looking path to gold that G-S5 would then
    have to reject. v0 refuses to represent it.
    """

    BLIND = "BLIND"


# --------------------------------------------------------------------------- guards


def _enum(value, enum_cls, field_name):
    """Reject anything that is not a genuine member of `enum_cls`.

    Type ANNOTATIONS are not enforcement. Python will happily accept
    `AssertedRelation(origin="MODEL")`, and every `is`-comparison against an enum member
    then falls through silently — which would defeat ST2 by bypassing the enum rather
    than extending it. Structural impossibility only holds if the boundary is checked.
    """
    if not isinstance(value, enum_cls):
        raise TypeError(
            f"{field_name} must be a {enum_cls.__name__} member, got {value!r}. "
            f"Permitted: {[m.name for m in enum_cls]}")
    return value


# ---------------------------------------------------------------- evidence + position


@dataclass(frozen=True, slots=True)
class SourcePosition:
    """Deterministic position within one immutable version of a source."""

    source_id: str
    source_version_hash: str
    coordinate_system: CoordinateSystem
    start: int
    end: int
    turn: int | None = None       # optional derived, pending parser audit
    message: int | None = None    # optional derived, pending parser audit

    def __post_init__(self) -> None:
        _enum(self.coordinate_system, CoordinateSystem, "SourcePosition.coordinate_system")
        if self.coordinate_system is not CoordinateSystem.LINE:
            raise ValueError("v0 canonical coordinate system is LINE")
        if self.start < 1 or self.end < self.start:
            raise ValueError(f"invalid line span {self.start}..{self.end}")
        if not self.source_version_hash:
            raise ValueError("source_version_hash is required; a position without a "
                             "version does not identify which text was cited")


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    """A re-verifiable pointer to a passage.

    Version and hash are required. We already have a live case where a document's indexed
    representation differs from the original archive, so document id plus quote does not
    identify WHICH VERSION was adjudicated. Re-verifiability needs identity + version +
    exact position + passage hash + verbatim anchor. This also serves B1: distinguishing
    "no evidence exists" from "evidence we can no longer locate" is only possible if
    references stay checkable after the store changes.
    """

    source_id: str
    source_system: SourceSystem
    source_version_hash: str
    position: SourcePosition
    passage_hash: str
    quote: str
    evidence_id: str

    def __post_init__(self) -> None:
        _enum(self.source_system, SourceSystem, "EvidenceRef.source_system")
        for name in ("source_version_hash", "passage_hash", "quote", "evidence_id"):
            if not getattr(self, name):
                raise ValueError(f"EvidenceRef.{name} is required for re-verifiability")
        if self.position.source_id != self.source_id:
            raise ValueError("position.source_id must match EvidenceRef.source_id")
        if self.position.source_version_hash != self.source_version_hash:
            raise ValueError("position and evidence must cite the same source version")

    @property
    def key(self) -> str:
        """Stable evidence identity.

        `source_id` is the document/source being cited. It is not the evidence row. A
        single document can produce multiple conflicting passages, so adjudication must
        key on evidence identity.
        """
        return self.evidence_id


@dataclass(frozen=True, slots=True)
class Question:
    """Stable question identity.

    A bare string made "two resolutions of the same question" undefined. Questions are
    versioned so a re-phrased question is a different object rather than a silent
    redefinition of an existing one.
    """

    id: str
    text: str
    version: int = 1
    caller_frame: str | None = None
    caller_taxonomy_version: str | None = None
    """An EXPLICIT frame supplied by the CALLER. It lives on the question, not on a
    RoutingProposal, because a boolean the inference layer could set would be
    self-certification. Caller-explicit routing and inferred routing are DIFFERENT
    provenance classes, not one class with a flag."""

    def __post_init__(self) -> None:
        if (self.caller_frame is None) != (self.caller_taxonomy_version is None):
            raise ValueError("caller_frame and caller_taxonomy_version must be set together")


# ------------------------------------------------------------------------ relations


@dataclass(frozen=True, slots=True)
class ProposedRelation:
    """A relation a model proposes. Permanently inferential. APPEND-ONLY.

    There is deliberately NO `disposition` field and NO `proposal_support_count` field.

    A mutable disposition would be a lifecycle knob on the proposal itself; disposition is
    recorded as a separate ProposalDispositionEvent so the original proposal is never
    edited. A stored support count would be a number a writer could inflate to argue for
    promotion. Support is instead DERIVED by counting independent proposal records
    (`derive_support`), which gives G-S3 its stronger form: 100 agreeing model proposals
    are still just 100 proposals, and the count is a description of the record rather than
    a claim made inside it.
    """

    id: str
    subject_ref: EvidenceRef
    relation_type: RelationType
    object_ref: EvidenceRef
    evidence_refs: tuple[EvidenceRef, ...]
    extractor_id: str
    extraction_run_id: str

    def __post_init__(self) -> None:
        _enum(self.relation_type, RelationType, "ProposedRelation.relation_type")
        if not self.extractor_id:
            raise ValueError("extractor_id is required: a proposal must name its extractor")
        if not self.extraction_run_id:
            raise ValueError("extraction_run_id is required to distinguish independent runs")

    @property
    def claim_key(self) -> tuple[str, str, str]:
        """Identity of the CLAIM, independent of which run produced it."""
        return (self.subject_ref.passage_hash, self.relation_type.value,
                self.object_ref.passage_hash)


@dataclass(frozen=True, slots=True)
class ProposalDispositionEvent:
    """Append-only lifecycle event. The proposal it refers to is never edited."""

    id: str
    proposal_id: str
    disposition: ProposalDisposition
    rationale: str
    superseded_by_proposal_id: str | None = None

    def __post_init__(self) -> None:
        _enum(self.disposition, ProposalDisposition, "ProposalDispositionEvent.disposition")
        if (self.disposition is ProposalDisposition.SUPERSEDED_BY_PROPOSAL
                and not self.superseded_by_proposal_id):
            raise ValueError("SUPERSEDED_BY_PROPOSAL requires superseded_by_proposal_id")


def derive_support(proposals: Sequence[ProposedRelation]) -> dict[tuple[str, str, str], int]:
    """Count INDEPENDENT extraction runs per claim.

    Repeats from one run are not independent support, so runs are de-duplicated. Nothing
    in the codebase consumes this to promote anything — it exists to describe the record.
    """
    seen: dict[tuple[str, str, str], set[str]] = {}
    for p in proposals:
        seen.setdefault(p.claim_key, set()).add(p.extraction_run_id)
    return {k: len(v) for k, v in seen.items()}


@dataclass(frozen=True, slots=True)
class AssertedRelation:
    """A relation explicitly asserted by an identifiable source or named human.

    ASSERTED means: an identifiable source or named human EXPLICITLY asserted this.
    ASSERTED DOES NOT MEAN: the relation is objectively true.

    Correspondingly, ABSENCE of an assertion proves nothing about whether the relation or
    event exists. The redacted ledger has a documented recording gap in which real work
    produced no claims on a healthy ledger. Source completeness and assertion explicitness
    are separate concepts and are kept separate here; no completeness score is modelled.
    """

    id: str
    subject_ref: EvidenceRef
    relation_type: RelationType
    object_ref: EvidenceRef
    evidence_refs: tuple[EvidenceRef, ...]
    origin: AssertionOrigin
    typed_source_ref: str | None = None
    human_adjudicator_id: str | None = None
    derived_from_proposal_id: str | None = None

    def __post_init__(self) -> None:
        o = _enum(self.origin, AssertionOrigin, "AssertedRelation.origin")
        _enum(self.relation_type, RelationType, "AssertedRelation.relation_type")
        if o is AssertionOrigin.TYPED_SOURCE:
            if not self.typed_source_ref:
                raise ValueError("TYPED_SOURCE origin requires typed_source_ref")
            if self.derived_from_proposal_id is not None:
                raise ValueError("TYPED_SOURCE assertion cannot derive from a proposal")
        elif o is AssertionOrigin.HUMAN_REVIEWED_PROPOSAL:
            if not self.human_adjudicator_id:
                raise ValueError("HUMAN_REVIEWED_PROPOSAL requires human_adjudicator_id")
            if not self.derived_from_proposal_id:
                raise ValueError("HUMAN_REVIEWED_PROPOSAL requires derived_from_proposal_id")


    @property
    def gold_eligible(self) -> bool:
        """DERIVED. A stored boolean would be a field someone could set."""
        return (self.origin is not AssertionOrigin.HUMAN_REVIEWED_PROPOSAL
                and self.derived_from_proposal_id is None)


@dataclass(frozen=True, slots=True)
class AssertedRelationReview:
    """Lifecycle event on an assertion. NOT the same as a CONTRADICTS relation.

        A CONTRADICTS B   a statement about EVIDENCE SEMANTICS
        A is retracted    a statement about the LIFECYCLE of an explicit assertion

    The original assertion stays immutable. A retraction proves the identified source or
    human explicitly retracted it; it does not rewrite history and does not make the
    original assertion cease to have existed.
    """

    id: str
    asserted_relation_id: str
    origin: ReviewOrigin
    verdict: AssertionReviewVerdict
    rationale: str
    typed_source_ref: str | None = None
    reviewer_id: str | None = None
    replacement_assertion_id: str | None = None

    def __post_init__(self) -> None:
        _enum(self.origin, ReviewOrigin, "AssertedRelationReview.origin")
        _enum(self.verdict, AssertionReviewVerdict, "AssertedRelationReview.verdict")
        if self.origin is ReviewOrigin.TYPED_SOURCE and not self.typed_source_ref:
            raise ValueError("TYPED_SOURCE review requires typed_source_ref")
        if self.origin is ReviewOrigin.HUMAN and not self.reviewer_id:
            raise ValueError("HUMAN review requires reviewer_id")


# ------------------------------------------------------------- interpretive proposals


@dataclass(frozen=True, slots=True)
class SourceRoleProposal:
    """Source role is INFERENCE even when obvious.

    There is deliberately no AssertedSourceRole type in v0 and no write path back into
    RAG v1 metadata: writing source role into the ingestion contract would disguise
    inference as deterministic metadata and retroactively alter a closed phase's record.
    """

    id: str
    source_ref: EvidenceRef
    proposed_role: SourceRole
    evidence_refs: tuple[EvidenceRef, ...]
    extractor_id: str

    def __post_init__(self) -> None:
        _enum(self.proposed_role, SourceRole, "SourceRoleProposal.proposed_role")
        if not self.extractor_id:
            raise ValueError("extractor_id is required")


@dataclass(frozen=True, slots=True)
class ClaimProposal:
    """What a model PROPOSES a piece of evidence says about a question. ALWAYS inferential.

    Modelled as a first-class proposal for the same reason SourceRoleProposal is: reading a
    document and deciding what it claims is inference, and the adjudicator's conclusion text
    comes straight from one of these. An earlier revision passed claims as anonymous tuples
    and synthesised `claim:<evidence_id>` identifiers at resolution time. Those strings were
    written into `Resolution.proposed_relation_refs`, a field whose PostgreSQL counterpart
    is `resolution_proposed_dep.proposal_id REFERENCES proposed_relation(id)` - so the
    resolution was not persistable at all, and the single most load-bearing inference in the
    whole resolution had no identity of its own.

    A claim is NOT a relation. It gets its own dependency edge rather than borrowing one.
    """

    id: str
    evidence_id: str
    claim: str
    extractor_id: str
    question_id: str | None = None

    def __post_init__(self) -> None:
        for name in ("id", "evidence_id", "claim", "extractor_id"):
            if not getattr(self, name):
                raise ValueError(f"ClaimProposal.{name} is required")


@dataclass(frozen=True, slots=True)
class FrameTaxonomy:
    """Closed, versioned enumeration of authority frames."""

    version: str
    frames: tuple[str, ...]
    UNKNOWN = "UNKNOWN_OR_AMBIGUOUS"

    def __post_init__(self) -> None:
        if not self.version:
            raise ValueError("taxonomy version is required")
        if self.UNKNOWN in self.frames:
            raise ValueError("UNKNOWN_OR_AMBIGUOUS is implicit and must not be enumerated")

    def permits(self, frame: str) -> bool:
        return frame == self.UNKNOWN or frame in self.frames


@dataclass(frozen=True, slots=True)
class RoutingProposal:
    """Which authority frame an EXTRACTOR proposes. ALWAYS inferential.

    There is no `explicitly_specified` flag: caller-explicit routing lives on
    `Question.caller_frame` and is a different provenance class. A flag here would let the
    inference layer certify its own route as caller-supplied - the same self-certification
    flaw as a self-reported blindness boolean.

    The frame MUST be validated against the referenced taxonomy; `from_extractor` requires
    the FrameTaxonomy object. In PostgreSQL the same rule is a composite foreign key
    (taxonomy_version, proposed_frame) -> taxonomy_entry(version, frame), which is the real
    enforcement.

    `alternates` records frames CONSIDERED but not selected, so "converged across the
    frames considered" is checkable rather than implied.
    """

    id: str
    question_id: str
    taxonomy_version: str
    proposed_frame: str
    extractor_id: str
    alternates: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not self.extractor_id:
            raise ValueError("a routing proposal is always inferential and must name its "
                             "extractor")

    @classmethod
    def from_extractor(cls, *, id: str, question: "Question", taxonomy: "FrameTaxonomy",
                       proposed_frame: str, extractor_id: str,
                       alternates: tuple[tuple[str, str], ...] = ()) -> "RoutingProposal":
        if not taxonomy.permits(proposed_frame):
            raise ValueError(
                f"frame {proposed_frame!r} is not in taxonomy {taxonomy.version!r}; "
                f"permitted: {list(taxonomy.frames) + [taxonomy.UNKNOWN]}")
        for frame, _ in alternates:
            if not taxonomy.permits(frame):
                raise ValueError(f"alternate frame {frame!r} is not in the taxonomy")
        return cls(id=id, question_id=question.id, taxonomy_version=taxonomy.version,
                   proposed_frame=proposed_frame, extractor_id=extractor_id,
                   alternates=alternates)


def caller_frame_of(question: "Question", taxonomy: "FrameTaxonomy") -> str | None:
    """The caller's explicit frame, validated. Returns None when the caller gave none.

    This is the ONLY route to an explicit frame. It reads the question and never consults
    an extractor, so no inference path can produce one.
    """
    if question.caller_frame is None:
        return None
    if question.caller_taxonomy_version != taxonomy.version:
        raise ValueError("caller frame cites a different taxonomy version")
    if not taxonomy.permits(question.caller_frame):
        raise ValueError(f"caller frame {question.caller_frame!r} is not in the taxonomy")
    return question.caller_frame
