"""Evaluation gold: four artifacts, because one would leak the answer.

    GoldCaseSeed        internal test-design object. Holds family and invariant
                        candidates, which are themselves contaminating.
    AdjudicationPacket  the ONLY thing a blind adjudicator sees.
    BlindAdjudication   the adjudicator's independent verdict.
    EvaluationGold      the expected answer, compiled only AFTER adjudication.

Contamination is prevented by ABSENCE, not by discipline: GoldCaseSeed has no field able
to hold an expected answer, and AdjudicationPacket has no field able to hold the family or
the invariant candidates. Telling an adjudicator "family = authority-trap, invariants =
NO_RECENCY_AS_AUTHORITY" hands them the answer without stating it.
"""

from __future__ import annotations

from dataclasses import dataclass

from .types import AdjudicationMode, AdjudicationVerdict, EvidenceRef, Outcome, _enum


@dataclass(frozen=True, slots=True)
class GoldCaseSeed:
    """Internal test-design object. NOT the blind packet."""

    id: str
    question_id: str
    question_text: str
    evidence_packet: tuple[EvidenceRef, ...]
    family: str
    invariant_candidates: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AdjudicationPacket:
    """Everything a blind adjudicator is permitted to see, and nothing else.

    Deliberately absent: family, invariant candidates, forbidden shortcuts, model
    proposals, expected outcome, prior Historian output.
    """

    id: str
    seed_id: str
    question_text: str
    evidence_packet: tuple[EvidenceRef, ...]
    packet_hash: str

    def __post_init__(self) -> None:
        if not self.packet_hash:
            raise ValueError("packet_hash is required so the adjudicated packet is pinned")


@dataclass(frozen=True, slots=True)
class BlindAdjudication:
    """An independent human verdict on a packet.

    `*_declared` fields are AUDIT ONLY. They are not the enforcement mechanism — anything
    can write False. Blindness is enforced by capability separation (see capability.py).
    """

    id: str
    packet_id: str
    adjudicator_id: str
    """In PostgreSQL this is OVERWRITTEN from the authenticated principal by trigger and a
    submitted value is discarded: SCRAM proves the connection is the adjudicator SERVICE
    role, never which human is at the keyboard, and G-S6 requires human provenance."""
    verdict: AdjudicationVerdict
    rationale: str
    evidence_used: tuple[EvidenceRef, ...] = ()
    resolution_text: str | None = None
    adjudication_mode: AdjudicationMode = AdjudicationMode.BLIND
    proposal_exposure_declared: bool = False
    system_output_seen_declared: bool = False

    def __post_init__(self) -> None:
        _enum(self.verdict, AdjudicationVerdict, "BlindAdjudication.verdict")
        _enum(self.adjudication_mode, AdjudicationMode, "BlindAdjudication.adjudication_mode")
        if not self.adjudicator_id:
            raise ValueError("adjudicator_id is required: gold must name its adjudicator")
        if self.adjudication_mode is not AdjudicationMode.BLIND:
            raise ValueError("only BLIND adjudication is permitted in v0")
        if self.verdict is AdjudicationVerdict.RESOLVED and not self.resolution_text:
            raise ValueError("a RESOLVED adjudication requires resolution_text")
        if self.verdict is AdjudicationVerdict.PACKET_INSUFFICIENT and self.resolution_text:
            raise ValueError("PACKET_INSUFFICIENT must not carry resolution_text")


@dataclass(frozen=True, slots=True)
class EvaluationGold:
    """The expected answer. Cannot exist without a BlindAdjudication to descend from."""

    id: str
    seed_id: str
    adjudication_id: str
    expected_outcome: Outcome
    allowed_abstention: bool
    defends_invariants: tuple[str, ...]
    expected_resolution: str | None = None

    def __post_init__(self) -> None:
        _enum(self.expected_outcome, Outcome, "EvaluationGold.expected_outcome")
        if not self.adjudication_id:
            raise ValueError(
                "EvaluationGold requires adjudication_id: there is no constructor for "
                "hand-written gold that did not descend from a blind adjudication")
        if self.expected_outcome is Outcome.RESOLVED and not self.expected_resolution:
            raise ValueError("RESOLVED gold requires expected_resolution")
        if self.expected_outcome is Outcome.RESOLVED and self.allowed_abstention:
            raise ValueError(
                "a case whose expected outcome is RESOLVED cannot allow abstention: "
                "false abstention is a hard failure (B4)")
