#!/usr/bin/env python3
"""v3 case-to-invariant audit — mechanical necessary conditions, shape only.

The v2 failure was that `defends` was author-supplied and nothing checked it. This runs the
check. Each invariant has a NECESSARY structural condition; a case failing it cannot
exercise that invariant regardless of what its label claims.

These conditions are necessary, not sufficient. Passing means "this case is capable of
exposing the failure", never "this case will". Sufficiency needs a human reading content,
which this audit deliberately does not do.
"""
import argparse
import json
import re
import sys
from pathlib import Path

from historian.coverage import BEHAVIOURAL_INVARIANTS


def facts(c, corpus):
    ds = c["evidence"]
    turns, dates = [], []
    for d in ds:
        h = (corpus / f"{d}.md").read_text(errors="replace")[:1200]
        turns.append(int(re.search(r"^turns: (\d+)", h, re.M).group(1)))
        dates.append(d[:10])
    return {"n": len(ds), "turns": turns, "dates": dates,
            "distinct_dates": len(set(dates)), "max_turns": max(turns)}


def check(short, f, c):
    """Necessary condition per invariant. Returns (ok, requirement)."""
    if short == "B1":   # absence must be POSSIBLE: needs >1 source so one can be silent
        return f["n"] >= 2, "needs >=2 sources so absence in one is a live temptation"
    if short == "B2":   # a later position must be able to supersede an earlier one
        return f["max_turns"] >= 8, "needs a source of >=8 turns; 2-3 turns is one exchange"
    if short == "B3":   # a correct UNRESOLVED must be structurally available
        return f["n"] >= 2, "needs >=2 sources that may fail to converge"
    if short == "B4":   # must be resolvable, so abstention could be wrong
        return f["n"] >= 1, "needs a source addressing the question"
    if short == "B5":   # a routing decision must actually arise
        return f["n"] >= 2, "needs >=2 sources spanning different frames"
    if short == "B6":   # the frame taxonomy must be exercised
        return f["n"] >= 2, "needs >=2 sources so a frame must be chosen"
    if short == "B7":   # recency and authority must be able to diverge
        return f["n"] >= 2 and f["distinct_dates"] >= 2, \
               "needs >=2 sources with DIFFERENT dates"
    if short == "B8":   # authority must be able to depend on the question
        return f["n"] >= 2, "needs >=2 competing sources"
    return False, "unknown invariant"


def main():
    import collections
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=Path(__file__).parent / "synthetic")
    parser.add_argument("--queue", type=Path, default=Path(__file__).parent / "case-queue.json")
    args = parser.parse_args()
    cases = json.loads(args.queue.read_text())
    print("SYNTHETIC CASE AUDIT — necessary conditions, not gold\n")
    ok_by, tally, problems = collections.defaultdict(list), collections.Counter(), []
    for c in cases:
        f = facts(c, args.corpus)
        line = f"{c['id']}  {f['n']} src, dates {'/'.join(sorted(set(f['dates'])))}, turns {f['turns']}"
        verdicts = []
        for inv in c["defends"]:
            short = inv.split("_")[0]
            good, req = check(short, f, c)
            tally["PASS" if good else "FAIL"] += 1
            verdicts.append(f"{short}:{'PASS' if good else 'FAIL'}")
            if good:
                ok_by[inv].append((c["id"], c["family"]))
            else:
                problems.append(f"  {c['id']} {short}: {req}")
        # every assignment must carry a specific wrong behaviour, not just a label
        exp = c.get("exposes", "")
        named = bool(exp) and not re.fullmatch(r"[\sA-Z0-9_,]+", exp)
        if not named:
            problems.append(f"  {c['id']}: `exposes` missing or merely restates the label")
            tally["NO_EXPOSES"] += 1
        print(f"{line}\n    {'  '.join(verdicts)}\n    exposes: {exp[:96]}")
    print("\n" + "=" * 72)
    if problems:
        print("PROBLEMS:")
        print("\n".join(problems))
    print(f"\nassignments: {tally['PASS']} PASS, {tally['FAIL']} FAIL, "
          f"{tally['NO_EXPOSES']} missing rationale\n")
    print(f"  {'invariant':34} {'cases':>5} {'fam':>4}  status")
    incomplete = False
    for inv in BEHAVIOURAL_INVARIANTS:
        got = ok_by.get(inv, [])
        fams = {x for _, x in got}
        good = len(got) >= 2 and len(fams) >= 2
        incomplete |= not good
        print(f"  {inv:34} {len(got):>5} {len(fams):>4}  {'OK ' if good else 'LOW'}"
              f"  {', '.join(c for c, _ in got)}")
    print("\n  " + ("ALL INVARIANTS MEET THE NECESSARY CONDITION"
                    if not incomplete else "SOME INVARIANTS BELOW MINIMUM"))
    print("  (necessary, not sufficient - sufficiency needs a human reading content)")
    return 1 if incomplete or tally["FAIL"] or tally["NO_EXPOSES"] else 0


if __name__ == "__main__":
    sys.exit(main())
