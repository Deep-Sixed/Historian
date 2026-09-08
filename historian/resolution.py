"""Resolutions and their epistemic basis.

Two INDEPENDENT dimensions, one stored and one derived:

    resolution_method   STORED    what actually performed the reasoning
    support_profile     DERIVED   what kind of evidence it rests on

They are independent because a model can make an inferential leap over purely asserted
evidence: "no proposed dependencies" does not imply "deterministically derived". Collapsing
them into one field — as an earlier revision did — makes some real states inexpressible,
notably structural abstention, which is a DETERMINISTIC_RULE applied over
PROPOSED_DEPENDENT inputs.

support_profile is derived rather than stored so a resolution cannot cite proposed
relations while declaring it rests only on assertions.
"""

from __future__ import annotations

from dataclasses import dataclass

from .types import (
    EvidenceRef,
    _enum,
    Outcome,
    ResolutionMethod,
    ReviewVerdict,
    SupportProfile,
)


@dataclass(frozen=True, slots=True)
class Resolution:
    """Immutable. Reconsideration creates a new Resolution referencing the old one."""

    id: str
    question_id: str
    outcome: Outcome
    resolution_method: ResolutionMethod
    evidence_refs: tuple[EvidenceRef, ...] = ()
    asserted_relation_refs: tuple[str, ...] = ()
    proposed_relation_refs: tuple[str, ...] = ()
    claim_proposal_refs: tuple[str, ...] = ()
    source_role_proposal_refs: tuple[str, ...] = ()
    routing_proposal_ref: str | None = None
    conclusion: str | None = None
    unresolved_reason: str | None = None
    previous_resolution_id: str | None = None
    revision_reason: str | None = None

    def __post_init__(self) -> None:
        _enum(self.outcome, Outcome, "Resolution.outcome")
        _enum(self.resolution_method, ResolutionMethod, "Resolution.resolution_method")
        if self.outcome is Outcome.RESOLVED and not self.conclusion:
            raise ValueError("a RESOLVED resolution requires a conclusion")
        if self.outcome is Outcome.UNRESOLVED and not self.unresolved_reason:
            raise ValueError(
                "an UNRESOLVED resolution requires unresolved_reason: refusing to resolve "
                "is a substantive answer and must say why")
        if self.outcome is Outcome.UNRESOLVED and self.conclusion:
            raise ValueError("an UNRESOLVED resolution must not carry a conclusion")

    @property
    def support_profile(self) -> SupportProfile:
        """DERIVED from dependency refs.

        routing_proposal_ref is deliberately EXCLUDED. Routing selects which authority
        rules apply; it does not support the conclusion. Including it would make every
        routed resolution PROPOSED_DEPENDENT, collapsing a four-value vocabulary to two
        reachable values and destroying the distinction the field exists to draw.

        Source-role proposals ARE included: an authority judgement genuinely rests on them.
        Claim proposals are included for a stronger reason - a RESOLVED conclusion is
        literally the text of a proposed claim. Omitting them would let a resolution whose
        every input was inferred report DIRECT_EVIDENCE_ONLY, which is the exact overclaim
        this property exists to prevent.
        """
        proposed = (bool(self.proposed_relation_refs)
                    or bool(self.claim_proposal_refs)
                    or bool(self.source_role_proposal_refs))
        asserted = bool(self.asserted_relation_refs)
        if proposed and asserted:
            return SupportProfile.MIXED
        if proposed:
            return SupportProfile.PROPOSED_DEPENDENT
        if asserted:
            return SupportProfile.ASSERTED_RELATION_DEPENDENT
        return SupportProfile.DIRECT_EVIDENCE_ONLY


@dataclass(frozen=True, slots=True)
class ResolutionReview:
    """A human's judgement about an OUTPUT. Never mutates the resolution.

    Three link types that must never collapse into one another:

        ResolutionReview        a human's judgement about an output
        previous_resolution_id  Historian output lineage
        SUPERSEDES              an evidential relationship

    A rejected resolution does NOT require a replacement: rejection establishes only that
    the resolution is not accepted, not what the correct answer is. "R1 rejected, no
    replacement" is a valid terminal state.
    """

    id: str
    resolution_id: str
    reviewer_id: str
    verdict: ReviewVerdict
    rationale: str
    replacement_resolution_id: str | None = None

    def __post_init__(self) -> None:
        _enum(self.verdict, ReviewVerdict, "ResolutionReview.verdict")
        if not self.reviewer_id:
            raise ValueError("reviewer_id is required")
        if self.verdict is ReviewVerdict.ACCEPTED and self.replacement_resolution_id:
            raise ValueError("an ACCEPTED review cannot name a replacement")
