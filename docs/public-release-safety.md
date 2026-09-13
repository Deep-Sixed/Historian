# Public-release safety

Historian is public. Supported source examples must be invented synthetic fixtures.
Operator exports, source-derived questions, queues, rendered packets, audit reports,
personal identifiers, deployment details and credentials belong outside Git.

PR #16 removes the legacy case archive and replaces the source-readability, unrouted
adjudication and case-shape checks with synthetic observatory/recycling fixtures. The
B1–B8 behavioral contract and Persistence v1 obligations are unchanged. Synthetic
coverage does not establish representative real-corpus performance or human gold.

Run `python scripts/public_release_guard.py`. CI scans the checked-out tree and preserves
its JSON report. The guard checks hashed known private markers, identifier patterns,
home paths, private-network addresses, credential patterns and prohibited file classes.
It rejects unapproved files under `cases/`, binary data and symlinks. It prints locations
and rule names, never matching values. No file-content exemptions are applied to the
scanner or its tests. Newly approved synthetic cases require review and an explicit
allowlist change. Pattern scanning cannot establish that all arbitrary prose is public;
review fixture provenance as well as the automated report.

For a distribution, extract it into an isolated directory and run the guard with
`--tree DIRECTORY`. The packaging job scans both the wheel and source distribution.
Build outputs are not source fixtures and must not be committed.

## Separate history operation — pending approval of PR #16

Cleaning a branch tip does not clean old commits, tags, pull-request refs or releases.
Do not represent this PR as removal of historical exposure. After approval:

1. Inventory remote branches, tags, pull-request refs and release assets in a restricted
   local mirror. Keep any recovery copy private and outside the public repository.
2. Rewrite every affected branch/tag using a reviewed path/content removal map. Remove
   the legacy corpus archive throughout history; retain only independently synthetic
   replacements at the new tip. Scan each distinct resulting tree, including old tags.
3. Replace affected remote refs with the reviewed rewrite and remove obsolete refs.
   Address GitHub-retained pull-request refs and cached views separately; repository
   owners may need GitHub Support to remove inaccessible historical references.
4. Remove affected old release assets. Rebuild any retained source/distribution assets
   from sanitized commits, regenerate checksums, and rerun conformance. Old evidence
   bound to old commit SHAs cannot be relabeled as evidence for rewritten commits.
5. Verify a fresh remote clone and every downloadable release asset. Record unresolved
   caches/forks explicitly; request collaborator re-clones to avoid reintroducing history.

If credentials are discovered, revoke/rotate them separately; removing Git objects does
not invalidate credentials. History rewriting cannot recall copies already downloaded.
Resume real-corpus validation, capacity measurement and recovery drills after the scrub.
