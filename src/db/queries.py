"""Named query templates for hybrid vector + temporal + relational search.

All queries return rows as dicts. Vector parameters are passed as
pgvector literals ('[0.1,0.2,...]').
"""

import logging
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.rows import dict_row

from src.utils.config import dsn

logger = logging.getLogger(__name__)


def _connect() -> psycopg.Connection:
    return psycopg.connect(dsn(), row_factory=dict_row)


# ---------------------------------------------------------------------------
# Semantic search
# ---------------------------------------------------------------------------

SEMANTIC_SEARCH = """\
SELECT hash, subject, authored_date, author_name, author_email,
       merge, insertions, deletions,
       msg_embedding <=> %(query_vec)s::vector AS distance
FROM commits
WHERE msg_embedding IS NOT NULL
ORDER BY msg_embedding <=> %(query_vec)s::vector
LIMIT %(limit)s
"""

SEMANTIC_SEARCH_WITH_PATH = """\
SELECT hash, subject, authored_date, author_name, author_email,
       merge, insertions, deletions,
       msg_embedding <=> %(query_vec)s::vector AS distance
FROM commits
WHERE msg_embedding IS NOT NULL
  AND EXISTS (
      SELECT 1 FROM unnest(files_changed) f
      WHERE f LIKE %(path_pattern)s
  )
ORDER BY msg_embedding <=> %(query_vec)s::vector
LIMIT %(limit)s
"""

# ---------------------------------------------------------------------------
# Temporal analysis
# ---------------------------------------------------------------------------

COMMITS_BY_TIME_BUCKET = """\
SELECT time_bucket(%(bucket)s::interval, authored_date) AS bucket,
       count(*) AS commits,
       sum(insertions) AS insertions,
       sum(deletions) AS deletions,
       count(DISTINCT author_email) AS authors
FROM commits
WHERE authored_date BETWEEN %(start)s AND %(end)s
GROUP BY bucket
ORDER BY bucket
"""

COMMITS_BY_TIME_BUCKET_WITH_PATH = """\
SELECT time_bucket(%(bucket)s::interval, authored_date) AS bucket,
       count(*) AS commits,
       sum(insertions) AS insertions,
       sum(deletions) AS deletions,
       count(DISTINCT author_email) AS authors
FROM commits
WHERE authored_date BETWEEN %(start)s AND %(end)s
  AND EXISTS (
      SELECT 1 FROM unnest(files_changed) f
      WHERE f LIKE %(path_pattern)s
  )
GROUP BY bucket
ORDER BY bucket
"""

# ---------------------------------------------------------------------------
# Hybrid: semantic + temporal + path
# ---------------------------------------------------------------------------

HYBRID_SEARCH = """\
SELECT hash, subject, authored_date, author_name, author_email,
       merge, insertions, deletions,
       msg_embedding <=> %(query_vec)s::vector AS distance
FROM commits
WHERE msg_embedding IS NOT NULL
  AND authored_date BETWEEN %(start)s AND %(end)s
ORDER BY msg_embedding <=> %(query_vec)s::vector
LIMIT %(limit)s
"""

HYBRID_SEARCH_WITH_PATH = """\
SELECT hash, subject, authored_date, author_name, author_email,
       merge, insertions, deletions,
       msg_embedding <=> %(query_vec)s::vector AS distance
FROM commits
WHERE msg_embedding IS NOT NULL
  AND authored_date BETWEEN %(start)s AND %(end)s
  AND EXISTS (
      SELECT 1 FROM unnest(files_changed) f
      WHERE f LIKE %(path_pattern)s
  )
ORDER BY msg_embedding <=> %(query_vec)s::vector
LIMIT %(limit)s
"""

# ---------------------------------------------------------------------------
# Contributor analysis
# ---------------------------------------------------------------------------

TOP_AUTHORS = """\
SELECT author_name, author_email,
       count(*) AS commits,
       sum(insertions) AS insertions,
       sum(deletions) AS deletions,
       min(authored_date) AS first_commit,
       max(authored_date) AS latest_commit
FROM commits
WHERE authored_date BETWEEN %(start)s AND %(end)s
GROUP BY author_name, author_email
ORDER BY commits DESC
LIMIT %(limit)s
"""

TOP_AUTHORS_WITH_PATH = """\
SELECT author_name, author_email,
       count(*) AS commits,
       sum(insertions) AS insertions,
       sum(deletions) AS deletions,
       min(authored_date) AS first_commit,
       max(authored_date) AS latest_commit
FROM commits
WHERE authored_date BETWEEN %(start)s AND %(end)s
  AND EXISTS (
      SELECT 1 FROM unnest(files_changed) f
      WHERE f LIKE %(path_pattern)s
  )
GROUP BY author_name, author_email
ORDER BY commits DESC
LIMIT %(limit)s
"""

TOP_AUTHORS_SEMANTIC = """\
SELECT author_name, author_email,
       count(*) AS commits,
       min(authored_date) AS first_commit,
       max(authored_date) AS latest_commit
FROM commits
WHERE msg_embedding IS NOT NULL
  AND msg_embedding <=> %(query_vec)s::vector < %(max_distance)s
GROUP BY author_name, author_email
ORDER BY commits DESC
LIMIT %(limit)s
"""

# ---------------------------------------------------------------------------
# Single commit lookup
# ---------------------------------------------------------------------------

COMMIT_BY_HASH = """\
SELECT hash, subject, body, authored_date, committed_date,
       author_name, author_email, committer_name, committer_email,
       files_changed, insertions, deletions, merge
FROM commits
WHERE hash LIKE %(hash_prefix)s || '%%'
LIMIT 5
"""

# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

DB_STATS = """\
SELECT
    count(*) AS total_commits,
    count(msg_embedding) AS embedded_commits,
    min(authored_date) AS earliest,
    max(authored_date) AS latest,
    count(DISTINCT author_email) AS unique_authors
FROM commits
"""


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------

@dataclass
class QueryResult:
    """Result of a named query execution."""
    query_name: str
    sql: str
    params: dict[str, Any]
    rows: list[dict[str, Any]]
    row_count: int


def execute_query(
    sql: str,
    params: dict[str, Any],
    *,
    query_name: str = "ad_hoc",
    conn: psycopg.Connection | None = None,
) -> QueryResult:
    """Execute a query and return structured results."""
    close = False
    if conn is None:
        conn = _connect()
        close = True

    try:
        cur = conn.execute(sql, params)
        rows = cur.fetchall()
        return QueryResult(
            query_name=query_name,
            sql=sql,
            params=params,
            rows=rows,
            row_count=len(rows),
        )
    finally:
        if close:
            conn.close()


def execute_raw_sql(
    sql: str,
    conn: psycopg.Connection | None = None,
) -> QueryResult:
    """Execute arbitrary SQL (for LLM-generated queries).

    Only SELECT statements are allowed.
    """
    stripped = sql.strip().rstrip(";")
    if not stripped.upper().startswith("SELECT"):
        raise ValueError("Only SELECT queries are allowed.")

    close = False
    if conn is None:
        conn = _connect()
        close = True

    try:
        cur = conn.execute(stripped)
        rows = cur.fetchall()
        return QueryResult(
            query_name="raw_sql",
            sql=sql,
            params={},
            rows=rows,
            row_count=len(rows),
        )
    finally:
        if close:
            conn.close()
