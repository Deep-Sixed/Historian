# G-S1..G-S9 — gate to mechanism mapping

Every gate names the **exact mechanism** that enforces it and the test that proves the gate
fires. Where the mechanism is "unrepresentable", the forbidden state has no encoding at all
— that is stronger than a check, because a check can be bypassed by a code path added later.

Implementation: `historian/` + `sql/` — **179 tests passing**. STRUCTURAL LAYER
FROZEN 2026-08-22, see STRUCTURAL-FROZEN.md, of which 45 execute against
the live `evecor_historian` database under **scram-sha-256** with per-human adjudicator
identities, and prove the role separation blocks. Verified over three consecutive runs
against the persistent append-only store.

| Gate | Forbidden state | Mechanism | Strength | Test |
|------|-----------------|-----------|----------|------|
| G-S1 | `PROPOSED -> ASSERTED` mutation | `ProposedRelation` and `AssertedRelation` are unrelated frozen types. No `epistemic_class` field exists anywhere. | UNREPRESENTABLE | `test_gs1_*` (3) |
| G-S2 | model-authored assertion | `AssertionOrigin` has no `MODEL` variant; `_enum()` rejects non-members so the enum cannot be bypassed with a bare string | UNREPRESENTABLE + guarded | `test_gs2_*` (3) |
| G-S3 | consensus promotion | `proposal_support_count` is an int consumed by nothing; `ProposalDisposition` has no `CONFIRMED` | UNREPRESENTABLE | `test_gs3_support_count_does_not_promote` |
| G-S4 | contaminated gold | `gold_eligible` is a derived `@property`, not a field; `HUMAN_BLIND_ADJUDICATION` + `derived_from_proposal_id` raises | DERIVED + rejected | `test_gs4_*` (4) |
| G-S5 | non-blind adjudication | `AdjudicationMode` has only `BLIND`; `AdjudicationPacket` has no field for family/invariants; `BlindAdjudicator` holds no seed reference | UNREPRESENTABLE + capability | `test_gs5_*` (3), `test_adjudicator_cannot_reach_the_seed` |
| G-S6 | gold without provenance | `BlindAdjudication.adjudicator_id` and `EvaluationGold.adjudication_id` are required at construction | rejected | `test_gs6_*` (3) |
| G-S7 | ad-hoc authority frame | `FrameTaxonomy.permits()`; an inferred route must name an extractor, an explicit one must not | rejected | `test_gs7_*` (3) |
| G-S8 | proposal overwritten by review | frozen dataclasses; review creates a new `AssertedRelation` referencing the original; retraction is `AssertedRelationReview`, never a `CONTRADICTS` relation | UNREPRESENTABLE | `test_gs8_*` (2) |
| G-S9 | coverage below minimum | `compute_coverage()` / `require_complete()` raising `SuiteIncomplete`; counts cases AND distinct families | computed | `test_gs9_*` (5) |

## PostgreSQL enforcement layer

The in-process capability classes express the boundary; these grants and constraints
enforce it. Verified live in `tests/test_pg_roles.py`.

| Gate | Database mechanism | Proof |
|------|--------------------|-------|
| G-S2/G-S3 | `historian_extractor` has **no INSERT grant** on `asserted_relation` | a model process is refused even when supplying `origin='HUMAN_BLIND_ADJUDICATION'` and a fabricated adjudicator id — `InsufficientPrivilege` |
| G-S2 | RLS policies bind origin to writer: typed ingestor may only write `TYPED_SOURCE`, human reviewer only `HUMAN_*` | policy violation on cross-origin insert |
| G-S4 | `gold_eligible` is `GENERATED ALWAYS ... STORED`; CHECK forbids `HUMAN_BLIND_ADJUDICATION` + `derived_from_proposal_id` | insert with an explicit `gold_eligible` is rejected |
| G-S5 | `historian_adjudicator` has SELECT on packets only — no grant on seeds, gold, resolutions or proposals | four separate `InsufficientPrivilege` proofs |
| G-S7 | composite FK `(taxonomy_version, proposed_frame) -> taxonomy_entry(version, frame)` | `ForeignKeyViolation` on an invented frame |
| G-S8 | UPDATE/DELETE/TRUNCATE revoked from every application role on every table | parametrised across all seven roles |
| support_profile | `resolution_support` VIEW, routing deliberately excluded | a routed resolution with only raw evidence stays `DIRECT_EVIDENCE_ONLY` |

### Five pre-persistence gaps closed

1. **Assertion-writer separation.** `ExtractorWriter` holds only a proposal store and has
   no assertion methods; `historian_extractor` has no INSERT grant on assertions. The enum
   guard stopped `origin="MODEL"`; this stops the more plausible attack of a model process
   asserting through a legitimate-looking origin.
2. **Routing bound to the taxonomy.** `RoutingProposal.from_extractor` / `.from_question`
   require the `FrameTaxonomy` object; the database enforces the same with a composite FK.
   `explicitly_specified` now derives from `Question.caller_specified_frame` — an inference
   path can no longer certify its own route as caller-specified.
3. **Proposals are append-only.** `disposition` and `proposal_support_count` are gone from
   `ProposedRelation`. Disposition is a separate event; support is derived by counting
   distinct extraction runs per claim, so 100 agreeing proposals are still 100 proposals.
4. **PacketBuilder verifies evidence.** It re-reads every reference from source at the
   stated version and position and recomputes the passage hash; a mismatch aborts. The
   adjudicator receives a checked snapshot rather than one asserted by the seed's author.
5. **GoldCompiler follows the chain.** `compile()` no longer takes `seed_id`; it derives
   adjudication -> packet -> seed and re-verifies every link. Previously a verdict produced
   for seed B could be compiled into gold for seed A.

## Two failure states, deliberately not merged

    SuiteIncomplete    behavioural coverage lost -> insufficient EVIDENCE of correctness
                       Historian acceptance cannot be claimed

    test failure       structural gate violated  -> the implementation VIOLATES the
                       architecture; cannot be released

## A bypass found while building this

`test_gs2_assertion_origin_cannot_be_a_string` failed on first run. Python does not enforce
dataclass type annotations, so `AssertedRelation(origin="MODEL")` constructed cleanly: every
`is`-comparison against an enum member fell through, and no branch raised.

ST2 had rested on "the enum has no MODEL variant" — true, but nothing stopped a caller
bypassing the enum entirely. `_enum()` now rejects non-members at every enum boundary. The
lesson generalises: **structural impossibility only holds where the boundary is checked.** A
closed enum is not a closed door if the field accepts arbitrary objects.

## Open decisions taken during implementation

1. **Routing excluded from `support_profile`.** Routing selects WHICH authority rules apply;
   it does not support the conclusion. Including it would make every routed resolution
   `PROPOSED_DEPENDENT`, leaving two of four values unreachable and the vocabulary
   decorative. Source-role proposals ARE included — an authority judgement genuinely rests
   on them. Test: `test_routing_does_not_collapse_the_vocabulary`.
2. **`Question` is a real type** with stable id and version. A bare `question_ref` string
   made "two resolutions of the same question" undefined.
3. **`RoutingProposal.explicitly_specified`** allows a caller to state the frame outright, so
   routing is not unavoidably inferential.
4. **LINE is the only canonical coordinate system** in v0; TURN/MESSAGE are optional and
   unpopulated pending a corpus-wide parser audit.

## Not yet built

* Persistence. All stores are Protocols; the in-memory test double is the only
  implementation. Deployment requires distinct service identities and database
  credentials per component — the in-process capability split is the expression of that
  boundary, not a substitute for it.
* Every behavioural invariant B1..B8 stands at **0/2 coverage**. No blind adjudication has
  been performed. `require_complete([])` correctly raises `SuiteIncomplete`.
* HIST-C3 remains a regression exhibit, not gold: its verdict already exists in the RAG v1
  manifest and ledger `clm-2026-eb52f4cd`, so no one with access to the EVECOR record can
  adjudicate it blind.


## Six capability bypasses found and closed (2026-08-22)

The first PostgreSQL revision passed 84 tests and still contained six structural bypasses.
The tests were valid; the conclusion drawn from them was too broad. Each is now covered by
a negative test.

**1. `trust` authentication defeated the whole model.** The suite proved *"if PostgreSQL
accepts that I am role X, the grants for X behave correctly"* — not *"only the intended
component can become role X"*, which is what capability separation requires. Any process
reaching 127.0.0.1:5444 could claim any role, including `historian_owner`. Now
scram-sha-256 with a distinct credential per role; `test_unauthenticated_connection_is_refused`
and `test_wrong_password_is_refused` cover it.

**2. The adjudicator was not packet-only.** The shared-read grant handed it `evidence_ref`,
`question`, `frame_taxonomy` and `taxonomy_entry` alongside every other role — directly
contradicting the "packet only" design. Worse, it *needed* that access, because
`adjudication_packet_evidence` stored only an `evidence_id`. The packet is now
**self-contained** (`snapshot_text`, `snapshot_hash`, version and position frozen at build
time), so the grant is neither needed nor given. Eleven parametrised refusals cover it.

**3. The gold chain was fixed in Python but not in SQL.** `evaluation_gold` still had
writable `seed_id`, `expected_outcome` and `expected_resolution`, so anyone holding the
gold-compiler credential could do over SQL exactly what the Python API had stopped —
cross-wire a verdict from seed B onto seed A, or record an expectation differing from the
adjudication. The table is now `(id, adjudication_id, allowed_abstention)`; everything else
is derived through `evaluation_gold_resolved` following adjudication → packet → seed, and
`defends_invariants` comes from the seed via `evaluation_gold_invariant`.

**4. Blindness could be self-certified.** Both `HumanReviewWriter` and the RLS policy let
the ordinary human-review path write `origin='HUMAN_BLIND_ADJUDICATION'` with any
adjudicator id — the same flaw class as the original bare-string `MODEL` bypass, one layer
up. Now `historian_human_reviewer` may write `HUMAN_REVIEWED_PROPOSAL` **only**; blind-origin
assertions come from `historian_blind_compiler` and must cite a real `blind_adjudication_id`
(CHECK + FK + RLS + in-process `BlindAssertionCompiler`).

**5. Caller-explicit routing could be self-certified.** `routing_proposal` let the extractor
insert `explicitly_specified=true, extractor_id=NULL`. The column is gone: `routing_proposal`
is unconditionally inferential with `extractor_id NOT NULL`, and caller-explicit routing
lives on `question.caller_frame` with its own composite FK to the taxonomy. They are
different provenance classes, not one class with a flag.

**6. Persistence dropped provenance.** `proposed_relation` had no supporting-evidence rows,
`source_role_proposal` no evidence, `routing_proposal` no alternates — so the persisted
record could not reproduce the in-memory epistemic state. *Why* a model proposed something
is provenance, not decoration. Added `proposed_relation_evidence`,
`source_role_proposal_evidence`, `routing_proposal_alternate`.

### A test-isolation property of append-only stores

The PG suite passed in isolation then failed on re-run: fixed row ids collided, and no role
can DELETE, so tests cannot clean up after themselves. All writes are now run-scoped by a
uuid suffix. This will apply to every future test against this database.


## Four further enforcement holes closed (2026-08-22, second review)

**7. The named human was still self-reported.** SCRAM proved the connection was the
`historian_adjudicator` *service* role; it said nothing about which human was at the
keyboard, while `adjudicator_id` remained caller-supplied data. G-S6 requires human
provenance, not provenance to a service account. Now `historian_adjudicator` is a **group
role with no login**; each adjudicating human has their own credential and a row in
`adjudicator_principal`, and a `BEFORE INSERT` trigger **overwrites** `adjudicator_id` from
`current_user`. A submitted value is discarded — verified: inserting as `adj_bob` while
claiming `'alice'` stores `bob / adj_bob`. An unregistered principal is refused outright.

**8. Blind assertions had the gold cross-wiring bug.** The `blind_adjudication_id` FK proved
only that the cited adjudication *exists*, never that it established that particular
subject/relation/object — so any real adjudication id licensed any relation triple. This is
the same defect I had just fixed for gold, reproduced one table over. Rather than ship an
epistemic label the database cannot enforce, **`HUMAN_BLIND_ADJUDICATION` is removed from
`assertion_origin` in v0**, along with the `historian_blind_compiler` role and the
`blind_adjudication_id` column. When the capability is genuinely needed, the correct shape
is a structured `BlindRelationAdjudication` whose human verdict itself carries
`subject_ref`, `relation_type` and `object_ref`, with both the assertion and
`human_adjudicator_id` derived from that row rather than supplied beside it.

**9. The adjudicator could read prior verdicts.** `GRANT INSERT, SELECT ON blind_adjudication`
let an adjudicator see other humans' verdicts and `resolution_text` — an avoidable
contamination channel across related or repeated cases. Now **INSERT only**. Separately, the
base `adjudication_packet` table carries `seed_id`, so the adjudicator now reads
`blind_packet` / `blind_packet_evidence` **views** which omit `seed_id`, `seed_evidence_id`,
family and invariants. Seed ids are no longer relied upon to be meaningless names.

**10. Packet snapshots were not bound to the seed in SQL.** Dropping `evidence_id` made the
packet self-contained but removed the relational proof that a snapshot materialises evidence
*that seed selected* — and the packet-builder credential can insert rows, so the guarantee
rested on a trusted PacketBuilder. That is weaker than the standard now applied to gold.
`adjudication_packet_evidence` keeps internal `seed_id` and `seed_evidence_id` with FKs to
`gold_case_seed_evidence(seed_id, evidence_id)` and `adjudication_packet(id, seed_id)`, so
evidence from another seed, or evidence that seed never selected, is rejected by the
database. `snapshot_hash` is now `GENERATED ALWAYS` from `snapshot_text` — two independently
writable values could disagree.


## Packet integrity and coverage identity (2026-08-22, third review)

Charles found the next hole using **my own test fixture as the proof**: seed S1 selects
`e1` and `e2`, packet `PK1` contained only `e1`, and the full 117-test suite passed. The
missing evidence was invisible to the adjudicator and to the gold chain.

**11. The packet was linked to the seed but not proven to BE the seed's packet.** FKs
showed a packet row named evidence the seed selected — nothing about completeness, order,
question identity or snapshot identity. Added `packet_finalization`, an append-only
aggregate boundary. `finalize_packet()` verifies the packet's evidence set is **exactly**
the seed's, in the **same ordinals**, then computes `packet_hash` canonically over question
plus ordered evidence identity. The demo now fails by name:
`packet demo is incomplete: 1 evidence item(s) selected by seed S1 are absent`.

**12. The question could be cross-wired.** Seeds carried "what?" and "other" while packets
were built with an independently writable "q" — and that string is exactly what the blind
adjudicator reads. A composite FK `(seed_id, question_text) -> gold_case_seed(id,
question_text)` now makes the packet's question *be* the seed's question. Without it the
chain adjudication → packet → seed could be structurally perfect while the human answered
something else.

**13. The snapshot was a pointer without its payload.** `seed_evidence_id` named `e1` while
`source_id`, version, lines and `snapshot_text` were supplied independently. Generating
`snapshot_hash` from `snapshot_text` proved only *this hash belongs to this text*. A
six-column FK now requires `(seed_evidence_id, source_id, source_version_hash, line_start,
line_end, snapshot_hash)` to match `evidence_ref(id, …, passage_hash)`, so freezing
unrelated text under a real evidence id is impossible. A `UNIQUE (packet_id,
seed_evidence_id)` prevents the same item appearing at several ordinals.

**14. There was no finalization boundary.** Evidence could be inserted *after* a verdict
without any UPDATE or DELETE, so the blind view would show a different packet than the
human saw. `packet_is_frozen()` rejects evidence on a finalized packet;
`require_finalized_packet()` rejects adjudication of an unfinalized one; and the blind views
join `packet_finalization`, so an adjudicator can only ever see a frozen packet. The
caller-supplied `packet_hash` column is gone — the hash is computed at finalization.

**15. G-S9 counted labels, not cases.** `compute_coverage()` counted distinct `case_id`
strings a caller invented. `coverage_from_gold_rows()` now builds cases from the
`gold_coverage` view, deriving identity through evaluation_gold → blind_adjudication →
adjudication_packet → gold_case_seed and keying on **seed_id**, so several gold artifacts
for one seed count as one case.

### Three bugs the tests caught in my own fixes

* `finalize_packet` compared ordinals across **every** packet — a missing
  `WHERE pe.packet_id = p_packet_id` — so unrelated packets produced false mismatches.
* The guard triggers needed `SECURITY DEFINER`: `require_finalized_packet` runs as the
  adjudicator, who deliberately cannot read `packet_finalization`.
* Under `SECURITY DEFINER`, `current_user` becomes the function owner, which broke the
  identity binding. It now uses **`session_user`** — the authenticated login, which
  `SET ROLE` cannot change, and therefore the stronger choice for binding a human.


## Fourth review: two bypasses closed, one leak claim corrected, one OPEN finding

**16. `packet_finalization` was forgeable, making the verifier optional.**
`historian_packet_builder` held INSERT on the table, and both `blind_packet` and
`require_finalized_packet()` only test that a finalization ROW EXISTS — never that it came
from `finalize_packet()`. A builder could therefore stamp `evidence_count=1` with any
non-empty hash and have an incomplete, or even empty, packet adjudicated. INSERT is now
revoked from every application role; the `SECURITY DEFINER` function is the sole writer.
`EXECUTE` is also revoked **from PUBLIC** — PostgreSQL grants it by default, so the
explicit grant alone proved nothing — and six roles are tested to be refused.

**17. The question cross-wire had only moved upstream.** `packet == seed` was enforced,
but `gold_case_seed.question_text` was still independently writable from `question.text`,
and the fixture proved it: `q1` read "what?" while seed `S2` claimed "other" against that
same `question_id`. Added `UNIQUE (id, text)` on `question` and a composite FK
`(question_id, question_text) -> question(id, text)`. The seed's frozen copy must now *be*
the Question's text.

**18. A false security claim, corrected.** The previous `provision.sh` asserted that piping
credential DDL through stdin instead of `-c` prevented PostgreSQL from logging the
password. **That was wrong** — the server receives the same statement either way, so the
script had moved from *leak possible, unnoticed* to *leak possible, detected afterwards*,
not to prevention. It now sends a **client-computed SCRAM verifier** (`sql/scram.py`), so
no plaintext ever crosses the wire; a failed statement can disclose only a salted hash. The
script additionally **forces a credential statement to fail** and asserts the log contains
the statement but not the secret — testing only the success path would prove nothing, since
the leak happens precisely when a statement errors.

### CLOSED — fabricated evidence reached gold (fixed, see below)

Probed at Charles's instruction rather than redesigned. The full chain **succeeds**:

    extractor inserts a fabricated EvidenceRef      SUCCEEDED
    seed selects it                                 SUCCEEDED
    packet built and FINALIZED                      SUCCEEDED
    blind adjudication accepted                     SUCCEEDED
    gold created, and it COUNTS TOWARD COVERAGE     SUCCEEDED

The snapshot matches its `EvidenceRef` perfectly — both are fabricated. Only the Python
`PacketBuilder` re-reads RAG v1 and recomputes the passage hash, and the database packet
path operates without it. So the pointer/payload binding stopped one layer short: it proves
*this snapshot is that EvidenceRef*, never *that EvidenceRef is real*.

The likely shape of a fix, not yet implemented: an append-only `evidence_verification`
table writable only by a RAG-reading verifier identity, with gold-path evidence required to
have a verification row. Probe artifacts were removed from the database.


## Fifth review: the evidence trust boundary moved up a layer

**19. Models may propose evidence LOCATIONS; only a verifier may create trusted evidence.**
Charles's ruling, and the right one: `EvidenceRef` already *means* "a source-backed,
re-verifiable passage", so letting a model-owned extractor create one made the type lie
about its own epistemic class — which is why a fabricated ref traversed seed → finalized
packet → adjudication → gold → coverage. A generic `verified` flag would have been another
label to remember; the capability split is structural.

    historian_extractor          WRITE evidence_candidate   NO INSERT evidence_ref
    historian_evidence_verifier  READ candidate + source    WRITE evidence_ref only

`EvidenceCandidate` carries a proposed source, version, position and quote with no trust.
`EvidenceVerifier` re-reads the actual source, recomputes the passage hash, checks the
anchor, and only then writes. PostgreSQL cannot read RAG v1, so the database enforces
**who** may create evidence and the verifier process enforces the **content** check —
pretending the database could do both would be the self-certification pattern again.

**VERIFICATION MEANS** the passage exists at that source, version and position with those
bytes. It does **not** mean the passage is authoritative, complete, current or true. For
the ledger specifically, confirming a claim exists says nothing about one that does not —
the documented recording gap makes absence uninformative.

The attack now fails at step one: `permission denied for table evidence_ref`.

**20. The seed was an unfrozen aggregate — the packet defect one level up.** Evidence or
invariants could be appended to a seed *after* a human answered it. The invariant case was
the dangerous one: `gold_coverage` reads the seed's **current** invariant rows, so appending
one would let a completed adjudication silently "cover" an invariant nobody judged —
manufacturing behavioural coverage with no additional case. Added `seed_finalization` and
`finalize_seed()`, hashing question id, question text, family, ordered evidence and sorted
invariants. After finalization the seed cannot change, packets may only be built from frozen
seeds, and `gold_coverage` joins `seed_finalization` so unfrozen seeds never count. A seed
with no evidence, or no invariant, cannot be finalized at all. `historian_case_designer`
now owns ordinary seed construction, leaving `historian_owner` as migration authority
rather than an application identity.

**21. Provisioning hygiene, corrected twice over.** The SCRAM change was only *plaintext
SQL-statement leak prevention*, not "no credential exposure": the real owner password was
still handed to Docker as `POSTGRES_PASSWORD`, landing in container metadata. Provisioning
now initialises with an **ephemeral bootstrap secret**, does all work with it, then replaces
`historian_owner` with the vault verifier and **asserts the bootstrap password no longer
authenticates** — so what remains in container metadata is a dead credential. The deliberate
failure probe also no longer derives its verifier from a live secret; it uses a dummy
canary, because there is no reason to push real credential material through a channel we are
trying to make fail.

### Bugs the tests caught in this round

* `evidence_candidate` was defined *after* the `evidence_ref` that references it.
* `provision.sh` used `cmd && echo`, which `set -e` does not fire through, so a failed
  schema load let provisioning continue against an empty database.
* The seed-freeze trigger fires *before* `ON CONFLICT`, so the test fixture could not
  re-run against a finalized seed. The trigger is right; the fixture was not idempotent.


## Sixth review: candidate provenance bound, and the verifier finally tested

**22. `derived_from_candidate_id` proved existence, not realisation.** Probed at Charles's
instruction and confirmed open: citing candidate `C1` (doc-A / version-A / lines 10–20)
while recording doc-B / version-B / lines 900–950 was **accepted**. The verifier legitimately
determines the *content*; it must not be able to change *which candidate it claims to have
verified*. `evidence_candidate` gained the missing `proposed_source_system` and a `UNIQUE`
locator, and `evidence_ref` now carries a six-column FK binding
`(derived_from_candidate_id, source_system, source_id, source_version_hash, line_start,
line_end)` to it. Seventh instance of the pointer/payload defect.

**23. `verified_by` was self-reported.** The verifier could name a different verifier — the
human-adjudicator identity defect in service form. It is now overwritten by trigger from
`session_user`. The test asserts the point directly: the verifier passes `"verifier-1"` and
the database records `historian_evidence_verifier`.

**24. The verifier's CONTENT check had never been exercised.** The role tests logged in as
the verifier and inserted rows *directly*, testing around the one component whose job is the
check. They proved only *the verifier identity may create evidence* — never *the verifier
rejects false locations*. `tests/test_evidence_verification.py` now runs `EvidenceVerifier`
against `RagV1SourceReader` over the **real 2,492-document corpus**:

    truthful candidate -> EvidenceRef, hash == actual source bytes   PASS
    nonexistent document                                            FAIL, 0 rows
    wrong document (real, but not the cited version)                FAIL, 0 rows
    wrong version hash                                              FAIL, 0 rows
    out-of-range span                                               FAIL, 0 rows
    wrong anchor (right doc/version/span)                           FAIL, 0 rows

Every negative asserts **zero evidence rows for that candidate** — "an exception was raised
somewhere" is not fail-closed; "nothing was written" is. `read_lines` returns `None` rather
than a best effort for a missing document, version mismatch or bad span, because *I could
not confirm this* and *this is what it says* must never share a return value.

### TRUSTED COMPUTING BASE — state this precisely, do not overclaim

    The DATABASE proves:  only the verifier identity can create an EvidenceRef.
    The VERIFIER proves:  the source bytes match what the EvidenceRef records.
    NEITHER ALONE PROVES BOTH.

`historian_evidence_verifier` **and its source adapter are part of the Historian trusted
computing base**. A process legitimately holding that credential can insert an
`EvidenceRef`; PostgreSQL cannot independently know whether it really read RAG v1. That is
where the boundary must sit absent cryptographic source attestation or a separate attesting
service. It is not a defect — but describing the database gate as though it independently
proved source existence would be one.


## Seventh review: the verifier's exact trust boundary

**25. `source_system` was a label, not a routing decision.** `EvidenceVerifier` called one
`read_lines()` and copied the candidate's declared system into the result, while
`RagV1SourceReader` took no source-system argument at all. A candidate claiming `LEDGER`
while naming a real RAG document id would have been verified **against RAG bytes**,
succeeded, and persisted `LEDGER` provenance — with the new candidate FK faithfully
preserving the wrong answer. Added `SourceRegistry`: the declared system now **selects the
backend that supplies the bytes**, and an unregistered system fails closed. Eighth instance
of the pointer/payload defect, and the first where the binding I had just added would have
*preserved* the error rather than caught it.

**26. The candidate's quote could drift.** The composite FK bound six locator fields but
not `proposed_quote`, so direct SQL under the verifier identity could cite a candidate at
the correct locator while recording a different anchor. `proposed_quote` is now part of the
candidate identity and the FK. `passage_hash` is deliberately **excluded** — discovering the
actual hash is the verifier's job, and binding it would require the candidate to already
know the answer.

**27. The reader trusted a model-controlled path component.** `source_id` originates in an
`EvidenceCandidate` a model may write, and the adapter did `corpus_dir / f"{source_id}.md"`
with no containment. `../../other-project/x` could have steered the **trusted** verifier
outside the corpus. Now validated against a document-id pattern *and* re-checked after
`resolve()`, because a trust boundary must not depend on which files happen to exist today.
Seven traversal forms are refused, and a traversal candidate writes zero evidence rows.

### Closed and not to be re-litigated

    model -> EvidenceRef direct write            CLOSED
    candidate locator cross-wire                 CLOSED
    verified_by self-report                      CLOSED
    source-system -> adapter binding             CLOSED
    candidate quote binding                      CLOSED
    corpus-root containment                      CLOSED
    real version / span / anchor / hash checks   PASS
    every negative writes zero rows              PASS


**28. The registry key was caller-supplied.** `SourceRegistry(**readers)` accepted
arbitrary mappings, so `SourceRegistry(LEDGER=rag_reader)` would resolve `LEDGER` while the
RAG reader supplied the bytes — the provenance defect the dispatch existed to close, moved
one layer out. Readers are now **positional**, and the key is read from `reader.source_system`.
A duplicate backend and a reader declaring nothing both raise. Second occurrence of *a
correct binding propagating an upstream error*.


---

## Acceptance model — v0 CLOSED 2026-08-23

    G-B1..G-B8   behavioural contract, 2 deterministic fixtures each      RELEASE GATE
    G-C1         contract coverage derived from collected node ids        RELEASE GATE
    G-S1..G-S9   structural invariants ST1-ST5                            RELEASE GATE
    G-K1         real-corpus canary HD-01..HD-20                          NON-BLOCKING
    G-H1         independently adjudicated gold coverage                  OPTIONAL / ABSENT

**29. The gate read its own threshold.** `test_every_behavioural_invariant_has_contract_fixtures`
asserted `>= MIN_CONTRACT_FIXTURES` — the same constant `require_contract_complete` reads.
Lowering that constant from 2 to 1 weakened the gate **and the test that guards it**, and the
suite stayed green. Found by mutation test, not by review. Now asserted against a duplicated
literal with the constant pinned separately.

Tenth instance of the recurring defect, and the first inside the acceptance machinery rather
than the thing being accepted: *a pointer bound while its payload stays independently
writable*. The lesson generalises past this codebase — **a gate parameterised by a value the
gate's own test also reads is not a gate.**

`G-H1` is absent by decision, not oversight. Independent human validation was not performed
and is not a v0 release requirement. The machinery that would consume it is retained and
tested; `require_complete([])` still raises, because at v0 there is no gold and the API must
not pretend there is.


## Closure review 2026-08-23 — three defects in the adjudicator

**30. A PROPOSED relation could settle a conflict.** `_resolves()` duck-typed on
`.relation_type` / `.subject_ref` / `.object_ref`, which `ProposedRelation` also has, so a
model could propose the settling relation and win with its own claim. Fixed by an
`isinstance` split at runtime; a look-alike object now raises rather than being ignored.
Eleventh instance of the recurring shape and the most direct one yet: **the ASSERTED/PROPOSED
distinction existed in the type system and was erased at the one call site that consumed it.**

**31. Partial resolution was reported as resolution.** A winner set from any single settled
pair discarded every other claim, so one asserted `A CORRECTS B` erased an untouched A-vs-C
conflict. A relation settles the pair it names. Dominance over *every* conflicting claim is
now required.

**32. The adjudicator's output could not be persisted.** `claim:<evidence_id>` strings were
written into `Resolution.proposed_relation_refs`, whose FK targets `proposed_relation(id)`.
No test caught it because no `ResolutionStore` implementation existed — only a Protocol.
**A type that is only ever held in memory cannot discover that it is unpersistable**, and a
Protocol with no implementation is an unproven claim about an interface, not an interface.
Claims became first-class `ClaimProposal` rows with their own dependency edge; source-role
and routing proposals now travel by identity.

    G-B9   only an AssertedRelation may settle a conflict          RELEASE GATE
    G-B10  a winner must dominate every conflicting claim          RELEASE GATE
    G-P1   adjudicator output round-trips through PostgreSQL       RELEASE GATE

### Found while fixing, by the new fixtures rather than by inspection

**33. The dominance gate rejected the legitimate case.** Gating on unsettled pairs was wrong
because a losing candidate always leaves pairs unsettled. Winner-hood was already complete.

**34. `_settles()` returned the first match.** With both directions asserted for one pair,
scan order decided the conflict — document order wearing a different hat, which is what B2
forbids. A pair asserted both ways now settles nothing.
