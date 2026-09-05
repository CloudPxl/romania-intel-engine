"""Read access to the ingested procurement legislation.

Backs the citations shown next to a generated document and lets the
copilot answer "which article actually says that" from the consolidated
text instead of from the model's recollection — which is where wrong
article numbers come from. Search is public because the law is public;
nothing here touches user data.
"""
from typing import Optional

from fastapi import APIRouter, Query

import legal_kb

router = APIRouter(prefix="/api/v1/legal", tags=["Legal"])


@router.get("/status")
def legal_kb_status():
    """What has been ingested, and when.

    `available: false` means scripts/build_legal_kb.py has not been run —
    documents still generate, just without quoted statutory text.
    """
    return legal_kb.stats()


@router.get("/topics")
def legal_topics():
    """The curated index: product concept -> the articles governing it."""
    return {
        "topics": [
            {"id": key, "label": spec["label"], "note": spec["note"], "articles": spec["articles"]}
            for key, spec in legal_kb.TOPICS.items()
        ]
    }


@router.get("/topic/{topic_id}")
def legal_topic(topic_id: str):
    return legal_kb.topic(topic_id)


@router.get("/search")
def legal_search(
    q: str = Query(..., min_length=3, max_length=120),
    law: Optional[str] = Query(None, description="Restrânge la o lege, ex. L98/2016"),
    limit: int = Query(8, ge=1, le=25),
):
    """Substring search across the corpus. Repealed articles are excluded —
    a search for a concept must not surface the dead provision that used to
    carry it (Art. 6 of Legea 101/2016 being the trap this avoids)."""
    return {
        "query": q,
        "results": legal_kb.search(q, law_keys=[law] if law else None, limit=limit),
    }
