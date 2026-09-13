# Synthetic case examples

All source text and questions in this directory are invented public fixtures.
The observatory and recycling scenarios are not renamed private conversations.
The queue supplies two distinct scenario families per behavioral invariant. Shape checks
are necessary conditions only; outcome checks remain in the behavioral contract suite.
Neither is independently adjudicated gold or representative real-corpus validation.

Run `python cases/audit_queue.py` and `python -m pytest tests/test_synthetic_cases.py`.
The staged `build_queue.py` service client is retained. For a synthetic plan use:

```sh
python cases/build_queue.py --run-id synthetic-example --corpus cases/synthetic
```

Keep operator queues, exports, rendered packets, audit reports and adjudication results
outside this repository. The public-release guard restricts this directory to these
reviewed files. The removed archive still requires a separate history scrub.
