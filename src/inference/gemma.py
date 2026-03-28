"""Interface to gemma.cpp via subprocess.

Sends a prompt to the gemma binary running in the gemma container
and streams tokens back.
"""

import logging
import subprocess
from typing import Iterator

logger = logging.getLogger(__name__)

# Default binary path inside the gemma container
_GEMMA_BIN = "/opt/gemma.cpp/build/gemma"
_CONTAINER = "kernel-chat-gemma"


def generate(
    prompt: str,
    *,
    model_path: str = "/models",
    model_type: str = "gemma3-12b-pt",
    max_tokens: int = 2048,
    temperature: float = 0.7,
    use_docker_exec: bool = True,
) -> Iterator[str]:
    """Stream tokens from gemma.cpp.

    When use_docker_exec is True (default), runs via
    `docker exec kernel-chat-gemma gemma ...`.
    When False, assumes gemma binary is available locally.
    """
    cmd: list[str] = []

    if use_docker_exec:
        cmd = ["docker", "exec", "-i", _CONTAINER]

    cmd.extend([
        _GEMMA_BIN,
        "--model", model_type,
        "--weights", f"{model_path}/model.sbs",
        "--max_tokens", str(max_tokens),
        "--temperature", str(temperature),
    ])

    logger.debug("Running: %s", " ".join(cmd))

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert proc.stdin is not None
    assert proc.stdout is not None

    # Send prompt and close stdin to signal end of input
    proc.stdin.write(prompt)
    proc.stdin.close()

    # Stream stdout token by token (line-buffered)
    for line in proc.stdout:
        yield line

    proc.wait()
    if proc.returncode != 0:
        stderr = proc.stderr.read() if proc.stderr else ""
        logger.error("gemma exited with %d: %s", proc.returncode, stderr[:500])


def generate_full(prompt: str, **kwargs) -> str:
    """Generate a complete response (non-streaming)."""
    return "".join(generate(prompt, **kwargs))
