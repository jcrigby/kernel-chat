"""Conversation loop and state management.

Implements the tool-use loop:
  user question -> LLM generates SQL/git -> execute -> feed results back -> repeat
  until LLM produces a natural language answer or max rounds reached.
"""

import logging
from dataclasses import dataclass, field

from src.inference.gemma import generate_full
from src.inference.prompts import build_prompt
from src.inference.tools import parse_tool_calls, execute_tool, ToolResult

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 5


@dataclass
class Session:
    """A single conversation session."""

    history: list[dict[str, str]] = field(default_factory=list)
    last_sql: str | None = None
    last_tool_results: list[ToolResult] = field(default_factory=list)

    def reset(self) -> None:
        """Clear conversation history."""
        self.history.clear()
        self.last_sql = None
        self.last_tool_results.clear()

    def ask(
        self,
        question: str,
        *,
        on_status: callable = lambda msg: None,
        on_token: callable = lambda tok: None,
    ) -> str:
        """Process a user question through the tool-use loop.

        Returns the final natural language answer.
        """
        self.last_sql = None
        self.last_tool_results.clear()

        for round_num in range(MAX_TOOL_ROUNDS):
            prompt = build_prompt(question, self.history)
            on_status(f"Thinking (round {round_num + 1})...")

            response = generate_full(prompt)

            # Check for tool calls
            tool_calls = parse_tool_calls(response)

            if not tool_calls:
                # No tool calls — this is the final answer
                self.history.append({"role": "user", "content": question})
                self.history.append({"role": "model", "content": response})
                return response.strip()

            # Execute tool calls
            results: list[ToolResult] = []
            for tc in tool_calls:
                on_status(f"Executing {tc.kind}: {tc.code[:60]}...")
                result = execute_tool(tc, search_text=question)
                results.append(result)

                if tc.kind == "sql":
                    self.last_sql = tc.code

            self.last_tool_results = results

            # Add to history for next round
            self.history.append({"role": "user", "content": question})
            self.history.append({"role": "model", "content": response})

            for result in results:
                self.history.append({
                    "role": "tool",
                    "content": result.output,
                })

            # The question for the next round becomes implicit
            # (the LLM sees the tool results and continues)
            question = "Based on the tool results above, please answer the original question."

        return "I wasn't able to find a complete answer after several rounds of querying. Please try rephrasing your question."


class DirectSession:
    """A session that bypasses Gemma and executes queries directly.

    Useful for testing the pipeline without the LLM, or when Gemma
    model weights are not yet available.
    """

    def __init__(self) -> None:
        self.last_sql: str | None = None

    def semantic_search(self, query: str, *, limit: int = 10) -> list[dict]:
        """Run a direct semantic search over commit messages."""
        from src.ingest.embed import embed_query
        from src.db.queries import execute_query, SEMANTIC_SEARCH

        vec = embed_query(query)
        vec_literal = "[" + ",".join(f"{v:.8f}" for v in vec) + "]"

        result = execute_query(
            SEMANTIC_SEARCH,
            {"query_vec": vec_literal, "limit": limit},
            query_name="semantic_search",
        )
        self.last_sql = SEMANTIC_SEARCH
        return result.rows

    def raw_sql(self, sql: str) -> list[dict]:
        """Execute raw SQL."""
        from src.db.queries import execute_raw_sql

        result = execute_raw_sql(sql)
        self.last_sql = sql
        return result.rows

    def git_show(self, hash_prefix: str) -> str:
        """Run git show on a commit."""
        from src.inference.tools import execute_tool, ToolCall

        call = ToolCall(kind="git", code=f"git show {hash_prefix}")
        result = execute_tool(call)
        return result.output
