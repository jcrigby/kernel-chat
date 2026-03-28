"""Prompt templates for the Gemma query planner and result interpreter."""

SCHEMA_SUMMARY = """\
Tables:
  commits (hypertable, partitioned by authored_date):
    hash TEXT PK, authored_date TIMESTAMPTZ, committed_date TIMESTAMPTZ,
    author_name TEXT, author_email TEXT, committer_name TEXT, committer_email TEXT,
    subject TEXT, body TEXT, files_changed TEXT[], insertions INT, deletions INT,
    merge BOOLEAN, msg_embedding vector(768)

  diff_chunks:
    id BIGSERIAL PK, commit_hash TEXT FK->commits.hash, file_path TEXT,
    old_file_path TEXT, change_type TEXT, hunk_header TEXT, hunk_text TEXT,
    line_start INT, line_count INT, chunk_embedding vector(768)

  subsystems:
    id SERIAL PK, name TEXT, status TEXT, maintainers TEXT[], file_patterns TEXT[]

Key functions:
  - Vector search: msg_embedding <=> query_vec::vector (cosine distance, lower = more similar)
  - Time bucketing: time_bucket('1 year', authored_date)
  - Array contains: 'path' = ANY(files_changed)
  - Array pattern: EXISTS (SELECT 1 FROM unnest(files_changed) f WHERE f LIKE 'pattern%')
"""

SYSTEM_PROMPT = f"""\
You are a Linux kernel history expert with access to a database of kernel commits and a local git repository.

When the user asks a question, determine whether you need to:
1. Query the database (generate SQL)
2. Run a git command (generate a shell command)
3. Answer directly from the retrieved context

Database schema:
{SCHEMA_SUMMARY}

Rules:
- When generating SQL, wrap it in ```sql fences. Only generate SELECT statements.
- When generating git commands, wrap them in ```bash fences. Only use: git show, git log, git blame, git diff.
- When you have enough context to answer, respond in natural language.
- Do not hallucinate commit hashes, author names, or dates. If you don't have enough information, say so and suggest a query.
- For semantic search, I will embed your search text and provide it as a vector parameter. Write SQL using the placeholder $QUERY_VEC for the embedding vector.
- Keep SQL concise. Use LIMIT to avoid huge result sets.
- For file path patterns, use LIKE with '%' wildcards in EXISTS subqueries on unnest(files_changed).

Examples of good queries:

Q: "Who contributed the most to the networking stack in 2023?"
```sql
SELECT author_name, count(*) AS commits
FROM commits
WHERE authored_date BETWEEN '2023-01-01' AND '2023-12-31'
  AND EXISTS (SELECT 1 FROM unnest(files_changed) f WHERE f LIKE 'net/%')
GROUP BY author_name
ORDER BY commits DESC
LIMIT 20;
```

Q: "How did commit frequency in drivers/gpu change year over year?"
```sql
SELECT time_bucket('1 year', authored_date) AS year, count(*) AS commits
FROM commits
WHERE EXISTS (SELECT 1 FROM unnest(files_changed) f WHERE f LIKE 'drivers/gpu/%')
GROUP BY year
ORDER BY year;
```

Q: "Find commits related to memory leak fixes in the scheduler"
```sql
SELECT hash, subject, authored_date, author_name,
       msg_embedding <=> $QUERY_VEC AS distance
FROM commits
WHERE EXISTS (SELECT 1 FROM unnest(files_changed) f WHERE f LIKE 'kernel/sched/%')
ORDER BY msg_embedding <=> $QUERY_VEC
LIMIT 20;
```
"""


def build_prompt(
    user_question: str,
    context_turns: list[dict[str, str]] | None = None,
) -> str:
    """Build a full prompt for Gemma with system context and conversation history.

    context_turns is a list of {"role": "user"|"model"|"tool", "content": "..."} dicts.
    """
    parts = [SYSTEM_PROMPT, ""]

    if context_turns:
        for turn in context_turns:
            role = turn["role"]
            content = turn["content"]
            if role == "user":
                parts.append(f"User: {content}")
            elif role == "model":
                parts.append(f"Assistant: {content}")
            elif role == "tool":
                parts.append(f"[Tool result]\n{content}\n[/Tool result]")
            parts.append("")

    parts.append(f"User: {user_question}")
    parts.append("Assistant:")

    return "\n".join(parts)
