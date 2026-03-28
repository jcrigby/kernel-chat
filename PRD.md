# PRD: Kernel History Chat

## Problem

The Linux kernel git repository contains ~1.2 million commits spanning 30+ years. It is one of the most information-dense software histories in existence — commit messages often contain detailed architectural rationale, design debates, and subsystem evolution context. But querying this history is limited to `git log --grep`, `git blame`, and manual archaeology. There is no semantic search, no temporal aggregation, and no way to ask questions like "how did the community's approach to real-time preemption evolve between 2015 and 2022?"

## Solution

A local, fully self-hosted chat interface that combines:

- **Semantic search** over commit messages and diff chunks (pgvector embeddings)
- **Temporal analysis** over commit history (TimescaleDB hypertables, time_bucket aggregation)
- **Relational filtering** on structured metadata (author, file paths, subsystems)
- **On-demand git operations** for full context retrieval (git show, git blame, git diff)
- **LLM interpretation** to synthesize results into natural language answers (Gemma 3 via gemma.cpp)

All running on a single machine with no cloud dependencies.

## Target Hardware

- **Machine**: Erasmus
- **CPU**: Intel i5-10400 (Comet Lake), 6 cores / 12 threads, 2.9 GHz base / 4.3 GHz boost, AVX2 (no AVX-512)
- **RAM**: 128GB DDR4
- **Storage**: Sufficient local SSD (kernel repo ~4GB, database ~30-50GB with embeddings)
- **Host OS**: Ubuntu 22.04 (Docker only — nothing else installed on host)
- **Container OS**: Ubuntu 24.04
- **GPU**: None available for inference

## Data Model

### Source Data

The Linux kernel git repository, cloned locally. Path configurable via `KERNEL_REPO_PATH` environment variable.

### Database: PostgreSQL with pgvector + TimescaleDB

#### Table: `commits`

This is a TimescaleDB hypertable partitioned on `authored_date`.

```sql
CREATE TABLE commits (
    hash            TEXT PRIMARY KEY,
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
    msg_embedding   vector(768)
);

-- Convert to hypertable
SELECT create_hypertable('commits', 'authored_date');

-- Vector similarity index
CREATE INDEX idx_commits_embedding ON commits
    USING hnsw (msg_embedding vector_cosine_ops);

-- Relational indexes
CREATE INDEX idx_commits_author ON commits (author_email);
CREATE INDEX idx_commits_files ON commits USING gin (files_changed);
```

#### Table: `diff_chunks`

Individual file-level hunks from each commit.

```sql
CREATE TABLE diff_chunks (
    id              BIGSERIAL PRIMARY KEY,
    commit_hash     TEXT NOT NULL REFERENCES commits(hash),
    file_path       TEXT NOT NULL,
    old_file_path   TEXT,                -- for renames
    change_type     TEXT NOT NULL,       -- add, modify, delete, rename
    hunk_header     TEXT,                -- @@ line
    hunk_text       TEXT NOT NULL,
    line_start      INTEGER,
    line_count      INTEGER,
    chunk_embedding vector(768)
);

CREATE INDEX idx_chunks_commit ON diff_chunks (commit_hash);
CREATE INDEX idx_chunks_file ON diff_chunks (file_path);
CREATE INDEX idx_chunks_embedding ON diff_chunks
    USING hnsw (chunk_embedding vector_cosine_ops);
```

#### Table: `subsystems`

Parsed from the MAINTAINERS file. Maps file path patterns to subsystem names and maintainers.

```sql
CREATE TABLE subsystems (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    status          TEXT,
    maintainers     TEXT[],
    file_patterns   TEXT[]
);
```

#### Useful View: subsystem-tagged commits

```sql
CREATE VIEW commits_with_subsystem AS
SELECT c.*, s.name AS subsystem
FROM commits c
LEFT JOIN LATERAL (
    SELECT s.name
    FROM subsystems s, unnest(s.file_patterns) pat,
         unnest(c.files_changed) f
    WHERE f LIKE pat
    LIMIT 1
) s ON true;
```

## Embedding Strategy

### Model

Nomic Embed Text v2, run locally. 768 dimensions. Apache 2.0 license.

- Supports Matryoshka truncation (768 → 256) if storage becomes a concern.
- Supports up to 8192 tokens context — sufficient for even long commit messages.
- Requires task prefix: `search_document:` for indexing, `search_query:` for queries.
- Runnable on CPU via sentence-transformers. No GPU required.

### What Gets Embedded

1. **Commit messages**: subject + body concatenated. Prefix: `search_document: <subject>\n<body>`. One embedding per commit.
2. **Diff chunks**: commit subject prepended as context, then the hunk text. Prefix: `search_document: [<commit subject>] <file_path>\n<hunk_text>`. One embedding per file-level hunk.

### What Does NOT Get Embedded

- Binary file changes (skip)
- Merge commits with no original content (skip, or embed only the merge message)
- Extremely large diffs (>8192 tokens after chunking) — truncate to fit context window

### Embedding Batch Process

- Use sentence-transformers `model.encode()` with batching (batch_size=256 or whatever saturates CPU).
- Process in parallel: one thread extracts git data, another embeds, another loads into Postgres.
- Estimate: ~1.2M commits at ~50ms per embed on CPU ≈ 16 hours for commit messages alone. Diff chunks will take longer. This is a one-time cost.
- Progress bar and resumability (track last-processed commit hash).

## Ingestion Pipeline

### Phase 1: Git Extraction

```bash
git log --all --format='COMMIT_START%n%H%n%aI%n%cI%n%aN%n%aE%n%cN%n%cE%n%s%n%b%nCOMMIT_END' --numstat
```

Parse this into structured records. Handle edge cases:
- Multi-line commit bodies (terminated by COMMIT_END sentinel)
- Merge commits (detect via parent count or `--merges`)
- Encoding issues in old commits (some use Latin-1)
- Commits with no file changes (empty merge commits)

### Phase 2: Diff Extraction

For each commit hash:
```bash
git diff-tree -p --no-commit-id <hash>
```

Parse unified diff output into per-file hunks. Each hunk becomes a `diff_chunks` record.

For the initial load, consider processing only commit messages (Phase 1 + embedding) first, then diff chunks as a second pass. This gets a working system faster.

### Phase 3: MAINTAINERS Parsing

Parse the kernel's `MAINTAINERS` file to populate the `subsystems` table. The format is well-defined:
```
SUBSYSTEM NAME
M:  Maintainer Name <email>
L:  mailing-list@vger.kernel.org
S:  Maintained
F:  drivers/subsystem/*
```

Extract name, maintainers, status, and file patterns (F: lines).

### Phase 4: Bulk Load

Use PostgreSQL `COPY` for bulk insertion. Build HNSW indexes after the bulk load completes (building incrementally during insert is much slower).

## Query Patterns

The system should support these categories of questions:

### Semantic Search
> "Find commits related to memory leak fixes in the networking stack"

```sql
SELECT hash, subject, authored_date, author_name,
       msg_embedding <=> $query_vec AS distance
FROM commits
WHERE files_changed && ARRAY['net/%']
ORDER BY msg_embedding <=> $query_vec
LIMIT 20;
```

### Temporal Analysis
> "How did commit frequency in drivers/gpu change year over year?"

```sql
SELECT time_bucket('1 year', authored_date) AS year,
       count(*) AS commits
FROM commits
WHERE 'drivers/gpu' = ANY(files_changed)
   OR EXISTS (
       SELECT 1 FROM unnest(files_changed) f
       WHERE f LIKE 'drivers/gpu/%'
   )
GROUP BY year
ORDER BY year;
```

### Hybrid (Semantic + Temporal + Relational)
> "What were the most significant scheduler changes between 2018 and 2020?"

```sql
SELECT hash, subject, authored_date, author_name,
       msg_embedding <=> $query_vec AS distance
FROM commits
WHERE authored_date BETWEEN '2018-01-01' AND '2020-12-31'
  AND EXISTS (
      SELECT 1 FROM unnest(files_changed) f
      WHERE f LIKE 'kernel/sched/%'
  )
ORDER BY msg_embedding <=> $query_vec
LIMIT 20;
```

### Contributor Analysis
> "Who were the top contributors to the Rust integration?"

```sql
SELECT author_name, count(*) AS commits,
       min(authored_date) AS first_commit,
       max(authored_date) AS latest_commit
FROM commits
WHERE msg_embedding <=> $query_vec < 0.3  -- semantic filter for Rust-related
GROUP BY author_name
ORDER BY commits DESC
LIMIT 20;
```

### Deep Dive (requires git operations)
> "Show me the full diff of that scheduler commit"

After identifying a commit via search, call `git show <hash>` and return the output to the user (or summarize it via Gemma if it's large).

## Gemma Integration

### Subprocess Model

gemma.cpp is built separately and invoked as a subprocess. The Python layer:
1. Constructs the full prompt (system context + retrieved docs + user question).
2. Writes the prompt to gemma.cpp's stdin (or passes via CLI args).
3. Reads streamed tokens from stdout.
4. Parses structured output (SQL in code fences, git commands, or natural language).

### System Prompt Template

```
You are a Linux kernel history expert with access to a database of all kernel commits and a local git repository.

When the user asks a question, determine whether you need to:
1. Query the database (generate SQL)
2. Run a git command (generate a shell command)
3. Answer directly from the retrieved context

Database schema:
{schema_summary}

When generating SQL, wrap it in ```sql fences.
When generating git commands, wrap them in ```bash fences.
When you have enough context to answer, respond in natural language.

Do not hallucinate commit hashes, author names, or dates. If you don't have enough information, say so and suggest a query that would help.
```

### Tool-Use Loop

```
User question
    → Gemma generates SQL or git command
    → Python executes it
    → Results injected into next prompt turn
    → Gemma interprets results (may generate follow-up query)
    → ... repeat until Gemma produces a natural language answer
    → Answer displayed to user
```

Maximum 5 tool-use rounds per question to prevent runaway loops.

## CLI Interface

Simple terminal interface. No TUI framework needed — just stdin/stdout.

```
$ kernel-chat

🐧 Kernel History Chat (Gemma 3 12B · 1,247,391 commits indexed)

> What was the most controversial scheduler change?

[Searching commits semantically...]
[Found 20 candidates, analyzing...]

The most debated scheduler change was the transition from the O(1) scheduler 
to the Completely Fair Scheduler (CFS) by Ingo Molnar in 2007. Commit 
abc123... introduced CFS in kernel 2.6.23. The discussion spanned months 
on LKML, with Con Kolivas's alternative SD scheduler being a significant 
competing proposal...

> Show me the original CFS commit

[Running: git show abc123...]
...
```

Features:
- Streaming token output from Gemma
- `%C` to reset conversation context
- `%Q` to quit
- `%S` to show the last SQL query executed
- `%T` to show token generation stats (tok/s)
- History via readline

## Performance Targets

These are goals, not hard requirements. Get it working first.

| Metric | Target |
|--------|--------|
| Embedding ingestion | ~1.2M commits in <24 hours |
| Semantic query (pgvector) | <100ms for top-20 results |
| Temporal aggregation | <500ms for year-over-year rollups |
| Gemma response (first token) | <5 seconds |
| Gemma response (full) | <60 seconds for typical question |
| End-to-end question answering | <90 seconds including tool-use rounds |

## Non-Goals for V1

- Web UI
- Multi-user support
- Real-time repo tracking (re-run ingest manually after `git pull`)
- Fine-tuning Gemma on kernel-specific data
- Embedding diffs for all 1.2M commits on first pass (do commit messages first)
- Supporting any kernel fork other than mainline torvalds/linux
- Windows or macOS support

## Success Criteria

The project is "done enough" when you can:

1. Ask "when did Rust support first appear in the kernel?" and get an accurate, sourced answer with commit hashes and dates.
2. Ask "who contributed the most to drivers/net in 2023?" and get correct contributor stats.
3. Ask "what changed in the memory management subsystem this year vs last year?" and get a meaningful comparative summary.
4. Ask "show me the commit that introduced io_uring" and get the actual diff.
5. Do all of the above entirely offline on Erasmus.
