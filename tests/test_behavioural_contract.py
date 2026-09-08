"""B1-B8 behavioural contract. Synthetic fixtures, expected results known BY CONSTRUCTION.

No human or model adjudicates anything here. Each fixture states the facts explicitly, so
the correct answer is a property of the fixture rather than a judgement about it. That is
what makes this suite a release gate where the real-corpus queue cannot be one.

WHAT THIS SUITE DOES NOT ESTABLISH, stated up front so it is never over-read: these are
clean constructed cases. Passing shows the RULES are right, not that the Historian survives
messy real evidence. The HD-01..HD-20 corpus canary covers that and is deliberately
non-blocking.

Assertions are on machine-checkable outputs only - outcome enum, evidence ids, frame,
caller-specified flag, silence, conflict. No prose is graded.
"""

import pytest

from historian.adjudicator import Adjudicator, AuthorityPolicy
from historian.types import (
    AssertedRelation,
    AssertionOrigin,
    ClaimProposal,
    CoordinateSystem,
    EvidenceRef,
    FrameTaxonomy,
    Outcome,
    ProposedRelation,
    Question,
    RelationType,
    RoutingProposal,
    SourcePosition,
    SourceRole,
    SourceRoleProposal,
    SourceSystem,
)

LOCAL_FRAME = "CURRENT_OPERATIONAL_STATE"
UPSTREAM_FRAME = "UPSTREAM_PRODUCT_STATE"
TAX = FrameTaxonomy("frames-v1", (LOCAL_FRAME, UPSTREAM_FRAME))
POLICY = AuthorityPolicy("frames-v1", {
    LOCAL_FRAME: (SourceRole.LOCAL_OPERATIONAL_DECISION, SourceRole.INCIDENT_RECORD),
    UPSTREAM_FRAME: (SourceRole.UPSTREAM_VENDOR_MATERIAL, SourceRole.COMPARATIVE_REVIEW),
})


@pytest.fixture
def eng():
    return Adjudicator(TAX, POLICY)


def ev(source_id, *, evidence_id=None, start=1, end=2):
    p = SourcePosition(source_id, "v1", CoordinateSystem.LINE, start, end)
    return EvidenceRef(source_id, SourceSystem.RAG_V1, "v1", p,
                       f"h-{source_id}-{start}", "anchor",
                       evidence_id=evidence_id or source_id)


def rel(kind, subject, obj):
    """An ASSERTED relation. Only these settle disagreements."""
    return AssertedRelation(f"rel-{subject}-{obj}", ev(subject), kind, ev(obj),
                            (ev(subject),), AssertionOrigin.TYPED_SOURCE,
                            typed_source_ref="fixture")


def proposed_rel(kind, subject, obj):
    """A PROPOSED relation. A model's inference. Must never settle a disagreement."""
    return ProposedRelation(f"prop-{subject}-{obj}", ev(subject), kind, ev(obj),
                            (ev(subject),), "model-x", "run-1")


def claim(evidence_id, text, extractor="m", qid="q1"):
    return ClaimProposal(f"cp-{evidence_id}", evidence_id, text, extractor, qid)


def roles(mapping):
    """Source roles arrive as PROPOSALS with identities, never as a bare dict."""
    return tuple(SourceRoleProposal(f"srp-{sid}", ev(sid), role, (ev(sid),), "m")
                 for sid, role in mapping.items())


def route(frame, qid="q1"):
    """A frame an extractor PROPOSES. Built via the plain constructor on purpose: the
    validating `from_extractor` path would refuse an out-of-taxonomy frame, and B6 needs to
    prove the ADJUDICATOR refuses it too - a rogue or misconfigured extractor writing
    straight to the table is exactly the case the invariant defends against."""
    return RoutingProposal(f"rp-{qid}", qid, "frames-v1", frame, "m")


def q(qid="q1", frame=None):
    return Question(qid, "constructed question", caller_frame=frame,
                    caller_taxonomy_version="frames-v1" if frame else None)


# ============================================================ B1 no relation by absence


def test_B1_silence_does_not_contradict(eng):
    """A says X, B says nothing. Silence must not become a competing claim."""
    a = eng.adjudicate(question=q(), evidence=(ev("A"), ev("B")),
                       claims=(claim("A", "X", "m"),),
                       source_role_proposals=roles({"A": SourceRole.LOCAL_OPERATIONAL_DECISION,
                                     "B": SourceRole.LOCAL_OPERATIONAL_DECISION}),
                       routing=route(LOCAL_FRAME))
    assert a.resolution.outcome is Outcome.RESOLVED
    assert a.resolution.conclusion == "X"
    assert a.silent_refs == ("B",)
    assert a.conflict is False


def test_B1_universal_silence_is_unresolved_not_a_negative(eng):
    """No source speaks. The answer is 'not established', never 'it is not so'."""
    a = eng.adjudicate(question=q(), evidence=(ev("A"), ev("B")), claims=(),
                       source_role_proposals=roles({"A": SourceRole.LOCAL_OPERATIONAL_DECISION,
                                     "B": SourceRole.LOCAL_OPERATIONAL_DECISION}),
                       routing=route(LOCAL_FRAME))
    assert a.resolution.outcome is Outcome.UNRESOLVED
    assert a.resolution.conclusion is None
    assert "no authoritative source offers a claim" in a.resolution.unresolved_reason
    assert set(a.silent_refs) == {"A", "B"}


# ============================================================ B2 order isn't authority


def test_B2_later_position_does_not_win_by_position(eng):
    """Two claims, the second stated later. Without an explicit relation, order settles
    nothing and the honest answer is UNRESOLVED."""
    a = eng.adjudicate(question=q(), evidence=(ev("EARLY"), ev("LATE")),
                       claims=(claim("EARLY", "A", "m"),
                               claim("LATE", "B", "m")),
                       source_role_proposals=roles({"EARLY": SourceRole.LOCAL_OPERATIONAL_DECISION,
                                     "LATE": SourceRole.LOCAL_OPERATIONAL_DECISION}),
                       routing=route(LOCAL_FRAME))
    assert a.resolution.outcome is Outcome.UNRESOLVED
    assert a.conflict is True


def test_B2_later_position_in_the_same_document_does_not_win(eng):
    """The v3 queue's B2 construction is one document with early/later spans.

    This is the regression for the source_id/evidence_id collapse: document id is not
    evidence identity. Two conflicting passages from one source must remain two speaking
    claims, not collapse to the later claim by dict insertion order.
    """
    early = ev("doc-42", evidence_id="doc-42:10-20", start=10, end=20)
    late = ev("doc-42", evidence_id="doc-42:300-310", start=300, end=310)
    a = eng.adjudicate(
        question=q(),
        evidence=(early, late),
        claims=(ClaimProposal("cp-early", early.key, "policy is X", "m", "q1"),
                ClaimProposal("cp-late", late.key, "policy is Y", "m", "q1")),
        source_role_proposals=(
            SourceRoleProposal("srp-early", early,
                               SourceRole.LOCAL_OPERATIONAL_DECISION, (early,), "m"),
            SourceRoleProposal("srp-late", late,
                               SourceRole.LOCAL_OPERATIONAL_DECISION, (late,), "m")),
        routing=route(LOCAL_FRAME),
    )
    assert a.resolution.outcome is Outcome.UNRESOLVED
    assert a.resolution.conclusion is None
    assert a.conflict is True
    assert a.authority_refs == (early.key, late.key)
    assert a.resolution.claim_proposal_refs == ("cp-early", "cp-late")


def test_claims_must_name_evidence_ids_in_packet(eng):
    """A document id is not a valid claim key when the packet contains span evidence ids."""
    early = ev("doc-42", evidence_id="doc-42:10-20", start=10, end=20)
    late = ev("doc-42", evidence_id="doc-42:300-310", start=300, end=310)
    with pytest.raises(ValueError, match="ClaimProposal.evidence_id"):
        eng.adjudicate(
            question=q(),
            evidence=(early, late),
            claims=(ClaimProposal("cp-early", "doc-42", "policy is X", "m", "q1"),),
            source_role_proposals=(
                SourceRoleProposal("srp-early", early,
                                   SourceRole.LOCAL_OPERATIONAL_DECISION, (early,), "m"),
                SourceRoleProposal("srp-late", late,
                                   SourceRole.LOCAL_OPERATIONAL_DECISION, (late,), "m")),
            routing=route(LOCAL_FRAME),
        )


def test_duplicate_claim_evidence_ids_are_rejected(eng):
    a = ev("doc-42", evidence_id="doc-42:10-20", start=10, end=20)
    with pytest.raises(ValueError, match="duplicate ClaimProposal.evidence_id"):
        eng.adjudicate(
            question=q(),
            evidence=(a,),
            claims=(ClaimProposal("cp-a", a.key, "policy is X", "m", "q1"),
                    ClaimProposal("cp-b", a.key, "policy is Y", "m", "q1")),
            source_role_proposals=(
                SourceRoleProposal("srp-a", a,
                                   SourceRole.LOCAL_OPERATIONAL_DECISION, (a,), "m"),),
            routing=route(LOCAL_FRAME),
        )


def test_relation_endpoints_must_name_evidence_ids_in_packet(eng):
    early = ev("doc-42", evidence_id="doc-42:10-20", start=10, end=20)
    late = ev("doc-42", evidence_id="doc-42:300-310", start=300, end=310)
    stale_doc_ref = ev("doc-42", evidence_id="doc-42", start=300, end=310)
    with pytest.raises(ValueError, match="relation evidence_id"):
        eng.adjudicate(
            question=q(),
            evidence=(early, late),
            claims=(ClaimProposal("cp-early", early.key, "policy is X", "m", "q1"),
                    ClaimProposal("cp-late", late.key, "policy is Y", "m", "q1")),
            source_role_proposals=(
                SourceRoleProposal("srp-early", early,
                                   SourceRole.LOCAL_OPERATIONAL_DECISION, (early,), "m"),
                SourceRoleProposal("srp-late", late,
                                   SourceRole.LOCAL_OPERATIONAL_DECISION, (late,), "m")),
            relations=(AssertedRelation("rel-stale", stale_doc_ref, RelationType.CORRECTS,
                                        early, (stale_doc_ref,),
                                        AssertionOrigin.TYPED_SOURCE,
                                        typed_source_ref="fixture"),),
            routing=route(LOCAL_FRAME),
        )


def test_routing_proposal_must_belong_to_the_question(eng):
    with pytest.raises(ValueError, match="RoutingProposal.question_id"):
        eng.adjudicate(
            question=q("q-current"),
            evidence=(ev("A"),),
            claims=(ClaimProposal("cp-A", "A", "X", "m", "q-current"),),
            source_role_proposals=roles({"A": SourceRole.LOCAL_OPERATIONAL_DECISION}),
            routing=route(LOCAL_FRAME, qid="q-other"),
        )


def test_claim_proposal_must_belong_to_the_question(eng):
    with pytest.raises(ValueError, match="ClaimProposal.question_id"):
        eng.adjudicate(
            question=q("q-current"),
            evidence=(ev("A"),),
            claims=(ClaimProposal("cp-A", "A", "X", "m", "q-other"),),
            source_role_proposals=roles({"A": SourceRole.LOCAL_OPERATIONAL_DECISION}),
            routing=route(LOCAL_FRAME, qid="q-current"),
        )


def test_conflicting_source_roles_are_not_order_dependent(eng):
    evidence = ev("A")
    a = eng.adjudicate(
        question=q(),
        evidence=(evidence,),
        claims=(ClaimProposal("cp-A", "A", "X", "m", "q1"),),
        source_role_proposals=(
            SourceRoleProposal("srp-local", evidence,
                               SourceRole.LOCAL_OPERATIONAL_DECISION, (evidence,), "m"),
            SourceRoleProposal("srp-vendor", evidence,
                               SourceRole.UPSTREAM_VENDOR_MATERIAL, (evidence,), "m"),
        ),
        routing=route(LOCAL_FRAME),
    )
    assert a.resolution.outcome is Outcome.UNRESOLVED
    assert a.resolution.conclusion is None
    assert "conflicting source-role proposals" in a.resolution.unresolved_reason
    assert a.authority_refs == ()
    assert a.resolution.source_role_proposal_refs == ("srp-local", "srp-vendor")


def test_B2_explicit_correction_does_win(eng):
    """The same pair, plus an ASSERTED CORRECTS. Now it resolves - to the corrector."""
    a = eng.adjudicate(question=q(), evidence=(ev("EARLY"), ev("LATE")),
                       claims=(claim("EARLY", "A", "m"),
                               claim("LATE", "B", "m")),
                       source_role_proposals=roles({"EARLY": SourceRole.LOCAL_OPERATIONAL_DECISION,
                                     "LATE": SourceRole.LOCAL_OPERATIONAL_DECISION}),
                       relations=(rel(RelationType.CORRECTS, "LATE", "EARLY"),),
                       routing=route(LOCAL_FRAME))
    assert a.resolution.outcome is Outcome.RESOLVED
    assert a.resolution.conclusion == "B"
    assert a.authority_refs == ("LATE",)


# ============================================================ B3 unresolved is valid


def test_B3_equal_sources_conflict_unresolved(eng):
    a = eng.adjudicate(question=q(), evidence=(ev("P"), ev("Q")),
                       claims=(claim("P", "yes", "m"),
                               claim("Q", "no", "m")),
                       source_role_proposals=roles({"P": SourceRole.LOCAL_OPERATIONAL_DECISION,
                                     "Q": SourceRole.LOCAL_OPERATIONAL_DECISION}),
                       routing=route(LOCAL_FRAME))
    assert a.resolution.outcome is Outcome.UNRESOLVED
    assert "disagree" in a.resolution.unresolved_reason


def test_B3_majority_is_not_authority(eng):
    """Two sources agree, one dissents, nothing resolves it. Counting heads is not a
    supersession relation, so this stays UNRESOLVED."""
    a = eng.adjudicate(question=q(), evidence=(ev("P"), ev("Q"), ev("R")),
                       claims=(claim("P", "yes", "m"),
                               claim("Q", "yes", "m"),
                               claim("R", "no", "m")),
                       source_role_proposals=roles({k: SourceRole.LOCAL_OPERATIONAL_DECISION
                                     for k in "PQR"}),
                       routing=route(LOCAL_FRAME))
    assert a.resolution.outcome is Outcome.UNRESOLVED


# ============================================================ B4 false abstention fails


def test_B4_single_clear_claim_resolves(eng):
    a = eng.adjudicate(question=q(), evidence=(ev("A"),),
                       claims=(claim("A", "the answer", "m"),),
                       source_role_proposals=roles({"A": SourceRole.LOCAL_OPERATIONAL_DECISION}),
                       routing=route(LOCAL_FRAME))
    assert a.resolution.outcome is Outcome.RESOLVED
    assert a.resolution.conclusion == "the answer"


def test_B4_agreement_is_not_conflict(eng):
    """Two sources saying the same thing must not be mistaken for a disagreement."""
    a = eng.adjudicate(question=q(), evidence=(ev("A"), ev("B")),
                       claims=(claim("A", "same", "m"),
                               claim("B", "same", "m")),
                       source_role_proposals=roles({"A": SourceRole.LOCAL_OPERATIONAL_DECISION,
                                     "B": SourceRole.LOCAL_OPERATIONAL_DECISION}),
                       routing=route(LOCAL_FRAME))
    assert a.resolution.outcome is Outcome.RESOLVED
    assert a.conflict is False


# ============================================================ B5 routing is inferential


def test_B5_proposed_route_is_never_caller_specified(eng):
    a = eng.adjudicate(question=q(), evidence=(ev("A"),),
                       claims=(claim("A", "x", "m"),),
                       source_role_proposals=roles({"A": SourceRole.LOCAL_OPERATIONAL_DECISION}),
                       routing=route(LOCAL_FRAME))
    assert a.frame == LOCAL_FRAME
    assert a.frame_is_caller_specified is False


def test_B5_caller_frame_is_marked_as_such(eng):
    a = eng.adjudicate(question=q(frame=UPSTREAM_FRAME), evidence=(ev("V"),),
                       claims=(claim("V", "x", "m"),),
                       source_role_proposals=roles({"V": SourceRole.UPSTREAM_VENDOR_MATERIAL}))
    assert a.frame == UPSTREAM_FRAME
    assert a.frame_is_caller_specified is True


# ============================================================ B6 closed frame space


def test_B6_frame_outside_taxonomy_is_never_adopted(eng):
    a = eng.adjudicate(question=q(), evidence=(ev("A"),),
                       claims=(claim("A", "x", "m"),),
                       source_role_proposals=roles({"A": SourceRole.LOCAL_OPERATIONAL_DECISION}),
                       routing=route("A_FRAME_NOBODY_DEFINED"))
    assert a.frame == FrameTaxonomy.UNKNOWN
    assert a.frame_is_caller_specified is False


def test_B6_no_proposed_frame_degrades_to_unknown(eng):
    a = eng.adjudicate(question=q(), evidence=(ev("A"),),
                       claims=(claim("A", "x", "m"),),
                       source_role_proposals=roles({"A": SourceRole.LOCAL_OPERATIONAL_DECISION}))
    assert a.frame == FrameTaxonomy.UNKNOWN


# ============================================================ B7 recency isn't authority


def test_B7_newer_vendor_does_not_override_older_local(eng):
    """OLD is a local decision; NEW is a newer vendor announcement. The question is about
    local configuration, so the OLDER source is authoritative and the newer one is out of
    scope entirely."""
    a = eng.adjudicate(question=q(), evidence=(ev("OLD_LOCAL"), ev("NEW_VENDOR")),
                       claims=(claim("OLD_LOCAL", "config X", "m"),
                               claim("NEW_VENDOR", "announcement Y", "m")),
                       source_role_proposals=roles({"OLD_LOCAL": SourceRole.LOCAL_OPERATIONAL_DECISION,
                                     "NEW_VENDOR": SourceRole.UPSTREAM_VENDOR_MATERIAL}),
                       routing=route(LOCAL_FRAME))
    assert a.resolution.outcome is Outcome.RESOLVED
    assert a.resolution.conclusion == "config X"
    assert a.authority_refs == ("OLD_LOCAL",)
    assert "NEW_VENDOR" not in a.authority_refs


def test_B7_recency_cannot_break_a_tie_between_equals(eng):
    """Same role, conflicting claims, one plainly later. Recency is not a tie-break, so
    this must stay UNRESOLVED. A recency rule would make it RESOLVED and fail here."""
    a = eng.adjudicate(question=q(), evidence=(ev("2026-01-OLD"), ev("2026-12-NEW")),
                       claims=(claim("2026-01-OLD", "old answer", "m"),
                               claim("2026-12-NEW", "new answer", "m")),
                       source_role_proposals=roles({"2026-01-OLD": SourceRole.LOCAL_OPERATIONAL_DECISION,
                                     "2026-12-NEW": SourceRole.LOCAL_OPERATIONAL_DECISION}),
                       routing=route(LOCAL_FRAME))
    assert a.resolution.outcome is Outcome.UNRESOLVED
    assert a.conflict is True


# ==================================================== B8 authority is question-relative


def _pair(engine, frame):
    return engine.adjudicate(
        question=q(frame=frame), evidence=(ev("LOCAL"), ev("VENDOR")),
        claims=(claim("LOCAL", "local answer", "m"),
                claim("VENDOR", "vendor answer", "m")),
        source_role_proposals=roles({"LOCAL": SourceRole.LOCAL_OPERATIONAL_DECISION,
                      "VENDOR": SourceRole.UPSTREAM_VENDOR_MATERIAL}))


def test_B8_authority_switches_with_the_question(eng):
    """THE core B8 assertion: identical evidence, different question, authority moves."""
    local = _pair(eng, LOCAL_FRAME)
    upstream = _pair(eng, UPSTREAM_FRAME)
    assert local.authority_refs == ("LOCAL",)
    assert upstream.authority_refs == ("VENDOR",)
    assert local.resolution.conclusion == "local answer"
    assert upstream.resolution.conclusion == "vendor answer"


def test_B8_out_of_frame_evidence_is_excluded_not_outvoted(eng):
    """The non-authoritative source is not merely outranked - it never enters scope, so it
    cannot contribute a conflict."""
    a = _pair(eng, LOCAL_FRAME)
    assert a.conflict is False
    assert "VENDOR" in a.considered_refs
    assert "VENDOR" not in a.authority_refs


# ==================================================== closure-review defects (2026-08-23)
# Three defects were found in this engine by review AFTER the first contract suite passed.
# Two are behavioural and are pinned here. Each has a positive control, because a test that
# only proves a refusal cannot distinguish "correctly refuses" from "refuses everything".


def test_B2_proposed_relation_never_settles_a_conflict(eng):
    """DEFECT 1. A model proposing `A CORRECTS B` must not decide the disagreement.

    The engine originally duck-typed the relation tuple on `.relation_type`,
    `.subject_ref`, `.object_ref` - the fields `ProposedRelation` also carries. A model
    could therefore manufacture the settling relation and its own claim would win. That is
    promotion of a proposal to an assertion by the back door, which the ASSERTED/PROPOSED
    split exists to make unreachable.
    """
    a = eng.adjudicate(question=q(), evidence=(ev("A"), ev("B")),
                       claims=(claim("A", "X"), claim("B", "Y")),
                       source_role_proposals=roles({
                           "A": SourceRole.LOCAL_OPERATIONAL_DECISION,
                           "B": SourceRole.LOCAL_OPERATIONAL_DECISION}),
                       relations=(proposed_rel(RelationType.CORRECTS, "A", "B"),),
                       routing=route(LOCAL_FRAME))
    assert a.resolution.outcome is Outcome.UNRESOLVED
    assert a.resolution.conclusion is None
    assert a.conflict is True
    assert "no asserted relation resolves" in a.resolution.unresolved_reason
    # seen, and recorded as refused - not silently dropped
    assert a.refused_relation_refs == ("prop-A-B",)
    # a refused proposal is NOT support: it must not appear in the resolution's basis
    assert a.resolution.proposed_relation_refs == ()


def test_B2_asserted_relation_still_settles(eng):
    """Positive control for DEFECT 1: the same shape, asserted, DOES settle."""
    a = eng.adjudicate(question=q(), evidence=(ev("A"), ev("B")),
                       claims=(claim("A", "X"), claim("B", "Y")),
                       source_role_proposals=roles({
                           "A": SourceRole.LOCAL_OPERATIONAL_DECISION,
                           "B": SourceRole.LOCAL_OPERATIONAL_DECISION}),
                       relations=(rel(RelationType.CORRECTS, "A", "B"),),
                       routing=route(LOCAL_FRAME))
    assert a.resolution.outcome is Outcome.RESOLVED
    assert a.resolution.conclusion == "X"
    assert a.resolution.asserted_relation_refs == ("rel-A-B",)


def test_B3_partial_resolution_leaves_the_rest_unresolved(eng):
    """DEFECT 2. Three conflicting claims, one asserted relation, no relation to C.

    The engine originally set a winner from ANY resolved pair and then discarded every
    other claim, so `A CORRECTS B` silently erased the untouched A-vs-C conflict and
    reported RESOLVED X. A relation settles the pair it names and says nothing about a
    third source.
    """
    a = eng.adjudicate(question=q(), evidence=(ev("A"), ev("B"), ev("C")),
                       claims=(claim("A", "X"), claim("B", "Y"), claim("C", "Z")),
                       source_role_proposals=roles({
                           "A": SourceRole.LOCAL_OPERATIONAL_DECISION,
                           "B": SourceRole.LOCAL_OPERATIONAL_DECISION,
                           "C": SourceRole.LOCAL_OPERATIONAL_DECISION}),
                       relations=(rel(RelationType.CORRECTS, "A", "B"),),
                       routing=route(LOCAL_FRAME))
    assert a.resolution.outcome is Outcome.UNRESOLVED
    assert a.resolution.conclusion is None
    assert a.conflict is True
    assert "leaves" in a.resolution.unresolved_reason
    assert "unsettled" in a.resolution.unresolved_reason


def test_B3_full_domination_resolves(eng):
    """Positive control for DEFECT 2: when A settles BOTH B and C, A wins.

    Without this the partial-resolution rule could be satisfied by never resolving a
    three-way conflict at all, which would be false abstention (B4) wearing a safe face.
    """
    a = eng.adjudicate(question=q(), evidence=(ev("A"), ev("B"), ev("C")),
                       claims=(claim("A", "X"), claim("B", "Y"), claim("C", "Z")),
                       source_role_proposals=roles({
                           "A": SourceRole.LOCAL_OPERATIONAL_DECISION,
                           "B": SourceRole.LOCAL_OPERATIONAL_DECISION,
                           "C": SourceRole.LOCAL_OPERATIONAL_DECISION}),
                       relations=(rel(RelationType.CORRECTS, "A", "B"),
                                  rel(RelationType.SUPERSEDES, "A", "C")),
                       routing=route(LOCAL_FRAME))
    assert a.resolution.outcome is Outcome.RESOLVED
    assert a.resolution.conclusion == "X"
    assert set(a.resolution.asserted_relation_refs) == {"rel-A-B", "rel-A-C"}


def test_B3_contradictory_relation_set_does_not_resolve(eng):
    """Two claims each dominating the other is a contradictory record, not a decision."""
    a = eng.adjudicate(question=q(), evidence=(ev("A"), ev("B")),
                       claims=(claim("A", "X"), claim("B", "Y")),
                       source_role_proposals=roles({
                           "A": SourceRole.LOCAL_OPERATIONAL_DECISION,
                           "B": SourceRole.LOCAL_OPERATIONAL_DECISION}),
                       relations=(rel(RelationType.CORRECTS, "A", "B"),
                                  rel(RelationType.SUPERSEDES, "B", "A")),
                       routing=route(LOCAL_FRAME))
    assert a.resolution.outcome is Outcome.UNRESOLVED
    assert "contradictory" in a.resolution.unresolved_reason


def test_relations_must_be_typed_not_duck_typed(eng):
    """An object that merely LOOKS like a relation is refused outright.

    Belt and braces for DEFECT 1: the isinstance filter would silently ignore a stray
    object, and silently ignoring it is how the duck-typing hole reopens later.
    """
    class LooksLikeOne:
        relation_type = RelationType.CORRECTS
        subject_ref = ev("A")
        object_ref = ev("B")

    with pytest.raises(TypeError, match="duck-type"):
        eng.adjudicate(question=q(), evidence=(ev("A"), ev("B")),
                       claims=(claim("A", "X"), claim("B", "Y")),
                       source_role_proposals=roles({
                           "A": SourceRole.LOCAL_OPERATIONAL_DECISION,
                           "B": SourceRole.LOCAL_OPERATIONAL_DECISION}),
                       relations=(LooksLikeOne(),), routing=route(LOCAL_FRAME))
