FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        cmake \
        git \
        wget \
    && rm -rf /var/lib/apt/lists/*

# Clone and build gemma.cpp with AVX2 support
RUN git clone https://github.com/google/gemma.cpp.git /opt/gemma.cpp \
    && cd /opt/gemma.cpp \
    && cmake -B build -DCMAKE_BUILD_TYPE=Release \
        -DWEIGHT_TYPE=hwy \
        -DCMAKE_CXX_FLAGS="-mavx2 -mfma" \
    && cmake --build build --config Release --target gemma -j$(nproc)

ENV PATH="/opt/gemma.cpp/build:$PATH"

# Model weights will be bind-mounted at /models (read-only)
WORKDIR /opt/gemma.cpp

# Default: keep container running, app container calls via docker exec
CMD ["sleep", "infinity"]
