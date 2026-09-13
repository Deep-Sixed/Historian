#!/usr/bin/env python3
"""Build the case queue through distinct kernel-authenticated service capabilities.

Run each stage as its assigned OS UID. This tool never changes identity or opens storage.
"""

import argparse
import json
from pathlib import Path

from historian.capability import PacketBuilder
from historian.gold import GoldCaseSeed
from historian.sqlite_store.stores import Store
from historian.persistence.locator import locator_to_record
from historian.source_adapter import (
    EvidenceLocator,
    SourceCoordinate,
    CoordinatePart,
    SourceMaterialState,
    sha256_text,
)
from historian.sources import RagV1SourceReader
from historian.types import (
    Question,
    EvidenceRef,
    SourcePosition,
    SourceSystem,
    CoordinateSystem,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--stage",
        choices=("plan", "candidates", "verify", "seeds", "packets"),
        default="plan",
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--corpus",
        type=Path,
        required=True,
        help="Readable copy matching the approved service corpus",
    )
    parser.add_argument(
        "--queue", type=Path, default=Path(__file__).with_name("case-queue.json")
    )
    parser.add_argument("--socket", default="/run/historian/historian.sock")
    args = parser.parse_args()
    cases = json.loads(args.queue.read_text())
    if not args.apply:
        print(json.dumps({"stage": args.stage, "cases": len(cases), "writes": False}))
        return
    if args.stage == "plan":
        parser.error("--apply requires one explicit capability stage")
    store = Store(args.socket)
    reader = RagV1SourceReader(args.corpus)

    def identity(prefix, value):
        return f"{args.run_id}-{prefix}-{value}"

    refs = {}
    for doc in sorted({doc for case in cases for doc in case["evidence"]}):
        version = reader.version_of(doc)
        count = len((args.corpus / f"{doc}.md").read_text().splitlines())
        text = reader.read_lines(doc, version, 1, count)
        if not text:
            raise ValueError("source is unavailable")
        quote = next(line for line in text.splitlines() if line.strip())[:200]
        eid, cid = identity("evidence", doc), identity("candidate", doc)
        loc = EvidenceLocator(
            "RAG_V1",
            "configured-corpus",
            doc,
            version,
            SourceCoordinate(
                "LINE",
                (CoordinatePart("start", "1"), CoordinatePart("end", str(count))),
            ),
            sha256_text(text),
            SourceMaterialState.ORIGINAL,
        )
        if args.stage == "candidates":
            store.call(
                "candidate",
                {"id": cid, "locator": locator_to_record(loc), "quote": quote, "extractor_id": "queue-builder", "extraction_run_id": args.run_id},
            )
        if args.stage == "verify":
            store.call(
                "verify_source",
                {
                    "id": eid,
                    "candidate_id": cid,
                    "source_id": doc,
                    "version_hash": version,
                    "start": 1,
                    "end": count,
                    "quote": quote,
                },
            )
        refs[doc] = EvidenceRef(
            doc,
            SourceSystem.RAG_V1,
            version,
            SourcePosition(doc, version, CoordinateSystem.LINE, 1, count),
            sha256_text(text),
            quote,
            eid,
        )
    for case in cases:
        sid, pid = identity("seed", case["id"]), identity("packet", case["id"])
        if args.stage == "seeds":
            q = Question(identity("question", case["id"]), case["question"])
            store.put(q)
            store.put_seed(
                GoldCaseSeed(
                    sid,
                    q.id,
                    q.text,
                    tuple(refs[d] for d in case["evidence"]),
                    case["family"],
                    tuple(case["defends"]),
                )
            )
        if args.stage == "packets":
            PacketBuilder(store, store, reader).build(sid, pid)
    print(json.dumps({"stage": args.stage, "cases": len(cases), "writes": True}))


if __name__ == "__main__":
    main()
