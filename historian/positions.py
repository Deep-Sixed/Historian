"""Deterministic ordering over source positions. No model involved.

These helpers establish ORDER. They establish nothing about PRECEDENCE. `precedes(A, B)`
means B occurs after A in the same version of the same source — it does not mean B
supersedes, corrects or augments A. Any such relation still requires explicit textual
evidence, a typed link, or the pair stays unresolved.

This is invariant B2 (ORDER_IS_NOT_AUTHORITY) made mechanical: the only ordering primitive
available cannot express authority, so authority cannot be derived from it by accident.
"""

from __future__ import annotations

from .types import EvidenceRef, SourcePosition


def _pos(x: EvidenceRef | SourcePosition) -> SourcePosition:
    return x.position if isinstance(x, EvidenceRef) else x


def same_source(a: EvidenceRef | SourcePosition, b: EvidenceRef | SourcePosition) -> bool:
    """True only when both cite the SAME source AND the same immutable version.

    Two positions in different versions of one document are not comparable: line 800 may
    denote different text after an edit. We have a live instance of exactly that.
    """
    pa, pb = _pos(a), _pos(b)
    return (pa.source_id == pb.source_id
            and pa.source_version_hash == pb.source_version_hash)


def precedes(a: EvidenceRef | SourcePosition, b: EvidenceRef | SourcePosition) -> bool:
    """True when a ends strictly before b begins, within one source version.

    Returns False for positions in different sources or different versions — cross-source
    ordering is a chronology question about the sources themselves, not a position
    question, and must not be silently answered here.
    """
    if not same_source(a, b):
        return False
    pa, pb = _pos(a), _pos(b)
    return pa.end < pb.start


def overlaps(a: EvidenceRef | SourcePosition, b: EvidenceRef | SourcePosition) -> bool:
    if not same_source(a, b):
        return False
    pa, pb = _pos(a), _pos(b)
    return pa.start <= pb.end and pb.start <= pa.end
