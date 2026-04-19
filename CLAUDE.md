# CLAUDE.md — Kernel History Chat

## Project Overview

A local system for semantic and temporal querying of the Linux kernel git history. Natural language questions go in, interpreted answers come out. The storage layer is PostgreSQL with pgvector and TimescaleDB. The LLM layer uses OpenRouter (any model) for the chat interface. Embeddings are generated locally with Nomic Embed Text v2 MoE.

Everything runs on a single machine ("Erasmus"): Intel i5-10400 (6C/12T, AVX2), 128GB RAM, Ubuntu 22.04 host. Runtime is Docker containers on Ubuntu 24.04.

GitHub: https://github.com/jcrigby/kernel-chat

## Current Status (April 2026)

### What's done and working
- **Database**: 1,429,131 kernel commits loaded with 768-dim embeddings, HNSW indexes built
- **Docker**: three containers (postgres, app, gemma) — all build and run
- **Ingestion pipeline**: git extraction → embedding → COPY bulk load (steps 1-5 complete)
- **Query layer**: semantic, temporal, hybrid, contributor SQL templates (step 6)
- **Chat CLI**: direct mode works — semantic search and raw SQL against the full database (step 8)
- **OpenRouter integration**: coded but **untested** — needs API key (step 7, revised)
- **Embedding model cache**: persistent Docker volume, runs offline after first download

### What's NOT done
1. **OpenRouter API key** — sign up at https://openrouter.ai/keys, set `OPENROUTER_API_KEY`. Default model is `google/gemma-3-27b-it:free` (no cost). This is the single blocker for LLM chat mode.
2. **LLM mode untested** — the tool-use loop (LLM generates SQL/git → execute → feed back) has never run end-to-end. Expect bugs.
3. **LLM eval suite** — test cases defined in `docs/llm-eval.md`, runner not yet implemented. Compares models on SQL correctness, result quality, answer quality.
4. **Diff chunk indexing** (step 9) — per-file hunk embeddings. Table exists, not populated. Deferred.
5. **MAINTAINERS parsing** — subsystems table exists but is empty. Not critical.
6. **Gemma local inference** — gemma.cpp container built, but model weights never downloaded. Parked as separate experiment.

### Ingestion performance
- 1,429,131 commits in ~120 hours (5 days) at ~3.3 commits/sec
- PRD estimated 16-24 hours. Actual 2-3x slower due to Nomic v2 MoE being heavier than assumed on CPU.
- If re-ingesting, consider the non-MoE Nomic model or GPU-accelerated embedding.

## Architecture Decisions

- **All-Postgres**: pgvector + TimescaleDB in one instance. No sidecar vector DB.
- **Embeddings**: Nomic Embed Text v2 MoE, 768 dimensions, local CPU inference via sentence-transformers. Cached in persistent Docker volume. Runs fully offline after first download.
- **LLM for chat**: OpenRouter API (any model). Decoupled from the vector DB — the database works without an LLM. Direct mode provides semantic search and raw SQL without any LLM.
- **Gemma local**: gemma.cpp is built in a container but parked. Weight download requires Kaggle account + license acceptance. Separate experiment from OpenRouter.
- **Kernel repo**: full git clone at `~/fun/linux`, bind-mounted read-only into the app container. Host manages `git pull`.
- **No cloud dependencies for data**: embeddings are local, database is local. Only the LLM chat mode calls an external API.

## Repository Structure

```
├── CLAUDE.md              # This file
├── PRD.md                 # Original product requirements
├── README.md              # User-facing setup and usage
├── docker-compose.yml     # Services: postgres, app, gemma
├── docs/
│   └── llm-eval.md        # LLM model evaluation plan
├── docker/
│   ├── postgres/           # PG 16 + pgvector + TimescaleDB
│   ├── app/                # Python 3.12 + sentence-transformers
│   └── gemma/              # gemma.cpp (AVX2)
├── pyproject.toml
├── src/
│   ├── ingest/
│   │   ├── extract.py      # Git log parser (sentinel-delimited)
│   │   ├── embed.py        # Nomic embedding (batched)
│   │   └── load.py         # COPY bulk loader
│   ├── db/
│   │   ├── schema.sql      # DDL: hypertable, indexes
│   │   └── queries.py      # Named query templates
│   ├── inference/
│   │   ├── openrouter.py   # OpenRouter chat completions client
│   │   ├── gemma.py        # gemma.cpp subprocess (parked)
│   │   ├── prompts.py      # System prompt with schema + few-shot
│   │   └── tools.py        # SQL/git tool execution from LLM output
│   ├── chat/
│   │   ├── session.py      # Tool-use loop (direct + LLM modes)
│   │   └── cli.py          # Terminal interface
│   └── utils/
│       ├── config.py       # Env var config
│       └── logging.py      # Structured logging
├── tests/
│   ├── test_extract.py     # 7 tests
│   ├── test_queries.py     # 3 tests
│   └── test_tools.py       # 5 tests
└── scripts/
    ├── setup_db.sh         # Apply schema (idempotent)
    ├── create_indexes.sql  # HNSW indexes (run after bulk load)
    ├── ingest.sh           # Full pipeline wrapper
    └── run.sh              # Start chat CLI
```

## Quick Start (database is already populated)

```bash
docker compose up -d postgres
docker compose run --rm -it app python -m src.chat.cli
```

Direct mode works immediately. For LLM mode:
```bash
export OPENROUTER_API_KEY=sk-or-v1-...
docker compose run --rm -it -e OPENROUTER_API_KEY=$OPENROUTER_API_KEY app python -m src.chat.cli
# Type %L to switch to LLM mode
```

## Coding Conventions

- Python 3.11+. Type hints. Dataclasses for structured data.
- No ORMs. Raw SQL via psycopg v3. SQL in `.sql` files or query constants.
- Tests: pytest. 15 tests passing.
- Config: environment variables with defaults (see `src/utils/config.py`).
- Logging: stdlib logging, structured format. No print statements for operational output.
- Git commits: conventional commits (feat:, fix:, refactor:, docs:, test:).

## Things to Avoid

- Do not over-engineer. Personal research tool, not a product.
- Do not add a web UI. CLI only for v1.
- Do not use LangChain, LlamaIndex, or similar frameworks. Direct code.
- Do not install anything on the host beyond Docker.

## Context for Blog Writeup

This project is intended as a writeup for "Agentic Recreations" — a blog/website inspired by Martin Gardner's Mathematical Recreations column. The entire build was done in collaborative agent sessions. Key data points for the writeup:
- 120-hour ingestion (vs 16-24 hour estimate)
- Architecture: all-Postgres with pgvector + TimescaleDB
- Separation of embedding (local, offline) from LLM chat (API, any model)
- The LLM eval suite as empirical comparison of model capabilities on structured query tasks
