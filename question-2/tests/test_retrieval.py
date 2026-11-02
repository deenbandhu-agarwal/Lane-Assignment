"""Chunker, BM25, flat cosine, RRF and the hybrid retriever (fake embedder, offline)."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from agent.retrieval.bm25 import BM25, tokenize
from agent.retrieval.chunker import chunk_document, load_corpus
from agent.retrieval.embedders import FakeEmbedder
from agent.retrieval.index import Mode, Retriever
from agent.retrieval.rrf import rrf
from agent.retrieval.vectors import VectorIndex

CORPUS = Path(__file__).resolve().parents[1] / "corpus"

DOC = """---
title: Release policy
date: 2024-03-12
---
# Release policy

## Merging
Every pull request needs 1 approval.

## Hotfixes
Hotfixes may ship on any day.
"""


# -- chunker -----------------------------------------------------------------------


def test_chunks_follow_headings_and_carry_date():
    chunks = chunk_document("rp.md", DOC)
    assert [c.id for c in chunks] == ["rp.md#1", "rp.md#2"]
    assert [c.heading for c in chunks] == ["Merging", "Hotfixes"]
    assert all(c.date == "2024-03-12" and c.title == "Release policy" for c in chunks)
    assert chunks[0].text.startswith("Release policy > Merging\n")


def test_long_section_is_windowed_with_overlap():
    words = [f"w{i}" for i in range(500)]
    doc = "## Big\n" + " ".join(words)
    chunks = chunk_document("big.md", doc, max_words=200, overlap=50)
    bodies = [c.text.split("\n", 1)[1].split() for c in chunks]
    assert len(chunks) == 3
    assert bodies[0][-50:] == bodies[1][:50]  # neighbours share 50 words
    assert {w for b in bodies for w in b} == set(words)  # nothing lost


def test_bad_overlap_rejected():
    with pytest.raises(ValueError):
        chunk_document("x.md", DOC, max_words=10, overlap=10)


def test_corpus_loads_with_unique_ids_and_dates():
    chunks = load_corpus(CORPUS)
    assert len({c.doc for c in chunks}) == 15
    assert len({c.id for c in chunks}) == len(chunks)
    assert all(c.date for c in chunks)


# -- BM25 --------------------------------------------------------------------------


def test_tokenize_drops_stopwords_and_strips_plurals():
    assert tokenize("What are the approvals for policies?") == ["approval", "policy"]


def test_bm25_rare_term_wins():
    docs = ["error E4012 token expired", "error E5031 ledger timeout", "error error error"]
    (best, _), *_ = BM25(docs).search("what is E4012", 3)
    assert best == 0


def test_bm25_idf_matches_formula():
    bm = BM25(["a x", "b x", "c y"])
    # "y" in 1 of 3 docs: ln(1 + (3 - 1 + 0.5) / (1 + 0.5))
    assert bm._idf["y"] == pytest.approx(math.log(1 + 2.5 / 1.5))


def test_bm25_no_match_returns_nothing():
    assert BM25(["alpha beta", "gamma"]).search("zeta", 5) == []


# -- vectors + RRF -------------------------------------------------------------------


def test_flat_cosine_ranks_nearest_first():
    idx = VectorIndex(np.array([[1, 0], [0, 1], [1, 1]], dtype=np.float32))
    ranked = idx.search(np.array([1, 0.1]), 3)
    assert [i for i, _ in ranked] == [0, 2, 1]
    assert ranked[0][1] == pytest.approx(1 / math.sqrt(1.01), rel=1e-5)


def test_rrf_worked_example():
    # From the design discussion: A is (1st, 3rd), B is (4th, 1st), C is (2nd, 9th).
    bm25 = ["A", "C", "x1", "B"]
    vec = ["B", "x2", "A", "x3", "x4", "x5", "x6", "x7", "C"]
    fused = dict(rrf([bm25, vec]))
    assert fused["A"] == pytest.approx(1 / 61 + 1 / 63)
    assert fused["B"] == pytest.approx(1 / 64 + 1 / 61)
    assert fused["C"] == pytest.approx(1 / 62 + 1 / 69)
    assert [k for k, _ in rrf([bm25, vec])][:3] == ["A", "B", "C"]


# -- retriever ---------------------------------------------------------------------


@pytest.fixture(scope="module")
def chunks():
    return load_corpus(CORPUS)


@pytest.mark.parametrize("mode", list(Mode))
def test_exact_error_code_found_in_every_mode(chunks, mode):
    hits = Retriever(chunks, FakeEmbedder(), mode=mode).search("What does E4012 mean?", 5)
    assert "error-codes.md#2" in [h.chunk.id for h in hits]


def test_both_contradicting_policies_are_retrieved(chunks):
    hits = Retriever(chunks, FakeEmbedder()).search("How many approvals to merge a pull request?", 5)
    docs = {h.chunk.doc for h in hits}
    assert {"release-policy-2024-03.md", "release-policy-2025-06.md"} <= docs


def test_unrelated_query_returns_nothing(chunks):
    assert Retriever(chunks, FakeEmbedder()).search("What was on the 2023 product roadmap?", 5) == []


def test_embedding_cache_is_reused_and_keyed_by_corpus(chunks, tmp_path):
    class Counting(FakeEmbedder):
        calls = 0

        def embed_documents(self, texts):
            Counting.calls += 1
            return super().embed_documents(texts)

    Retriever(chunks, Counting(), cache_dir=tmp_path)
    Retriever(chunks, Counting(), cache_dir=tmp_path)
    assert Counting.calls == 1
    Retriever(chunks[:-1], Counting(), cache_dir=tmp_path)  # corpus changed -> re-embed
    assert Counting.calls == 2
