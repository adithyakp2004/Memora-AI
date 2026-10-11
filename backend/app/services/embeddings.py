import logging
import math
from functools import lru_cache
from threading import Lock
from typing import Protocol

from app.core.config import settings
from app.models.document_chunk import EMBEDDING_DIMENSION

logger = logging.getLogger(__name__)
_MODEL_CACHE: dict[str, object] = {}
_MODEL_CACHE_LOCK = Lock()


class EmbeddingError(RuntimeError):
    def __init__(self, category: str = "model_unavailable") -> None:
        super().__init__("The local embedding model is unavailable.")
        self.category = category


class TextEncoder(Protocol):
    def encode(self, texts: list[str], batch_size: int) -> list[list[float]]: ...


def _load_sentence_transformer(model_name: str):
    with _MODEL_CACHE_LOCK:
        if model_name in _MODEL_CACHE:
            return _MODEL_CACHE[model_name]
        return _load_sentence_transformer_once(model_name)


def _load_sentence_transformer_once(model_name: str):
    stage = "embedding_model_initialization"
    logger.info(
        "Embedding stage started stage=%s expected_dimension=%d",
        stage,
        EMBEDDING_DIMENSION,
    )
    try:
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(model_name, device="cpu")
        get_dimension = getattr(model, "get_embedding_dimension", None)
        if get_dimension is None:
            get_dimension = model.get_sentence_embedding_dimension
        dimension = get_dimension()
        if dimension != EMBEDDING_DIMENSION:
            logger.error(
                "Embedding stage failed stage=%s exception_class=%s "
                "expected_dimension=%d actual_dimension=%s",
                "embedding_model_validation",
                "EmbeddingError",
                EMBEDDING_DIMENSION,
                dimension,
            )
            raise EmbeddingError("dimension_mismatch")
        _MODEL_CACHE[model_name] = model
        logger.info(
            "Embedding stage completed stage=%s embedding_dimension=%d",
            stage,
            dimension,
        )
        return model
    except EmbeddingError:
        raise
    except Exception as exc:
        logger.error(
            "Embedding stage failed stage=%s exception_class=%s",
            stage,
            type(exc).__name__,
        )
        raise EmbeddingError() from None


class LocalEmbeddingService:
    def __init__(
        self,
        model_name: str,
        batch_size: int,
        encoder: TextEncoder | None = None,
    ) -> None:
        self.model_name = model_name
        self.batch_size = batch_size
        self._encoder = encoder

    def _get_encoder(self) -> TextEncoder:
        if self._encoder is None:
            self._encoder = _load_sentence_transformer(self.model_name)
        return self._encoder

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._get_encoder()
        stage = "embedding_generation"
        logger.info(
            "Embedding stage started stage=%s text_count=%d",
            stage,
            len(texts),
        )
        try:
            if hasattr(model, "encode"):
                vectors = model.encode(
                    texts,
                    batch_size=self.batch_size,
                    convert_to_numpy=True,
                    normalize_embeddings=True,
                    show_progress_bar=False,
                )
            else:
                vectors = model.embed_texts(texts)
        except TypeError:
            try:
                vectors = model.encode(texts, batch_size=self.batch_size)
            except Exception as exc:
                logger.error(
                    "Embedding stage failed stage=%s exception_class=%s "
                    "text_count=%d",
                    stage,
                    type(exc).__name__,
                    len(texts),
                )
                raise EmbeddingError("generation_failed") from None
        except Exception as exc:
            logger.error(
                "Embedding stage failed stage=%s exception_class=%s text_count=%d",
                stage,
                type(exc).__name__,
                len(texts),
            )
            raise EmbeddingError("generation_failed") from None

        actual_dimension: int | None = None
        try:
            rows = vectors.tolist() if hasattr(vectors, "tolist") else list(vectors)
            result = []
            for vector in rows:
                values = [float(value) for value in vector]
                actual_dimension = len(values)
                if actual_dimension != EMBEDDING_DIMENSION or not all(
                    math.isfinite(value) for value in values
                ):
                    raise ValueError("Invalid vector shape or values.")
                norm = math.sqrt(sum(value * value for value in values))
                if norm == 0:
                    raise ValueError("Zero vector.")
                result.append([value / norm for value in values])
            if len(result) != len(texts):
                raise ValueError("Embedding count does not match input count.")
            logger.info(
                "Embedding stage completed stage=embedding_validation text_count=%d "
                "embedding_dimension=%d",
                len(texts),
                EMBEDDING_DIMENSION,
            )
            return result
        except (TypeError, ValueError, OverflowError) as exc:
            logger.error(
                "Embedding stage failed stage=embedding_validation "
                "exception_class=%s text_count=%d "
                "expected_dimension=%d actual_dimension=%s",
                type(exc).__name__,
                len(texts),
                EMBEDDING_DIMENSION,
                actual_dimension,
            )
            raise EmbeddingError("invalid_output") from None

    def embed_query(self, query: str) -> list[float]:
        return self.embed_texts([query])[0]


@lru_cache(maxsize=4)
def _embedding_service(model_name: str, batch_size: int) -> LocalEmbeddingService:
    return LocalEmbeddingService(model_name, batch_size)


def get_embedding_service() -> LocalEmbeddingService:
    return _embedding_service(settings.embedding_model_name, settings.embedding_batch_size)
