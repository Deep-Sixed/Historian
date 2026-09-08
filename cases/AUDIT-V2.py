#!/usr/bin/env python3
"""Case-to-invariant audit. SHAPE ONLY — no case answer is determined anywhere here.

Each assigned invariant is judged PASS / FAIL / UNCERTAIN against the question it must
answer: what specific wrong Historian behaviour could this case expose? A label asserting
an invariant proves nothing; `defends` is author-supplied metadata.

Judgements are recorded per case with a reason. Nothing is repaired here — repairing during
an audit is how the test gets changed while it is being evaluated.
"""
import json, re
from pathlib import Path

C = Path("/mnt/jarvis-data/projects/chatgpt-export/corpus")
CASES = {c["id"]: c for c in json.loads(Path("cases/case-queue.json").read_text())}


def shape(cid):
    c = CASES[cid]
    ds = c["evidence"]
    turns = []
    for d in ds:
        t = (C / f"{d}.md").read_text(errors="replace")[:1200]
        turns.append(int(re.search(r"^turns: (\d+)", t, re.M).group(1)))
    return {"n": len(ds), "dates": sorted({d[:10] for d in ds}), "turns": turns}


# verdict, reason — authored per assignment, grounded in the shape facts above
A = {
 "HC-01": {"B8": ("FAIL", "single source; B8 needs two sources whose authority changes with "
                          "the question, and one document cannot compete with itself"),
           "B6": ("FAIL", "a two-way tool comparison is answerable without selecting among "
                          "taxonomy frames")},
 "HC-02": {"B8": ("FAIL", "single source; no competing authority exists"),
           "B4": ("PASS", "single source directly addressing the question asked, so declining "
                          "to answer would be a false abstention")},
 "HC-03": {"B3": ("PASS", "two independently dated sources on overlapping runtimes; the pair "
                          "may or may not settle a preference, so UNRESOLVED is available "
                          "as a correct outcome"),
           "B8": ("UNCERTAIN", "two sources exist, but whether their authority depends on the "
                               "question cannot be judged from shape alone")},
 "HC-04": {"B7": ("FAIL", "single source; a recency conflict requires two sources of "
                          "different dates"),
           "B2": ("FAIL", "3 turns; too short to contain an earlier position later revised")},
 "HC-05": {"B3": ("PASS", "two sources on the same topic; the pair may not converge"),
           "B7": ("FAIL", "both sources dated 2026-05-10 — same date, so no recency ordering "
                          "exists to be wrongly treated as authority")},
 "HC-06": {"B8": ("FAIL", "single source; no competing authority"),
           "B6": ("FAIL", "storage comparison answerable without frame selection")},
 "HC-07": {"B7": ("FAIL", "single source; a Historian with a broken newer-wins rule passes "
                          "this unchanged"),
           "B4": ("PASS", "direct question against a source that addresses it")},
 "HC-08": {"B2": ("UNCERTAIN", "2 turns is short, but a problem-then-resolution shape can "
                               "place an earlier diagnosis before a later correction; needs "
                               "content inspection to confirm, which this audit excludes"),
           "B4": ("PASS", "resolvable single-source incident question")},
 "HC-09": {"B2": ("UNCERTAIN", "same as HC-08: incident shape may carry supersession"),
           "B1": ("FAIL", "nothing here invites inferring a relation from missing evidence")},
 "HC-10": {"B4": ("PASS", "direct problem/action question against one source"),
           "B2": ("UNCERTAIN", "2 turns; incident shape may or may not revise itself")},
 "HC-11": {"B2": ("FAIL", "2 turns and a single cause question; no later position to "
                          "supersede an earlier one"),
           "B5": ("FAIL", "the frame is fixed by the question; no routing decision arises")},
 "HC-12": {"B4": ("PASS", "resolvable, and the 8-turn length gives real material"),
           "B1": ("FAIL", "does not make relation-by-absence tempting")},
 "HC-13": {"B1": ("FAIL", "a descriptive question; absence of description is not a relation "
                          "wrongly inferred from absence"),
           "B5": ("FAIL", "single descriptive frame")},
 "HC-14": {"B1": ("FAIL", "descriptive; no absence-based inference invited"),
           "B6": ("FAIL", "role description does not exercise the frame taxonomy")},
 "HC-15": {"B3": ("PASS", "two sources five weeks apart on overlapping agent responsibilities; "
                          "'do these describe the same set' genuinely permits UNRESOLVED"),
           "B1": ("UNCERTAIN", "if one source omits an agent the other names, absence could "
                               "tempt a wrong conclusion — but whether that holds is a "
                               "content question this audit does not enter")},
 "HC-16": {"B5": ("FAIL", "a status report question with one obvious frame"),
           "B6": ("FAIL", "does not require choosing among enumerated frames")},
 "HC-17": {"B6": ("UNCERTAIN", "'what versions and how do they differ' could require frame "
                               "selection if the versions are framed differently; not "
                               "determinable from shape"),
           "B5": ("FAIL", "single source, single frame")},
 "HC-18": {"B7": ("FAIL", "single source; no recency competition"),
           "B3": ("FAIL", "single source on a narrow decision; little room for a correct "
                          "UNRESOLVED")},
 "HC-19": {"B5": ("FAIL", "single descriptive frame"),
           "B4": ("PASS", "resolvable role question against one source")},
 "HC-20": {"B7": ("FAIL", "single source; no dated competition"),
           "B8": ("FAIL", "single source; no question-dependent authority")},
}

FULL = {"B1": "B1_NO_RELATION_BY_ABSENCE", "B2": "B2_ORDER_IS_NOT_AUTHORITY",
        "B3": "B3_UNRESOLVED_IS_VALID", "B4": "B4_FALSE_ABSTENTION_IS_FAILURE",
        "B5": "B5_ROUTING_IS_INFERENTIAL", "B6": "B6_CLOSED_FRAME_SPACE",
        "B7": "B7_NO_RECENCY_AS_AUTHORITY", "B8": "B8_QUESTION_RELATIVE_AUTHORITY"}

if __name__ == "__main__":
    import collections
    print("CASE-TO-INVARIANT AUDIT — shape only, no answers determined\n")
    passing = collections.defaultdict(list)
    tally = collections.Counter()
    for cid in sorted(CASES):
        s = shape(cid)
        c = CASES[cid]
        assigned = [i.split("_")[0] for i in c["defends"]]
        print(f"{cid}   {s['n']} source(s), dates {'/'.join(s['dates'])}, turns {s['turns']}")
        print(f"  assigned: {', '.join(assigned)}")
        for short in assigned:
            v, why = A[cid][short]
            tally[v] += 1
            if v == "PASS":
                passing[FULL[short]].append((cid, c["family"]))
            print(f"    {short}: {v}\n        {why}")
        kept = [i for i in assigned if A[cid][i][0] == "PASS"]
        print(f"  disposition: {'KEEP for ' + ','.join(kept) if kept else 'NO VALID ASSIGNMENT'}\n")

    print("=" * 72)
    print(f"assignments: {tally['PASS']} PASS, {tally['FAIL']} FAIL, {tally['UNCERTAIN']} UNCERTAIN\n")
    print(f"  {'invariant':34} {'cases':>5} {'families':>8}  status")
    for k in sorted(FULL.values()):
        got = passing.get(k, [])
        fams = {f for _, f in got}
        ok = len(got) >= 2 and len(fams) >= 2
        print(f"  {k:34} {len(got):>5} {len(fams):>8}  {'OK ' if ok else 'LOW'}"
              f"   {', '.join(c for c, _ in got)}")
