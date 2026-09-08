"""Invariant coverage enforcement (ST5 / G-S9).

"Retiring a case recomputes coverage immediately; below minimum => SUITE INCOMPLETE" is
mechanically checkable, which makes it a structural invariant needing a gate rather than a
construction convention. Without this, the coverage rule is a policy reminder — the exact
category this design keeps converting into enforcement.

Two distinct failure states, deliberately not merged:

    SUITE INCOMPLETE   insufficient EVIDENCE of correctness (behavioural coverage lost)
    BUILD FAILURE      the implementation VIOLATES the architecture (structural gate)

Two coverage paths exist, and they are NOT interchangeable:

    CONTRACT COVERAGE  deterministic synthetic fixtures whose expected resolution,
                       evidence selection, frame and abstention behaviour are known BY
                       CONSTRUCTION. This is the v0 RELEASE GATE.
    GOLD COVERAGE      independently adjudicated real-corpus cases. Strictly stronger
                       evidence, OPTIONAL at v0, retained and unmodified.

Gold coverage counts adjudicated gold only; a specified candidate contributes nothing.
Contract coverage counts collected test fixtures only; a label contributes nothing.

Neither is derived from caller-supplied strings. Gold coverage comes from real seed ids in
the database view; contract coverage comes from the node ids pytest actually collected. A
fixture that is deleted or renamed out of the pattern stops counting the moment it stops
running, which is the only property that makes a coverage number worth reading.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

MIN_CASES = 2
MIN_FAMILIES = 2

BEHAVIOURAL_INVARIANTS = (
    "B1_NO_RELATION_BY_ABSENCE",
    "B2_ORDER_IS_NOT_AUTHORITY",
    "B3_UNRESOLVED_IS_VALID",
    "B4_FALSE_ABSTENTION_IS_FAILURE",
    "B5_ROUTING_IS_INFERENTIAL",
    "B6_CLOSED_FRAME_SPACE",
    "B7_NO_RECENCY_AS_AUTHORITY",
    "B8_QUESTION_RELATIVE_AUTHORITY",
)

_BY_NUMBER = {inv.split("_")[0]: inv for inv in BEHAVIOURAL_INVARIANTS}

STRUCTURAL_INVARIANTS = (
    "ST1_EPISTEMIC_CLASS_IS_IMMUTABLE",
    "ST2_MODEL_CONSENSUS_IS_NOT_PROMOTION",
    "ST3_GOLD_IS_HUMAN_ADJUDICATED",
    "ST4_GOLD_INDEPENDENT_OF_SYSTEM",
    "ST5_EVALUATION_COVERAGE_IS_EXPLICIT",
)


@dataclass(frozen=True, slots=True)
class CaseCoverage:
    """One adjudicated gold case and what it defends.

    `case_id` MUST be a real seed id. Build these with `coverage_from_gold_rows` from the
    database `gold_coverage` view rather than by hand: counting caller-made labels would
    let two strings masquerade as two independently adjudicated cases, which is the exact
    illusion the invariant matrix exists to prevent.
    """

    case_id: str
    family: str
    defends: tuple[str, ...]


def coverage_from_gold_rows(rows) -> list[CaseCoverage]:
    """Build coverage from `gold_coverage` rows: (seed_id, family, invariant).

    Keyed by SEED, so multiple adjudications or gold artifacts for one seed still count as
    ONE case. Case identity is derived through evaluation_gold -> blind_adjudication ->
    adjudication_packet -> gold_case_seed and cannot be asserted by a caller.
    """
    by_seed: dict[str, tuple[str, set[str]]] = {}
    for seed_id, family, invariant in rows:
        fam, invs = by_seed.setdefault(seed_id, (family, set()))
        if fam != family:
            raise ValueError(f"seed {seed_id} reported under two families: {fam}, {family}")
        invs.add(invariant)
    return [CaseCoverage(seed, fam, tuple(sorted(invs)))
            for seed, (fam, invs) in sorted(by_seed.items())]


@dataclass(frozen=True, slots=True)
class CoverageReport:
    complete: bool
    per_invariant: dict[str, tuple[int, int]]   # invariant -> (cases, families)
    deficient: tuple[str, ...]
    lines: tuple[str, ...]

    def render(self) -> str:
        return "\n".join(self.lines)


def compute_coverage(cases: list[CaseCoverage]) -> CoverageReport:
    by_inv_cases: dict[str, set[str]] = defaultdict(set)
    by_inv_fams: dict[str, set[str]] = defaultdict(set)
    for c in cases:
        for inv in c.defends:
            by_inv_cases[inv].add(c.case_id)
            by_inv_fams[inv].add(c.family)

    per, deficient, lines = {}, [], []
    for inv in BEHAVIOURAL_INVARIANTS:
        n_cases = len(by_inv_cases.get(inv, ()))
        n_fams = len(by_inv_fams.get(inv, ()))
        per[inv] = (n_cases, n_fams)
        ok = n_cases >= MIN_CASES and n_fams >= MIN_FAMILIES
        if not ok:
            deficient.append(inv)
        lines.append(
            f"  [{'OK ' if ok else 'LOW'}] {inv:<34} {n_cases} case(s) / {n_fams} family(ies)"
            + ("" if ok else f"  need >={MIN_CASES}/{MIN_FAMILIES}"))

    complete = not deficient
    lines.append("")
    lines.append("  SUITE COMPLETE" if complete else
                 f"  SUITE INCOMPLETE - {len(deficient)} invariant(s) below minimum; "
                 "Historian acceptance cannot be claimed")
    return CoverageReport(complete, per, tuple(deficient), tuple(lines))


# --------------------------------------------------------------------------------------
# Contract coverage - the v0 release gate
# --------------------------------------------------------------------------------------

MIN_CONTRACT_FIXTURES = 2

_FIXTURE_RE = re.compile(r"::(test_(B[1-8])_[A-Za-z0-9_]+)$")


def contract_coverage_from_node_ids(node_ids) -> dict[str, tuple[str, ...]]:
    """Map B1..B8 -> the contract fixtures that actually defend it.

    Takes the node ids pytest COLLECTED, not a hand-written table. The invariant is read
    from the fixture name, so a fixture cannot claim coverage it does not run, and renaming
    one out of the `test_B<n>_` pattern removes its coverage rather than silently keeping
    it. This is the same rule as `coverage_from_gold_rows`: derive, never accept.
    """
    found: dict[str, set[str]] = defaultdict(set)
    for nid in node_ids:
        m = _FIXTURE_RE.search(nid)
        if m:
            found[_BY_NUMBER[m.group(2)]].add(m.group(1))
    return {inv: tuple(sorted(found.get(inv, ()))) for inv in BEHAVIOURAL_INVARIANTS}


def contract_report(by_invariant: dict[str, tuple[str, ...]]) -> CoverageReport:
    per, deficient, lines = {}, [], []
    for inv in BEHAVIOURAL_INVARIANTS:
        fixtures = by_invariant.get(inv, ())
        n = len(fixtures)
        per[inv] = (n, n)
        ok = n >= MIN_CONTRACT_FIXTURES
        if not ok:
            deficient.append(inv)
        lines.append(f"  [{'OK ' if ok else 'LOW'}] {inv:<34} {n} contract fixture(s)"
                     + ("" if ok else f"  need >={MIN_CONTRACT_FIXTURES}"))
    complete = not deficient
    lines.append("")
    lines.append("  CONTRACT COMPLETE - v0 release gate satisfied" if complete else
                 f"  CONTRACT INCOMPLETE - {len(deficient)} invariant(s) below minimum; "
                 "v0 release gate NOT satisfied")
    return CoverageReport(complete, per, tuple(deficient), tuple(lines))


def require_contract_complete(node_ids) -> CoverageReport:
    """The v0 release gate. Raises `SuiteIncomplete` if any B-invariant is under-covered.

    Passing this establishes that the adjudication RULES behave as specified on evidence
    built to have a known answer. It does NOT establish that the Historian survives messy
    real evidence - that is what gold coverage would add, and it is not claimed here.
    """
    report = contract_report(contract_coverage_from_node_ids(node_ids))
    if not report.complete:
        raise SuiteIncomplete(
            f"contract fixtures below minimum: {', '.join(report.deficient)}")
    return report


class SuiteIncomplete(RuntimeError):
    """Behavioural coverage lost. NOT a build failure — insufficient evidence of
    correctness, which is a different thing from an architectural violation."""


def require_complete(cases: list[CaseCoverage]) -> CoverageReport:
    """Human-gold coverage gate. RETAINED and unchanged, but NOT a v0 release dependency.

    Kept live so that if independent adjudication ever happens, the machinery to consume it
    is already built and already tested. Calling it with no gold still raises - that is
    correct, because it answers "is there adjudicated gold coverage", and at v0 the honest
    answer is no.
    """
    report = compute_coverage(cases)
    if not report.complete:
        raise SuiteIncomplete(
            f"invariants below minimum coverage: {', '.join(report.deficient)}")
    return report
