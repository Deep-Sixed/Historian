#!/usr/bin/env bash
# Provision the evecor_historian instance from KeePassXC.
#
# Two failure modes this script exists to prevent, both learned the hard way:
#
#  1. READINESS RACE. `pg_isready` succeeds against initdb's TEMPORARY server, so a naive
#     wait lets the schema land nowhere. We poll a real query over TCP instead.
#
#  2. CREDENTIAL DISCLOSURE. PostgreSQL logs full statement text on ERROR, so
#     `ALTER ROLE x PASSWORD '<plaintext>'` can put the password in the server log the
#     instant anything in that statement fails. Piping via stdin does NOT prevent this —
#     the server receives the same SQL either way; an earlier version of this script
#     claimed otherwise and was wrong. We send a CLIENT-COMPUTED SCRAM VERIFIER instead,
#     so no plaintext ever crosses the wire. A failed statement can then disclose only a
#     salted hash, which is what the server stores anyway.
set -euo pipefail

SECRET=/mnt/jarvis-data/projects/EVECOR/bin/jarvis-secret
NAME=evecor-historian-db
PORT=5444
HERE="$(cd "$(dirname "$0")" && pwd)"

s()   { "$SECRET" get "$1"; }
verif() { s "$1" | "$HERE/scram.py"; }        # plaintext never enters argv or SQL

# EPHEMERAL BOOTSTRAP SECRET. The real owner credential is NOT handed to Docker: it would
# then sit in the container's environment and config metadata in plaintext. We initialise
# with a throwaway, do all provisioning with it, then replace historian_owner with the
# vault SCRAM verifier - after which the secret embedded in the container metadata is dead.
BOOTSTRAP_PW="$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')"
OWNER_PW="$BOOTSTRAP_PW"

docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d --name "$NAME" \
  -e POSTGRES_DB=evecor_historian -e POSTGRES_USER=historian_owner \
  -e POSTGRES_PASSWORD="$BOOTSTRAP_PW" \
  -e POSTGRES_HOST_AUTH_METHOD=scram-sha-256 \
  -e POSTGRES_INITDB_ARGS="--auth-host=scram-sha-256 --auth-local=scram-sha-256" \
  -p 127.0.0.1:$PORT:5432 --memory 1g --restart no postgres:18-alpine >/dev/null

until PGPASSWORD="$OWNER_PW" psql -h 127.0.0.1 -p $PORT -U historian_owner \
        -d evecor_historian -w -tAc 'select 1' >/dev/null 2>&1; do sleep 2; done
echo "  instance ready"

q() { PGPASSWORD="$OWNER_PW" psql -h 127.0.0.1 -p $PORT -U historian_owner \
        -d evecor_historian -w -v ON_ERROR_STOP=1 "$@"; }

# `set -e` does not fire through `cmd && echo`, so a failed schema load previously let
# provisioning continue against an empty database. Check explicitly.
q -f "$HERE/01-schema.sql" >/dev/null || { echo "  schema FAILED" >&2; exit 1; }
echo "  schema applied"
q -f "$HERE/02-roles.sql"  >/dev/null || { echo "  roles FAILED" >&2; exit 1; }
echo "  roles applied"

# Credentials as verifiers. Even if one of these statements errors and PostgreSQL logs it,
# the disclosed value is a salted hash, not the password.
{
  for r in EXTRACTOR EVIDENCE_VERIFIER CASE_DESIGNER TYPED_INGESTOR HUMAN_REVIEWER \
           RUNTIME PACKET_BUILDER GOLD_COMPILER; do
    lc="historian_$(echo "$r" | tr 'A-Z' 'a-z')"
    printf "ALTER ROLE %s LOGIN PASSWORD '%s';\n" "$lc" "$(verif "HISTORIAN_$r")"
  done
  printf "CREATE ROLE adj_alice LOGIN PASSWORD '%s';\n" "$(verif HISTORIAN_ADJ_ALICE)"
  printf "CREATE ROLE adj_bob   LOGIN PASSWORD '%s';\n" "$(verif HISTORIAN_ADJ_BOB)"
  cat <<'SQL'
GRANT historian_adjudicator TO adj_alice, adj_bob;
INSERT INTO adjudicator_principal(db_principal,human_id,display_name)
     VALUES ('adj_alice','alice','Alice A'),('adj_bob','bob','Bob B');
SQL
} | q >/dev/null || { echo "  credentials FAILED" >&2; exit 1; }
echo "  credentials applied as SCRAM verifiers"

# Retire the bootstrap secret: historian_owner becomes the vault credential, so the
# plaintext still visible in the container's metadata no longer opens anything.
printf "ALTER ROLE historian_owner PASSWORD '%s';\n" "$(verif HISTORIAN_OWNER)" | q >/dev/null
OWNER_PW="$(s HISTORIAN_OWNER)"
PGPASSWORD="$OWNER_PW" psql -h 127.0.0.1 -p $PORT -U historian_owner -d evecor_historian \
    -w -tAc 'select 1' >/dev/null || { echo "  owner rotation FAILED" >&2; exit 1; }
if PGPASSWORD="$BOOTSTRAP_PW" psql -h 127.0.0.1 -p $PORT -U historian_owner \
     -d evecor_historian -w -tAc 'select 1' >/dev/null 2>&1; then
  echo "  FATAL: bootstrap secret still works after rotation" >&2; exit 1
fi
echo "  bootstrap secret retired; container metadata holds a dead credential"

# DELIBERATE FAILURE-PATH TEST. Force a credential statement to error and confirm the
# log discloses no plaintext. Testing only the success path would prove nothing, since
# the leak happens precisely when a statement fails.
# A DUMMY, never live credential material: there is no reason to push a real secret - or
# a verifier derived from one, which is still offline-guessable - through a channel we are
# deliberately trying to make fail.
CANARY='THIS_IS_NOT_A_REAL_HISTORIAN_SECRET'
printf "ALTER ROLE role_that_does_not_exist LOGIN PASSWORD '%s';\n" \
  "$(printf '%s' "$CANARY" | "$HERE/scram.py")" \
  | PGPASSWORD="$OWNER_PW" psql -h 127.0.0.1 -p $PORT -U historian_owner \
      -d evecor_historian -w >/dev/null 2>&1 || true

if docker logs "$NAME" 2>&1 | grep -qF "$CANARY"; then
  echo "  FATAL: plaintext credential reached the container log - ROTATE NOW" >&2
  exit 1
fi
if ! docker logs "$NAME" 2>&1 | grep -q "role_that_does_not_exist"; then
  echo "  WARNING: the failure-path probe did not appear in the log at all; leak" >&2
  echo "           prevention was not actually exercised" >&2
  exit 1
fi
echo "  failure path exercised: statement logged, plaintext absent"
