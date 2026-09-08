# Adjudicator brief

**This is the only document you should read.** If you have read anything else about this
project, stop and say so — see Eligibility.

---

## What you are doing

You will be given a series of **packets**. Each contains:

* one **question**
* one or more **evidence excerpts** — verbatim spans from a corpus of conversation
  transcripts about a personal software and infrastructure project

For each packet you make one judgement, recorded in two passes.

---

## Pass 1 — is the packet adequate?

Before answering anything, decide only this: **does the supplied evidence contain enough
material to answer the question?**

If it does not, record **`PACKET_INSUFFICIENT`** and move on. That is a normal, expected
outcome, not a failure on your part or a wrong answer. The excerpts were selected
mechanically, so some will simply miss what the question needs. Rejecting them is useful
work — the case gets rebuilt with different excerpts.

Do not try to answer a question from evidence you consider inadequate.

## Pass 2 — adjudicate the adequate packets

For each packet that passed pass 1, record one of:

* **`RESOLVED`** — the evidence supports a defensible answer. Write it in
  `resolution_text`, with your reasoning in `rationale`.
* **`UNRESOLVED`** — the evidence bears on the question but does not settle it: sources
  conflict, or the material is genuinely ambiguous. Say why in `rationale`.

`UNRESOLVED` and `PACKET_INSUFFICIENT` are different. `UNRESOLVED` says *the evidence
doesn't settle it*. `PACKET_INSUFFICIENT` says *I wasn't given enough to tell*.

Both are legitimate outcomes. Neither is a lesser answer than `RESOLVED`. Do not reach for
a confident answer to seem useful, and do not reach for uncertainty to seem careful —
either distortion damages the result.

---

## The one rule that has no technical enforcement

**When you record `PACKET_INSUFFICIENT`, your rationale must not contain what you think
the answer is.**

The system prevents you filing a formal answer alongside an insufficiency report, but it
cannot police free text. Someone else reads your rationale to choose better excerpts. If it
carries your conclusion, the rebuilt case is spoiled before anyone sees it.

    WRITE THIS   "the excerpt covers only the opening exchange; the question asks about a
                  later decision that isn't present"
    WRITE THIS   "two documents are supplied but neither states a version"

    NOT THIS     "the answer is obviously X, but the excerpt doesn't show it"
    NOT THIS     "this contradicts the other case I saw about Y"

---

## Eligibility

You are **not** eligible if you have read this project's design record, its ledger, its
architecture notes, or discussed the reasoning behind these cases with anyone who has.

That is not a formality. The value of your judgement comes entirely from it being formed
independently, from the evidence in front of you and nothing else.

Two people are already disqualified: the project's author and the assistant that built
this. Both have discussed these cases in detail, so neither can supply a usable verdict.

## Do not seek out

Other documents from the corpus, other packets' verdicts, the project's repository or
notes, or any explanation of why a particular case exists or what it is meant to test.

If someone offers you that context, decline it. If you have already seen some of it, say
which — a case you were exposed to can be reassigned, but a contaminated verdict recorded
as clean cannot be undone.

## Questions you may ask

How to operate the tool. What a field means. Whether an excerpt rendered correctly.

Not: whether your answer is right, what others concluded, or what the case is about.
