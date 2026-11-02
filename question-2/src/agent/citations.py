"""Check the final answer's citations against what tools actually returned in this run.

- Cited ids that no tool returned are "unsupported", and so are citation-like tokens
  that are no valid id (e.g. [list_pulls#0]): they cannot be checked.
- If the run found no evidence at all and the answer still cites something, the answer
  is replaced with the not-found message: it can only be invented.
- If there was evidence but some citations are unsupported, a warning is appended.
Recognised citation forms: [file.md#3], [issue#12], [pr#7]; several may share brackets.
Text is normalised first (see normalize) so models that emit 【】 or no-break spaces still parse.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

NOT_FOUND = "I couldn't find that in the notes or the repo."

_BRACKET = re.compile(r"\[([^\[\]]+)\]")
_ID = re.compile(r"^(?:[\w.-]+\.(?:md|txt)#\d+|issue#\d+|pr#\d+)$")


_DASHES = dict.fromkeys(map(ord, "\u2010\u2011\u2012\u2013\u2014\u2212"), "-")
_BRACKETS = {ord("\u3010"): "[", ord("\u3011"): "]"}  # 【 】, used by some models


def normalize(text: str) -> str:
    """NFKC (no-break spaces -> space), unicode dashes -> '-', lenticular brackets -> []."""
    return unicodedata.normalize("NFKC", text).translate(_DASHES).translate(_BRACKETS)


def _tokens(answer: str) -> list[str]:
    return [
        part.strip().lower().replace(" ", "")
        for group in _BRACKET.findall(normalize(answer))
        for part in re.split(r"[,;]", group)
    ]


def cited_ids(answer: str) -> set[str]:
    return {t for t in _tokens(answer) if _ID.match(t)}


def malformed_cites(answer: str) -> set[str]:
    """Bracketed tokens that look like citations (contain '#') but are no valid id,
    e.g. [list_pulls#0]. They cannot be checked, so they count as unsupported."""
    return {t for t in _tokens(answer) if "#" in t and not _ID.match(t)}


def evidence_ids(tool: str, data: Any) -> set[str]:
    """Ids a successful tool result makes citable."""
    if not data:
        return set()
    if tool == "search_notes":
        return {r["chunk_id"].lower() for r in data.get("results", [])}
    if tool in ("list_issues", "get_issue"):
        items = data if isinstance(data, list) else [data]
        return {f"issue#{i['number']}" for i in items if "number" in i}
    if tool in ("list_pulls", "get_pull"):
        items = data if isinstance(data, list) else [data]
        ids = {f"pr#{p['number']}" for p in items if "number" in p}
        ids |= {f"issue#{p['linked_issue']}" for p in items if p.get("linked_issue")}
        return ids
    return set()


@dataclass(frozen=True)
class CitationCheck:
    answer: str
    cited: set[str]
    unsupported: set[str]
    replaced: bool


def check_answer(answer: str, evidence: set[str]) -> CitationCheck:
    cited = cited_ids(answer)
    unsupported = (cited - evidence) | malformed_cites(answer)
    if unsupported and not evidence:
        return CitationCheck(NOT_FOUND, cited, unsupported, replaced=True)
    if unsupported:
        note = ", ".join(sorted(unsupported))
        answer += (
            f"\n\n(Warning: these citations were not returned by any tool in this run "
            f"and may be wrong: {note})"
        )
    return CitationCheck(answer, cited, unsupported, replaced=False)
