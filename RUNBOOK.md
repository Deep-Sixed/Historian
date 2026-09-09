# Historian — runbook

## Database

    container   evecor-historian-db     postgres:18-alpine, --memory 1g, restart no
    bind        127.0.0.1:5444          localhost only
    database    evecor_historian
    owner       historian_owner

Provision from scratch:

    docker run -d --name evecor-historian-db \
      -e POSTGRES_DB=evecor_historian -e POSTGRES_USER=historian_owner \
      -p 127.0.0.1:5444:5432 --memory 1g --restart no postgres:18-alpine
    docker exec -i evecor-historian-db psql -U historian_owner -d evecor_historian \
      -v ON_ERROR_STOP=1 < sql/01-schema.sql
    docker exec -i evecor-historian-db psql -U historian_owner -d evecor_historian \
      -v ON_ERROR_STOP=1 < sql/02-roles.sql

## Authentication

`scram-sha-256`, with a distinct credential per role. `trust` was removed once it became
clear it defeated the capability model outright: it proved only that grants behave *given*
an identity, never that a component can obtain *only its own* identity.

    docker run -d --name evecor-historian-db \
      -e POSTGRES_DB=evecor_historian -e POSTGRES_USER=historian_owner \
      -e POSTGRES_PASSWORD="$HISTORIAN_OWNER_PW" \
      -e POSTGRES_HOST_AUTH_METHOD=scram-sha-256 \
      -e POSTGRES_INITDB_ARGS="--auth-host=scram-sha-256 --auth-local=scram-sha-256" \
      -p 127.0.0.1:5444:5432 --memory 1g --restart no postgres:18-alpine

Use `sql/provision.sh`, which reads every credential from KeePassXC. It exists because two
things are easy to get wrong: `pg_isready` succeeds against initdb's TEMPORARY server (so a
naive wait races and the schema lands nowhere), and PostgreSQL logs full statement text on
ERROR — so `ALTER ROLE ... PASSWORD` passed with `-c` leaks the value into `docker logs` the
moment anything in that statement fails. All credential DDL is piped via stdin, and the log
is grepped afterwards to prove nothing leaked.

### Credentials — in KeePassXC

All nine live in the vault under **`DATA/HISTORIAN/`**, alongside `DATA/RAGFlow`:

    HISTORIAN_OWNER            HISTORIAN_RUNTIME
    HISTORIAN_EXTRACTOR        HISTORIAN_PACKET_BUILDER
    HISTORIAN_TYPED_INGESTOR   HISTORIAN_GOLD_COMPILER
    HISTORIAN_HUMAN_REVIEWER   HISTORIAN_ADJ_ALICE / HISTORIAN_ADJ_BOB

Each entry carries the database role as its username and the connection URL. Read them the
normal way:

    jarvis-secret get HISTORIAN_RUNTIME

Wired into `bin/jarvis-secret` (`APPROVED_NAMES`) and `bin/keepass_batch.py`
(`SECRET_ENTRY_PATHS`). **There is no credential file.** The generated working copies were
shredded once every entry was verified to authenticate against the live database, and the
test suite reads exclusively through `jarvis-secret`.

`sql/02-roles.sql` creates roles `NOLOGIN` and contains no passwords;
`sql/03-credentials.sql.tmpl` holds only `${...}` placeholders rendered from the vault at
deploy time. Neither must ever contain a value.

Vault backup taken before the write:
`.config/Secrets/friday@friday.pre-historian-2026-08-22.kdbx`.

## Tests

    python3 -m pytest -q -m "not pg and not canary"
        # Python/core + static schema contract only

    python3 -m pytest -q -m pg --run-pg
        # PostgreSQL security/invariant gate; fails if :5444 or credentials are unavailable

    python3 -m pytest -q -m canary --run-corpus
        # Real-corpus canary; non-blocking and expected to skip where the corpus is absent

Do not report a skipped PostgreSQL gate as passing. Status should be recorded separately:

    Python/core tests        PASS / FAIL
    PostgreSQL gates         PASS / FAIL / NOT RUN
    Corpus canary            PASS / FAIL / NOT RUN

The suite is re-runnable against a persistent database: writes use a run-scoped id
suffix, because the tables are append-only by design and no role can DELETE, so tests
must not depend on cleanup that is deliberately impossible.

## Adjudicator identities

`historian_adjudicator` is a GROUP role with **no login**. Each adjudicating human needs:

    CREATE ROLE adj_<human> LOGIN PASSWORD '<from KeePassXC>';
    GRANT historian_adjudicator TO adj_<human>;
    INSERT INTO adjudicator_principal(db_principal, human_id, display_name)
         VALUES ('adj_<human>', '<human-id>', '<Display Name>');

`blind_adjudication.adjudicator_id` is then derived from `current_user` by trigger; a
submitted value is discarded, and an unregistered principal cannot adjudicate at all.

An adjudicator reads `blind_packet` and `blind_packet_evidence` only — never the base
tables, which carry `seed_id` — and has **INSERT without SELECT** on `blind_adjudication`,
so prior verdicts are unreadable.

## Current status

    structural gates       G-S1..G-S9 implemented and enforced (code + database)
    evidence trust         models propose candidates; only the verifier creates evidence
                           candidate locator bound relationally; verified_by = session_user
                           content check exercised against the real corpus, fail-closed
                           source system selects the adapter; reader contained to corpus
    seed + packet          both frozen aggregates; coverage counts frozen seeds only
    packet integrity       finalized: exact set, order, question and snapshot binding
    coverage identity      derived from real gold seeds, not caller labels
    persistence            PostgreSQL, capability roles, append-only, scram-sha-256
    adjudicator identity   per-human logins, derived from authenticated principal
    blind assertion origin REMOVED in v0 (unenforceable as designed)
    behavioural coverage   B1..B8 all 0/2 - SUITE INCOMPLETE
    Historian acceptance   CANNOT BE CLAIMED
    credentials            NOT vault-managed - still outstanding

The only external blocker is blind human adjudication by someone who has not read the
EVECOR record. HIST-C3 cannot supply it: its verdict is already in the RAG v1 manifest
and ledger clm-2026-eb52f4cd.
