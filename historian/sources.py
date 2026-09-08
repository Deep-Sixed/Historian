"""Read-only source adapters, keyed by source system.

The database cannot read RAG v1, so it enforces WHO may create evidence while a reader
here supplies WHAT the source says. Both halves are required and neither substitutes for
the other — see the trusted-computing-base note in GATE-MAPPING.md.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

# A RAG v1 document id is a corpus filename stem: YYYY-MM-DD followed by a slug. Anything
# else - a separator, a parent reference, an absolute path - is rejected before it can
# reach the filesystem, because source_id originates in an EvidenceCandidate that a model
# may write.
DOCUMENT_ID = re.compile(r"\A\d{4}-\d{2}-\d{2}-[A-Za-z0-9._-]+\Z")


class SourceUnavailable(RuntimeError):
    """No reader is registered for this source system."""


class RagV1SourceReader:
    """Reads the RAG v1 markdown corpus by document id, version and line span.

    `source_id` is the document id (the corpus filename stem, matching RAG v1's
    document_id metadata). `version_hash` is the sha256 of the whole file, so a reference
    pins one immutable revision: we have a live case where a document's indexed
    representation differs from the original archive, and line 800 need not denote the
    same text across revisions.
    """

    source_system = "RAG_V1"

    def __init__(self, corpus_dir: str | Path):
        self._dir = Path(corpus_dir).resolve()

    def _path(self, source_id: str) -> Path | None:
        """Resolve inside the corpus, or None. Containment is checked, not assumed.

        A model-proposed id like '../../other-project/x' must never cause the TRUSTED
        verifier to read outside the corpus. The trust boundary cannot depend on which
        files happen to exist on disk today.
        """
        if not DOCUMENT_ID.fullmatch(source_id or ""):
            return None
        p = (self._dir / f"{source_id}.md").resolve()
        if p.parent != self._dir:          # belt and braces after the pattern check
            return None
        return p if p.is_file() else None

    def version_of(self, source_id: str) -> str | None:
        p = self._path(source_id)
        return hashlib.sha256(p.read_bytes()).hexdigest() if p else None

    def read_lines(self, source_id: str, version_hash: str,
                   start: int, end: int) -> str | None:
        """Exact text of lines start..end, or None if anything fails to match.

        Returns None — not a best effort, not an exception — for a rejected id, a missing
        document, a version mismatch or an out-of-range span. A verifier must fail CLOSED:
        "I could not confirm this" and "this is what it says" must never share a return
        value.
        """
        p = self._path(source_id)
        if p is None:
            return None
        raw = p.read_bytes()
        if hashlib.sha256(raw).hexdigest() != version_hash:
            return None
        lines = raw.decode(errors="replace").splitlines(keepends=True)
        if start < 1 or end > len(lines) or end < start:
            return None
        return "".join(lines[start - 1:end])


class SourceRegistry:
    """Dispatches to the reader for a candidate's declared source system.

    Without this, `source_system` is a LABEL rather than a routing decision: a candidate
    claiming LEDGER while naming a real RAG document id would be verified against RAG
    bytes, succeed, and persist LEDGER provenance — with the candidate FK faithfully
    preserving the wrong answer. The label must select the backend that supplies the bytes.
    """

    def __init__(self, *readers):
        """Readers are POSITIONAL. The key is taken FROM each reader, never supplied
        beside it.

        A keyword form - SourceRegistry(LEDGER=rag_reader) - would let the registry itself
        lie about which backend it registered: the lookup would resolve LEDGER, the RAG
        reader would supply the bytes, and the EvidenceRef would record LEDGER. That is the
        same defect the dispatch was added to close, moved one layer out. A structurally
        correct binding can still propagate a bad value from upstream, so the key must be
        derived rather than declared.
        """
        self._readers: dict[str, object] = {}
        for reader in readers:
            source_system = getattr(reader, "source_system", None)
            if not source_system:
                raise ValueError(
                    f"{type(reader).__name__} declares no source_system; a reader that "
                    f"cannot say what it reads cannot be routed to")
            if source_system in self._readers:
                raise ValueError(f"duplicate reader for source system {source_system!r}")
            self._readers[source_system] = reader

    def reader_for(self, source_system: str):
        r = self._readers.get(source_system)
        if r is None:
            raise SourceUnavailable(
                f"no reader registered for source system {source_system!r}; "
                f"registered: {sorted(self._readers)}")
        return r
