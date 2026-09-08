"""Capability separation (ST2, ST4 / G-S2, G-S3, G-S4, G-S5).

A boolean saying `proposal_exposure = False` is a declaration, and anything can write
False. Naming stores a component "must not read" is configuration. Neither is enforcement.

Each component here is constructed with ONLY the stores it may reach. It cannot touch a
forbidden store because it holds no reference to one — there is no method to call and no
permission to misconfigure.

IN DEPLOYMENT these run under DISTINCT POSTGRESQL ROLES against `evecor_historian`, with
grants matching each class's capabilities and UPDATE/DELETE revoked on append-only tables.
This module is the in-process expression of that boundary, never a substitute for it:

    historian_extractor        -> ExtractorWriter
    historian_typed_ingestor   -> TypedSourceIngestor
    historian_human_reviewer   -> HumanReviewWriter
    historian_runtime          -> RuntimeResolver
    historian_packet_builder   -> PacketBuilder
    historian_adjudicator      -> BlindAdjudicator
    historian_gold_compiler    -> GoldCompiler
"""

from __future__ import annotations

import hashlib
from typing import Protocol

from .gold import AdjudicationPacket, BlindAdjudication, EvaluationGold, GoldCaseSeed
from .resolution import Resolution
from .sources import SourceUnavailable
from .types import (
    AssertedRelation,
    AssertedRelationReview,
    AssertionOrigin,
    AdjudicationVerdict,
    EvidenceRef,
    Outcome,
    ProposalDispositionEvent,
    ProposedRelation,
    RoutingProposal,
    SourceRoleProposal,
)


# ------------------------------------------------------------------- store protocols


class ProposalStore(Protocol):
    def put_proposal(self, p: ProposedRelation) -> None: ...
    def put_disposition(self, e: ProposalDispositionEvent) -> None: ...
    def put_source_role(self, p: SourceRoleProposal) -> None: ...
    def put_routing(self, p: RoutingProposal) -> None: ...


class AssertionStore(Protocol):
    def put_assertion(self, a: AssertedRelation) -> None: ...
    def put_assertion_review(self, r: AssertedRelationReview) -> None: ...


class ResolutionStore(Protocol):
    def put_resolution(self, r: Resolution) -> None: ...


class SeedStore(Protocol):
    def get_seed(self, seed_id: str) -> GoldCaseSeed: ...


class PacketStore(Protocol):
    def get_packet(self, packet_id: str) -> AdjudicationPacket: ...
    def put_packet(self, packet: AdjudicationPacket) -> None: ...


class AdjudicationStore(Protocol):
    def get_adjudication(self, adjudication_id: str) -> BlindAdjudication: ...
    def put_adjudication(self, adj: BlindAdjudication) -> None: ...


class GoldStore(Protocol):
    def put_gold(self, gold: EvaluationGold) -> None: ...


class SourceReader(Protocol):
    """Read-only access to source bytes. RAG v1 exposes no Historian state."""

    def read_lines(self, source_id: str, version_hash: str,
                   start: int, end: int) -> str: ...


# ----------------------------------------------------------------- writer separation


class ExtractorWriter:
    """Model/extractor identity. Writes PROPOSALS ONLY.

    Holds no assertion store, so it cannot create an AssertedRelation at all — not even
    one claiming `origin=HUMAN_BLIND_ADJUDICATION` with a fabricated adjudicator id. The
    enum guard blocks `origin="MODEL"`; this blocks the far more plausible attack of a
    model process asserting through a legitimate-looking origin. In PostgreSQL,
    `historian_extractor` simply has no INSERT grant on the assertion tables.
    """

    def __init__(self, proposals: ProposalStore) -> None:
        self._proposals = proposals

    def propose_relation(self, p: ProposedRelation) -> ProposedRelation:
        self._proposals.put_proposal(p)
        return p

    def propose_source_role(self, p: SourceRoleProposal) -> SourceRoleProposal:
        self._proposals.put_source_role(p)
        return p

    def propose_route(self, p: RoutingProposal) -> RoutingProposal:
        # RoutingProposal is unconditionally inferential; there is no flag to misuse.
        self._proposals.put_routing(p)
        return p

    def record_disposition(self, e: ProposalDispositionEvent) -> ProposalDispositionEvent:
        self._proposals.put_disposition(e)
        return e


class EvidenceVerificationError(RuntimeError):
    """A proposed location could not be confirmed against the source."""


class EvidenceVerifier:
    """The ONLY identity that may create an EvidenceRef.

    Reads a model-proposed EvidenceCandidate, re-reads the ACTUAL source at the stated
    version and position, recomputes the passage hash, and only then writes evidence.
    Holds no proposal, assertion, resolution or gold store, so it is an evidence authority
    and nothing else.

    VERIFICATION MEANS: this passage exists at this source, version and position, with
    these bytes. IT DOES NOT MEAN the passage is authoritative, complete, current or true.
    For the ledger specifically, confirming a claim exists says nothing about one that does
    not - the documented recording gap makes absence uninformative.
    """

    def __init__(self, candidates, evidence, registry, verifier_id: str) -> None:
        self._candidates = candidates
        self._evidence = evidence
        self._registry = registry
        self._verifier_id = verifier_id

    def verify(self, candidate_id: str, evidence_id: str):
        c = self._candidates.get_candidate(candidate_id)
        # The declared source system SELECTS the backend. If it were only copied into the
        # result, a candidate could claim LEDGER, be verified against RAG bytes, and
        # persist provenance the bytes never supported.
        try:
            reader = self._registry.reader_for(c.proposed_source_system)
        except SourceUnavailable as e:
            raise EvidenceVerificationError(str(e)) from e
        text = reader.read_lines(c.proposed_source_id, c.proposed_version_hash,
                                 c.proposed_line_start, c.proposed_line_end)
        if not text:
            raise EvidenceVerificationError(
                f"{c.proposed_source_id}@{c.proposed_version_hash} lines "
                f"{c.proposed_line_start}-{c.proposed_line_end} does not exist in source")
        if c.proposed_quote and c.proposed_quote not in text:
            raise EvidenceVerificationError(
                "proposed anchor is not present at the proposed position")
        ref = {"id": evidence_id,
               "source_system": c.proposed_source_system,
               "source_id": c.proposed_source_id,
               "source_version_hash": c.proposed_version_hash,
               "line_start": c.proposed_line_start, "line_end": c.proposed_line_end,
               "passage_hash": _passage_hash(text), "quote": c.proposed_quote,
               "derived_from_candidate_id": c.id,
               # verified_by is overwritten from session_user by a database trigger; the
               # value passed here is advisory only and must never be trusted.
               "verified_by": self._verifier_id}
        self._evidence.put_evidence(ref)
        return ref


class TypedSourceIngestor:
    """Writes TYPED_SOURCE assertions only — e.g. a typed ledger relation."""

    def __init__(self, assertions: AssertionStore) -> None:
        self._assertions = assertions

    def ingest(self, a: AssertedRelation) -> AssertedRelation:
        if a.origin is not AssertionOrigin.TYPED_SOURCE:
            raise ValueError(
                f"typed-source ingestor may only write TYPED_SOURCE assertions, got "
                f"{a.origin.name}")
        self._assertions.put_assertion(a)
        return a


class HumanReviewWriter:
    """Writes HUMAN_REVIEWED_PROPOSAL assertions and assertion reviews only.

    It may NOT write HUMAN_BLIND_ADJUDICATION. Letting the ordinary review path stamp the
    blind origin would be self-certified blindness - the same flaw class as the original
    bare-string MODEL bypass. Blind-origin assertions come from BlindAssertionCompiler,
    and only from a real adjudication row.
    """

    def __init__(self, assertions: AssertionStore) -> None:
        self._assertions = assertions

    def assert_reviewed(self, a: AssertedRelation) -> AssertedRelation:
        if a.origin is not AssertionOrigin.HUMAN_REVIEWED_PROPOSAL:
            raise ValueError(
                f"human reviewer may only write HUMAN_REVIEWED_PROPOSAL, got "
                f"{a.origin.name}")
        self._assertions.put_assertion(a)
        return a

    def review_assertion(self, r: AssertedRelationReview) -> AssertedRelationReview:
        self._assertions.put_assertion_review(r)
        return r


class RuntimeResolver:
    """Produces Resolutions. Cannot write proposals or assertions."""

    def __init__(self, resolutions: ResolutionStore) -> None:
        self._resolutions = resolutions

    def resolve(self, r: Resolution) -> Resolution:
        self._resolutions.put_resolution(r)
        return r


# ------------------------------------------------------------------- gold pipeline


def packet_hash(question_text: str, evidence) -> str:
    h = hashlib.sha256()
    h.update(question_text.encode())
    for e in evidence:
        h.update(e.source_id.encode())
        h.update(e.source_version_hash.encode())
        h.update(e.passage_hash.encode())
    return h.hexdigest()


def _passage_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class PacketBuilder:
    """Materialises a seed into a VERIFIED, immutable packet.

    It does not trust whoever wrote the seed. Every EvidenceRef is re-read from source at
    the stated version and position, and the passage hash recomputed; a mismatch aborts.
    The adjudicator therefore receives an evidence snapshot that has been checked against
    the source bytes rather than one asserted by the seed's author.

    Holds no reference to proposal, routing, resolution or gold stores. Its source reader
    is read-only and points at RAG v1, which exposes no Historian state.
    """

    def __init__(self, seeds: SeedStore, packets: PacketStore,
                 sources: SourceReader) -> None:
        self._seeds = seeds
        self._packets = packets
        self._sources = sources

    def _verify(self, e: EvidenceRef) -> None:
        text = self._sources.read_lines(
            e.source_id, e.source_version_hash, e.position.start, e.position.end)
        if text is None:
            raise EvidenceVerificationError(
                f"{e.source_id}@{e.source_version_hash} lines "
                f"{e.position.start}-{e.position.end} could not be read")
        actual = _passage_hash(text)
        if actual != e.passage_hash:
            raise EvidenceVerificationError(
                f"passage hash mismatch for {e.source_id} lines "
                f"{e.position.start}-{e.position.end}: seed claims {e.passage_hash[:12]}, "
                f"source yields {actual[:12]}")
        if e.quote and e.quote not in text:
            raise EvidenceVerificationError(
                f"verbatim anchor not present in {e.source_id} at the cited position")

    def build(self, seed_id: str, packet_id: str) -> AdjudicationPacket:
        seed = self._seeds.get_seed(seed_id)
        for e in seed.evidence_packet:
            self._verify(e)
        packet = AdjudicationPacket(
            id=packet_id,
            seed_id=seed.id,
            question_text=seed.question_text,
            evidence_packet=seed.evidence_packet,
            packet_hash=packet_hash(seed.question_text, seed.evidence_packet),
        )
        self._packets.put_packet(packet)
        return packet


class BlindAdjudicator:
    """Records an independent human verdict.

    Holds ONLY packet and adjudication stores: no seeds (so family and invariant
    candidates are unreachable), no proposals or resolutions (so no system output is
    visible), no gold (so no expected answer). Blindness is the absence of a reference.
    """

    def __init__(self, packets: PacketStore, adjudications: AdjudicationStore) -> None:
        self._packets = packets
        self._adjudications = adjudications

    def adjudicate(self, *, adjudication_id: str, packet_id: str, adjudicator_id: str,
                   verdict: AdjudicationVerdict, rationale: str,
                   resolution_text: str | None = None) -> BlindAdjudication:
        packet = self._packets.get_packet(packet_id)
        adj = BlindAdjudication(
            id=adjudication_id, packet_id=packet.id, adjudicator_id=adjudicator_id,
            verdict=verdict, rationale=rationale, resolution_text=resolution_text,
            evidence_used=packet.evidence_packet)
        self._adjudications.put_adjudication(adj)
        return adj


class GoldCompiler:
    """Compiles gold by following the chain adjudication -> packet -> seed.

    The seed is NOT a caller argument. An earlier version accepted seed_id and
    adjudication_id independently and checked only that the adjudication had some packet
    id, so a verdict produced for Seed B could be compiled into gold for Seed A. The chain
    is now derived, and every link verified.
    """

    def __init__(self, seeds: SeedStore, packets: PacketStore,
                 adjudications: AdjudicationStore, gold: GoldStore) -> None:
        self._seeds = seeds
        self._packets = packets
        self._adjudications = adjudications
        self._gold = gold

    def compile(self, *, gold_id: str, adjudication_id: str,
                allowed_abstention: bool) -> EvaluationGold:
        adj = self._adjudications.get_adjudication(adjudication_id)
        if not adj.packet_id:
            raise ValueError("adjudication is not bound to a packet")
        packet = self._packets.get_packet(adj.packet_id)
        if not packet.seed_id:
            raise ValueError("packet is not bound to a seed")
        seed = self._seeds.get_seed(packet.seed_id)

        # every link re-verified rather than assumed
        if packet.question_text != seed.question_text:
            raise ValueError("packet question does not match its seed")
        expected = packet_hash(seed.question_text, seed.evidence_packet)
        if packet.packet_hash != expected:
            raise ValueError("packet hash does not match the seed it claims to render")

        if adj.verdict is AdjudicationVerdict.PACKET_INSUFFICIENT:
            raise ValueError(
                "PACKET_INSUFFICIENT means the packet must be reseeded; it cannot become gold")
        expected_outcome = (
            Outcome.RESOLVED if adj.verdict is AdjudicationVerdict.RESOLVED
            else Outcome.UNRESOLVED
        )

        g = EvaluationGold(
            id=gold_id, seed_id=seed.id, adjudication_id=adj.id,
            expected_outcome=expected_outcome, expected_resolution=adj.resolution_text,
            allowed_abstention=allowed_abstention,
            defends_invariants=seed.invariant_candidates)
        self._gold.put_gold(g)
        return g
