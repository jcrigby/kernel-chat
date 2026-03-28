# CLAUDE.md — Kernel History Chat

## Project Overview

A local, self-hosted system for semantic and temporal querying of the Linux kernel git history. Natural language questions go in, interpreted answers come out. The LLM inference layer is Gemma (via gemma.cpp), the storage layer is PostgreSQL with pgvector and TimescaleDB, and the kernel repo itself is available for on-demand git operations.

Everything runs on a single machine ("Erasmus"): Intel i5-10400 (6C/12T, AVX2, no AVX-512), 128GB RAM, Ubuntu 22.04 host. The development and runtime environment runs inside Docker containers on a clean base (Ubuntu 24.04), keeping the host uncontaminated.

## Architecture Decisions (Already Made — Do Not Revisit)

- **LLM inference**: gemma.cpp, CPU-only. Target Gemma 3 12B fp8 as primary, 4B as fallback. Do not use Ollama, llama.cpp, or any Python inference framework.
- **Vector store**: PostgreSQL + pgvector (HNSW indexes, cosine similarity). No dedicated vector DB.
- **Time-series**: TimescaleDB extension on the same Postgres instance. Commits are time-series data — use hypertables and time_bucket().
- **Embedding model**: Nomic Embed Text v2 via local inference (sentence-transformers or similar). 768 dimensions, Matryoshka-capable. Do not call external APIs for embeddings.
- **Kernel repo**: Full git clone at a configurable path. Used for on-demand `git show`, `git log`, `git blame`, `git diff` operations when the LLM needs raw content beyond what's indexed.
- **Language**: Python for orchestration, data pipeline, and the chat interface layer. C++ only touches gemma.cpp (we don't modify it, we link to it or call it as a subprocess).
- **Containerized**: All services run in Docker containers via docker-compose. The host (Ubuntu 22.04) only needs Docker installed. No conda, no system Python, no Postgres on the host.
- **No cloud dependencies**. No API keys required for any runtime operation. Everything local.

## Repository Structure

```
kernel-chat/
├── CLAUDE.md              # This file
├── PRD.md                 # Product requirements
├── README.md              # User-facing setup and usage
├── docker-compose.yml     # All services: postgres, app, gemma
├── docker/
│   ├── postgres/
│   │   └── Dockerfile     # Postgres 16 + pgvector + TimescaleDB
│   ├── app/
│   │   └── Dockerfile     # Python 3.12 + sentence-transformers + project deps
│   └── gemma/
│       └── Dockerfile     # Ubuntu 24.04 + CMake + gemma.cpp build
├── pyproject.toml         # Python project config (use uv or pip)
├── src/
│   ├── ingest/            # Git history extraction and embedding pipeline
│   │   ├── extract.py     # Parse git log into structured records
│   │   ├── chunk.py       # Chunk diffs by file-level hunks
│   │   ├── embed.py       # Generate embeddings via local model
│   │   └── load.py        # Bulk load into Postgres
│   ├── db/
│   │   ├── schema.sql     # DDL: tables, hypertables, indexes
│   │   ├── migrations/    # Schema migrations if needed
│   │   └── queries.py     # Named query templates
│   ├── inference/
│   │   ├── gemma.py       # Interface to gemma.cpp (subprocess or binding)
│   │   ├── prompts.py     # Prompt templates for query generation, summarization
│   │   └── tools.py       # Tool definitions: SQL execution, git commands
│   ├── chat/
│   │   ├── session.py     # Conversation loop and state management
│   │   └── cli.py         # Terminal interface
│   └── utils/
│       ├── config.py      # All paths, model params, DB connection
│       └── logging.py     # Structured logging
├── tests/
│   ├── test_extract.py
│   ├── test_chunk.py
│   ├── test_embed.py
│   ├── test_queries.py
│   └── test_integration.py
└── scripts/
    ├── setup_db.sh        # Create DB, enable extensions, run schema
    ├── ingest.sh          # Run full ingestion pipeline
    └── run.sh             # Start chat session
```

## Coding Conventions

- Python 3.11+. Type hints everywhere. Use dataclasses or Pydantic for structured data.
- Async where it helps (DB queries, subprocess calls to gemma.cpp). Sync is fine for the CLI loop.
- No ORMs. Raw SQL via psycopg (v3, async). SQL lives in `.sql` files or clearly marked query constants — not buried in application logic.
- Tests use pytest. Integration tests can assume a running Postgres instance.
- Config via environment variables with sensible defaults (see `src/utils/config.py`). No config files to manage.
- Logging via Python's stdlib logging, structured format. No print statements for operational output.
- Error handling: fail loud on setup/config errors, retry with backoff on transient DB/inference errors.
- Git commits: conventional commits (feat:, fix:, refactor:, docs:, test:).

## Key Technical Details

### Database Schema

The core tables (see PRD.md for full schema):
- `commits` — hypertable partitioned by `authored_date`, with a `msg_embedding vector(768)` column and HNSW index.
- `diff_chunks` — individual file-level hunks linked to commits, each with `chunk_embedding vector(768)` and HNSW index.
- `subsystems` — extracted from MAINTAINERS file, linked to file path patterns.

### Ingestion Pipeline

1. `git log --format=<custom> --numstat` to extract structured commit data.
2. For each commit, `git diff-tree` to get per-file hunks.
3. Chunk diffs at the file-hunk level. Prepend commit subject as context prefix before embedding.
4. Embed commit messages and diff chunks separately using Nomic Embed Text v2.
5. Bulk COPY into Postgres.
6. Build HNSW indexes after bulk load (faster than incremental).

Expect ~1.2M commits. At 768-dim float32, that's ~3.5GB for commit embeddings alone. Diff chunks will be larger. Budget 20-30GB total for the vector data. Erasmus has headroom.

### Gemma Integration

gemma.cpp is called as a subprocess (or via a thin C++/Python binding if one exists). The interaction pattern:
- Construct a prompt with system context + retrieved documents + user question.
- Stream tokens from gemma.cpp stdout.
- Parse structured output (SQL queries, git commands) from the response.
- Execute the parsed commands, feed results back as a new turn.

This is a tool-use loop: question → generate query → execute → interpret → respond (or generate another query).

### Prompt Strategy

Gemma acts as a query planner and result interpreter. Prompts should:
- Include the DB schema as context so Gemma can write valid SQL.
- Include examples of good queries (few-shot).
- Request structured output (e.g., ```sql blocks or JSON tool calls).
- Never send raw diff content into the prompt — too large. Summarize or excerpt.

## What to Build First (Priority Order)

1. **Docker setup** — docker-compose.yml, Dockerfiles, verify all containers build and talk to each other.
2. **Database schema and setup script** — get Postgres with extensions running, tables created.
3. **Git extraction** — parse the kernel log into structured Python objects.
4. **Embedding pipeline** — local Nomic model, generate embeddings for commit messages.
5. **Bulk load** — get data into Postgres with indexes.
6. **Query layer** — SQL query templates for hybrid vector + temporal + relational search.
7. **Gemma integration** — subprocess interface, prompt templates.
8. **Chat loop** — interactive CLI that ties it all together.
9. **Diff chunk indexing** — the second pass, adding file-level hunk embeddings.

## Things to Avoid

- Do not over-engineer. This is a personal research tool, not a product.
- Do not add a web UI. CLI only for v1.
- Do not use LangChain, LlamaIndex, or similar orchestration frameworks. Direct code.
- Do not install anything on the host beyond Docker. All dependencies live in containers.
- Do not add authentication, multi-user support, or API endpoints.
- Do not optimize prematurely — get it working end to end first, then profile.

## Container Strategy

Three containers via docker-compose, all on the host network:

1. **postgres** — Postgres 16 with pgvector + TimescaleDB. Data volume mounted from host for persistence.
2. **app** — Ubuntu 24.04, Python 3.12, sentence-transformers, psycopg, project code. The kernel repo is bind-mounted read-only from the host. This container runs the ingestion pipeline and the chat CLI.
3. **gemma** — Ubuntu 24.04, build tools, gemma.cpp compiled with AVX2. Model weights mounted from host. Exposes inference via stdin/stdout (the app container calls it via `docker exec` or a simple socket/pipe).

Alternatively, the app and gemma containers can be combined into one if the subprocess model is simpler that way. Keep it simple — don't over-separate if it creates IPC complexity.

The kernel repo clone lives on the host at a configurable path and is bind-mounted into the app container. The host is responsible for `git pull` to update the repo; the containers only read from it.

Persistent data volumes:
- `pgdata` — Postgres data directory
- Model weights directory (bind mount from host, read-only)
