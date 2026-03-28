"""Tool execution: parse LLM output for SQL/git commands, execute them, return results.

The LLM generates structured output with ```sql or ```bash fences.
This module extracts those blocks, executes them safely, and formats
the results for injection back into the conversation.
"""

import logging
import re
import subprocess
from dataclasses import dataclass

from src.db.queries import execute_raw_sql, QueryResult
from src.ingest.embed import embed_query
from src.utils.config import KERNEL_REPO_PATH

logger = logging.getLogger(__name__)

# Max rows to include in tool results sent back to the LLM
MAX_RESULT_ROWS = 30

# Allowed git subcommands
_ALLOWED_GIT_CMDS = {"show", "log", "blame", "diff", "diff-tree"}

_SQL_BLOCK_RE = re.compile(r"```sql\s*\n(.*?)```", re.DOTALL)
_BASH_BLOCK_RE = re.compile(r"```bash\s*\n(.*?)```", re.DOTALL)
_QUERY_VEC_PLACEHOLDER = "$QUERY_VEC"


@dataclass
class ToolCall:
    """A parsed tool call from LLM output."""
    kind: str  # "sql" or "git"
    code: str  # The raw SQL or bash command


@dataclass
class ToolResult:
    """Result of executing a tool call."""
    tool_call: ToolCall
    output: str
    success: bool
    query_result: QueryResult | None = None


def parse_tool_calls(llm_output: str) -> list[ToolCall]:
    """Extract SQL and bash tool calls from LLM output."""
    calls: list[ToolCall] = []

    for match in _SQL_BLOCK_RE.finditer(llm_output):
        sql = match.group(1).strip()
        if sql:
            calls.append(ToolCall(kind="sql", code=sql))

    for match in _BASH_BLOCK_RE.finditer(llm_output):
        cmd = match.group(1).strip()
        if cmd:
            calls.append(ToolCall(kind="git", code=cmd))

    return calls


def execute_tool(call: ToolCall, *, search_text: str | None = None) -> ToolResult:
    """Execute a single tool call and return the result."""
    if call.kind == "sql":
        return _execute_sql(call, search_text=search_text)
    elif call.kind == "git":
        return _execute_git(call)
    else:
        return ToolResult(
            tool_call=call,
            output=f"Unknown tool kind: {call.kind}",
            success=False,
        )


def _execute_sql(call: ToolCall, *, search_text: str | None = None) -> ToolResult:
    """Execute a SQL query, substituting $QUERY_VEC if needed."""
    sql = call.code.rstrip(";")

    # If the query uses $QUERY_VEC, embed the search text and substitute
    if _QUERY_VEC_PLACEHOLDER in sql:
        if search_text is None:
            return ToolResult(
                tool_call=call,
                output="Query uses $QUERY_VEC but no search text available.",
                success=False,
            )
        vec = embed_query(search_text)
        vec_literal = "'" + "[" + ",".join(f"{v:.8f}" for v in vec) + "]" + "'::vector"
        sql = sql.replace(_QUERY_VEC_PLACEHOLDER, vec_literal)

    try:
        result = execute_raw_sql(sql)
        output = _format_query_result(result)
        return ToolResult(
            tool_call=call,
            output=output,
            success=True,
            query_result=result,
        )
    except Exception as e:
        logger.error("SQL execution failed: %s", e)
        return ToolResult(
            tool_call=call,
            output=f"SQL error: {e}",
            success=False,
        )


def _execute_git(call: ToolCall) -> ToolResult:
    """Execute a git command against the kernel repo."""
    cmd = call.code.strip()

    # Basic safety: only allow git commands
    parts = cmd.split()
    if not parts or parts[0] != "git":
        return ToolResult(
            tool_call=call,
            output="Only git commands are allowed.",
            success=False,
        )

    if len(parts) < 2 or parts[1] not in _ALLOWED_GIT_CMDS:
        return ToolResult(
            tool_call=call,
            output=f"Only these git subcommands are allowed: {', '.join(sorted(_ALLOWED_GIT_CMDS))}",
            success=False,
        )

    # Inject -C repo_path after 'git'
    full_cmd = ["git", "-C", KERNEL_REPO_PATH] + parts[1:]

    try:
        result = subprocess.run(
            full_cmd,
            capture_output=True,
            text=True,
            timeout=30,
            errors="replace",
        )
        output = result.stdout
        if result.returncode != 0:
            output = f"Exit code {result.returncode}\n{result.stderr}\n{result.stdout}"

        # Truncate very long output
        if len(output) > 8000:
            output = output[:8000] + "\n... (truncated)"

        return ToolResult(
            tool_call=call,
            output=output,
            success=result.returncode == 0,
        )
    except subprocess.TimeoutExpired:
        return ToolResult(
            tool_call=call,
            output="Command timed out after 30 seconds.",
            success=False,
        )
    except Exception as e:
        return ToolResult(
            tool_call=call,
            output=f"Error: {e}",
            success=False,
        )


def _format_query_result(result: QueryResult) -> str:
    """Format query results as a readable text table for the LLM."""
    if not result.rows:
        return "(0 rows returned)"

    rows = result.rows[:MAX_RESULT_ROWS]
    columns = list(rows[0].keys())

    # Build simple text table
    lines = [" | ".join(columns)]
    lines.append("-+-".join("-" * len(c) for c in columns))

    for row in rows:
        vals = []
        for col in columns:
            v = row[col]
            if v is None:
                vals.append("NULL")
            else:
                s = str(v)
                if len(s) > 80:
                    s = s[:77] + "..."
                vals.append(s)
        lines.append(" | ".join(vals))

    if result.row_count > MAX_RESULT_ROWS:
        lines.append(f"... ({result.row_count - MAX_RESULT_ROWS} more rows)")

    lines.append(f"({result.row_count} rows)")
    return "\n".join(lines)
