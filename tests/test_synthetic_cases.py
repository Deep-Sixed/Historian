"""Public synthetic replacement for source readability and unrouted queue regression.

Runs without external data in normal CI. It does not establish real-corpus readiness
or independent gold; B1-B8 outcomes are tested by the behavioural contract suite.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from historian.adjudicator import Adjudicator, AuthorityPolicy
from historian.sources import RagV1SourceReader
from historian.types import (
    ClaimProposal, CoordinateSystem, EvidenceRef, FrameTaxonomy, Question, SourcePosition,
    SourceRole, SourceRoleProposal, SourceSystem,
)

HERE = Path(__file__).resolve().parent.parent
CORPUS = HERE / "cases/synthetic"
CASES = json.loads((HERE / "cases/case-queue.json").read_text())
TAX = FrameTaxonomy("frames-v1", ("CURRENT_OPERATIONAL_STATE", "UPSTREAM_PRODUCT_STATE"))
POLICY = AuthorityPolicy("frames-v1", {
    "CURRENT_OPERATIONAL_STATE": (SourceRole.LOCAL_OPERATIONAL_DECISION,),
    "UPSTREAM_PRODUCT_STATE": (SourceRole.UPSTREAM_VENDOR_MATERIAL,),
})


@pytest.fixture(scope="module")
def reader():
    return RagV1SourceReader(CORPUS)


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_evidence_still_verifies_against_source(case, reader):
    """The whole point of verified evidence: it stays checkable as the corpus ages."""
    for doc in case["evidence"]:
        version = reader.version_of(doc)
        assert version, f"{case['id']}: {doc} no longer resolvable in the corpus"
        assert reader.read_lines(doc, version, 1, 1), f"{case['id']}: {doc} unreadable"


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_adjudicator_runs_over_synthetic_evidence(case, reader):
    """An unrouted case must produce a well-formed decision with an unknown frame."""
    eng = Adjudicator(TAX, POLICY)
    qid = f"q-{case['id']}"
    evs, claims, roles = [], [], []
    for i, doc in enumerate(case["evidence"]):
        v = reader.version_of(doc)
        p = SourcePosition(doc, v, CoordinateSystem.LINE, 1, 2)
        e = EvidenceRef(doc, SourceSystem.RAG_V1, v, p, f"h{i}", "anchor",
                        evidence_id=f"{case['id']}:{i}:{doc}")
        evs.append(e)
        claims.append(ClaimProposal(f"cp-{case['id']}-{i}", e.key, f"claim-from-{doc}",
                                    "canary", qid))
        roles.append(SourceRoleProposal(f"srp-{case['id']}-{i}", e, SourceRole.UNKNOWN,
                                        (e,), "canary"))
    a = eng.adjudicate(question=Question(qid, case["question"]),
                       evidence=tuple(evs), claims=tuple(claims),
                       source_role_proposals=tuple(roles),
                       resolution_id=f"canary-{case['id']}")
    assert a.resolution.outcome is not None
    assert a.frame == FrameTaxonomy.UNKNOWN      # no route proposed, so it must degrade
    assert a.resolution.question_id == f"q-{case['id']}"


def test_queue_shape_is_unchanged(reader):
    """Guards the queue against silent drift: counts that documentation depends on."""
    assert len(CASES) == 16
    assert len({d for c in CASES for d in c["evidence"]}) == 4
    assert sum(len(c["defends"]) for c in CASES) == 16
    assert len({c["family"] for c in CASES}) == 2


def test_case_invariant_audit_still_passes(reader):
    """The v3 audit is a gate, not a one-off report."""
    r = subprocess.run([sys.executable, str(HERE / "cases/audit_queue.py")],
                       capture_output=True, text=True, timeout=300, cwd=HERE)
    assert r.returncode == 0, f"case-to-invariant audit regressed:\n{r.stdout[-1500:]}\n{r.stderr[-1500:]}"
    assert "ALL INVARIANTS MEET THE NECESSARY CONDITION" in r.stdout


def test_case_audit_rejects_missing_invariant_and_family(tmp_path):
    """Deleting coverage must fail even if every surviving assignment is valid."""
    for surviving in (
        [c for c in CASES if not c["defends"][0].startswith("B8_")],
        [c for c in CASES if c["family"] == "observatory"],
    ):
        queue = tmp_path / "queue.json"
        queue.write_text(json.dumps(surviving))
        run = subprocess.run([sys.executable, str(HERE / "cases/audit_queue.py"),
                              "--queue", str(queue)], capture_output=True, text=True)
        assert run.returncode == 1
        assert "SOME INVARIANTS BELOW MINIMUM" in run.stdout
