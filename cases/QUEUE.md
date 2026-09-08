# Behavioural case queue — v3

> ## CASE-DESIGNER DOCUMENT — DO NOT GIVE THIS TO AN ADJUDICATOR
>
> This file names the invariants, the scenario families, and what each case is built to
> expose. Anyone who reads it can no longer adjudicate these cases blind.
>
> **The adjudicator gets `ADJUDICATOR-BRIEF.md` and the files in `packets/`, nothing else.**

> ## ROLE CHANGED 2026-08-23 — REAL-CORPUS CANARY, NOT HUMAN-GOLD ACCEPTANCE
>
> This queue is **preserved in full** and is now an **automated, NON-BLOCKING regression
> and canary suite** (`tests/test_corpus_canary.py`, marked `canary`). It contributes
> **zero gold coverage** and is **not** the v0 release gate.
>
> The v0 gate is the deterministic behavioural contract in
> `tests/test_behavioural_contract.py`. See `HISTORIAN-V0-CLOSED.md`.
>
> Everything below remains true about how these cases were CONSTRUCTED, and that
> construction is why they are worth running automatically. What changed is what a
> passing run entitles anyone to claim.

    PIPELINE_READY   seeds and packets built, evidence verified against source   YES
    CASE_CAPABLE     each assignment meets the necessary structural condition    YES
    CANARY_ACTIVE    runs automatically every suite run, non-blocking            YES
    CASE_READY       a blind human has confirmed the packet is adequate          NOT DONE
    ACCEPTED         adjudicated gold exists                                     NOT DONE

**20 cases · 24 evidence documents · 29 assignments · 14 families · 142 KB**
**Gold 0 · Gold coverage 0 · Contract coverage B1–B8 2/2 · v0 GATE SATISFIED**

### What the canary checks automatically

Evidence still resolves and reads from the RAG v1 corpus; the adjudicator executes over real
corpus evidence and returns a well-formed decision; an unrouted real-evidence case degrades
to `UNKNOWN` frame instead of inventing one; the queue counts have not drifted; `AUDIT-V3.py`
still passes.

It does **not** check whether any decision is correct. Nobody established these answers —
that is exactly what an independent adjudicator would have added, and that path is retained
but not required. A canary failure is a signal to investigate, never a release blocker.

## What v3 changed, and why

v2 assigned invariants as **labels** and the coverage function counted them. An audit
against case shape found 25 of 40 assignments could not exercise what they claimed: 17 of
20 cases were single-source, so B7 (recency vs authority) had **zero** usable cases — a
Historian with a completely broken "newer wins" rule passed all five — and B8 had one.

The error was building cases and labelling them afterwards. **Relational invariants must be
constructed as relations.** v3 builds each case from the failure it should expose:

| invariant | construction |
|---|---|
| B1 | two sources where one is silent on what the other raises |
| B2 | one source of 8–28 turns, so an early position can be superseded later |
| B3 | two sources that may genuinely fail to converge |
| B4 | a source that plainly addresses the question, so abstention would be wrong |
| B5 | two sources spanning different frames, forcing a routing decision |
| B6 | a question answerable only after choosing a frame |
| B7 | two sources, different dates, where the **newer** is the wrong authority |
| B8 | upstream and local sources whose authority flips with the question |

The pattern doing most of the work is **upstream-vendor document paired with local-deployment
document**. That single shape creates frame ambiguity, question-relative authority, and
recency-versus-authority tension by construction — the newer external announcement is
genuinely *not* the authority for a question about local practice.

## Audit status

`AUDIT-V3.py` checks a **necessary** structural condition per assignment and can fail. All
29 pass; report in `AUDIT-V3-REPORT.txt`. Every case also carries an `exposes` field naming
the specific wrong behaviour it catches, and the audit rejects one that merely restates the
invariant name.

Necessary is not sufficient. Passing means *this case is capable of exposing the failure*,
never *this case will*. Sufficiency requires reading content, which the audit does not do —
because determining a case's answer during construction is what contaminated HIST-C3.

## Delivery

**One packet per file** in `packets/`, largest 10 KB. Not a single bundle: the synthetic
pilot proved large pastes truncate silently, and a model asked for a one-word verdict will
supply one for material it never received. Each file states how many documents it should
contain and instructs the reader to report TRUNCATED rather than judge a partial packet.

**Verify receipt with content the adjudicator could not guess before accepting any verdict.**
A check whose answer appears in the question is not a check.

## Still true, and load-bearing

Seed construction stays **shallow by design** — documents chosen by size and title, spans
not chosen at all, whole documents used. Nobody assembling these cases determined an answer.
Anyone "improving" a packet by curating more precisely relevant evidence would contaminate
it exactly as HIST-C3 was contaminated.

HIST-C3 remains permanently non-gold; its verdict is in the RAG v1 manifest and ledger
`clm-2026-eb52f4cd`. It is a regression exhibit contributing zero coverage.

Neither Claude nor Charles can adjudicate: both have seen the reasoning, so any verdict from
either is `HUMAN_REVIEWED_PROPOSAL` and permanently `gold_eligible = false`.
