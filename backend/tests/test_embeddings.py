import math
import sys
from types import ModuleType

import pytest

from app.models.document_chunk import EMBEDDING_DIMENSION
from app.services import embeddings
from app.services.embeddings import EmbeddingError, LocalEmbeddingService


class FakeEncoder:
    def __init__(self, output):
        self.output = output
        self.calls = []

    def encode(self, texts, **kwargs):
        self.calls.append((texts, kwargs))
        return self.output


def test_batches_texts_and_normalizes_vectors():
    encoder = FakeEncoder([[3.0, 4.0] + [0.0] * (EMBEDDING_DIMENSION - 2)] * 2)
    service = LocalEmbeddingService("test-model", 8, encoder)

    vectors = service.embed_texts(["first", "second"])

    assert len(vectors) == 2
    assert len(vectors[0]) == EMBEDDING_DIMENSION
    assert math.isclose(math.sqrt(sum(value * value for value in vectors[0])), 1)
    assert encoder.calls[0][0] == ["first", "second"]
    assert encoder.calls[0][1]["batch_size"] == 8
    assert encoder.calls[0][1]["normalize_embeddings"] is True


def test_query_uses_the_same_embedding_path_and_dimension():
    encoder = FakeEncoder([[1.0] + [0.0] * (EMBEDDING_DIMENSION - 1)])
    service = LocalEmbeddingService("test-model", 4, encoder)

    vector = service.embed_query("query")

    assert len(vector) == EMBEDDING_DIMENSION
    assert vector[0] == 1.0


@pytest.mark.parametrize(
    "output",
    [
        [[1.0, 2.0]],
        [[float("nan")] + [0.0] * (EMBEDDING_DIMENSION - 1)],
        [[float("inf")] + [0.0] * (EMBEDDING_DIMENSION - 1)],
        [[0.0] * EMBEDDING_DIMENSION],
        [],
    ],
)
def test_invalid_or_incomplete_embedding_output_is_rejected(output, caplog):
    service = LocalEmbeddingService("test-model", 8, FakeEncoder(output))

    with pytest.raises(EmbeddingError):
        service.embed_texts(["input"])
    assert "stage=embedding_validation" in caplog.text
    assert "expected_dimension=384" in caplog.text
    assert "input" not in caplog.text


def test_empty_batch_does_not_load_model():
    service = LocalEmbeddingService("missing-model", 8)

    assert service.embed_texts([]) == []


def test_model_load_failure_is_safe(monkeypatch, caplog):
    calls = []

    class BrokenSentenceTransformer:
        def __init__(self, model_name, device):
            calls.append((model_name, device))
            raise OSError("synthetic model failure")

    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        ModuleType("sentence_transformers"),
    )
    sys.modules["sentence_transformers"].SentenceTransformer = (
        BrokenSentenceTransformer
    )
    embeddings._MODEL_CACHE.clear()
    service = LocalEmbeddingService("synthetic-model", 8)
    try:
        with pytest.raises(EmbeddingError) as error:
            service.embed_query("private query")
        assert error.value.category == "model_unavailable"
        assert "private query" not in str(error.value)
        assert calls == [("synthetic-model", "cpu")]
        assert "stage=embedding_model_initialization" in caplog.text
        assert "exception_class=OSError" in caplog.text
        assert "synthetic model failure" not in caplog.text
        assert "private query" not in caplog.text
    finally:
        embeddings._MODEL_CACHE.clear()


def test_model_is_loaded_once_for_multiple_service_instances(monkeypatch):
    calls = []

    class ReusableSentenceTransformer:
        def __init__(self, model_name, device):
            calls.append((model_name, device))

        def get_embedding_dimension(self):
            return EMBEDDING_DIMENSION

        def encode(self, texts, **_kwargs):
            return [[1.0] + [0.0] * (EMBEDDING_DIMENSION - 1) for _ in texts]

    module = ModuleType("sentence_transformers")
    module.SentenceTransformer = ReusableSentenceTransformer
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)
    embeddings._MODEL_CACHE.clear()
    try:
        first = LocalEmbeddingService("cached-model", 4).embed_query("one")
        second = LocalEmbeddingService("cached-model", 4).embed_query("two")

        assert first == second
        assert calls == [("cached-model", "cpu")]
    finally:
        embeddings._MODEL_CACHE.clear()
