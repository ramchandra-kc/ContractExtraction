from __future__ import annotations

import json
import uuid

import httpx
import pytest

from contract_extraction.domain.config import Model, ModelProfile, Provider
from contract_extraction.providers.base import Point, ProviderError
from contract_extraction.providers.memory import MemoryStore
from contract_extraction.providers.ollama import OllamaChat, OllamaEmbedder
from contract_extraction.providers.openai_compat import OpenAICompatChat, OpenAICompatEmbedder
from contract_extraction.providers.qdrant import QdrantStore

PROVIDER = Provider(id=uuid.uuid4(), key="p", kind="ollama", base_url="http://llm")
PROFILE = ModelProfile(
    id=uuid.uuid4(), name="extraction", temperature="0.2", top_p="0.2", top_k=20, num_ctx=8192, json_mode=True,
    model=Model(id=uuid.uuid4(), name="llama3.1:8b", kind="chat", provider=PROVIDER),
)


def _client(handler, base="http://llm") -> tuple[httpx.Client, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    return httpx.Client(base_url=base, transport=httpx.MockTransport(wrapped)), seen


def test_ollama_chat_request_and_usage():
    client, seen = _client(lambda r: httpx.Response(200, json={
        "message": {"content": '{"customer_name": "Acme"}'}, "prompt_eval_count": 120, "eval_count": 9}))
    result = OllamaChat("http://llm", client).complete("sys", "user", PROFILE)

    body = json.loads(seen[0].content)
    assert seen[0].url.path == "/api/chat"
    assert body["format"] == "json" and body["stream"] is False
    assert body["options"] == {"temperature": 0.2, "top_p": 0.2, "top_k": 20, "num_ctx": 8192}
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    assert result.text == '{"customer_name": "Acme"}'
    assert (result.prompt_tokens, result.completion_tokens) == (120, 9)
    assert result.params["model"] == "llama3.1:8b"


def test_ollama_errors_and_timeouts():
    client, _ = _client(lambda r: httpx.Response(500, text="model not found"))
    with pytest.raises(ProviderError, match="HTTP 500"):
        OllamaChat("http://llm", client).complete("s", "u", PROFILE)

    def boom(request):
        raise httpx.ReadTimeout("slow", request=request)

    client, _ = _client(boom)
    with pytest.raises(ProviderError) as info:
        OllamaChat("http://llm", client).complete("s", "u", PROFILE)
    assert info.value.timeout


def test_ollama_embed_batch():
    client, seen = _client(lambda r: httpx.Response(200, json={"embeddings": [[0.1, 0.2], [0.3, 0.4]]}))
    vectors = OllamaEmbedder("http://llm", "nomic", client).embed(["a", "b"])
    assert vectors == [[0.1, 0.2], [0.3, 0.4]]
    assert json.loads(seen[0].content) == {"model": "nomic", "input": ["a", "b"]}

    client, _ = _client(lambda r: httpx.Response(200, json={"embeddings": [[0.1]]}))
    with pytest.raises(ProviderError, match="expected 2"):
        OllamaEmbedder("http://llm", "nomic", client).embed(["a", "b"])


def test_openai_compatible_chat_and_embeddings():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/chat/completions"):
            return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}],
                                             "usage": {"prompt_tokens": 50, "completion_tokens": 2}})
        return httpx.Response(200, json={"data": [{"index": 1, "embedding": [2.0]}, {"index": 0, "embedding": [1.0]}]})

    client, seen = _client(handler, "https://openrouter.ai/api/v1")
    result = OpenAICompatChat("https://openrouter.ai/api/v1", "key", client).complete("s", "u", PROFILE)
    body = json.loads(seen[0].content)
    assert body["response_format"] == {"type": "json_object"} and body["model"] == "llama3.1:8b"
    assert (result.prompt_tokens, result.completion_tokens) == (50, 2)

    vectors = OpenAICompatEmbedder("https://openrouter.ai/api/v1", "key", "emb", client).embed(["a", "b"])
    assert vectors == [[1.0], [2.0]]


def test_qdrant_rest_calls():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path.endswith("/exists"):
            return httpx.Response(200, json={"result": {"exists": False}})
        if request.url.path.endswith("/points/search"):
            pid = str(uuid.uuid4())
            return httpx.Response(200, json={"result": [{"id": pid, "score": 0.9, "payload": {"page": 1}}]})
        return httpx.Response(200, json={"result": True})

    client, seen = _client(handler, "http://qdrant")
    store = QdrantStore("http://qdrant", client=client)
    store.ensure_collection("c", 3, "cosine")
    store.upsert("c", [Point(uuid.uuid4(), [1.0, 0.0, 0.0], {"text": "x"})])
    hits = store.search("c", [1.0, 0.0, 0.0], 5)

    assert calls[:3] == [("GET", "/collections/c/exists"), ("PUT", "/collections/c"), ("PUT", "/collections/c/points")]
    assert json.loads(seen[1].content) == {"vectors": {"size": 3, "distance": "Cosine"}}
    assert seen[2].url.params["wait"] == "true"
    assert hits[0].score == 0.9 and hits[0].payload == {"page": 1}


def test_memory_store_ranks_by_cosine():
    store = MemoryStore()
    store.ensure_collection("c", 2, "cosine")
    a, b = uuid.uuid4(), uuid.uuid4()
    store.upsert("c", [Point(a, [1.0, 0.0], {}), Point(b, [0.0, 1.0], {})])
    hits = store.search("c", [0.9, 0.1], 2)
    assert [h.id for h in hits] == [a, b]
    with pytest.raises(ProviderError):
        store.ensure_collection("c", 3, "cosine")
