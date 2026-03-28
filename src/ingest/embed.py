"""Generate embeddings for commit messages using Nomic Embed Text v2.

Uses sentence-transformers for local CPU inference. Batches commits
for throughput and yields (hash, embedding) pairs.
"""

import logging
from typing import Iterator

import numpy as np
from numpy.typing import NDArray

logger = logging.getLogger(__name__)

# Lazy-loaded model singleton
_model = None


def _get_model():
    """Load the embedding model on first use."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        from src.utils.config import EMBEDDING_MODEL

        logger.info("Loading embedding model: %s", EMBEDDING_MODEL)
        _model = SentenceTransformer(EMBEDDING_MODEL, trust_remote_code=True)
        logger.info("Model loaded.")
    return _model


def embed_texts(
    texts: list[str],
    *,
    batch_size: int = 256,
    prefix: str = "search_document: ",
) -> NDArray[np.float32]:
    """Embed a list of texts, returning an (N, 768) float32 array.

    Nomic v2 requires a task prefix: 'search_document:' for indexing,
    'search_query:' for queries.
    """
    model = _get_model()
    prefixed = [prefix + t for t in texts]
    embeddings = model.encode(
        prefixed,
        batch_size=batch_size,
        show_progress_bar=False,
        normalize_embeddings=True,
    )
    return embeddings  # type: ignore[return-value]


def embed_query(text: str) -> NDArray[np.float32]:
    """Embed a single query string. Returns a (768,) vector."""
    result = embed_texts([text], prefix="search_query: ")
    return result[0]


def format_commit_text(subject: str, body: str) -> str:
    """Format a commit message for embedding."""
    if body:
        return f"{subject}\n{body}"
    return subject


def embed_commits_batched(
    commits: Iterator[tuple[str, str, str]],
    *,
    batch_size: int = 256,
) -> Iterator[tuple[str, NDArray[np.float32]]]:
    """Embed commit messages in batches.

    Parameters
    ----------
    commits:
        Iterator of (hash, subject, body) tuples.
    batch_size:
        Number of commits per embedding batch.

    Yields
    ------
    (hash, embedding) pairs.
    """
    batch_hashes: list[str] = []
    batch_texts: list[str] = []

    for hash_, subject, body in commits:
        batch_hashes.append(hash_)
        batch_texts.append(format_commit_text(subject, body))

        if len(batch_texts) >= batch_size:
            embeddings = embed_texts(batch_texts, batch_size=batch_size)
            for h, emb in zip(batch_hashes, embeddings):
                yield h, emb
            batch_hashes.clear()
            batch_texts.clear()

    # Final partial batch
    if batch_texts:
        embeddings = embed_texts(batch_texts, batch_size=batch_size)
        for h, emb in zip(batch_hashes, embeddings):
            yield h, emb


if __name__ == "__main__":
    from src.utils.logging import setup_logging

    setup_logging()

    # Quick smoke test: embed a few strings
    texts = [
        "sched: Fix race in task migration",
        "mm: Add huge page support for ARM64",
        "net: Fix TCP retransmission timeout calculation",
    ]
    embeddings = embed_texts(texts)
    print(f"Shape: {embeddings.shape}")
    print(f"Dtype: {embeddings.dtype}")
    # Cosine similarity between first two (should be < 1.0 since they differ)
    sim = np.dot(embeddings[0], embeddings[1])
    print(f"Similarity(sched, mm): {sim:.4f}")
    sim2 = np.dot(embeddings[0], embeddings[2])
    print(f"Similarity(sched, net): {sim2:.4f}")
