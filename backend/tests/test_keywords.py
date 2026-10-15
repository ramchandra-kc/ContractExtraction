from __future__ import annotations

import uuid
import zlib

from contract_extraction.indexing import keywords
from contract_extraction.indexing.keywords import HEADING_BOOST, K1, doc_vector, length, query_vector, term_id, terms
from contract_extraction.providers.base import Point
from contract_extraction.providers.memory import MemoryStore


def test_terms_are_stemmed_without_stop_words():
    assert terms("All contracting Parties and their roles") == ["contract", "parti", "role"]
    assert terms("party") == terms("Parties"), "plural and singular match"
    assert terms("the and of") == []


def test_term_ids_are_stable():
    assert term_id("parti") == zlib.crc32(b"parti"), "the same id in every process"
    assert query_vector("Parties party").indices == [term_id("parti")], "repeated query terms count once"
    assert query_vector("the of").indices == []


def test_doc_vector_weights_follow_bm25():
    [weight] = doc_vector("party", "", avgdl=1.0).values
    assert weight == (K1 + 1) / (1 + K1), "one occurrence in an average-length chunk"
    short, long = doc_vector("party", "", 4.0).values[0], doc_vector("party fee fee fee", "", 4.0).values[0]
    assert short > long, "the same term weighs more in a shorter chunk"


def test_heading_terms_are_boosted():
    assert length("Parties\nName: Acme Pty Ltd", "Parties") == length("Parties\nName: Acme Pty Ltd") + HEADING_BOOST - 1
    def weight(v, term):
        return dict(zip(v.indices, v.values, strict=True))[term_id(term)]

    titled, mention = doc_vector("Parties\nName: Acme", "Parties", 4.0), doc_vector("the parties agree to pay", "", 4.0)
    assert weight(titled, "parti") > weight(mention, "parti")


def test_rare_terms_rank_first():
    """Through the memory store: 'contract' is in most chunks, so the chunk titled 'Parties' wins."""
    texts = [("Parties\nName: Acme Rail Pty Ltd\nName: Widget Services Pty Ltd", "Parties"),
             ("Each party must remedy a breach of this contract within 30 days of notice.", ""),
             ("The contract price is payable monthly under this contract.", ""),
             ("This contract is governed by the laws of New South Wales.", ""),
             ("Variations to the contract must be in writing.", "")]
    avgdl = sum(length(t, h) for t, h in texts) / len(texts)
    store = MemoryStore()
    store.ensure_collection("c", 1, "cosine")
    ids = [uuid.uuid4() for _ in texts]
    store.upsert("c", [Point(i, [1.0], {}, keywords.doc_vector(t, h, avgdl)) for i, (t, h) in zip(ids, texts, strict=True)])
    hits = store.keyword_search("c", query_vector("All contracting parties and their roles"), 5)
    assert hits[0].id == ids[0]
