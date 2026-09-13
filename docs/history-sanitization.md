# History sanitization status

PR #16 was merged and its separately authorized history operation was performed on
2026-09-13. No replacement release or tag has been created.

## Completed repository operations

- Rewrote all 16 writable branches with git-filter-repo 2.47.0 and an atomic push
  guarded by the recorded previous ref values. Existing branch work was preserved.
- Processed 47 commits; 45 remain after empty-commit pruning. Removed 49 sensitive
  file versions and redacted 38 other versions. Git author/committer identities were
  preserved. The merged application tree was byte-for-byte identical after rewriting.
- Removed all three old tags and both old releases, including their downloadable assets.
- Removed all 46 pre-scrub workflow runs and their logs/artifacts. New CI evidence must
  be generated against sanitized commits; old evidence cannot be relabeled.
- Scanned every retained historical tree in the rewrite. No unresolved findings remained.
  Three exact historical test-blob matches were reviewed as synthetic: two deliberately
  invalid authentication values and one constructed export fixture. They were retained;
  the public-source guard itself was not weakened or given exemptions.
- Checked out the sanitized code independently: 267 core tests passed; 34 deployment
  tests require the isolated CI container. The application, Persistence v1 catalog and
  libSQL profile v3 were not changed by the scrub.

## Remaining GitHub exposure — release blocker

GitHub still advertises 16 closed pull-request refs pointing into old history. An old
commit was also retrievable through the commit API after the branch rewrite. These are
hosting-service references and caches outside the writable branch/tag namespace.

Repository-owner Git operations cannot establish complete deletion while those refs
remain. GitHub Support must remove affected cached views/references and perform the
required server cleanup. A support request has been prepared separately for the owner;
it contains the affected ref inventory and first-changed commit identifiers without
reproducing source contents. No support request has been submitted by this operation.

Do not create a new release/tag until the Support cleanup is resolved and verified.
Afterward verify advertised refs, old commit access, a fresh clone and all downloadable
assets, then resume representative real-corpus validation.

## Existing clones

Re-clone before contributing. A push or merge from an old clone can reintroduce removed
history. A restricted local recovery mirror is retained for audit; it is not a release
source. Rewriting GitHub history cannot recall copies downloaded before the scrub.
