# Kernel History Chat

Semantic and temporal querying of the Linux kernel git history. Ask natural language questions, get answers backed by real commits.

Runs entirely locally on a single machine. No cloud dependencies, no API keys.

## Prerequisites

- Docker and Docker Compose (v2)
- A local clone of the Linux kernel repo
- ~50GB free disk (kernel repo + database with embeddings)
- Patience for the initial ingestion (~1.2M commits)

## Quick Start

### 1. Clone the kernel repo (if you don't have one)

```bash
git clone https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git ~/fun/linux
```

### 2. Configure paths

The default kernel repo path is `~/fun/linux`. If yours is elsewhere, either set environment variables or create a `.env` file:

```bash
cp .env.example .env
# Edit .env to set KERNEL_REPO_PATH and GEMMA_MODEL_PATH
```

### 3. Build containers

```bash
docker compose build
```

This builds three containers:
- **postgres** — PostgreSQL 16 with pgvector and TimescaleDB
- **app** — Python 3.12 with sentence-transformers, psycopg, project code
- **gemma** — gemma.cpp compiled with AVX2 (for LLM inference, used later)

### 4. Start the database

```bash
docker compose up -d postgres
```

### 5. Initialize the schema

```bash
docker compose run --rm app bash scripts/setup_db.sh
```

### 6. Ingest commits

Start small to verify everything works:

```bash
docker compose run --rm app python -m src.ingest.load 100
```

This extracts 100 commits from git, embeds the commit messages with Nomic Embed Text v2, and bulk-loads them into Postgres. Should take about a minute (most of that is loading the embedding model on first run).

Once you're satisfied, ingest more. Some useful batch sizes:

| Commits | Approx time | Good for |
|---------|-------------|----------|
| 1,000 | ~5 min | Quick smoke test |
| 10,000 | ~30 min | Useful subset (recent history) |
| 100,000 | ~5 hours | Solid coverage |
| all (~1.2M) | ~16-24 hours | Full index |

```bash
# Ingest 10,000 commits
docker compose run --rm app python -m src.ingest.load 10000

# Ingest everything (go make dinner, then go to bed)
docker compose run --rm app python -m src.ingest.load
```

Commits are loaded newest-first. You can stop and resume — but note that the current version does not deduplicate, so restarting will insert duplicates. Clear the database first if you need to restart:

```bash
docker compose run --rm app psql -h localhost -U kernelchat -d kernelchat \
  -c "TRUNCATE commits CASCADE;"
```

### 7. Build vector indexes

After your initial bulk load is complete, build the HNSW indexes for fast similarity search:

```bash
docker compose run --rm app psql -h localhost -U kernelchat -d kernelchat \
  -f /app/scripts/create_indexes.sql
```

This can take a few minutes depending on how many commits are indexed. Skip this step if you're still loading data — indexes slow down bulk inserts.

### 8. Start chatting

```bash
docker compose run --rm -it app python -m src.chat.cli
```

## Usage

The CLI starts in **direct mode** — no Gemma LLM required. You can:

**Semantic search** — type a natural language query:
```
> memory leak fixes in the networking stack
> io_uring performance improvements
> scheduler changes related to real-time preemption
```

**Raw SQL** — type a SELECT statement directly:
```
> SELECT author_name, count(*) AS n FROM commits WHERE authored_date > '2024-01-01' GROUP BY author_name ORDER BY n DESC LIMIT 10
```

### Commands

| Command | Description |
|---------|-------------|
| `%Q` | Quit |
| `%C` | Clear conversation context |
| `%S` | Show the last SQL query executed |
| `%D` | Switch to direct mode (default) |
| `%G` | Switch to Gemma mode (requires model weights) |

### Gemma mode (optional)

If you have Gemma 3 model weights, place them at the configured `GEMMA_MODEL_PATH` and start the gemma container:

```bash
docker compose up -d gemma
```

Then in the CLI, type `%G` to switch to Gemma mode. In this mode, the LLM plans and executes queries on your behalf — you just ask questions in plain English.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Host (Ubuntu 22.04)                                │
│                                                     │
│  ~/fun/linux/  ←── kernel git repo (bind mount, ro) │
│                                                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐         │
│  │ postgres │  │   app    │  │  gemma   │         │
│  │          │  │          │  │          │         │
│  │ PG 16    │  │ Python   │  │ gemma.cpp│         │
│  │ pgvector │◄─┤ embed    │  │ (AVX2)   │         │
│  │ Timescale│  │ ingest   │  │          │         │
│  │          │  │ chat CLI │──┤          │         │
│  └──────────┘  └──────────┘  └──────────┘         │
│       ▲              ▲                              │
│       │              │                              │
│    pgdata         /kernel                           │
│    volume        bind mount                         │
└─────────────────────────────────────────────────────┘
```

## Checking database status

```bash
docker compose run --rm app psql -h localhost -U kernelchat -d kernelchat \
  -c "SELECT count(*) AS total, count(msg_embedding) AS with_embeddings, min(authored_date)::date AS earliest, max(authored_date)::date AS latest FROM commits;"
```

## Stopping

```bash
docker compose down        # stop containers, keep data
docker compose down -v     # stop and DELETE all data (pgdata volume)
```
