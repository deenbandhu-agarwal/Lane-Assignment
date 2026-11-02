"""search_notes: hybrid search over the team notes."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from agent.retrieval.index import Retriever
from agent.tools.registry import Tool


class SearchNotesArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=500, description="What to look for, in plain words")
    k: int = Field(5, ge=1, le=10, description="How many chunks to return")


def notes_tool(retriever: Retriever) -> Tool:
    def search(a: SearchNotesArgs) -> dict:
        hits = retriever.search(a.query, a.k)
        if not hits:
            return {"status": "no_relevant_results", "results": []}
        return {
            "status": "ok",
            "results": [
                {
                    "chunk_id": h.chunk.id,
                    "title": h.chunk.title,
                    "date": h.chunk.date,
                    "text": h.chunk.text,
                }
                for h in hits
            ],
        }

    return Tool(
        "search_notes",
        "Search the team's internal notes (policies, runbooks, ownership, on-call, error codes). "
        "Returns chunks with chunk_id and the note's date; cite chunk_ids in your answer.",
        SearchNotesArgs,
        search,
    )
