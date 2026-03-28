"""Configuration from environment variables with sensible defaults."""

import os


KERNEL_REPO_PATH: str = os.environ.get("KERNEL_REPO_PATH", "/kernel")

DB_HOST: str = os.environ.get("DB_HOST", "localhost")
DB_PORT: int = int(os.environ.get("DB_PORT", "5432"))
DB_NAME: str = os.environ.get("DB_NAME", "kernelchat")
DB_USER: str = os.environ.get("DB_USER", "kernelchat")
DB_PASSWORD: str = os.environ.get("DB_PASSWORD", "kernelchat")

GEMMA_MODEL_PATH: str = os.environ.get("GEMMA_MODEL_PATH", "/models")

# Embedding
EMBEDDING_MODEL: str = os.environ.get("EMBEDDING_MODEL", "nomic-ai/nomic-embed-text-v2-moe")
EMBEDDING_DIM: int = 768
EMBEDDING_BATCH_SIZE: int = int(os.environ.get("EMBEDDING_BATCH_SIZE", "256"))


def dsn() -> str:
    """Return a PostgreSQL connection string."""
    return f"host={DB_HOST} port={DB_PORT} dbname={DB_NAME} user={DB_USER} password={DB_PASSWORD}"
