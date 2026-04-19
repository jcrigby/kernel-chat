"""LLM inference via OpenRouter API.

Drop-in replacement for the gemma.cpp subprocess interface.
Uses the OpenRouter chat completions endpoint (OpenAI-compatible).
"""

import json
import logging
from typing import Iterator
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from src.utils.config import OPENROUTER_API_KEY, OPENROUTER_BASE_URL, OPENROUTER_MODEL

logger = logging.getLogger(__name__)


def chat_completion(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    max_tokens: int = 2048,
    temperature: float = 0.3,
    stream: bool = False,
) -> str:
    """Send a chat completion request to OpenRouter.

    Returns the full response text.
    """
    if not OPENROUTER_API_KEY:
        raise RuntimeError(
            "OPENROUTER_API_KEY not set. "
            "Get one at https://openrouter.ai/keys and set it in your environment."
        )

    model = model or OPENROUTER_MODEL

    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    req = Request(
        f"{OPENROUTER_BASE_URL}/chat/completions",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/kernel-chat",
        },
        method="POST",
    )

    logger.debug("OpenRouter request: model=%s, messages=%d", model, len(messages))

    try:
        with urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read())
    except HTTPError as e:
        error_body = e.read().decode() if e.fp else ""
        logger.error("OpenRouter HTTP %d: %s", e.code, error_body[:500])
        raise RuntimeError(f"OpenRouter API error ({e.code}): {error_body[:200]}") from e

    choices = body.get("choices", [])
    if not choices:
        logger.error("OpenRouter returned no choices: %s", body)
        raise RuntimeError("OpenRouter returned no choices.")

    content = choices[0].get("message", {}).get("content", "")

    usage = body.get("usage", {})
    if usage:
        logger.info(
            "Tokens: %d prompt, %d completion, model=%s",
            usage.get("prompt_tokens", 0),
            usage.get("completion_tokens", 0),
            model,
        )

    return content


def generate_full(
    system_prompt: str,
    conversation: list[dict[str, str]],
    **kwargs,
) -> str:
    """Generate a response given a system prompt and conversation history.

    conversation is a list of {"role": "user"|"assistant"|"tool", "content": "..."}.
    """
    messages = [{"role": "system", "content": system_prompt}]

    for turn in conversation:
        role = turn["role"]
        # Map our internal roles to OpenAI-compatible roles
        if role == "model":
            role = "assistant"
        elif role == "tool":
            role = "user"  # tool results go as user messages with prefix
            messages.append({
                "role": "user",
                "content": f"[Tool result]\n{turn['content']}\n[/Tool result]",
            })
            continue
        messages.append({"role": role, "content": turn["content"]})

    return chat_completion(messages, **kwargs)
