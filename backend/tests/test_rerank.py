"""Reranker score cache (providers/rerank.py): the model loads only for scores the cache lacks."""

from __future__ import annotations

from contract_extraction.providers.rerank import FastEmbedReranker, ScoreCache


class FakeEncoder:
    def __init__(self):
        self.calls: list[list[str]] = []

    def rerank(self, query, texts, batch_size):
        self.calls.append(list(texts))
        return [float(len(t)) for t in texts]


def test_scores_are_cached_across_processes_and_the_model_loads_lazily(tmp_path, monkeypatch):
    first = FastEmbedReranker("m", ScoreCache(tmp_path / "s.sqlite"))
    encoder = FakeEncoder()
    loads = []
    monkeypatch.setattr(first, "_load", lambda: loads.append(1) or encoder)
    assert first.score("q", []) == [] and not loads
    assert first.score("q", ["aa", "bbb"]) == [2.0, 3.0]
    assert first.score("q", ["bbb", "c"]) == [3.0, 1.0] and encoder.calls == [["aa", "bbb"], ["c"]] and loads == [1]

    second = FastEmbedReranker("m", ScoreCache(tmp_path / "s.sqlite"))  # another worker process
    monkeypatch.setattr(second, "_load", lambda: (_ for _ in ()).throw(AssertionError("model loaded")))
    assert second.score("q", ["c", "aa"]) == [1.0, 2.0], "every score cached: the model never loads"

    other = FastEmbedReranker("other-model", ScoreCache(tmp_path / "s.sqlite"))
    monkeypatch.setattr(other, "_load", lambda: encoder)
    other.score("q", ["aa"])
    assert encoder.calls[-1] == ["aa"], "scores are per model"
