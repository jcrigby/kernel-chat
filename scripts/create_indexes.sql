-- HNSW vector indexes — run AFTER bulk data load
-- These are expensive to build incrementally, so we defer them.

CREATE INDEX IF NOT EXISTS idx_commits_embedding ON commits
    USING hnsw (msg_embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON diff_chunks
    USING hnsw (chunk_embedding vector_cosine_ops);
