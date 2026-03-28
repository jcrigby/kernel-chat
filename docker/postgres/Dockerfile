FROM postgres:16-bookworm

# Install build dependencies for pgvector
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        git \
        postgresql-server-dev-16 \
    && rm -rf /var/lib/apt/lists/*

# Build and install pgvector
RUN git clone --branch v0.8.0 https://github.com/pgvector/pgvector.git /tmp/pgvector \
    && cd /tmp/pgvector \
    && make OPTFLAGS="" \
    && make install \
    && rm -rf /tmp/pgvector

# Install TimescaleDB from their APT repo
RUN apt-get update && apt-get install -y --no-install-recommends \
        lsb-release \
        wget \
        gnupg \
    && echo "deb https://packagecloud.io/timescale/timescaledb/debian/ $(lsb_release -cs) main" \
        > /etc/apt/sources.list.d/timescaledb.list \
    && wget --quiet -O - https://packagecloud.io/timescale/timescaledb/gpgkey | gpg --dearmor -o /etc/apt/trusted.gpg.d/timescaledb.gpg \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        timescaledb-2-postgresql-16 \
    && rm -rf /var/lib/apt/lists/*

# Preload shared libraries
RUN echo "shared_preload_libraries = 'timescaledb'" >> /usr/share/postgresql/postgresql.conf.sample

# Init script to enable extensions
COPY initdb.sql /docker-entrypoint-initdb.d/01-extensions.sql
