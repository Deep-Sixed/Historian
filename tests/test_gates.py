"""G-S1..G-S9 structural gate enforcement.

Each gate is tested BOTH ways: the forbidden state must be rejected or unrepresentable,
AND the legitimate neighbouring state must still work. A gate that rejects everything is
not enforcement, it is breakage — and would be indistinguishable from enforcement if only
the negative case were tested.
"""

import dataclasses
import pytest

from historian.capability import BlindAdjudicator, GoldCompiler, PacketBuilder
from historian.coverage import (
    CaseCoverage,
    SuiteIncomplete,
    compute_coverage,
    require_complete,
)
from historian.gold import (
    AdjudicationPacket,
    BlindAdjudication,
    EvaluationGold,
    GoldCaseSeed,
)
from historian.positions import precedes, same_source
from historian.resolution import Resolution, ResolutionReview
from historian.types import (
    AdjudicationMode,
    AdjudicationVerdict,
    ProposalDispositionEvent,
    Question,
    caller_frame_of,
    derive_support,
    AssertedRelation,
    AssertedRelationReview,
    AssertionOrigin,
    AssertionReviewVerdict,
    CoordinateSystem,
    EvidenceRef,
    FrameTaxonomy,
    Outcome,
    ProposalDisposition,
    ProposedRelation,
    RelationType,
    ResolutionMethod,
    ReviewOrigin,
    ReviewVerdict,
    RoutingProposal,
    SourcePosition,
    SourceRole,
    SourceRoleProposal,
    SourceSystem,
    SupportProfile,
)

pytestmark = pytest.mark.structural_gate


# ------------------------------------------------------------------ fixtures


def pos(source="doc-a", ver="v1", start=1, end=10):
    return SourcePosition(source, ver, CoordinateSystem.LINE, start, end)


def ev(source="doc-a", ver="v1", start=1, end=10, quote="anchor"):
    return EvidenceRef(source, SourceSystem.RAG_V1, ver,
                       pos(source, ver, start, end), f"h-{source}-{start}", quote,
                       evidence_id=f"{source}:{ver}:{start}-{end}")


def proposal(pid="P17", run="run-1"):
    return ProposedRelation(pid, ev(), RelationType.AUGMENTS, ev("doc-b"),
                            (ev(),), "model-x", run)


# ------------------------------------------------------- G-S1 epistemic immutability


def test_gs1_no_epistemic_class_field_exists():
    """PROPOSED -> ASSERTED is not a mutation because class is encoded by TYPE."""
    p = proposal()
    assert not hasattr(p, "epistemic_class")
    assert not hasattr(AssertedRelation, "epistemic_class")
    # the two are unrelated types; neither is a subclass of the other
    assert not issubclass(ProposedRelation, AssertedRelation)
    assert not issubclass(AssertedRelation, ProposedRelation)


def test_gs1_proposal_is_frozen():
    p = proposal()
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.extractor_id = "someone-else"


def test_gs1_proposal_is_append_only():
    """No disposition or support-count field on the proposal itself."""
    fields = {f.name for f in dataclasses.fields(ProposedRelation)}
    assert "disposition" not in fields
    assert "proposal_support_count" not in fields


def test_gs1_disposition_is_a_separate_event():
    e = ProposalDispositionEvent("D1", "P17", ProposalDisposition.REJECTED, "bad extract")
    assert e.proposal_id == "P17"
    assert not isinstance(e, ProposedRelation)


def test_gs1_supersession_event_needs_its_successor():
    with pytest.raises(ValueError, match="superseded_by_proposal_id"):
        ProposalDispositionEvent("D2", "P17",
                                 ProposalDisposition.SUPERSEDED_BY_PROPOSAL, "newer")


def test_gs1_disposition_has_no_confirmed_value():
    """A CONFIRMED disposition would be promotion by another name."""
    assert not hasattr(ProposalDisposition, "CONFIRMED")
    assert {d.name for d in ProposalDisposition} == {
        "ACTIVE", "REJECTED", "SUPERSEDED_BY_PROPOSAL"}


# ------------------------------------------------- G-S2 / G-S3 model cannot assert


def test_gs2_no_model_origin_variant():
    """A model-authored assertion is unrepresentable, not rejected."""
    names = {o.name for o in AssertionOrigin}
    assert "MODEL" not in names
    assert "MODEL_CONSENSUS" not in names
    assert names == {"TYPED_SOURCE", "HUMAN_REVIEWED_PROPOSAL"}


def test_blind_origin_is_not_representable_in_v0():
    """Citing an adjudication id proves it EXISTS, never which relation it established.

    That is the gold cross-wiring bug relocated into the assertion path, so rather than
    ship a label the system cannot enforce, the origin does not exist in v0.
    """
    assert "HUMAN_BLIND_ADJUDICATION" not in {o.name for o in AssertionOrigin}
    fields = {f.name for f in dataclasses.fields(AssertedRelation)}
    assert "blind_adjudication_id" not in fields


def test_gs2_assertion_origin_cannot_be_a_string():
    with pytest.raises(Exception):
        AssertedRelation("A1", ev(), RelationType.AUGMENTS, ev("doc-b"), (ev(),),
                         "MODEL").__post_init__()


def test_gs3_support_is_derived_not_stored():
    """100 agreeing proposals are still 100 proposals.

    Support cannot be written INSIDE a proposal to argue for its own promotion; it is
    counted across independent extraction runs, and nothing consumes the count.
    """
    props = [proposal(f"P{i}", run=f"run-{i}") for i in range(100)]
    support = derive_support(props)
    assert list(support.values()) == [100]
    for p in props:
        assert type(p) is ProposedRelation
        assert not hasattr(p, "gold_eligible")


def test_gs3_repeats_within_one_run_are_not_independent_support():
    props = [proposal("Pa", run="run-1"), proposal("Pb", run="run-1"),
             proposal("Pc", run="run-2")]
    assert list(derive_support(props).values()) == [2]


def test_gs2_model_review_of_assertion_is_unrepresentable():
    assert "MODEL" not in {o.name for o in ReviewOrigin}


# --------------------------------------------------------- G-S4 contaminated gold


def test_gs4_reviewed_proposal_is_not_gold_eligible():
    a = AssertedRelation("A42", ev(), RelationType.AUGMENTS, ev("doc-b"), (ev(),),
                         AssertionOrigin.HUMAN_REVIEWED_PROPOSAL,
                         human_adjudicator_id="redacted",
                         derived_from_proposal_id="P17")
    assert a.gold_eligible is False








def test_gs4_gold_eligible_is_derived_not_settable():
    a = AssertedRelation("A45", ev(), RelationType.AUGMENTS, ev("doc-b"), (ev(),),
                         AssertionOrigin.TYPED_SOURCE, typed_source_ref="clm-x")
    with pytest.raises(AttributeError):
        a.gold_eligible = False


# ------------------------------------------------------------ G-S5 blindness only


def test_gs5_only_blind_mode_is_representable():
    assert [m.name for m in AdjudicationMode] == ["BLIND"]


def test_gs5_packet_omits_family_and_invariants():
    """The packet has no field able to carry the contaminating context."""
    fields = {f.name for f in dataclasses.fields(AdjudicationPacket)}
    assert "family" not in fields
    assert "invariant_candidates" not in fields
    assert "expected_outcome" not in fields


def test_gs5_adjudicator_holds_no_seed_reference():
    """Blindness as absence of a reference, not as a flag."""
    adj = BlindAdjudicator(packets=object(), adjudications=object())
    assert not hasattr(adj, "_seeds")
    assert not hasattr(adj, "_gold")


# ---------------------------------------------------------- G-S6 gold provenance


def test_gs6_adjudicator_id_required():
    with pytest.raises(ValueError, match="adjudicator_id"):
        BlindAdjudication("ADJ1", "PKT1", "", AdjudicationVerdict.UNRESOLVED, "why")


def test_packet_insufficient_is_representable_but_not_an_outcome():
    adj = BlindAdjudication(
        "ADJ-ins", "PKT1", "alice", AdjudicationVerdict.PACKET_INSUFFICIENT,
        "the supplied packet omits the bearing evidence")
    assert adj.verdict is AdjudicationVerdict.PACKET_INSUFFICIENT
    assert "PACKET_INSUFFICIENT" not in {o.name for o in Outcome}


def test_packet_insufficient_cannot_smuggle_resolution_text():
    with pytest.raises(ValueError, match="PACKET_INSUFFICIENT"):
        BlindAdjudication(
            "ADJ-ins-bad", "PKT1", "alice",
            AdjudicationVerdict.PACKET_INSUFFICIENT, "bad packet",
            resolution_text="the answer is X")


def test_gs6_gold_requires_an_adjudication():
    with pytest.raises(ValueError, match="adjudication_id"):
        EvaluationGold("G1", "SEED1", "", Outcome.UNRESOLVED, True, ("B3",))


def test_gs6_resolved_gold_cannot_allow_abstention():
    """False abstention is a hard failure (B4), so the combination is rejected."""
    with pytest.raises(ValueError, match="false abstention"):
        EvaluationGold("G2", "SEED1", "ADJ1", Outcome.RESOLVED, True, ("B4",),
                       expected_resolution="x")


# ------------------------------------------------------------- G-S7 closed frames


def test_gs7_frame_must_be_in_taxonomy():
    tax = FrameTaxonomy("historian-frames-v1",
                        ("CURRENT_OPERATIONAL_STATE", "UPSTREAM_PRODUCT_STATE"))
    assert tax.permits("CURRENT_OPERATIONAL_STATE")
    assert tax.permits(FrameTaxonomy.UNKNOWN)
    assert not tax.permits("INVENTED_FRAME")


def test_gs7_inferred_route_must_name_its_extractor():
    with pytest.raises(ValueError, match="must name its"):
        RoutingProposal("R1", "q1", "v1", "CURRENT_OPERATIONAL_STATE", "")


def test_gs7_routing_proposal_has_no_explicit_flag():
    """A flag here would let the inference layer certify its own route."""
    fields = {f.name for f in dataclasses.fields(RoutingProposal)}
    assert "explicitly_specified" not in fields


def test_gs7_route_frame_is_validated_against_the_taxonomy():
    """The factory refuses a frame nobody checked - the composite FK in-process."""
    tax = FrameTaxonomy("v1", ("CURRENT_OPERATIONAL_STATE",))
    q = Question("q1", "what is the state?")
    with pytest.raises(ValueError, match="not in taxonomy"):
        RoutingProposal.from_extractor(id="R1", question=q, taxonomy=tax,
                                       proposed_frame="INVENTED", extractor_id="m")


def test_gs7_alternates_are_validated_too():
    tax = FrameTaxonomy("v1", ("CURRENT_OPERATIONAL_STATE",))
    q = Question("q1", "what is the state?")
    with pytest.raises(ValueError, match="alternate frame"):
        RoutingProposal.from_extractor(
            id="R1", question=q, taxonomy=tax,
            proposed_frame="CURRENT_OPERATIONAL_STATE", extractor_id="m",
            alternates=(("MADE_UP", "considered"),))


def test_gs7_no_caller_frame_means_none():
    """An absent caller frame yields None - it is never manufactured."""
    tax = FrameTaxonomy("v1", ("CURRENT_OPERATIONAL_STATE",))
    q = Question("q1", "what is the state?")
    assert caller_frame_of(q, tax) is None


def test_gs7_caller_frame_comes_only_from_the_question():
    tax = FrameTaxonomy("v1", ("CURRENT_OPERATIONAL_STATE",))
    q = Question("q1", "what is the state?",
                 caller_frame="CURRENT_OPERATIONAL_STATE", caller_taxonomy_version="v1")
    assert caller_frame_of(q, tax) == "CURRENT_OPERATIONAL_STATE"


def test_gs7_caller_frame_is_validated():
    tax = FrameTaxonomy("v1", ("CURRENT_OPERATIONAL_STATE",))
    q = Question("q1", "q", caller_frame="INVENTED", caller_taxonomy_version="v1")
    with pytest.raises(ValueError, match="not in the taxonomy"):
        caller_frame_of(q, tax)


def test_gs7_caller_frame_needs_its_taxonomy_version():
    with pytest.raises(ValueError, match="set together"):
        Question("q1", "q", caller_frame="CURRENT_OPERATIONAL_STATE")


# ---------------------------------------------------------- G-S8 proposal retained


def test_gs8_review_creates_new_object_and_leaves_proposal_intact():
    p = proposal("P17")
    a = AssertedRelation("A42", p.subject_ref, p.relation_type, p.object_ref,
                         p.evidence_refs, AssertionOrigin.HUMAN_REVIEWED_PROPOSAL,
                         human_adjudicator_id="redacted",
                         derived_from_proposal_id=p.id)
    assert a.derived_from_proposal_id == p.id
    assert dataclasses.asdict(p) == dataclasses.asdict(proposal("P17"))  # untouched
    assert a.gold_eligible is False


def test_gs8_retraction_is_not_a_contradicts_relation():
    """Retraction is a lifecycle event, not a statement about evidence semantics."""
    r = AssertedRelationReview("REV1", "A42", ReviewOrigin.HUMAN,
                               AssertionReviewVerdict.RETRACTED, "withdrawn",
                               reviewer_id="redacted")
    assert r.verdict is AssertionReviewVerdict.RETRACTED
    assert not isinstance(r, AssertedRelation)
    assert "RETRACTED" not in {t.name for t in RelationType}


# --------------------------------------------------------------- G-S9 coverage


def test_gs9_empty_suite_is_incomplete():
    report = compute_coverage([])
    assert report.complete is False
    assert len(report.deficient) == 8


def test_gs9_single_case_across_many_invariants_is_not_coverage():
    """One case defending four invariants is one case carrying four pieces of assurance."""
    cases = [CaseCoverage("HIST-C3", "authority-trap",
                          ("B4_FALSE_ABSTENTION_IS_FAILURE", "B5_ROUTING_IS_INFERENTIAL",
                           "B7_NO_RECENCY_AS_AUTHORITY",
                           "B8_QUESTION_RELATIVE_AUTHORITY"))]
    report = compute_coverage(cases)
    assert report.complete is False
    for inv in ("B4_FALSE_ABSTENTION_IS_FAILURE", "B7_NO_RECENCY_AS_AUTHORITY"):
        assert report.per_invariant[inv] == (1, 1)


def test_gs9_two_cases_same_family_is_not_coverage():
    cases = [CaseCoverage("X1", "authority-trap", ("B7_NO_RECENCY_AS_AUTHORITY",)),
             CaseCoverage("X2", "authority-trap", ("B7_NO_RECENCY_AS_AUTHORITY",))]
    report = compute_coverage(cases)
    assert report.per_invariant["B7_NO_RECENCY_AS_AUTHORITY"] == (2, 1)
    assert "B7_NO_RECENCY_AS_AUTHORITY" in report.deficient


def test_gs9_two_cases_two_families_covers():
    cases = [CaseCoverage("X1", "authority-trap", ("B7_NO_RECENCY_AS_AUTHORITY",)),
             CaseCoverage("X2", "vendor-vs-local", ("B7_NO_RECENCY_AS_AUTHORITY",))]
    report = compute_coverage(cases)
    assert report.per_invariant["B7_NO_RECENCY_AS_AUTHORITY"] == (2, 2)
    assert "B7_NO_RECENCY_AS_AUTHORITY" not in report.deficient


def test_gs9_require_complete_raises_suite_incomplete():
    with pytest.raises(SuiteIncomplete):
        require_complete([])


# ------------------------------------------- G-S9 case identity comes from real seeds


def test_coverage_case_identity_is_the_seed():
    """Two gold artifacts for ONE seed are ONE case, not two."""
    from historian.coverage import coverage_from_gold_rows
    rows = [("S1", "authority-trap", "B7_NO_RECENCY_AS_AUTHORITY"),
            ("S1", "authority-trap", "B8_QUESTION_RELATIVE_AUTHORITY")]
    cases = coverage_from_gold_rows(rows)
    assert len(cases) == 1
    assert cases[0].case_id == "S1"
    assert cases[0].defends == ("B7_NO_RECENCY_AS_AUTHORITY",
                                "B8_QUESTION_RELATIVE_AUTHORITY")
    report = compute_coverage(cases)
    assert report.per_invariant["B7_NO_RECENCY_AS_AUTHORITY"] == (1, 1)
    assert not report.complete


def test_coverage_two_seeds_two_families_covers():
    from historian.coverage import coverage_from_gold_rows
    rows = [("S1", "authority-trap", "B7_NO_RECENCY_AS_AUTHORITY"),
            ("S2", "vendor-vs-local", "B7_NO_RECENCY_AS_AUTHORITY")]
    report = compute_coverage(coverage_from_gold_rows(rows))
    assert report.per_invariant["B7_NO_RECENCY_AS_AUTHORITY"] == (2, 2)


def test_coverage_rejects_a_seed_with_two_families():
    from historian.coverage import coverage_from_gold_rows
    with pytest.raises(ValueError, match="two families"):
        coverage_from_gold_rows([("S1", "a", "B1_NO_RELATION_BY_ABSENCE"),
                                 ("S1", "b", "B1_NO_RELATION_BY_ABSENCE")])
