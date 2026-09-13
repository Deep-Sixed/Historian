"""Full application persistence through the existing kernel-authenticated service."""

import json
from dataclasses import fields, is_dataclass, replace

from historian import types as t
from historian.gold import (
    GoldCaseSeed,
    AdjudicationPacket,
    BlindAdjudication,
    EvaluationGold,
)
from historian.resolution import ResolutionReview
from historian.capability import packet_hash
from historian.sqlite_store.codec import encode, decode
from historian.sqlite_store.repository import canonical, transaction

from historian.sqlite_store.access import WRITE, READ

LINKS = {
    "taxonomy_version": "FrameTaxonomy",
    "proposal_id": "ProposedRelation",
    "superseded_by_proposal_id": "ProposedRelation",
    "derived_from_proposal_id": "ProposedRelation",
    "asserted_relation_id": "AssertedRelation",
    "replacement_assertion_id": "AssertedRelation",
    "resolution_id": "Resolution",
    "replacement_resolution_id": "Resolution",
    "previous_resolution_id": "Resolution",
    "asserted_relation_refs": "AssertedRelation",
    "proposed_relation_refs": "ProposedRelation",
    "claim_proposal_refs": "ClaimProposal",
    "source_role_proposal_refs": "SourceRoleProposal",
    "routing_proposal_ref": "RoutingProposal",
    "seed_id": "GoldCaseSeed",
    "packet_id": "AdjudicationPacket",
    "adjudication_id": "BlindAdjudication",
}


def get(c, kind, identity):
    row = c.execute(
        "SELECT payload FROM app_object JOIN app_seal USING(kind,id) WHERE kind=? AND id=?",
        (kind, identity),
    ).fetchone()
    if row is None:
        raise KeyError(identity)
    return decode(json.loads(row[0]))


def refs(value):
    if isinstance(value, t.EvidenceRef):
        yield value
    elif is_dataclass(value):
        for f in fields(value):
            yield from refs(getattr(value, f.name))
    elif isinstance(value, (tuple, list)):
        for v in value:
            yield from refs(v)


def validate_evidence(c, ref):
    row = c.execute(
        "SELECT locator,quote FROM evidence WHERE id=?", (ref.key,)
    ).fetchone()
    if row is None:
        raise ValueError("unknown evidence")
    loc = json.loads(row[0])
    parts = {p["name"]: p["value"] for p in loc["coordinate_parts"]}
    if (
        loc["record_id"] != ref.source_id
        or loc["source_system"] != ref.source_system.value
        or loc["version_hash"] != ref.source_version_hash
        or loc["content_hash"] != ref.passage_hash
        or loc["coordinate_system"] != ref.position.coordinate_system.value
        or parts != {"start": str(ref.position.start), "end": str(ref.position.end)}
        or row[1] != ref.quote
    ):
        raise ValueError("evidence reference differs from verified storage")


def put(repository, obj, role, principal, corpus):
    kind = type(obj).__name__
    if role not in WRITE.get(kind, set()):
        raise PermissionError("domain capability denied")
    c = repository.connection
    if isinstance(obj, BlindAdjudication):
        obj = replace(obj, adjudicator_id=principal)
    if (
        isinstance(obj, t.AssertedRelation)
        and obj.origin is t.AssertionOrigin.HUMAN_REVIEWED_PROPOSAL
    ):
        obj = replace(obj, human_adjudicator_id=principal)
    if isinstance(obj, t.AssertedRelationReview):
        expected = "typed" if obj.origin is t.ReviewOrigin.TYPED_SOURCE else "reviewer"
        if role != expected:
            raise PermissionError("review origin does not match capability")
        if expected == "reviewer":
            obj = replace(obj, reviewer_id=principal)
    if isinstance(obj, ResolutionReview):
        obj = replace(obj, reviewer_id=principal)
    if isinstance(obj, t.FrameTaxonomy):
        # Taxonomy uses version as its durable identity, not an invented separate ID.
        identity = obj.version
        payload = encode(obj)
        payload["fields"]["id"] = identity
    else:
        identity, payload = obj.id, encode(obj)
    question_id = getattr(obj, "question_id", None)
    question_text = getattr(obj, "question_text", None)
    if isinstance(obj, t.Question):
        question_id, question_text = obj.id, obj.text
    if isinstance(obj, ResolutionReview):
        question_id = get(c, "Resolution", obj.resolution_id).question_id
    with transaction(c):
        if isinstance(obj, t.Question):
            c.execute("INSERT INTO question VALUES (?,?)", (obj.id, obj.text))
        if isinstance(obj, t.RoutingProposal):
            taxonomy = get(c, "FrameTaxonomy", obj.taxonomy_version)
            if not taxonomy.permits(obj.proposed_frame) or any(
                not taxonomy.permits(frame) for frame, _ in obj.alternates
            ):
                raise ValueError("frame outside taxonomy")
            c.execute(
                "INSERT INTO route VALUES (?,?,?)",
                (obj.id, obj.question_id, obj.proposed_frame),
            )
        if isinstance(obj, t.ClaimProposal):
            c.execute(
                "INSERT INTO claim VALUES (?,?,?,?)",
                (obj.id, obj.evidence_id, obj.question_id, obj.claim),
            )
        if isinstance(obj, t.AssertedRelation):
            if obj.origin is t.AssertionOrigin.HUMAN_REVIEWED_PROPOSAL:
                proposal = get(c, "ProposedRelation", obj.derived_from_proposal_id)
                if (obj.subject_ref.key, obj.relation_type, obj.object_ref.key) != (
                    proposal.subject_ref.key,
                    proposal.relation_type,
                    proposal.object_ref.key,
                ):
                    raise ValueError("reviewed assertion differs from proposal")
            repository.insert_assertion(
                {
                    "id": obj.id,
                    "subject_id": obj.subject_ref.key,
                    "object_id": obj.object_ref.key,
                    "origin": obj.origin.value,
                },
                principal,
                role,
            )
        if isinstance(obj, GoldCaseSeed):
            if not obj.evidence_packet or not obj.invariant_candidates:
                raise ValueError("seed requires evidence and invariants")
            c.execute(
                "INSERT INTO seed VALUES (?,?,?)",
                (obj.id, obj.question_id, obj.question_text),
            )
            for ref in obj.evidence_packet:
                c.execute("INSERT INTO seed_evidence VALUES (?,?)", (obj.id, ref.key))
            c.execute("INSERT INTO seed_seal VALUES (?)", (obj.id,))
        if isinstance(obj, AdjudicationPacket):
            from historian.sources import RagV1SourceReader
            from historian.source_adapter import sha256_text

            seed = get(c, "GoldCaseSeed", obj.seed_id)
            if (
                obj.question_text != seed.question_text
                or obj.evidence_packet != seed.evidence_packet
                or obj.packet_hash
                != packet_hash(seed.question_text, seed.evidence_packet)
            ):
                raise ValueError("packet differs from seed")
            snapshots = []
            for ref in obj.evidence_packet:
                if ref.source_system is not t.SourceSystem.RAG_V1:
                    raise ValueError("packet source reader unavailable")
                text = RagV1SourceReader(corpus).read_lines(
                    ref.source_id,
                    ref.source_version_hash,
                    ref.position.start,
                    ref.position.end,
                )
                if (
                    not text
                    or sha256_text(text) != ref.passage_hash
                    or ref.quote not in text
                ):
                    raise ValueError("packet source mismatch")
                snapshots.append(text)
            c.execute("INSERT INTO packet VALUES (?,?)", (obj.id, obj.seed_id))
            for ref in obj.evidence_packet:
                c.execute("INSERT INTO packet_evidence VALUES (?,?)", (obj.id, ref.key))
            for index, (ref, text) in enumerate(zip(obj.evidence_packet, snapshots)):
                c.execute(
                    "INSERT INTO app_snapshot VALUES (?,?,?,?)",
                    (obj.id, ref.key, index, text),
                )
            c.execute("INSERT INTO packet_seal VALUES (?)", (obj.id,))
        if isinstance(obj, BlindAdjudication):
            packet = get(c, "AdjudicationPacket", obj.packet_id)
            if obj.evidence_used != packet.evidence_packet:
                raise ValueError("adjudication evidence differs from packet")
            c.execute(
                "INSERT INTO adjudication VALUES (?,?,?,?,?)",
                (
                    obj.id,
                    obj.packet_id,
                    principal,
                    obj.verdict.value,
                    obj.resolution_text,
                ),
            )
        if isinstance(obj, EvaluationGold):
            adj = get(c, "BlindAdjudication", obj.adjudication_id)
            packet = get(c, "AdjudicationPacket", adj.packet_id)
            seed = get(c, "GoldCaseSeed", packet.seed_id)
            if (
                obj.seed_id != seed.id
                or obj.defends_invariants != seed.invariant_candidates
                or obj.expected_resolution != adj.resolution_text
                or obj.expected_outcome.value != adj.verdict.value
            ):
                raise ValueError("gold does not match adjudication lineage")
            c.execute("INSERT INTO gold VALUES (?,?)", (obj.id, obj.adjudication_id))
        c.execute(
            "INSERT INTO app_object VALUES (?,?,?,?,?,?)",
            (kind, identity, question_id, question_text, canonical(payload), principal),
        )
        for f in fields(obj):
            if f.name not in LINKS:
                continue
            value = getattr(obj, f.name)
            values = (
                value
                if isinstance(value, tuple)
                else (() if value is None else (value,))
            )
            for target in values:
                qid = (
                    question_id
                    if f.name
                    in (
                        "claim_proposal_refs",
                        "routing_proposal_ref",
                        "previous_resolution_id",
                        "replacement_resolution_id",
                    )
                    else None
                )
                c.execute(
                    "INSERT INTO app_link VALUES (?,?,?,?,?,?)",
                    (kind, identity, f.name, LINKS[f.name], target, qid),
                )
        evidence = set()
        for ref in refs(obj):
            validate_evidence(c, ref)
            evidence.add(ref.key)
        if isinstance(obj, t.ClaimProposal):
            evidence.add(obj.evidence_id)
        for eid in evidence:
            c.execute("INSERT INTO app_evidence VALUES (?,?,?)", (kind, identity, eid))
        c.execute("INSERT INTO app_seal VALUES (?,?)", (kind, identity))
    return identity


def dispatch(repository, operation, data, role, principal, corpus):
    if operation == "put_object":
        if role not in WRITE.get(data.get("object", {}).get("type"), set()):
            raise PermissionError("domain write denied")
        return put(repository, decode(data["object"]), role, principal, corpus)
    kind = "AdjudicationPacket" if operation == "get_packet_snapshot" else data["kind"]
    if role not in READ.get(kind, set()):
        raise PermissionError("domain read denied")
    value = get(repository.connection, kind, data["id"])
    if operation == "get_packet_snapshot":
        return [
            {"evidence_id": eid, "ordinal": ordinal, "text": text}
            for eid, ordinal, text in repository.connection.execute(
                "SELECT evidence_id,ordinal,snapshot_text FROM app_snapshot WHERE packet_id=? ORDER BY ordinal",
                (data["id"],),
            ).fetchall()
        ]
    if isinstance(value, AdjudicationPacket) and role == "adjudicator":
        value = replace(value, seed_id="")
    return encode(value)
