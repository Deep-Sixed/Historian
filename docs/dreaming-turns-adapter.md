# Dreaming Turns Adapter

`historian.dreaming_turns.DreamingTurnsAdapter` makes the turns recorded by Dreaming (memory
store v2) a Historian source. Dreaming records conversation and agent turns for memory
consolidation. Historian qualifies them as evidence through the same `SourceAdapter`
contract as any export.

## Source identity

| Field | Value |
|---|---|
| `source_system` | `DREAMING_TURNS` |
| `source_instance_id` | the Dreaming tenant's public id (`tnt_...`): opaque, no PII |
| `record_id` | the Dreaming turn's public id (`trn_...`) |
| `version_hash` | SHA-256 of the turn's stored canonical JSON bytes, equal to Dreaming's `content_sha256` |
| coordinates | `BYTE_RANGE` over those bytes, or `JSON_POINTER` into them (canonical JSON of the value) |

Only turns are a source. Dreaming's consolidated memories are model output, and model output
never becomes Historian authority.

## How it reads

The adapter is a client of Dreaming's authenticated `/v2` API and needs a read-scoped token
for one tenant:

- `GET /v2/tenants/{tenant}/turns?after_seq=&limit=` enumerates the turns. The listing has no
  content, and forgotten turns are flagged so the adapter skips them.
- `GET /v2/turns/{id}/raw` returns the exact stored bytes, with the headers
  `X-Dreaming-Content-SHA256` and `X-Dreaming-Tenant-Id`.

Every `read` and `verify` re-fetches the bytes. Each read fails closed when any of these holds:

| Condition | Failure |
|---|---|
| the bytes do not hash to the declared value | `INTEGRITY_FAILURE` |
| the bytes do not hash to the pointer's version | `VERSION_MISMATCH` |
| the turn belongs to another tenant, or the instance is unknown | `NOT_FOUND` |
| the turn was forgotten in Dreaming (HTTP 410) | `NOT_FOUND` |
| the API is unreachable, refuses the token, or errors | `UNAVAILABLE` |
| the coordinate system is not `BYTE_RANGE` or `JSON_POINTER` | `UNSUPPORTED_COORDINATE` |
| the coordinate is malformed or out of range | `INVALID_POINTER` |

Enumeration raises `SourceEnumerationError` in these cases. It also raises when the tenant id
changes between pages, or when a pinned `source_instance_id` does not match Dreaming.

`origin_classes` limits enumeration to turns of the given Dreaming origins, for example only
`human`. Dreaming records which client sent each turn and which origin it was allowed to
claim. Verification of an explicit pointer does not depend on the filter.

The transport is the standard library: `http(s)://host:port`, or `unix:/path/to/gateway.sock`
for a Unix socket mounted into the verifier's namespace.

## Erasure

A turn forgotten in Dreaming no longer verifies, and new intake skips it. Evidence that
Historian has already committed stays committed: application identities cannot delete it
(PV10). Removing it needs the operator procedure on the Historian side.

## Provisioning (not done by this change)

Running the adapter for real needs these steps:

1. **Historian's verifier identity** (UID 10002) runs the adapter. The profile already trusts
   that identity to verify external adapter bytes before direct evidence intake. Extraction
   (UID 10001) proposes candidates as before.
2. **A Dreaming read token**, limited to the tenant to be ingested. On the Dreaming host:

   ```bash
   python -m dreaming.admin client create historian-intake --scope read --tenant <tenant>
   ```

   The token goes only into the verifier's environment as `DREAMING_TOKEN`, never into the
   repository or service configuration.
3. **Reachability:** the verifier sets `DREAMING_URL` to `unix:/path/to/gateway.sock`, with the
   socket directory mounted into its namespace. It also sets `DREAMING_TENANT`, and optionally
   `DREAMING_SOURCE_INSTANCE_ID` to pin the tenant id and `DREAMING_ORIGIN_CLASSES=human`.
4. **Optional link back:** after evidence is committed, a separate Dreaming client with the
   `feed` scope reports `archived_as` through `PUT /v2/external-refs`, carrying Historian's id
   and the `version_hash`. Dreaming then knows which turns Historian holds.
   This identity is separate from the read token.

## Tests

`tests/test_dreaming_turns_adapter.py` uses a synthetic in-memory Dreaming and real HTTP and
Unix-socket servers, with synthetic data only. Dreaming's own test suite runs this adapter
against its real API when `HISTORIAN_SRC` points to a Historian checkout.
