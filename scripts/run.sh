#!/usr/bin/env bash
# Start the kernel-chat CLI session.
set -euo pipefail
exec python -m src.chat.cli
