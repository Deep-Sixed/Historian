#!/usr/bin/env python3
"""Build the blind-ready behavioural case queue.

Runs the REAL pipeline: model-proposed candidate -> verifier reads the actual corpus ->
EvidenceRef -> finalized seed -> finalized packet. Nothing here produces gold, and nothing
here determines an answer.

SEED CONSTRUCTION IS SHALLOW BY DESIGN. Evidence spans are selected mechanically - the
first substantive block after the frontmatter - and no document is read closely enough to
work out what it establishes. If the person assembling a case reasons out the verdict, the
case is contaminated exactly as HIST-C3 was, and no amount of later blindness repairs it.

  ./build_queue.py --plan     # show what would be built
  ./build_queue.py --apply
"""
import argparse, hashlib, json, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import psycopg
from historian.capability import EvidenceVerificationError, EvidenceVerifier
from historian.sources import RagV1SourceReader, SourceRegistry

HERE = Path(__file__).resolve().parent
CORPUS = Path("/mnt/jarvis-data/projects/chatgpt-export/corpus")
SECRET = Path("/mnt/jarvis-data/projects/EVECOR/bin/jarvis-secret")
VAULT = {"historian_extractor": "HISTORIAN_EXTRACTOR",
         "historian_evidence_verifier": "HISTORIAN_EVIDENCE_VERIFIER",
         "historian_case_designer": "HISTORIAN_CASE_DESIGNER",
         "historian_packet_builder": "HISTORIAN_PACKET_BUILDER",
         "historian_owner": "HISTORIAN_OWNER"}
_cache = {}


def secret(name):
    if name not in _cache:
        _cache[name] = subprocess.run([str(SECRET), "get", name], capture_output=True,
                                      text=True, timeout=120).stdout.strip()
    return _cache[name]


def conn(role):
    return psycopg.connect(f"host=127.0.0.1 port=5444 dbname=evecor_historian "
                           f"user={role} password={secret(VAULT[role])}", autocommit=True)


def span_for(doc: str) -> tuple[int, int]:
    """THE WHOLE DOCUMENT. There is no span selection.

    v1 took the first 25 lines after the frontmatter. A blind pilot rejected 11 of 18
    packets, and the rationales were explicit: "cuts off mid-sentence", "stops before
    showing any finalized configuration". In a conversation transcript the opening block
    is the user ASKING; the decision, correction or conclusion comes later. Any question
    about an outcome therefore failed structurally.

    Widening the window would not have fixed it, because choosing a window at all is a
    judgement about where answers live - and for B2 (order is not authority) the material
    may sit anywhere. Selecting whole documents small enough to present entire removes the
    judgement instead of enlarging it.

    The v1 selection also skewed large: those 23 documents had a median of 29KB against a
    corpus median of 6KB, because topic-first picking pulls the biggest conversations.
    """
    lines = (CORPUS / f"{doc}.md").read_text(errors="replace").splitlines()
    return 1, len(lines)


class Candidates:
    def __init__(self, c): self._c = c
    def get_candidate(self, cid):
        r = self._c.execute(
            "SELECT id, proposed_source_system::text, proposed_source_id, "
            "proposed_version_hash, proposed_line_start, proposed_line_end, proposed_quote "
            "FROM evidence_candidate WHERE id=%s", (cid,)).fetchone()
        if r is None:
            raise KeyError(cid)
        o = type("C", (), {})()
        (o.id, o.proposed_source_system, o.proposed_source_id, o.proposed_version_hash,
         o.proposed_line_start, o.proposed_line_end, o.proposed_quote) = r
        return o


class Evidence:
    def __init__(self, c): self._c = c
    def put_evidence(self, r):
        self._c.execute("""INSERT INTO evidence_ref(id,source_id,source_system,
            source_version_hash,line_start,line_end,passage_hash,quote,
            derived_from_candidate_id,verified_by)
            VALUES (%(id)s,%(source_id)s,%(source_system)s,%(source_version_hash)s,
            %(line_start)s,%(line_end)s,%(passage_hash)s,%(quote)s,
            %(derived_from_candidate_id)s,%(verified_by)s)""", r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    cases = json.loads((HERE / "case-queue.json").read_text())
    reader = RagV1SourceReader(CORPUS)
    registry = SourceRegistry(reader)

    docs = sorted({d for c in cases for d in c["evidence"]})
    print(f"  {len(cases)} cases, {len(docs)} distinct evidence documents")
    if not a.apply:
        for c in cases:
            print(f"    {c['id']}  {c['family']:26} {len(c['evidence'])} doc(s)  "
                  f"-> {', '.join(i.split('_')[0] for i in c['defends'])}")
        print("\n  --plan: nothing written")
        return 0

    # 1. candidates (model role) -> 2. verified evidence (verifier role)
    ev_id = {}
    with conn("historian_extractor") as x, conn("historian_evidence_verifier") as v:
        verifier = EvidenceVerifier(Candidates(v), Evidence(v), registry, "queue-builder")
        for doc in docs:
            version = reader.version_of(doc)
            if not version:
                print(f"    SKIP {doc}: not in corpus"); continue
            s, e = span_for(doc)
            text = reader.read_lines(doc, version, s, e)
            quote = next((l for l in text.splitlines() if l.strip()), "")[:200]
            cid, eid = f"cand-{doc}", f"ev-{doc}"
            x.execute("""INSERT INTO evidence_candidate(id,proposed_source_system,
                proposed_source_id,proposed_version_hash,proposed_line_start,
                proposed_line_end,proposed_quote,extractor_id,extraction_run_id)
                VALUES (%s,'RAG_V1',%s,%s,%s,%s,%s,'queue-builder','q1')
                ON CONFLICT DO NOTHING""", (cid, doc, version, s, e, quote))
            if not v.execute("SELECT 1 FROM evidence_ref WHERE id=%s", (eid,)).fetchone():
                try:
                    verifier.verify(cid, eid)
                except EvidenceVerificationError as err:
                    print(f"    SKIP {doc}: {err}"); continue
            ev_id[doc] = eid
    print(f"  verified evidence: {len(ev_id)}/{len(docs)}")

    built = 0
    with conn("historian_case_designer") as d, conn("historian_packet_builder") as b:
        for c in cases:
            sid, pid = f"seed-{c['id']}", f"pkt-{c['id']}"
            if d.execute("SELECT 1 FROM seed_finalization WHERE seed_id=%s",
                         (sid,)).fetchone():
                continue
            evs = [ev_id[x] for x in c["evidence"] if x in ev_id]
            if not evs:
                print(f"    SKIP {c['id']}: no verified evidence"); continue
            qid = f"q-{c['id']}"
            with conn("historian_owner") as o:
                o.execute("INSERT INTO question(id,text) VALUES (%s,%s) "
                          "ON CONFLICT DO NOTHING", (qid, c["question"]))
            d.execute("""INSERT INTO gold_case_seed(id,question_id,question_text,family)
                VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                      (sid, qid, c["question"], c["family"]))
            for i, e in enumerate(evs):
                d.execute("INSERT INTO gold_case_seed_evidence(seed_id,evidence_id,ordinal)"
                          " VALUES (%s,%s,%s) ON CONFLICT DO NOTHING", (sid, e, i))
            for inv in c["defends"]:
                d.execute("INSERT INTO gold_case_seed_invariant(seed_id,invariant) "
                          "VALUES (%s,%s) ON CONFLICT DO NOTHING", (sid, inv))
            d.execute("SELECT finalize_seed(%s)", (sid,))

            b.execute("INSERT INTO adjudication_packet(id,seed_id,question_text) "
                      "VALUES (%s,%s,%s)", (pid, sid, c["question"]))
            for i, e in enumerate(evs):
                r = b.execute("SELECT source_id,source_version_hash,line_start,line_end "
                              "FROM evidence_ref WHERE id=%s", (e,)).fetchone()
                snap = reader.read_lines(*r)
                b.execute("""INSERT INTO adjudication_packet_evidence(packet_id,ordinal,
                    seed_id,seed_evidence_id,source_id,source_version_hash,line_start,
                    line_end,snapshot_text) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                          (pid, i, sid, e, r[0], r[1], r[2], r[3], snap))
            b.execute("SELECT finalize_packet(%s)", (pid,))
            built += 1
    print(f"  seeds finalized and packets rendered: {built}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
