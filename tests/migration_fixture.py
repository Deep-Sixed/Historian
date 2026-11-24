"""Populate a database through the service's own write paths, in process.

Used by the core migration tests and by scripts/ci-migration-compat.sh, which runs this
same file against the last profile v3 commit with libSQL 0.1.11 to produce a genuine v3
database. The storage package is historian.libsql_store in v3 and historian.sqlite_store from v4;
store() resolves whichever the running checkout has. Otherwise it only uses names that
exist unchanged in v3 and v4. Roles and principals
are passed explicitly here: this is a fixture writer, not a capability-boundary test.

Usage: python tests/migration_fixture.py create|append DATABASE CORPUS
       python tests/migration_fixture.py summary DATABASE
"""

import hashlib
import importlib
import json
import sys
from uuid import uuid4
from pathlib import Path

ROLE_UIDS = {"extractor": 10001, "verifier": 10002, "designer": 10003, "typed": 10004,
             "reviewer": 10005, "runtime": 10006, "builder": 10007,
             "adjudicator": 10008, "gold": 10009}
SOURCE = "2026-01-01-source"
TEXT = b"authority passage\nsecond line\n"


def store(module):
    """Import a storage submodule from v4 (sqlite_store) or v3 (libsql_store)."""
    try:
        return importlib.import_module(f"historian.sqlite_store.{module}")
    except ModuleNotFoundError as exc:
        if exc.name not in ("historian.sqlite_store", f"historian.sqlite_store.{module}"):
            raise
        return importlib.import_module(f"historian.libsql_store.{module}")


def write_corpus(corpus):
    corpus = Path(corpus)
    corpus.mkdir(parents=True, exist_ok=True)
    (corpus / f"{SOURCE}.md").write_bytes(TEXT)
    return hashlib.sha256(TEXT).hexdigest()


def _call(repository, operation, role, corpus, **data):
    dispatch = store("service").dispatch
    return dispatch(repository, operation, data, role, f"uid:{ROLE_UIDS[role]}", str(corpus))


def populate(database, corpus, prefix="m", cases=3):
    from historian import types as t
    encode = store("codec").encode
    Repository, initialize = store("repository").Repository, store("repository").initialize

    version = write_corpus(corpus)
    initialize(database)
    repository = Repository(database)
    try:
        for n in range(cases):
            rid = f"{prefix}{n}"
            q = f"{rid}-q"
            # Complete application objects (app_object/app_link/app_seal) and question.
            _call(repository, "put_object", "designer", corpus,
                  object=encode(t.Question(q, f"Which claim is supported? ({rid})")))
            _call(repository, "put_object", "designer", corpus,
                  object=encode(t.FrameTaxonomy(f"{rid}-tax", ("CURRENT_OPERATIONAL_STATE",))))
            # Candidate -> verified evidence through the RAG source reader.
            for suffix in ("a", "b"):
                _call(repository, "verify_source", "verifier", corpus, id=f"{rid}-e{suffix}",
                      source_id=SOURCE, version_hash=version, start=1, end=1,
                      quote="authority passage")
            _call(repository, "claim", "extractor", corpus, id=f"{rid}-c",
                  evidence_id=f"{rid}-ea", question_id=q, text="supported claim")
            _call(repository, "route", "extractor", corpus, id=f"{rid}-r",
                  question_id=q, frame="CURRENT_OPERATIONAL_STATE")
            _call(repository, "publish", "runtime", corpus, id=f"{rid}-res", question_id=q,
                  conclusion="answer", route_id=f"{rid}-r",
                  evidence_ids=[f"{rid}-ea", f"{rid}-eb"], claim_ids=[f"{rid}-c"])
            _call(repository, "seed", "designer", corpus, id=f"{rid}-seed", question_id=q,
                  question_text=f"Which claim is supported? ({rid})",
                  evidence_ids=[f"{rid}-ea", f"{rid}-eb"])
            _call(repository, "packet", "builder", corpus, id=f"{rid}-p", seed_id=f"{rid}-seed")
            _call(repository, "assertion", "typed", corpus, id=f"{rid}-at",
                  subject_id=f"{rid}-ea", object_id=f"{rid}-eb", origin="TYPED_SOURCE")
            _call(repository, "assertion", "reviewer", corpus, id=f"{rid}-ar",
                  subject_id=f"{rid}-eb", object_id=f"{rid}-ea",
                  origin="HUMAN_REVIEWED_PROPOSAL")
            _call(repository, "adjudicate", "adjudicator", corpus, id=f"{rid}-adj",
                  packet_id=f"{rid}-p", verdict="RESOLVED", conclusion="answer")
            _call(repository, "gold", "gold", corpus, id=f"{rid}-g", adjudication_id=f"{rid}-adj")
    finally:
        repository.close()


def summary(database):
    connect = store("repository").connect
    c = connect(database)
    try:
        tables = [r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name").fetchall()]
        return {name: c.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]
                for name in tables}
    finally:
        c.close()


def main(argv):
    command, database, *rest = argv
    corpus = rest[0] if rest else None
    if command == "create":
        populate(database, corpus)
    elif command == "append":
        populate(database, corpus, prefix=f"append-{uuid4().hex[:8]}-", cases=1)
    elif command != "summary":
        raise SystemExit(f"unknown command {command}")
    print(json.dumps(summary(database), sort_keys=True))


if __name__ == "__main__":
    main(sys.argv[1:])
