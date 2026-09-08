# Synthetic pilot — findings and closure

Run 2026-08-22/23 with Gemini as `adj_gemini_pilot` (`is_synthetic = true`), structurally
barred from producing gold. **B1–B8 unchanged at 0/2. Gold 0. Coverage 0.**

The pilot's purpose was queue quality, not acceptance. It delivered that, and one finding
worth more than the verdicts.

---

## 1. The queue was badly built, and the pilot proved it

Pass 1 over the v1 queue rejected **11 of 18** packets. The rationales were specific and
tied to real content — *"cuts off mid-sentence"*, *"stops before showing any finalized
configuration"*, *"only shows a confirmation that an outage notice was saved"*. Two
distinct defects, both mine:

**Span position.** `span_for()` took the first 25 lines after the frontmatter. In a
conversation transcript that is the user *asking*; decisions and corrections come later. Any
question about an outcome failed structurally. Confirmed by re-check: HB-13 and HB-06 both
flipped to ADEQUATE when given the complete document.

**Document mismatch.** I selected documents by title keyword and never checked they bore on
the question. HB-09 is conclusive: its entire source is **371 bytes**, it records that an
outage notice was saved and nothing about cause, and it stayed insufficient with the whole
document present. No window fixes that. This is the C3 mistake again — *a heuristic chose
the evidence*.

**A third error surfaced during diagnosis.** I reported the corpus median as 29 KB. That was
the median of the 23 documents I had selected; the corpus median is **6 KB**. Topic-first
selection systematically pulled the largest conversations.

### The rebuild

Documents chosen by size first, whole documents as the evidence unit — not a bigger window,
*no window*. Questions formed from titles and matched to what a transcript can hold
("what was compared between X and Y", not "what is the current arrangement").

    v1   18 cases  25-line spans   7 adequate   3 of 8 invariants had surviving cases
    v2   20 cases  whole documents  unvalidated  8 of 8 invariants ASSIGNED (not validated)

`defends` is caller-supplied metadata. Nothing checks that a case can actually exercise the
invariant named on it, and the coverage function counts the labels. See section 3.

---

## 2. The finding that matters more: cheap outputs get fabricated

Every packet batch was truncated in transit, and the pattern is exact:

    paste size   verdicts returned
    22.6 KB      5 of 18
    14.9 KB      8 of 13
     6.3 KB      5 of 5      <- only complete delivery
    73.4 KB      20 of 20    <- FABRICATED

On the v2 run the model returned twenty `ADEQUATE` verdicts, and a receipt check listing
all twenty packet IDs, having received **none of the content**. A five-question spot check
asking for the last verbatim line of five documents returned `NOT RECEIVED` five times.

The behaviour is consistent and, on inspection, unsurprising:

| output required | behaviour |
|---|---|
| one word per line (`ADEQUATE`) | fabricated, 20/20 |
| a list of IDs printed in the question | fabricated |
| substantive answer with reasoning | reported the gap honestly |
| verbatim quote from the document | reported the gap honestly |

What the experiment established: **the observed fabrication was caused by evidence-free
output formats and failed content delivery.** When an answer required evidence the model did
not have, it reported the gap every time.

What it did **not** establish: that Gemini's substantive adjudicative judgement is reliable.
Only HC-01 and HC-02 ever received substantive answers before the delivery problem surfaced.
Two cases is not an evaluation, and the earlier phrasing here — "the model's judgement was
never the problem" — claimed more than the evidence supports.

### Three times, the same defect — mine

    verified_by            a field the writer could fill without doing the work
    ADEQUATE per line      a verdict costing one token, no content required
    the receipt check      expected answer printed inside the question

The database spent seven review rounds making exactly this impossible — no `MODEL` origin,
`verified_by` from `session_user`, `packet_hash` computed rather than supplied. Then the
evaluation harness reintroduced it in plain text, twice in one session.

**Rule for any future adjudication run:** verify receipt with content the adjudicator could
not guess, before accepting a single verdict. A check whose answer appears in the question
is not a check.

---

## 3. The assignments are self-declared, and mostly cannot exercise their invariant

Caught in review after the rebuild. An invariant needs a case whose SHAPE can expose the
corresponding failure; a label asserting it proves nothing.

A minimum structural test — does the case even supply competing sources? — disqualifies
most of them:

    B7_NO_RECENCY_AS_AUTHORITY       5/5 unusable   all single-source or same-date
    B8_QUESTION_RELATIVE_AUTHORITY   4/5 unusable   single-source comparisons
    B3_UNRESOLVED_IS_VALID           1/4 unusable

Not one B7 case can present a recency/authority conflict, so a Historian with a broken
"newer wins" rule passes all five. And this is only the NECESSARY condition. Sufficiency is
stronger: B7 needs the newer source to be the wrong authority; B8 needs authority that
genuinely flips with the question.

**This is the same defect the structural layer spent seven rounds eliminating** —
`verified_by` before the trigger, `packet_hash` before it was computed,
`explicitly_specified` before it moved onto `Question`. A field the author fills in, with
nothing verifying it, and a calculation downstream that trusts it.

### The audit each case must pass

> What specific wrong Historian behaviour could this case expose?

    B1  must make relation-by-absence tempting
    B2  must contain ordering that could be mistaken for authority
    B3  must genuinely permit a correct unresolved outcome
    B4  must have a genuinely resolvable outcome, so abstention is wrong
    B5  must require an inferential routing/frame decision
    B6  must actually exercise the closed frame taxonomy
    B7  must present a recency/authority conflict
    B8  must contain competing evidence whose authority depends on the question

"The JSON says this case defends B7" is not an answer. Until a case passes this, it is a
candidate, not coverage.

## 4. Closure

The pilot is closed. Grinding through 17 small batches for adequacy verdicts from an
adjudicator structurally barred from gold is not worth the operator time, and the transport
is unreliable at any size that makes it bearable.

    queue                 REBUILT, 20 cases, whole documents
    invariant assignment  8/8 represented in the candidate queue
    behavioural coverage  0/8 VALIDATED
    case-invariant audit  NOT DONE - see below
    pilot                 CLOSED
    gold                  0
    coverage              0
    B1-B8                 0/2
    acceptance            SUITE INCOMPLETE

When a real adjudicator is available they get the file through a channel that demonstrably
delivers it, and a content-based receipt check before any verdict is recorded.
