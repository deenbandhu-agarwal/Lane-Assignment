"""Heading-aware chunker.

1. Read the front-matter (title, date) so every chunk carries its note's date.
2. Split the body at markdown headings: one section = one topic.
3. A section longer than max_words is cut into windows with `overlap` words shared
   between neighbours, so a sentence near a cut still has its context.
Chunk ids are stable and human-readable: "<file>#<n>", n counting from 1 per file.
Every chunk's text starts with "<title> > <heading>" so both BM25 and the embedder see it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_FRONT = re.compile(r"\A---\n(.*?)\n---\n", re.S)
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$", re.M)


@dataclass(frozen=True)
class Chunk:
    id: str
    doc: str
    title: str
    date: str
    heading: str
    text: str


def parse_front_matter(raw: str) -> tuple[dict[str, str], str]:
    m = _FRONT.match(raw)
    if not m:
        return {}, raw
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta, raw[m.end() :]


def _sections(body: str) -> list[tuple[str, str]]:
    """[(heading, text)], keeping text before the first heading under heading ''."""
    out: list[tuple[str, str]] = []
    marks = list(_HEADING.finditer(body))
    if not marks or marks[0].start() > 0:
        lead = body[: marks[0].start() if marks else len(body)].strip()
        if lead:
            out.append(("", lead))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(body)
        text = body[m.end() : end].strip()
        if text:
            out.append((m.group(2).strip(), text))
    return out


def _windows(words: list[str], size: int, overlap: int) -> list[list[str]]:
    if len(words) <= size:
        return [words]
    step = size - overlap
    return [words[i : i + size] for i in range(0, max(len(words) - overlap, 1), step)]


def chunk_document(
    name: str, raw: str, *, max_words: int = 220, overlap: int = 40
) -> list[Chunk]:
    if not 0 <= overlap < max_words:
        raise ValueError("need 0 <= overlap < max_words")
    meta, body = parse_front_matter(raw)
    title = meta.get("title", name)
    date = meta.get("date", "")
    chunks: list[Chunk] = []
    for heading, text in _sections(body):
        if heading == title and not text:
            continue
        for window in _windows(text.split(), max_words, overlap):
            label = f"{title} > {heading}" if heading and heading != title else title
            chunks.append(
                Chunk(
                    id=f"{name}#{len(chunks) + 1}",
                    doc=name,
                    title=title,
                    date=date,
                    heading=heading,
                    text=f"{label}\n{' '.join(window)}",
                )
            )
    return chunks


def load_corpus(directory: Path, **kw: int) -> list[Chunk]:
    chunks: list[Chunk] = []
    for path in sorted(Path(directory).glob("*.md")) + sorted(Path(directory).glob("*.txt")):
        chunks += chunk_document(path.name, path.read_text(encoding="utf-8"), **kw)
    return chunks
