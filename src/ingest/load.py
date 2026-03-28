"""Bulk load commit records and embeddings into PostgreSQL.

Uses COPY for high-throughput insertion. Designed to work with the
extract and embed pipeline stages.
"""

import io
import logging
from typing import Iterator

import numpy as np
import psycopg
from numpy.typing import NDArray

from src.ingest.embed import embed_texts, format_commit_text
from src.ingest.extract import CommitRecord
from src.utils.config import EMBEDDING_BATCH_SIZE, dsn

logger = logging.getLogger(__name__)


def _vector_literal(vec: NDArray[np.float32]) -> str:
    """Format a numpy vector as a pgvector literal: '[0.1,0.2,...]'."""
    return "[" + ",".join(f"{v:.8f}" for v in vec) + "]"


def _escape_copy(val: str | None) -> str:
    """Escape a value for COPY tab-delimited format."""
    if val is None:
        return r"\N"
    return val.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r")


def _array_literal(items: list[str]) -> str:
    """Format a Python list as a Postgres array literal for COPY."""
    if not items:
        return "{}"
    escaped = []
    for item in items:
        s = item.replace("\\", "\\\\").replace('"', '\\"')
        escaped.append(f'"{s}"')
    return "{" + ",".join(escaped) + "}"


def bulk_load_commits(
    commits: Iterator[CommitRecord],
    *,
    batch_size: int = EMBEDDING_BATCH_SIZE,
    embed: bool = True,
) -> int:
    """Load commits into the database, optionally embedding messages.

    Returns the number of rows inserted.
    """
    conn = psycopg.connect(dsn())
    total = 0

    try:
        batch: list[CommitRecord] = []

        for record in commits:
            batch.append(record)

            if len(batch) >= batch_size:
                total += _flush_batch(conn, batch, embed=embed)
                batch.clear()

        if batch:
            total += _flush_batch(conn, batch, embed=embed)

    finally:
        conn.close()

    logger.info("Loaded %d commits total.", total)
    return total


def _flush_batch(
    conn: psycopg.Connection,
    batch: list[CommitRecord],
    *,
    embed: bool,
) -> int:
    """Embed and COPY one batch of commits. Returns rows inserted."""
    embeddings: list[NDArray[np.float32] | None]

    if embed:
        texts = [format_commit_text(r.subject, r.body) for r in batch]
        emb_array = embed_texts(texts, batch_size=len(texts))
        embeddings = [emb_array[i] for i in range(len(batch))]
    else:
        embeddings = [None] * len(batch)

    # Build COPY data
    buf = io.StringIO()
    for record, emb in zip(batch, embeddings):
        fields = [
            _escape_copy(record.hash),
            _escape_copy(record.authored_date.isoformat()),
            _escape_copy(record.committed_date.isoformat()),
            _escape_copy(record.author_name),
            _escape_copy(record.author_email),
            _escape_copy(record.committer_name),
            _escape_copy(record.committer_email),
            _escape_copy(record.subject),
            _escape_copy(record.body or None),
            _escape_copy(_array_literal(record.files_changed)),
            str(record.insertions),
            str(record.deletions),
            "t" if record.merge else "f",
            _escape_copy(_vector_literal(emb) if emb is not None else None),
        ]
        buf.write("\t".join(fields) + "\n")

    buf.seek(0)
    columns = (
        "hash", "authored_date", "committed_date",
        "author_name", "author_email", "committer_name", "committer_email",
        "subject", "body", "files_changed", "insertions", "deletions",
        "merge", "msg_embedding",
    )

    with conn.cursor() as cur:
        with cur.copy(
            f"COPY commits ({','.join(columns)}) FROM STDIN"
        ) as copy:
            copy.write(buf.getvalue())
    conn.commit()

    count = len(batch)
    logger.info("Flushed batch of %d commits.", count)
    return count


def get_loaded_count(conn: psycopg.Connection | None = None) -> int:
    """Return the number of commits already in the database."""
    close = False
    if conn is None:
        conn = psycopg.connect(dsn())
        close = True
    try:
        row = conn.execute("SELECT count(*) FROM commits").fetchone()
        return row[0] if row else 0
    finally:
        if close:
            conn.close()


def get_last_loaded_hash(conn: psycopg.Connection | None = None) -> str | None:
    """Return the hash of the most recently authored commit in the DB."""
    close = False
    if conn is None:
        conn = psycopg.connect(dsn())
        close = True
    try:
        row = conn.execute(
            "SELECT hash FROM commits ORDER BY authored_date DESC LIMIT 1"
        ).fetchone()
        return row[0] if row else None
    finally:
        if close:
            conn.close()


if __name__ == "__main__":
    import sys
    from tqdm import tqdm

    from src.ingest.extract import extract_commits
    from src.utils.config import KERNEL_REPO_PATH
    from src.utils.logging import setup_logging

    setup_logging()

    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None

    existing = get_loaded_count()
    if existing > 0:
        logger.info("Database already has %d commits.", existing)

    if limit:
        logger.info("Extracting up to %d commits from %s", limit, KERNEL_REPO_PATH)
    else:
        logger.info("Extracting all commits from %s", KERNEL_REPO_PATH)

    commits = extract_commits(KERNEL_REPO_PATH, limit=limit)
    commits_with_progress = tqdm(commits, total=limit, desc="Loading", unit="commits")
    total = bulk_load_commits(commits_with_progress, embed=True)
    print(f"\nLoaded {total} commits into database (total now: {existing + total}).")
