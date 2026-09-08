"""The Historian's adjudication core. DETERMINISTIC RULES over typed evidence.

This engine does not read documents. Reading is inference, and inference produces PROPOSED
annotations - a source role, a relation, a claim, a route. The engine consumes those and
applies B1-B8 as rules. That division is the architecture's central commitment:

    deterministic facts constrain inference;
    inference must never manufacture deterministic facts.

Every rule below exists because a specific wrong behaviour is otherwise available, and each
is named in the code rather than left implicit, so that removing one is a visible act.

The engine consumes PROPOSAL OBJECTS, not loose values. It used to take a raw
`dict[str, SourceRole]` and a bare `proposed_frame: str`, which meant the resulting
Resolution could not say whose inference it rested on. Provenance that is discarded at the
door cannot be reconstructed downstream, so the identities travel with the values.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from .resolution import Resolution
from .types import (
    AssertedRelation,
    ClaimProposal,
    EvidenceRef,
    FrameTaxonomy,
    Outcome,
    ProposedRelation,
    Question,
    RelationType,
    ResolutionMethod,
    RoutingProposal,
    SourceRole,
    SourceRoleProposal,
    _enum,
)

UNKNOWN = FrameTaxonomy.UNKNOWN
SETTLING = (RelationType.SUPERSEDES, RelationType.CORRECTS)


def _evidence_key(e: EvidenceRef) -> str:
    return e.key


# --------------------------------------------------------------------- inputs


@dataclass(frozen=True, slots=True)
class AuthorityPolicy:
    """Which source roles carry authority for which frame. Declared, versioned, inspectable.

    This is the mechanism behind B8: authority is a property of the (frame, role) pair, not
    of a source. The same document is authoritative for one question and not for another.
    """

    taxonomy_version: str
    by_frame: dict[str, tuple[SourceRole, ...]]

    def authoritative_roles(self, frame: str) -> tuple[SourceRole, ...]:
        return self.by_frame.get(frame, ())


@dataclass(frozen=True, slots=True)
class Adjudication:
    """The engine's decision, plus the trace that makes it checkable.

    The trace is deliberately WIDER than the Resolution's dependency refs. A Resolution
    records what its conclusion RESTS ON; the trace also records what was in scope and
    played no part - notably proposed relations, which are seen and refused. Putting those
    into the Resolution would inflate its support profile with inferences it did not use.
    """

    resolution: Resolution
    frame: str
    frame_is_caller_specified: bool
    authority_refs: tuple[str, ...]      # evidence treated as authoritative
    considered_refs: tuple[str, ...]     # evidence in scope before authority filtering
    silent_refs: tuple[str, ...]         # in scope, no claim offered
    conflict: bool
    refused_relation_refs: tuple[str, ...] = ()   # proposed relations, seen and not obeyed
    notes: tuple[str, ...] = ()


# ---------------------------------------------------------------------- engine


class Adjudicator:
    """Applies B1-B8 deterministically. No model is consulted anywhere in this class."""

    def __init__(self, taxonomy: FrameTaxonomy, policy: AuthorityPolicy) -> None:
        if policy.taxonomy_version != taxonomy.version:
            raise ValueError("authority policy and taxonomy versions disagree")
        self._tax = taxonomy
        self._policy = policy

    # -- B5 / B6 -----------------------------------------------------------
    def _route(self, question: Question,
               routing: RoutingProposal | None) -> tuple[str, bool, str | None]:
        """Select a frame. Returns (frame, caller_specified, routing_proposal_id).

        B6: a frame outside the versioned taxonomy is NEVER adopted - it degrades to
        UNKNOWN_OR_AMBIGUOUS. Inventing a frame would let the routing layer expand the
        space it is supposed to be constrained by.

        B5: routing is inferential unless the CALLER supplied the frame on the Question.
        A proposed frame is never reported as caller-specified.

        A routing proposal that is REFUSED is not cited: the resolution did not route by it.
        """
        if question.caller_frame is not None:
            if not self._tax.permits(question.caller_frame):
                return UNKNOWN, False, None
            return question.caller_frame, True, None
        if routing is None or not self._tax.permits(routing.proposed_frame):
            return UNKNOWN, False, None
        if routing.taxonomy_version != self._tax.version:
            return UNKNOWN, False, None
        return routing.proposed_frame, False, routing.id

    # -- B8 ----------------------------------------------------------------
    def _authoritative(self, frame: str, evidence: tuple[EvidenceRef, ...],
                       roles: dict[str, SourceRole]) -> tuple[str, ...]:
        """Evidence whose role carries authority FOR THIS FRAME.

        With an unknown frame no role is privileged, so everything stays in scope and the
        conflict rules decide. Guessing an authority under an unknown frame would be
        exactly the invention B6 forbids, one layer down.
        """
        if frame == UNKNOWN:
            return tuple(_evidence_key(e) for e in evidence)
        ok = self._policy.authoritative_roles(frame)
        return tuple(_evidence_key(e) for e in evidence
                     if roles.get(_evidence_key(e), SourceRole.UNKNOWN) in ok)

    # -- B2 / B7 -----------------------------------------------------------
    @staticmethod
    def _settles(a: str, b: str, asserted: tuple[AssertedRelation, ...]):
        """Does an ASSERTED relation settle a disagreement between two sources?

        Returns (winner_evidence_id, relation_id) or (None, None).

        Only SUPERSEDES and CORRECTS settle anything, and only when ASSERTED. Neither
        document order (B2) nor date (B7) is consulted here - deliberately. A tie-break on
        recency is the single most tempting wrong rule in the whole design, so recency is
        not available to this function at all: it never receives a date.

        The parameter is typed AND the caller filters by `isinstance`. An earlier revision
        took an untyped tuple and duck-typed on `.relation_type` / `.subject_ref` /
        `.object_ref` - fields `ProposedRelation` also has - so a MODEL could propose
        `A CORRECTS B` and settle a real conflict with it. That is the promotion path the
        ASSERTED/PROPOSED split exists to make unreachable.
        """
        wins: dict[str, str] = {}
        for r in asserted:
            if r.relation_type not in SETTLING:
                continue
            s, o = _evidence_key(r.subject_ref), _evidence_key(r.object_ref)
            if {s, o} == {a, b} and s != o:
                wins.setdefault(s, r.id)
        # BOTH directions asserted for the same pair is a contradictory record. Returning
        # the first match would let scan order decide a conflict, which is document order
        # wearing a different hat (B2). A contradictory pair settles nothing.
        if len(wins) != 1:
            return None, None
        winner, rel_id = next(iter(wins.items()))
        return winner, rel_id

    @staticmethod
    def _contradicted(a: str, b: str, asserted: tuple[AssertedRelation, ...]) -> bool:
        """Both directions asserted for one pair. A contradictory record, not a decision."""
        dirs = {_evidence_key(r.subject_ref) for r in asserted
                if r.relation_type in SETTLING
                and {_evidence_key(r.subject_ref), _evidence_key(r.object_ref)} == {a, b}
                and _evidence_key(r.subject_ref) != _evidence_key(r.object_ref)}
        return len(dirs) > 1

    def _dominant(self, speaking, asserted):
        """Claims that settle EVERY conflicting claim among the survivors.

        Returns (winners, used_relation_ids, unsettled_pairs).

        A winner must dominate every OTHER claim it disagrees with, not merely one of them.
        An earlier revision set `winner` from any single resolved pair and then discarded
        every other claim, so with A/B/C and one asserted `A CORRECTS B`, the untouched
        A-vs-C conflict silently vanished and the engine reported RESOLVED. A relation
        settles the pair it names. It says nothing about a third source.

        `unsettled_pairs` shapes the failure MESSAGE only. It must never gate the outcome:
        a losing candidate always leaves pairs unsettled, so treating a non-empty list as
        disqualifying would reject the legitimate two-source case this rule exists to
        permit. Winner-hood is already the complete test.
        """
        winners, used, unsettled = [], [], []
        for w in speaking:
            opposed = [c for c in speaking if c.claim != w.claim]
            rels, ok = [], True
            for c in opposed:
                who, rel = self._settles(w.evidence_id, c.evidence_id, asserted)
                if who == w.evidence_id:
                    rels.append(rel)
                else:
                    ok = False
                    unsettled.append((w.evidence_id, c.evidence_id))
            if ok:
                winners.append(w)
                used.extend(rels)
        return winners, used, unsettled

    @staticmethod
    def _reject_duplicate_claim_keys(claims: tuple[ClaimProposal, ...]) -> None:
        counts = Counter(c.evidence_id for c in claims)
        duplicates = sorted(k for k, n in counts.items() if n > 1)
        if duplicates:
            raise ValueError(
                "duplicate ClaimProposal.evidence_id values: " + ", ".join(duplicates))

    @staticmethod
    def _reject_unknown_refs(*, considered: tuple[str, ...],
                             claims: tuple[ClaimProposal, ...],
                             relations: tuple[AssertedRelation | ProposedRelation, ...],
                             roles: tuple[SourceRoleProposal, ...]) -> None:
        evidence_keys = set(considered)
        unknown_claims = sorted({c.evidence_id for c in claims} - evidence_keys)
        if unknown_claims:
            raise ValueError(
                "ClaimProposal.evidence_id not present in evidence: "
                + ", ".join(unknown_claims))

        unknown_roles = sorted({_evidence_key(sp.source_ref) for sp in roles} - evidence_keys)
        if unknown_roles:
            raise ValueError(
                "SourceRoleProposal.source_ref.evidence_id not present in evidence: "
                + ", ".join(unknown_roles))

        relation_refs = {
            key
            for r in relations
            for key in (_evidence_key(r.subject_ref), _evidence_key(r.object_ref))
        }
        unknown_relations = sorted(relation_refs - evidence_keys)
        if unknown_relations:
            raise ValueError(
                "relation evidence_id not present in evidence: "
                + ", ".join(unknown_relations))

    def adjudicate(self, *, question: Question, evidence: tuple[EvidenceRef, ...],
                   claims: tuple[ClaimProposal, ...],
                   source_role_proposals: tuple[SourceRoleProposal, ...] = (),
                   relations: tuple = (),
                   routing: RoutingProposal | None = None,
                   resolution_id: str = "R") -> Adjudication:
        considered = tuple(_evidence_key(e) for e in evidence)
        self._reject_duplicate_claim_keys(claims)

        roles: dict[str, SourceRole] = {}
        role_refs: list[str] = []
        for sp in source_role_proposals:
            _enum(sp.proposed_role, SourceRole, "SourceRoleProposal.proposed_role")
            roles[_evidence_key(sp.source_ref)] = sp.proposed_role
            role_refs.append(sp.id)

        # A relation may only settle a conflict if it is ASSERTED. The split is by TYPE at
        # runtime, not by an annotation, because an annotation is not enforcement.
        asserted = tuple(r for r in relations if isinstance(r, AssertedRelation))
        refused = tuple(r.id for r in relations if isinstance(r, ProposedRelation))
        unknown_kind = [r for r in relations
                        if not isinstance(r, (AssertedRelation, ProposedRelation))]
        if unknown_kind:
            raise TypeError(
                "relations must be AssertedRelation or ProposedRelation; refusing to "
                "duck-type an object into settling authority")
        self._reject_unknown_refs(
            considered=considered,
            claims=claims,
            relations=asserted + tuple(r for r in relations if isinstance(r, ProposedRelation)),
            roles=source_role_proposals,
        )

        frame, caller, routing_ref = self._route(question, routing)
        authority = self._authoritative(frame, evidence, roles)

        by_evidence = {c.evidence_id: c for c in claims}
        # B1: a source offering no claim is SILENT. Silence is recorded and then plays no
        # further part - it never becomes a negative claim, and never creates a relation.
        silent = tuple(s for s in authority if s not in by_evidence)
        speaking = [by_evidence[s] for s in authority if s in by_evidence]

        claim_refs = tuple(c.id for c in speaking)
        notes: list[str] = []

        def out(outcome, *, conclusion=None, reason=None, conflict=False,
                survivors=None, asserted_refs=()):
            res = Resolution(
                id=resolution_id, question_id=question.id, outcome=outcome,
                resolution_method=ResolutionMethod.DETERMINISTIC_RULE,
                conclusion=conclusion, unresolved_reason=reason,
                evidence_refs=evidence,
                asserted_relation_refs=tuple(dict.fromkeys(asserted_refs)),
                claim_proposal_refs=claim_refs,
                source_role_proposal_refs=tuple(role_refs),
                routing_proposal_ref=routing_ref)
            return Adjudication(res, frame, caller,
                                survivors if survivors is not None else authority,
                                considered, silent, conflict, refused, tuple(notes))

        if not speaking:
            return out(Outcome.UNRESOLVED,
                       reason=("no authoritative source offers a claim on this question"
                               if authority else
                               "no evidence carries authority for the selected frame"))

        conflict = len({c.claim for c in speaking}) > 1
        if conflict:
            # B2 / B7: only an ASSERTED relation settles it. Order and recency cannot.
            winners, used, unsettled = self._dominant(speaking, asserted)
            distinct_wins = {w.claim for w in winners}

            if not winners:
                # Partial resolution is NOT resolution. Distinguished from "nothing settled
                # anything" because the two states need different remedies: one wants a
                # further assertion, the other wants any assertion at all.
                opposed_pairs = [(a, b) for i, a in enumerate(speaking)
                                 for b in speaking[i + 1:] if a.claim != b.claim]
                if any(self._contradicted(a.evidence_id, b.evidence_id, asserted)
                       for a, b in opposed_pairs):
                    return out(Outcome.UNRESOLVED, conflict=True, reason=(
                        "asserted relations point in both directions for the same pair; "
                        "the relation set is itself contradictory and cannot settle the "
                        "disagreement"))
                settled_any = any(
                    self._settles(a.evidence_id, b.evidence_id, asserted)[0] is not None
                    for a, b in opposed_pairs)
                if settled_any:
                    pairs = ", ".join(f"{a} vs {b}" for a, b in unsettled[:3])
                    return out(Outcome.UNRESOLVED, conflict=True, reason=(
                        "an asserted relation settles part of the disagreement but leaves "
                        f"conflicting authoritative claims unsettled ({pairs})"))
                # B3: a genuine conflict with nothing to settle it is UNRESOLVED, and that
                # is a correct answer rather than a failure to produce one.
                return out(Outcome.UNRESOLVED, conflict=True, reason=(
                    "authoritative sources disagree and no asserted relation resolves the "
                    "disagreement"))
            if len(distinct_wins) > 1:
                return out(Outcome.UNRESOLVED, conflict=True, reason=(
                    "asserted relations name more than one dominant claim; the relation "
                    "set is itself contradictory and cannot settle the disagreement"))

            notes.append("asserted relations settle every conflicting claim in favour of "
                         + sorted(distinct_wins)[0])
            survivors = tuple(w.evidence_id for w in winners)
            return out(Outcome.RESOLVED, conclusion=winners[0].claim, conflict=True,
                       survivors=survivors, asserted_refs=used)

        # B4: a single authoritative claim resolves. Declining here would be false
        # abstention, which is a failure and not a safe default.
        return out(Outcome.RESOLVED, conclusion=speaking[0].claim,
                   survivors=tuple(c.evidence_id for c in speaking))
