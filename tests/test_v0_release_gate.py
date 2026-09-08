"""The v0 release gate, enforced against what pytest actually collects.

Historian v0 accepts on the DETERMINISTIC BEHAVIOURAL CONTRACT, not on independently
adjudicated human gold. That substitution is a real weakening and is recorded as one: the
contract proves the adjudication rules are right on evidence built to have a known answer.
It does not prove the Historian survives messy real evidence.

The gate is derived, not declared. It runs pytest's own collector and reads the fixtures
that exist right now, so deleting or renaming a contract fixture lowers coverage and fails
this test.
"""

import subprocess
import sys
from pathlib import Path

import pytest

from historian.coverage import (
    BEHAVIOURAL_INVARIANTS, MIN_CONTRACT_FIXTURES, SuiteIncomplete,
    contract_coverage_from_node_ids, require_complete, require_contract_complete,
)

HERE = Path(__file__).resolve().parent
CONTRACT = HERE / "test_behavioural_contract.py"


def _collected() -> list[str]:
    r = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q",
                        str(CONTRACT)], capture_output=True, text=True, timeout=300,
                       cwd=HERE.parent)
    assert r.returncode == 0, f"contract suite failed to collect:\n{r.stdout[-1000:]}"
    return [ln.strip() for ln in r.stdout.splitlines() if "::" in ln]


def test_every_behavioural_invariant_has_contract_fixtures():
    """Asserts against a LITERAL 2, not against `MIN_CONTRACT_FIXTURES`.

    Found by mutation test: reading the threshold from the same constant the gate reads
    meant lowering that constant to 1 weakened the gate and passed every test. A gate whose
    own strength is a free variable is not a gate. The literal is duplicated on purpose.
    """
    report = require_contract_complete(_collected())
    assert report.complete
    assert MIN_CONTRACT_FIXTURES == 2, "the v0 contract minimum was weakened"
    for inv in BEHAVIOURAL_INVARIANTS:
        assert report.per_invariant[inv][0] >= 2, f"{inv} has too few contract fixtures"


def test_gate_fails_when_an_invariant_loses_its_fixtures():
    """A gate that cannot fail is decoration. Drop B7's fixtures and it must refuse."""
    surviving = [n for n in _collected() if "test_B7_" not in n]
    with pytest.raises(SuiteIncomplete, match="B7_NO_RECENCY_AS_AUTHORITY"):
        require_contract_complete(surviving)


def test_coverage_is_not_credulous_about_names():
    """A fixture that does not run cannot lend coverage, whatever it is called."""
    cov = contract_coverage_from_node_ids([
        "tests/test_fake.py::test_B1_this_was_never_collected_by_the_real_run",
        "tests/test_fake.py::test_covers_B1_B2_B3_B4_B5_B6_B7_B8_honestly",
        "tests/test_fake.py::test_B9_not_an_invariant",
    ])
    assert cov["B1_NO_RELATION_BY_ABSENCE"] == (
        "test_B1_this_was_never_collected_by_the_real_run",)
    assert cov["B2_ORDER_IS_NOT_AUTHORITY"] == ()
    assert all(inv.startswith("B") for inv in cov)


def test_human_gold_path_is_retained_and_still_honest():
    """v0 does not require gold. It also must not PRETEND to have it."""
    with pytest.raises(SuiteIncomplete):
        require_complete([])
