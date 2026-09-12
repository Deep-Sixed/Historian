"""Application parity exercised through real Linux UID processes and raw storage."""

from dataclasses import replace
from uuid import uuid4
import json

import pytest

pytest.importorskip("libsql")
from test_libsql_profile import deployment  # noqa: F401
from historian import types as t
from historian.adjudicator import Adjudicator, AuthorityPolicy
from historian.gold import (
    GoldCaseSeed,
    AdjudicationPacket,
    BlindAdjudication,
    EvaluationGold,
)
from historian.capability import packet_hash
from historian.libsql_store.codec import encode, decode
from historian.sources import RagV1SourceReader
from historian.source_adapter import sha256_text

pytestmark = pytest.mark.libsql


def put(probe, role, obj):
    result = probe.call(role, "put_object", object=encode(obj))
    assert result["ok"], result
    return result["result"]


def get(probe, role, kind, identity):
    result = probe.call(role, "get_object", kind=kind, id=identity)
    assert result["ok"], result
    return decode(result["result"])


@pytest.fixture
def inputs(deployment):  # noqa: F811
    probe, _, _ = deployment
    rid = uuid4().hex
    q = t.Question(rid, "Which claim is supported?")
    put(probe, "designer", q)
    doc = "2026-01-01-source"
    reader = RagV1SourceReader(probe.corpus)
    version = reader.version_of(doc)
    text = reader.read_lines(doc, version, 1, 1)
    refs = []
    for suffix in ("a", "b"):
        eid = rid + suffix
        result = probe.call(
            "verifier",
            "verify_source",
            id=eid,
            source_id=doc,
            version_hash=version,
            start=1,
            end=1,
            quote="authority passage",
        )
        assert result["ok"], result
        refs.append(
            t.EvidenceRef(
                doc,
                t.SourceSystem.RAG_V1,
                version,
                t.SourcePosition(doc, version, t.CoordinateSystem.LINE, 1, 1),
                sha256_text(text),
                "authority passage",
                eid,
            )
        )
    return probe, rid, q, tuple(refs)


@pytest.mark.parametrize("asserted", [False, True])
def test_real_adjudicator_roundtrips_all_dependencies(inputs, asserted):
    probe, rid, q, refs = inputs
    taxonomy = t.FrameTaxonomy(rid, ("CURRENT_OPERATIONAL_STATE",))
    put(probe, "designer", taxonomy)
    route = t.RoutingProposal(
        rid + "route", q.id, rid, "CURRENT_OPERATIONAL_STATE", "model"
    )
    put(probe, "extractor", route)
    claims = tuple(
        t.ClaimProposal(rid + "c" + str(i), r.key, txt, "model", q.id)
        for i, (r, txt) in enumerate(zip(refs, ("X", "Y")))
    )
    roles = tuple(
        t.SourceRoleProposal(
            rid + "s" + str(i),
            r,
            t.SourceRole.LOCAL_OPERATIONAL_DECISION,
            (r,),
            "model",
        )
        for i, r in enumerate(refs)
    )
    proposal = t.ProposedRelation(
        rid + "p", refs[0], t.RelationType.CORRECTS, refs[1], (refs[0],), "m", "run"
    )
    for obj in (*claims, *roles, proposal):
        put(probe, "extractor", obj)
    relations = [proposal]
    if asserted:
        relation = t.AssertedRelation(
            rid + "rel",
            refs[0],
            t.RelationType.CORRECTS,
            refs[1],
            (refs[0],),
            t.AssertionOrigin.TYPED_SOURCE,
            typed_source_ref="ledger:test",
        )
        put(probe, "typed", relation)
        relations.append(relation)
    result = (
        Adjudicator(
            taxonomy,
            AuthorityPolicy(
                rid,
                {
                    "CURRENT_OPERATIONAL_STATE": (
                        t.SourceRole.LOCAL_OPERATIONAL_DECISION,
                    )
                },
            ),
        )
        .adjudicate(
            question=q,
            evidence=refs,
            claims=claims,
            source_role_proposals=roles,
            relations=tuple(relations),
            routing=route,
            resolution_id=rid + "r",
        )
        .resolution
    )
    put(probe, "runtime", result)
    assert get(probe, "runtime", "Resolution", result.id) == result
    assert result.outcome is (t.Outcome.RESOLVED if asserted else t.Outcome.UNRESOLVED)
    db = probe.sql(
        ("SELECT support_profile FROM app_resolution_support WHERE id=?", (result.id,))
    )
    assert db["rows"][0][0][0] == result.support_profile.value
    # A fabricated proposal ID cannot replace a claim edge; the whole write rolls back.
    bad = replace(result, id=rid + "bad", proposed_relation_refs=("claim:invented",))
    assert not probe.call("runtime", "put_object", object=encode(bad))["ok"]
    assert probe.sql(("SELECT id FROM app_object WHERE id=?", (bad.id,)))["rows"] == [
        []
    ]
    other = t.Question(rid + "other", "Other question")
    put(probe, "designer", other)
    crosswired = replace(result, id=rid + "cross", question_id=other.id)
    assert not probe.call("runtime", "put_object", object=encode(crosswired))["ok"]
    revision = replace(
        result,
        id=rid + "revision",
        previous_resolution_id=result.id,
        revision_reason="reconsidered",
    )
    put(probe, "runtime", revision)
    assert get(probe, "runtime", "Resolution", result.id) == result
    assert get(probe, "runtime", "Resolution", revision.id) == revision
    for statement, params in (
        ("UPDATE app_object SET writer=? WHERE id=?", ("tamper",result.id)),
        ("DELETE FROM app_object WHERE id=?", (result.id,)),
    ):
        raw = probe.sql((statement,params))
        assert not raw['ok'] and 'immutable' in raw['detail']
    late = probe.sql(("INSERT INTO app_link VALUES (?,?,?,?,?,?)",
                      ('Resolution',result.id,'proposed_relation_refs','ProposedRelation',proposal.id,None)))
    assert not late['ok'] and 'published' in late['detail']


def test_gold_pipeline_and_blind_isolation(inputs):
    probe, rid, q, refs = inputs
    seed = GoldCaseSeed(rid + "seed", q.id, q.text, refs, "private-family", ("B1",))
    put(probe, "designer", seed)
    packet = AdjudicationPacket(
        rid + "packet", seed.id, q.text, refs, packet_hash(q.text, refs)
    )
    put(probe, "builder", packet)
    blind = get(probe, "adjudicator", "AdjudicationPacket", packet.id)
    assert blind.seed_id == "" and blind.evidence_packet == refs
    snapshots = probe.call("adjudicator", "get_packet_snapshot", id=packet.id)
    assert snapshots["ok"]
    assert [s["evidence_id"] for s in snapshots["result"]] == [r.key for r in refs]
    assert all(s["text"] == "authority passage\n" for s in snapshots["result"])
    assert not probe.call("adjudicator", "get_object", kind="GoldCaseSeed", id=seed.id)[
        "ok"
    ]
    for verdict in (
        t.AdjudicationVerdict.RESOLVED,
        t.AdjudicationVerdict.PACKET_INSUFFICIENT,
    ):
        adj = BlindAdjudication(
            rid + verdict.value,
            packet.id,
            "forged human",
            verdict,
            "reviewed",
            refs,
            "answer" if verdict is t.AdjudicationVerdict.RESOLVED else None,
        )
        put(probe, "adjudicator", adj)
        stored = get(probe, "gold", "BlindAdjudication", adj.id)
        assert stored.adjudicator_id == "uid:10008"
        gold = EvaluationGold(
            rid + "gold" + verdict.value,
            seed.id,
            adj.id,
            t.Outcome.RESOLVED
            if verdict is t.AdjudicationVerdict.RESOLVED
            else t.Outcome.UNRESOLVED,
            False,
            seed.invariant_candidates,
            stored.resolution_text,
        )
        result = probe.call("gold", "put_object", object=encode(gold))
        assert result["ok"] is (verdict is t.AdjudicationVerdict.RESOLVED)


def test_domain_api_cannot_grant_writer_or_reader_capability(inputs):
    probe, rid, q, refs = inputs
    claim = t.ClaimProposal(rid + "claim", refs[0].key, "claim", "model", q.id)
    for role in ("runtime", "adjudicator", "builder", "unassigned"):
        result = probe.call(role, "put_object", object=encode(claim), role="extractor")
        assert not result["ok"] and result["error"] == "forbidden"
    put(probe, "extractor", claim)
    for role in ("adjudicator", "builder", "gold", "unassigned"):
        result = probe.call(role, "get_object", kind="ClaimProposal", id=claim.id)
        assert not result["ok"] and result["error"] == "forbidden"


def test_verifier_mismatch_leaves_no_evidence(inputs):
    probe, rid, q, refs = inputs
    for changes in (
        {"quote": "not in the source"},
        {"version_hash": "0" * 64},
        {"start": 500, "end": 501},
    ):
        identity = uuid4().hex
        data = dict(
            id=identity,
            source_id=refs[0].source_id,
            version_hash=refs[0].source_version_hash,
            start=1,
            end=1,
            quote="authority passage",
        )
        data.update(changes)
        assert not probe.call("verifier", "verify_source", **data)["ok"]
        assert probe.sql(("SELECT id FROM evidence WHERE id=?", (identity,)))[
            "rows"
        ] == [[]]


def test_every_domain_capability_rejects_unauthorized_uids(deployment):  # noqa: F811
    from pathlib import Path
    from libsql_probe import ROLES
    from historian.libsql_store.access import READ, WRITE
    from historian.libsql_store.profile import LIBSQL

    probe, _, _ = deployment
    observations = []
    for operation, mapping in [
        ("get_object", READ),
        ("put_object", WRITE),
        ("get_packet_snapshot", {"AdjudicationPacket": READ["AdjudicationPacket"]}),
    ]:
        for kind, permitted in mapping.items():
            for role in [*ROLES, "unassigned"]:
                if role in permitted:
                    continue
                data = (
                    {"kind": kind, "id": "missing"}
                    if operation != "put_object"
                    else {"object": {"type": kind, "fields": {}}}
                )
                result = probe.call(role, operation, **data)
                observations.append(
                    {
                        "actor": result["principal"],
                        "capability": role,
                        "operation": operation,
                        "kind": kind,
                        "expected": "forbidden",
                        "observed": result.get("error", "accepted"),
                    }
                )
                assert not result["ok"] and result["error"] == "forbidden"
    Path("/tmp/historian-libsql-application.json").write_text(
        json.dumps(
            {
                "profile_name": LIBSQL.name,
                "profile_version": LIBSQL.version,
                "profile_digest": LIBSQL.digest,
                "evidence": observations,
            },
            indent=2,
        )
    )


def test_review_events_preserve_original_objects_and_authenticated_identity(inputs):
    from historian.resolution import Resolution, ResolutionReview

    probe, rid, q, refs = inputs
    proposal = t.ProposedRelation(
        rid + "p", refs[0], t.RelationType.CORRECTS, refs[1], refs, "model", "run"
    )
    put(probe, "extractor", proposal)
    event = t.ProposalDispositionEvent(
        rid + "event", proposal.id, t.ProposalDisposition.REJECTED, "rejected"
    )
    put(probe, "extractor", event)
    assert get(probe, "runtime", "ProposedRelation", proposal.id) == proposal
    asserted = t.AssertedRelation(
        rid + "a",
        refs[0],
        t.RelationType.CORRECTS,
        refs[1],
        refs,
        t.AssertionOrigin.HUMAN_REVIEWED_PROPOSAL,
        human_adjudicator_id="forged",
        derived_from_proposal_id=proposal.id,
    )
    put(probe, "reviewer", asserted)
    assert (
        get(probe, "runtime", "AssertedRelation", asserted.id).human_adjudicator_id
        == "uid:10005"
    )
    mismatched = replace(asserted, id=rid + "bad-a", subject_ref=refs[1])
    assert not probe.call("reviewer", "put_object", object=encode(mismatched))["ok"]
    review = t.AssertedRelationReview(
        rid + "review",
        asserted.id,
        t.ReviewOrigin.HUMAN,
        t.AssertionReviewVerdict.RETRACTED,
        "retracted",
        reviewer_id="forged",
    )
    put(probe, "reviewer", review)
    assert (
        get(probe, "runtime", "AssertedRelationReview", review.id).reviewer_id
        == "uid:10005"
    )
    output = Resolution(
        rid + "r",
        q.id,
        t.Outcome.UNRESOLVED,
        t.ResolutionMethod.DETERMINISTIC_RULE,
        evidence_refs=refs,
        unresolved_reason="insufficient",
    )
    put(probe, "runtime", output)
    resolution_review = ResolutionReview(
        rid + "rr", output.id, "forged", t.ReviewVerdict.REJECTED, "reviewed"
    )
    put(probe, "reviewer", resolution_review)
    assert (
        get(probe, "runtime", "ResolutionReview", resolution_review.id).reviewer_id
        == "uid:10005"
    )
