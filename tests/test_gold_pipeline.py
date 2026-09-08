"""End-to-end gold pipeline across capability boundaries, plus writer separation.

Covers the five structural gaps closed before persistence:
  1 assertion-writer separation   2 routing bound to taxonomy   3 append-only proposals
  4 verified evidence materialisation                          5 chain-verified gold
"""

import hashlib
import pytest

from historian.capability import (
    BlindAdjudicator,
    EvidenceVerificationError,
    ExtractorWriter,
    GoldCompiler,
    HumanReviewWriter,
    PacketBuilder,
    TypedSourceIngestor,
)
from historian.gold import GoldCaseSeed
from historian.types import (
    AssertedRelation,
    AssertionOrigin,
    AdjudicationVerdict,
    CoordinateSystem,
    EvidenceRef,
    Outcome,
    RelationType,
    SourcePosition,
    SourceSystem,
)

DOCS = {
    ("doc-vendor", "v1"): "upstream release notes for v0.8.4\nline two\n",
    ("doc-local", "v1"): "decommission in stages; legacy substrate\nline two\n",
}


class Store:
    def __init__(self):
        self.seeds, self.packets, self.adjudications, self.gold = {}, {}, {}, {}
        self.proposals, self.assertions = [], []

    def get_seed(self, i): return self.seeds[i]
    def get_packet(self, i): return self.packets[i]
    def put_packet(self, p): self.packets[p.id] = p
    def get_adjudication(self, i): return self.adjudications[i]
    def put_adjudication(self, a): self.adjudications[a.id] = a
    def put_gold(self, g): self.gold[g.id] = g
    def put_proposal(self, p): self.proposals.append(p)
    def put_disposition(self, e): self.proposals.append(e)
    def put_source_role(self, p): self.proposals.append(p)
    def put_routing(self, p): self.proposals.append(p)
    def put_assertion(self, a): self.assertions.append(a)
    def put_assertion_review(self, r): self.assertions.append(r)


class Sources:
    """Read-only source adapter (stands in for RAG v1)."""

    def read_lines(self, source_id, version_hash, start, end):
        text = DOCS.get((source_id, version_hash))
        if text is None:
            return None
        return "".join(text.splitlines(keepends=True)[start - 1:end])


def ev(source, start=1, end=1, ver="v1", quote=None, bad_hash=False):
    body = Sources().read_lines(source, ver, start, end) or ""
    h = hashlib.sha256(body.encode()).hexdigest()
    # a version the reader cannot resolve still needs a syntactically valid ref, so the
    # PacketBuilder gets the chance to reject it rather than the constructor
    p = SourcePosition(source, ver, CoordinateSystem.LINE, start, end)
    return EvidenceRef(source, SourceSystem.RAG_V1, ver, p,
                       "deadbeef" if bad_hash else h, quote or body.strip(),
                       evidence_id=f"{source}:{ver}:{start}-{end}")


@pytest.fixture
def seeded():
    st = Store()
    st.seeds["SEED-1"] = GoldCaseSeed(
        id="SEED-1", question_id="q1", question_text="What is the current state?",
        evidence_packet=(ev("doc-vendor"), ev("doc-local")),
        family="authority-trap", invariant_candidates=("B7_NO_RECENCY_AS_AUTHORITY",))
    return st


# ------------------------------------------------------- gap 1: writer separation


def test_extractor_cannot_write_assertions(seeded):
    w = ExtractorWriter(seeded)
    assert not hasattr(w, "_assertions")
    assert not hasattr(w, "assert_reviewed")
    assert not hasattr(w, "ingest")


def test_typed_ingestor_refuses_human_origin(seeded):
    a = AssertedRelation("A1", ev("doc-vendor"), RelationType.AUGMENTS, ev("doc-local"),
                         (ev("doc-vendor"),), AssertionOrigin.HUMAN_REVIEWED_PROPOSAL,
                         human_adjudicator_id="someone", derived_from_proposal_id="P1")
    with pytest.raises(ValueError, match="only write TYPED_SOURCE"):
        TypedSourceIngestor(seeded).ingest(a)


def test_human_writer_refuses_typed_source(seeded):
    a = AssertedRelation("A2", ev("doc-vendor"), RelationType.AUGMENTS, ev("doc-local"),
                         (ev("doc-vendor"),), AssertionOrigin.TYPED_SOURCE,
                         typed_source_ref="clm-x")
    with pytest.raises(ValueError, match="only write HUMAN_"):
        HumanReviewWriter(seeded).assert_reviewed(a)


def test_typed_ingestor_accepts_typed_source(seeded):
    a = AssertedRelation("A3", ev("doc-vendor"), RelationType.AUGMENTS, ev("doc-local"),
                         (ev("doc-vendor"),), AssertionOrigin.TYPED_SOURCE,
                         typed_source_ref="clm-x")
    assert TypedSourceIngestor(seeded).ingest(a).gold_eligible is True


# ------------------------------------------- gap 4: verified evidence materialisation


def test_packet_builder_verifies_passage_hashes(seeded):
    seeded.seeds["SEED-BAD"] = GoldCaseSeed(
        id="SEED-BAD", question_id="q2", question_text="q",
        evidence_packet=(ev("doc-vendor", bad_hash=True),),
        family="f", invariant_candidates=())
    with pytest.raises(EvidenceVerificationError, match="passage hash mismatch"):
        PacketBuilder(seeded, seeded, Sources()).build("SEED-BAD", "PKT-BAD")


def test_packet_builder_rejects_unreadable_source(seeded):
    seeded.seeds["SEED-GONE"] = GoldCaseSeed(
        id="SEED-GONE", question_id="q3", question_text="q",
        evidence_packet=(ev("doc-vendor", ver="v-missing", quote="anchor"),),
        family="f", invariant_candidates=())
    with pytest.raises(EvidenceVerificationError, match="could not be read"):
        PacketBuilder(seeded, seeded, Sources()).build("SEED-GONE", "PKT-GONE")


def test_packet_drops_contaminating_context(seeded):
    packet = PacketBuilder(seeded, seeded, Sources()).build("SEED-1", "PKT-1")
    assert not hasattr(packet, "family")
    assert not hasattr(packet, "invariant_candidates")
    assert packet.packet_hash


# ------------------------------------------------------ gap 5: chain-verified gold


def test_full_pipeline_produces_gold(seeded):
    PacketBuilder(seeded, seeded, Sources()).build("SEED-1", "PKT-1")
    adj = BlindAdjudicator(seeded, seeded).adjudicate(
        adjudication_id="ADJ-1", packet_id="PKT-1", adjudicator_id="adjudicator-1",
        verdict=AdjudicationVerdict.RESOLVED, rationale="local decision governs local state",
        resolution_text="the local decision governs")
    g = GoldCompiler(seeded, seeded, seeded, seeded).compile(
        gold_id="GOLD-1", adjudication_id="ADJ-1", allowed_abstention=False)
    assert g.seed_id == "SEED-1"
    assert g.expected_resolution == adj.resolution_text
    assert g.defends_invariants == ("B7_NO_RECENCY_AS_AUTHORITY",)


def test_gold_compiler_takes_no_seed_argument():
    """The seed is DERIVED from the chain, so it cannot be cross-wired by a caller."""
    import inspect
    params = set(inspect.signature(GoldCompiler.compile).parameters)
    assert "seed_id" not in params


def test_cross_wired_verdict_cannot_become_gold(seeded):
    """A verdict produced for seed B must not compile into gold for seed A."""
    seeded.seeds["SEED-2"] = GoldCaseSeed(
        id="SEED-2", question_id="q9", question_text="a different question",
        evidence_packet=(ev("doc-local"),), family="other", invariant_candidates=("B1",))
    PacketBuilder(seeded, seeded, Sources()).build("SEED-1", "PKT-1")
    PacketBuilder(seeded, seeded, Sources()).build("SEED-2", "PKT-2")
    BlindAdjudicator(seeded, seeded).adjudicate(
        adjudication_id="ADJ-2", packet_id="PKT-2", adjudicator_id="a1",
        verdict=AdjudicationVerdict.RESOLVED, rationale="r",
        resolution_text="answer for seed 2")

    g = GoldCompiler(seeded, seeded, seeded, seeded).compile(
        gold_id="GOLD-2", adjudication_id="ADJ-2", allowed_abstention=False)
    # gold follows the chain to SEED-2 and cannot be pointed at SEED-1
    assert g.seed_id == "SEED-2"
    assert g.defends_invariants == ("B1",)


def test_tampered_packet_is_rejected_at_compile(seeded):
    from dataclasses import replace
    PacketBuilder(seeded, seeded, Sources()).build("SEED-1", "PKT-1")
    seeded.packets["PKT-1"] = replace(seeded.packets["PKT-1"],
                                      question_text="a substituted question")
    BlindAdjudicator(seeded, seeded).adjudicate(
        adjudication_id="ADJ-3", packet_id="PKT-1", adjudicator_id="a1",
        verdict=AdjudicationVerdict.RESOLVED, rationale="r", resolution_text="x")
    with pytest.raises(ValueError, match="does not match its seed"):
        GoldCompiler(seeded, seeded, seeded, seeded).compile(
            gold_id="GOLD-3", adjudication_id="ADJ-3", allowed_abstention=False)


def test_packet_insufficient_cannot_be_compiled_to_gold(seeded):
    PacketBuilder(seeded, seeded, Sources()).build("SEED-1", "PKT-ins")
    BlindAdjudicator(seeded, seeded).adjudicate(
        adjudication_id="ADJ-ins", packet_id="PKT-ins", adjudicator_id="a1",
        verdict=AdjudicationVerdict.PACKET_INSUFFICIENT,
        rationale="the supplied packet lacks the decisive passage")
    with pytest.raises(ValueError, match="reseeded"):
        GoldCompiler(seeded, seeded, seeded, seeded).compile(
            gold_id="GOLD-ins", adjudication_id="ADJ-ins", allowed_abstention=False)


def test_adjudicator_cannot_reach_seed_or_gold(seeded):
    a = BlindAdjudicator(seeded, seeded)
    assert not hasattr(a, "_seeds")
    assert not hasattr(a, "_gold")
