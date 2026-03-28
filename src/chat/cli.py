"""Kernel History Chat — Terminal interface.

Commands:
  %C  - Reset conversation context
  %Q  - Quit
  %S  - Show last SQL query executed
  %D  - Direct mode (bypass Gemma, use built-in queries)
  %G  - Gemma mode (use LLM for query planning)
"""

import readline  # noqa: F401 — enables line editing in input()
import sys

from src.db.queries import execute_raw_sql
from src.chat.session import DirectSession, Session
from src.utils.logging import setup_logging


def _print_status(msg: str) -> None:
    print(f"\033[90m[{msg}]\033[0m", file=sys.stderr)


def _print_rows(rows: list[dict], max_rows: int = 20) -> None:
    """Pretty-print query result rows."""
    if not rows:
        print("(no results)")
        return

    columns = list(rows[0].keys())
    col_widths = {c: len(c) for c in columns}
    display_rows = rows[:max_rows]

    for row in display_rows:
        for c in columns:
            val = str(row[c]) if row[c] is not None else "NULL"
            col_widths[c] = min(max(col_widths[c], len(val)), 80)

    header = " | ".join(c.ljust(col_widths[c]) for c in columns)
    sep = "-+-".join("-" * col_widths[c] for c in columns)
    print(header)
    print(sep)

    for row in display_rows:
        vals = []
        for c in columns:
            val = str(row[c]) if row[c] is not None else "NULL"
            if len(val) > 80:
                val = val[:77] + "..."
            vals.append(val.ljust(col_widths[c]))
        print(" | ".join(vals))

    if len(rows) > max_rows:
        print(f"... ({len(rows) - max_rows} more rows)")
    print(f"({len(rows)} rows)")


def _get_db_stats() -> str:
    """Get a one-line summary of indexed data."""
    try:
        result = execute_raw_sql(
            "SELECT count(*) AS n, count(msg_embedding) AS emb FROM commits"
        )
        row = result.rows[0]
        return f"{row['n']:,} commits indexed, {row['emb']:,} with embeddings"
    except Exception:
        return "database not available"


def main() -> None:
    setup_logging("WARNING")

    stats = _get_db_stats()
    print(f"\n  Kernel History Chat ({stats})")
    print("  Type %C to reset, %S for last SQL, %Q to quit\n")

    # Start in direct mode (no Gemma needed)
    direct = DirectSession()
    gemma_session = None
    use_gemma = False

    while True:
        try:
            user_input = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not user_input:
            continue

        # Commands
        if user_input.upper() == "%Q":
            break
        elif user_input.upper() == "%C":
            if gemma_session:
                gemma_session.reset()
            print("Context cleared.")
            continue
        elif user_input.upper() == "%S":
            sql = direct.last_sql if not use_gemma else (gemma_session.last_sql if gemma_session else None)
            if sql:
                print(f"```sql\n{sql}\n```")
            else:
                print("No SQL executed yet.")
            continue
        elif user_input.upper() == "%D":
            use_gemma = False
            print("Switched to direct mode.")
            continue
        elif user_input.upper() == "%G":
            use_gemma = True
            if gemma_session is None:
                gemma_session = Session()
            print("Switched to Gemma mode.")
            continue

        # Handle queries
        if use_gemma:
            if gemma_session is None:
                gemma_session = Session()
            try:
                answer = gemma_session.ask(
                    user_input,
                    on_status=_print_status,
                )
                print(f"\n{answer}\n")
            except Exception as e:
                print(f"Error: {e}")
        else:
            # Direct mode: semantic search by default, or raw SQL if starts with SELECT
            if user_input.upper().startswith("SELECT"):
                try:
                    rows = direct.raw_sql(user_input)
                    _print_rows(rows)
                except Exception as e:
                    print(f"SQL error: {e}")
            else:
                try:
                    _print_status("Searching...")
                    rows = direct.semantic_search(user_input)
                    _print_rows(rows)
                except Exception as e:
                    print(f"Search error: {e}")

        print()


if __name__ == "__main__":
    main()
