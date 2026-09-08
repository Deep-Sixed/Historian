"""The adjudicator's output must traverse the REAL persistence path.

DEFECT 3 of the closure review. The engine used to synthesise `claim:<evidence_id>` strings
and write them into `Resolution.proposed_relation_refs`, whose PostgreSQL counterpart is
`resolution_proposed_dep.proposal_id REFERENCES proposed_relation(id)`. Nothing in the
Python layer objected, because nothing in the Python layer ever tried to persist a
Resolution - there is no SQL-backed ResolutionStore, only a Protocol. A type that is only
ever held in memory cannot discover that it is unpersistable.

So these tests write the adjudicator's actual output to the actual tables under the actual
runtime role, and then prove the old shape is REJECTED by the foreign key. A round trip
that only exercises the new path would not establish that the old one was really broken.
"""

import uuid

import pytest

from historian.adjudicator import Adjudicator, AuthorityPolicy
from historian.types import (
    AssertedRelation, AssertionOrigin, ClaimProposal, CoordinateSystem, EvidenceRef,
    FrameTaxonomy, Outcome, ProposedRelation, Question, RelationType, RoutingProposal,
    SourcePosition, SourceRole, SourceRoleProposal, SourceSystem,
)

psycopg = pytest.importorskip("psycopg")
from test_pg_roles import conn, sha  # noqa: E402  (shared vault-backed connection helper)

LOCAL = "CURRENT_OPERATIONAL_STATE"
TAX = FrameTaxonomy("v1", (LOCAL, "UPSTREAM_PRODUCT_STATE"))
POLICY = AuthorityPolicy("v1", {LOCAL: (SourceRole.LOCAL_OPERATIONAL_DECISION,)})
RUN = uuid.uuid4().hex[:8]


def n(x):
    return f"{x}-{RUN}"


@pytest.fixture(scope="module")
def fixture_rows():
    """Real rows, written by the identities entitled to write them."""
    with conn("historian_owner") as c:
        c.execute("INSERT INTO frame_taxonomy(version) VALUES ('v1') ON CONFLICT DO NOTHING")
        c.execute("INSERT INTO taxonomy_entry(version,frame) VALUES "
                  "('v1',%s) ON CONFLICT DO NOTHING", (LOCAL,))
        c.execute("INSERT INTO question(id,text) VALUES (%s,'persisted question')",
                  (n("q"),))
    with conn("historian_evidence_verifier") as c:
        for s in ("A", "B"):
            c.execute("""INSERT INTO evidence_ref
                (id,source_id,source_system,source_version_hash,line_start,line_end,
                 passage_hash,quote,verified_by)
                VALUES (%s,%s,'RAG_V1','vh',1,2,%s,'anchor','verifier-1')""",
                      (n(s), n(s), sha(f"passage {s}\n")))
    with conn("historian_extractor") as c:
        for s, txt in (("A", "X"), ("B", "Y")):
            c.execute("""INSERT INTO claim_proposal
                (id,evidence_id,question_id,claim,extractor_id)
                VALUES (%s,%s,%s,%s,'model-x')""",
                      (n(f"cp{s}"), n(s), n("q"), txt))
            c.execute("""INSERT INTO source_role_proposal
                (id,source_ref_id,proposed_role,extractor_id)
                VALUES (%s,%s,'LOCAL_OPERATIONAL_DECISION','model-x')""",
                      (n(f"srp{s}"), n(s)))
        c.execute("""INSERT INTO routing_proposal
            (id,question_id,taxonomy_version,proposed_frame,extractor_id)
            VALUES (%s,%s,'v1',%s,'model-x')""", (n("rp"), n("q"), LOCAL))
        c.execute("""INSERT INTO proposed_relation
            (id,subject_ref_id,relation_type,object_ref_id,extractor_id,extraction_run_id)
            VALUES (%s,%s,'CORRECTS',%s,'model-x','run-1')""",
                  (n("prop"), n("A"), n("B")))
    with conn("historian_typed_ingestor") as c:
        c.execute("""INSERT INTO asserted_relation
            (id,subject_ref_id,relation_type,object_ref_id,origin,typed_source_ref)
            VALUES (%s,%s,'CORRECTS',%s,'TYPED_SOURCE','ledger:x')""",
                  (n("rel"), n("A"), n("B")))
    return True


def _ev(s):
    p = SourcePosition(n(s), "vh", CoordinateSystem.LINE, 1, 2)
    return EvidenceRef(n(s), SourceSystem.RAG_V1, "vh", p, sha(f"passage {s}\n"),
                       "anchor", evidence_id=n(s))


def _adjudicate(with_asserted: bool):
    eng = Adjudicator(TAX, POLICY)
    rels = []
    if with_asserted:
        rels.append(AssertedRelation(n("rel"), _ev("A"), RelationType.CORRECTS, _ev("B"),
                                     (_ev("A"),), AssertionOrigin.TYPED_SOURCE,
                                     typed_source_ref="ledger:x"))
    rels.append(ProposedRelation(n("prop"), _ev("A"), RelationType.CORRECTS, _ev("B"),
                                 (_ev("A"),), "model-x", "run-1"))
    return eng.adjudicate(
        question=Question(n("q"), "persisted question"),
        evidence=(_ev("A"), _ev("B")),
        claims=(ClaimProposal(n("cpA"), n("A"), "X", "model-x"),
                ClaimProposal(n("cpB"), n("B"), "Y", "model-x")),
        source_role_proposals=(
            SourceRoleProposal(n("srpA"), _ev("A"),
                               SourceRole.LOCAL_OPERATIONAL_DECISION, (_ev("A"),), "m"),
            SourceRoleProposal(n("srpB"), _ev("B"),
                               SourceRole.LOCAL_OPERATIONAL_DECISION, (_ev("B"),), "m")),
        relations=tuple(rels),
        routing=RoutingProposal(n("rp"), n("q"), "v1", LOCAL, "model-x"),
        resolution_id=n("R1" if with_asserted else "R2"))


def _persist(c, r):
    """Write a Resolution and every dependency edge it declares."""
    c.execute("""INSERT INTO resolution
        (id,question_id,outcome,resolution_method,conclusion,unresolved_reason,
         routing_proposal_id)
        VALUES (%s,%s,%s,%s,%s,%s,%s)""",
              (r.id, r.question_id, r.outcome.value, r.resolution_method.value,
               r.conclusion, r.unresolved_reason, r.routing_proposal_ref))
    for e in r.evidence_refs:
        c.execute("INSERT INTO resolution_evidence VALUES (%s,%s)", (r.id, e.key))
    for i in r.asserted_relation_refs:
        c.execute("INSERT INTO resolution_asserted_dep VALUES (%s,%s)", (r.id, i))
    for i in r.proposed_relation_refs:
        c.execute("INSERT INTO resolution_proposed_dep VALUES (%s,%s)", (r.id, i))
    for i in r.claim_proposal_refs:
        c.execute("INSERT INTO resolution_claim_dep VALUES (%s,%s)", (r.id, i))
    for i in r.source_role_proposal_refs:
        c.execute("INSERT INTO resolution_source_role_dep VALUES (%s,%s)", (r.id, i))


def test_resolved_adjudication_persists_with_every_dependency(fixture_rows):
    a = _adjudicate(with_asserted=True)
    assert a.resolution.outcome is Outcome.RESOLVED
    with conn("historian_runtime") as c:
        _persist(c, a.resolution)
        assert c.execute("SELECT conclusion FROM resolution WHERE id=%s",
                         (a.resolution.id,)).fetchone()[0] == "X"
        assert c.execute("SELECT count(*) FROM resolution_claim_dep WHERE resolution_id=%s",
                         (a.resolution.id,)).fetchone()[0] == 2
        assert c.execute("SELECT count(*) FROM resolution_asserted_dep WHERE "
                         "resolution_id=%s", (a.resolution.id,)).fetchone()[0] == 1
        assert c.execute("SELECT count(*) FROM resolution_source_role_dep WHERE "
                         "resolution_id=%s", (a.resolution.id,)).fetchone()[0] == 2
        assert c.execute("SELECT routing_proposal_id FROM resolution WHERE id=%s",
                         (a.resolution.id,)).fetchone()[0] == n("rp")


def test_support_profile_agrees_between_python_and_postgresql(fixture_rows):
    """The derived profile must not depend on which layer computes it."""
    a = _adjudicate(with_asserted=True)
    with conn("historian_runtime") as c:
        db = c.execute("SELECT support_profile FROM resolution_support WHERE "
                       "resolution_id=%s", (a.resolution.id,)).fetchone()[0]
    assert db == a.resolution.support_profile.value == "MIXED"


def test_refused_proposal_is_not_recorded_as_support(fixture_rows):
    """The refused ProposedRelation is in the trace, never in the dependency edges."""
    a = _adjudicate(with_asserted=True)
    assert n("prop") in a.refused_relation_refs
    with conn("historian_runtime") as c:
        assert c.execute("SELECT count(*) FROM resolution_proposed_dep WHERE "
                         "resolution_id=%s", (a.resolution.id,)).fetchone()[0] == 0


def test_the_old_fabricated_claim_id_is_rejected_by_the_foreign_key(fixture_rows):
    """Proves DEFECT 3 was real: the pre-fix shape cannot be inserted at all."""
    a = _adjudicate(with_asserted=True)
    with conn("historian_runtime") as c, pytest.raises(psycopg.errors.ForeignKeyViolation):
        c.execute("INSERT INTO resolution_proposed_dep VALUES (%s,%s)",
                  (a.resolution.id, f"claim:{n('A')}"))


def test_runtime_cannot_author_a_claim_it_may_only_cite_one(fixture_rows):
    """Claims are inference. The resolver citing one must not be able to invent one."""
    with conn("historian_runtime") as c, pytest.raises(psycopg.errors.InsufficientPrivilege):
        c.execute("""INSERT INTO claim_proposal(id,evidence_id,claim,extractor_id)
                     VALUES (%s,%s,'invented','historian_runtime')""",
                  (n("cpX"), n("A")))


def test_unresolved_adjudication_also_persists(fixture_rows):
    """Without the asserted relation the same inputs are UNRESOLVED - and must still
    round-trip, because an abstention is a real answer that has to be storable."""
    a = _adjudicate(with_asserted=False)
    assert a.resolution.outcome is Outcome.UNRESOLVED
    with conn("historian_runtime") as c:
        _persist(c, a.resolution)
        row = c.execute("SELECT outcome,conclusion,unresolved_reason FROM resolution "
                        "WHERE id=%s", (a.resolution.id,)).fetchone()
    assert row[0] == "UNRESOLVED" and row[1] is None and row[2]


def test_same_source_distinct_evidence_survives_adjudication_and_persistence(fixture_rows):
    """P1 regression: evidence identity must not collapse to source/document identity."""
    qid = n("q-same-source")
    doc = n("doc-42")
    e_old = n("E-old")
    e_new = n("E-new")
    with conn("historian_owner") as c:
        c.execute("INSERT INTO question(id,text) VALUES (%s,'same source question')",
                  (qid,))
    with conn("historian_evidence_verifier") as c:
        c.execute("""INSERT INTO evidence_ref
            (id,source_id,source_system,source_version_hash,line_start,line_end,
             passage_hash,quote,verified_by)
            VALUES (%s,%s,'RAG_V1','vh',10,20,%s,'old anchor','verifier-1'),
                   (%s,%s,'RAG_V1','vh',300,310,%s,'new anchor','verifier-1')""",
                  (e_old, doc, sha("old passage\n"), e_new, doc, sha("new passage\n")))
    with conn("historian_extractor") as c:
        c.execute("""INSERT INTO claim_proposal
            (id,evidence_id,question_id,claim,extractor_id)
            VALUES (%s,%s,%s,'policy is X','model-x'),
                   (%s,%s,%s,'policy is Y','model-x')""",
                  (n("cp-old"), e_old, qid, n("cp-new"), e_new, qid))
        c.execute("""INSERT INTO source_role_proposal
            (id,source_ref_id,proposed_role,extractor_id)
            VALUES (%s,%s,'LOCAL_OPERATIONAL_DECISION','model-x'),
                   (%s,%s,'LOCAL_OPERATIONAL_DECISION','model-x')""",
                  (n("srp-old"), e_old, n("srp-new"), e_new))
        c.execute("""INSERT INTO routing_proposal
            (id,question_id,taxonomy_version,proposed_frame,extractor_id)
            VALUES (%s,%s,'v1',%s,'model-x')""", (n("rp-same"), qid, LOCAL))

    old_ref = EvidenceRef(
        doc, SourceSystem.RAG_V1, "vh",
        SourcePosition(doc, "vh", CoordinateSystem.LINE, 10, 20),
        sha("old passage\n"), "old anchor", evidence_id=e_old)
    new_ref = EvidenceRef(
        doc, SourceSystem.RAG_V1, "vh",
        SourcePosition(doc, "vh", CoordinateSystem.LINE, 300, 310),
        sha("new passage\n"), "new anchor", evidence_id=e_new)
    a = Adjudicator(TAX, POLICY).adjudicate(
        question=Question(qid, "same source question"),
        evidence=(old_ref, new_ref),
        claims=(ClaimProposal(n("cp-old"), e_old, "policy is X", "model-x"),
                ClaimProposal(n("cp-new"), e_new, "policy is Y", "model-x")),
        source_role_proposals=(
            SourceRoleProposal(n("srp-old"), old_ref,
                               SourceRole.LOCAL_OPERATIONAL_DECISION, (old_ref,), "m"),
            SourceRoleProposal(n("srp-new"), new_ref,
                               SourceRole.LOCAL_OPERATIONAL_DECISION, (new_ref,), "m")),
        routing=RoutingProposal(n("rp-same"), qid, "v1", LOCAL, "model-x"),
        resolution_id=n("R-same-source"))

    assert a.resolution.outcome is Outcome.UNRESOLVED
    assert a.conflict is True
    assert a.authority_refs == (e_old, e_new)
    assert a.resolution.claim_proposal_refs == (n("cp-old"), n("cp-new"))

    with conn("historian_runtime") as c:
        _persist(c, a.resolution)
        row = c.execute("SELECT outcome, conclusion FROM resolution WHERE id=%s",
                        (a.resolution.id,)).fetchone()
        evidence_ids = {r[0] for r in c.execute(
            "SELECT evidence_id FROM resolution_evidence WHERE resolution_id=%s",
            (a.resolution.id,)).fetchall()}
        claim_ids = {r[0] for r in c.execute(
            "SELECT claim_id FROM resolution_claim_dep WHERE resolution_id=%s",
            (a.resolution.id,)).fetchall()}
    assert row == ("UNRESOLVED", None)
    assert evidence_ids == {e_old, e_new}
    assert claim_ids == {n("cp-old"), n("cp-new")}
