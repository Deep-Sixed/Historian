#!/usr/bin/env bash
set -euo pipefail

: "${PGHOST:=127.0.0.1}"
: "${PGPORT:=5444}"
: "${PGDATABASE:=evecor_historian}"
: "${PGUSER:=postgres}"
: "${PGPASSWORD:=postgres}"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

psql_super() {
  psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" -w \
    -v ON_ERROR_STOP=1 "$@"
}

until psql_super -tAc 'select 1' >/dev/null 2>&1; do
  sleep 1
done

psql_super <<SQL
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'historian_owner') THEN
        CREATE ROLE historian_owner LOGIN SUPERUSER PASSWORD '${HISTORIAN_OWNER}';
    ELSE
        ALTER ROLE historian_owner LOGIN SUPERUSER PASSWORD '${HISTORIAN_OWNER}';
    END IF;
END \$\$;
SQL

PGUSER=historian_owner
PGPASSWORD="$HISTORIAN_OWNER"

psql_owner() {
  psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" -w \
    -v ON_ERROR_STOP=1 "$@"
}

git -C "$ROOT" show v0.0.0-original:sql/01-schema.sql | psql_owner >/dev/null
git -C "$ROOT" show v0.0.0-original:sql/02-roles.sql | psql_owner >/dev/null
psql_owner -f "$ROOT/sql/migrations/001-question-bound-provenance.sql" >/dev/null

psql_owner <<SQL
ALTER ROLE historian_extractor LOGIN PASSWORD '${HISTORIAN_EXTRACTOR}';
ALTER ROLE historian_evidence_verifier LOGIN PASSWORD '${HISTORIAN_EVIDENCE_VERIFIER}';
ALTER ROLE historian_case_designer LOGIN PASSWORD '${HISTORIAN_CASE_DESIGNER}';
ALTER ROLE historian_typed_ingestor LOGIN PASSWORD '${HISTORIAN_TYPED_INGESTOR}';
ALTER ROLE historian_human_reviewer LOGIN PASSWORD '${HISTORIAN_HUMAN_REVIEWER}';
ALTER ROLE historian_runtime LOGIN PASSWORD '${HISTORIAN_RUNTIME}';
ALTER ROLE historian_packet_builder LOGIN PASSWORD '${HISTORIAN_PACKET_BUILDER}';
ALTER ROLE historian_gold_compiler LOGIN PASSWORD '${HISTORIAN_GOLD_COMPILER}';
CREATE ROLE adj_alice LOGIN PASSWORD '${HISTORIAN_ADJ_ALICE}';
CREATE ROLE adj_bob LOGIN PASSWORD '${HISTORIAN_ADJ_BOB}';
GRANT historian_adjudicator TO adj_alice, adj_bob;
INSERT INTO adjudicator_principal(db_principal,human_id,display_name)
     VALUES ('adj_alice','alice','Alice A'),('adj_bob','bob','Bob B');
SQL
