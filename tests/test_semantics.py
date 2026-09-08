"""Mechanical guarantees the behavioural invariants rest on.

These are not behavioural acceptance cases — those require blind human adjudication. They
test that the PRIMITIVES a behavioural case would rely on cannot themselves be misused.
"""

import pytest

from historian.positions import overlaps, precedes, same_source
from historian.resolution import Resolution
from historian.types import (
    CoordinateSystem,
    EvidenceRef,
    Outcome,
    RelationType,
    ResolutionMethod,
    SourcePosition,
    SourceSystem,
    SupportProfile,
)


def ev(source="doc-a", ver="v1", start=1, end=10):
    p = SourcePosition(source, ver, CoordinateSystem.LINE, start, end)
    return EvidenceRef(source, SourceSystem.RAG_V1, ver, p, f"h{start}", "anchor",
                       evidence_id=f"{source}:{ver}:{start}-{end}")


# --------------------------------------------------------- B2: order, not authority


def test_precedes_is_deterministic_within_one_version():
    """Canary S2: 'Root Cause: Disk Full' precedes 'second root cause on top of it'."""
    a = ev(start=51, end=54)      # earlier passage
    b = ev(start=111, end=126)    # later passage, same file, same date
    assert same_source(a, b)
    assert precedes(a, b)
    assert not precedes(b, a)


def test_precedes_claims_nothing_about_supersession():
    """The ordering primitive cannot express authority, so authority cannot leak from it.

    B2 is enforced by the API surface: `precedes` returns a bool about position. There is
    no helper that turns order into a relation, and RelationType has no member that could
    be produced automatically from ordering.
    """
    import historian.positions as P
    exported = {n for n in dir(P) if not n.startswith("_")}
    assert exported & {"same_source", "precedes", "overlaps"}
    # nothing in the module produces or implies a relation
    assert not any(n.lower().startswith(("supersede", "correct", "augment"))
                   for n in exported)


def test_positions_in_different_versions_are_not_comparable():
    """Line 800 may denote different text after an edit; we have a live instance."""
    a = ev(ver="v1", start=1, end=10)
    b = ev(ver="v2", start=20, end=30)
    assert not same_source(a, b)
    assert not precedes(a, b)      # refuses rather than guessing
    assert not overlaps(a, b)


def test_cross_source_ordering_is_refused():
    a = ev(source="doc-a", start=1, end=10)
    b = ev(source="doc-b", start=20, end=30)
    assert not precedes(a, b)


# ------------------------------------------------ support_profile is derived, honest


def _res(**kw):
    base = dict(id="R1", question_id="q1", outcome=Outcome.RESOLVED,
                resolution_method=ResolutionMethod.MODEL_INFERENCE,
                conclusion="c")
    base.update(kw)
    return Resolution(**base)


def test_direct_evidence_only():
    r = _res(evidence_refs=(ev(),))
    assert r.support_profile is SupportProfile.DIRECT_EVIDENCE_ONLY


def test_asserted_relation_dependent():
    r = _res(asserted_relation_refs=("A1",))
    assert r.support_profile is SupportProfile.ASSERTED_RELATION_DEPENDENT


def test_proposed_dependent_via_source_role():
    """C3-shaped: the authority judgement rests on source-role PROPOSALS."""
    r = _res(source_role_proposal_refs=("SRP1", "SRP2"))
    assert r.support_profile is SupportProfile.PROPOSED_DEPENDENT


def test_mixed():
    r = _res(asserted_relation_refs=("A1",), proposed_relation_refs=("P1",))
    assert r.support_profile is SupportProfile.MIXED


def test_routing_does_not_collapse_the_vocabulary():
    """Routing selects WHICH authority rules apply; it does not support the conclusion.

    If routing counted, every routed resolution would be PROPOSED_DEPENDENT and two of the
    four values would be unreachable — a decorative vocabulary.
    """
    r = _res(evidence_refs=(ev(),), routing_proposal_ref="RP1")
    assert r.support_profile is SupportProfile.DIRECT_EVIDENCE_ONLY


def test_support_profile_cannot_be_set():
    r = _res(proposed_relation_refs=("P1",))
    with pytest.raises(AttributeError):
        r.support_profile = SupportProfile.ASSERTED_RELATION_DEPENDENT


# --------------------------------------- structural abstention must be expressible


def test_structural_abstention_is_expressible():
    """A DETERMINISTIC_RULE applied over PROPOSED inputs.

    'Two sources conflict and no relation resolves them' is mechanical, but its inputs are
    inferential. An earlier design derived one combined field and could not express this
    state at all — it would have been forced to call itself INFERENTIAL, hiding that the
    abstention decision was itself deterministic.
    """
    r = Resolution(
        id="R2", question_id="q1", outcome=Outcome.UNRESOLVED,
        resolution_method=ResolutionMethod.DETERMINISTIC_RULE,
        proposed_relation_refs=("P1", "P2"),
        unresolved_reason="two sources conflict; no relation resolves them")
    assert r.support_profile is SupportProfile.PROPOSED_DEPENDENT
    assert r.resolution_method is ResolutionMethod.DETERMINISTIC_RULE


def test_unresolved_must_say_why():
    with pytest.raises(ValueError, match="unresolved_reason"):
        Resolution(id="R3", question_id="q1", outcome=Outcome.UNRESOLVED,
                   resolution_method=ResolutionMethod.DETERMINISTIC_RULE)


def test_unresolved_cannot_carry_a_conclusion():
    with pytest.raises(ValueError, match="must not carry a conclusion"):
        Resolution(id="R4", question_id="q1", outcome=Outcome.UNRESOLVED,
                   resolution_method=ResolutionMethod.DETERMINISTIC_RULE,
                   unresolved_reason="conflict", conclusion="but actually...")


def test_relation_type_cannot_express_unresolvedness():
    """Unresolvedness is an OUTCOME. Two encodings would eventually disagree."""
    assert "UNRESOLVED_WITH" not in {t.name for t in RelationType}
