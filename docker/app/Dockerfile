FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.12 \
        python3.12-venv \
        python3-pip \
        git \
        postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Create venv and install Python deps
RUN python3.12 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY pyproject.toml /app/pyproject.toml
WORKDIR /app
RUN pip install --no-cache-dir -e ".[dev]"

# Copy project source
COPY src/ /app/src/
COPY scripts/ /app/scripts/
COPY tests/ /app/tests/

# Kernel repo will be bind-mounted at /kernel (read-only)
# Gemma weights will be bind-mounted at /models (read-only)
RUN git config --global --add safe.directory /kernel

CMD ["python", "-m", "src.chat.cli"]
