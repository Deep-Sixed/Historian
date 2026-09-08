"""HD-01..HD-20 real-corpus canary. NON-BLOCKING by design.

These cases use messy real evidence whose answers nobody has established, so they cannot
grade a conclusion. What they CAN prove, automatically and repeatedly, is that the pipeline
still processes real corpus material end to end: evidence still verifies against source
bytes, seeds and packets still finalize, and the adjudicator runs over real evidence without
error.

They are marked `canary` and excluded from the release gate. A failure here is a signal to
investigate, not a reason to block - the release gate is the deterministic behavioural
contract, whose expected results are known by construction.
"""

import json
import subprocess
from pathlib import Path

import pytest

from historian.adjudicator import Adjudicator, AuthorityPolicy
from historian.sources import RagV1SourceReader
from historian.types import (
    ClaimProposal, CoordinateSystem, EvidenceRef, FrameTaxonomy, Question, SourcePosition,
    SourceRole, SourceRoleProposal, SourceSystem,
)

pytestmark = pytest.mark.canary

HERE = Path(__file__).resolve().parent.parent
CORPUS = Path("/mnt/jarvis-data/projects/chatgpt-export/corpus")
CASES = json.loads((HERE / "cases/case-queue.json").read_text())
TAX = FrameTaxonomy("frames-v1", ("CURRENT_OPERATIONAL_STATE", "UPSTREAM_PRODUCT_STATE"))
POLICY = AuthorityPolicy("frames-v1", {
    "CURRENT_OPERATIONAL_STATE": (SourceRole.LOCAL_OPERATIONAL_DECISION,),
    "UPSTREAM_PRODUCT_STATE": (SourceRole.UPSTREAM_VENDOR_MATERIAL,),
})


@pytest.fixture(scope="module")
def reader():
    if not CORPUS.is_dir():
        pytest.skip("RAG v1 corpus unavailable")
    return RagV1SourceReader(CORPUS)


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_evidence_still_verifies_against_source(case, reader):
    """The whole point of verified evidence: it stays checkable as the corpus ages."""
    for doc in case["evidence"]:
        version = reader.version_of(doc)
        assert version, f"{case['id']}: {doc} no longer resolvable in the corpus"
        assert reader.read_lines(doc, version, 1, 1), f"{case['id']}: {doc} unreadable"


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_adjudicator_runs_over_real_evidence(case, reader):
    """Runs the engine on real corpus evidence. Asserts it produces a well-formed decision
    - NOT that the decision is correct, which nobody has established."""
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
    assert len(CASES) == 20
    assert len({d for c in CASES for d in c["evidence"]}) == 24
    assert sum(len(c["defends"]) for c in CASES) == 29
    assert len({c["family"] for c in CASES}) == 14


def test_case_invariant_audit_still_passes(reader):
    """The v3 audit is a gate, not a one-off report."""
    r = subprocess.run(["python3", str(HERE / "cases/AUDIT-V3.py")],
                       capture_output=True, text=True, timeout=300, cwd=HERE)
    assert r.returncode == 0, f"case-to-invariant audit regressed:\n{r.stdout[-1500:]}"
    assert "ALL INVARIANTS MEET THE NECESSARY CONDITION" in r.stdout
