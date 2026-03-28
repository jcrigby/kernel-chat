-- Kernel History Chat — Database Schema
-- Requires: pgvector, timescaledb extensions (created by initdb.sql)

-- Commits table (will become a hypertable)
CREATE TABLE IF NOT EXISTS commits (
    hash            TEXT NOT NULL,
    authored_date   TIMESTAMPTZ NOT NULL,
    committed_date  TIMESTAMPTZ NOT NULL,
    author_name     TEXT NOT NULL,
    author_email    TEXT NOT NULL,
    committer_name  TEXT,
    committer_email TEXT,
    subject         TEXT NOT NULL,
    body            TEXT,
    files_changed   TEXT[],
    insertions      INTEGER,
    deletions       INTEGER,
    merge           BOOLEAN DEFAULT FALSE,
    msg_embedding   vector(768),
    PRIMARY KEY (hash, authored_date)
);

-- Convert to hypertable partitioned by authored_date
-- The if_not_exists flag makes this idempotent
SELECT create_hypertable('commits', 'authored_date',
    chunk_time_interval => INTERVAL '2 years',
    if_not_exists => TRUE,
    migrate_data => TRUE
);

-- Diff chunks table
CREATE TABLE IF NOT EXISTS diff_chunks (
    id              BIGSERIAL,
    commit_hash     TEXT NOT NULL,
    file_path       TEXT NOT NULL,
    old_file_path   TEXT,
    change_type     TEXT NOT NULL,
    hunk_header     TEXT,
    hunk_text       TEXT NOT NULL,
    line_start      INTEGER,
    line_count      INTEGER,
    chunk_embedding vector(768)
);

-- Subsystems table (from MAINTAINERS)
CREATE TABLE IF NOT EXISTS subsystems (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    status          TEXT,
    maintainers     TEXT[],
    file_patterns   TEXT[]
);

-- Relational indexes (created unconditionally, safe to re-run)
CREATE INDEX IF NOT EXISTS idx_commits_author ON commits (author_email);
CREATE INDEX IF NOT EXISTS idx_commits_files ON commits USING gin (files_changed);

CREATE INDEX IF NOT EXISTS idx_chunks_commit ON diff_chunks (commit_hash);
CREATE INDEX IF NOT EXISTS idx_chunks_file ON diff_chunks (file_path);

-- View: commits tagged with subsystem
CREATE OR REPLACE VIEW commits_with_subsystem AS
SELECT c.*, s.name AS subsystem
FROM commits c
LEFT JOIN LATERAL (
    SELECT s.name
    FROM subsystems s, unnest(s.file_patterns) pat,
         unnest(c.files_changed) f
    WHERE f LIKE pat
    LIMIT 1
) s ON true;

-- NOTE: HNSW vector indexes are intentionally NOT created here.
-- They should be built AFTER bulk data load for much better performance.
-- See scripts/create_indexes.sql for the index definitions.
