from atlas.acquisition.repository import Repository
from atlas.knowledge.base import KnowledgeBase, ParsedDocument


def parse_incremental(repo: Repository, kb: KnowledgeBase) -> list[ParsedDocument]:
    """Parse catalog entries not yet successfully extracted.

    Skips entries with status='ok'. Retries entries with status='failed'
    on every call, including those that previously had no registered extractor,
    so adding a new extractor to _EXTRACTORS is sufficient to unblock them.
    """
    ok = kb.ok_ids()
    results: list[ParsedDocument] = []
    for entry in repo.list_evidence():
        if entry.evidence_id not in ok:
            results.append(kb.parse(entry))
    return results
