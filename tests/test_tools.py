"""Tests for src.inference.tools — parsing tool calls from LLM output."""

from src.inference.tools import parse_tool_calls


def test_parse_sql_block():
    output = """Here's a query:
```sql
SELECT count(*) FROM commits;
```
"""
    calls = parse_tool_calls(output)
    assert len(calls) == 1
    assert calls[0].kind == "sql"
    assert "SELECT count(*)" in calls[0].code


def test_parse_bash_block():
    output = """Let me show that commit:
```bash
git show abc123
```
"""
    calls = parse_tool_calls(output)
    assert len(calls) == 1
    assert calls[0].kind == "git"
    assert calls[0].code == "git show abc123"


def test_parse_multiple_blocks():
    output = """First query:
```sql
SELECT * FROM commits LIMIT 5;
```
Then check git:
```bash
git log --oneline -5
```
"""
    calls = parse_tool_calls(output)
    assert len(calls) == 2
    assert calls[0].kind == "sql"
    assert calls[1].kind == "git"


def test_parse_no_blocks():
    output = "This is just a plain text answer with no code blocks."
    calls = parse_tool_calls(output)
    assert len(calls) == 0


def test_parse_non_tool_code_block():
    output = """Here's some python:
```python
print("hello")
```
"""
    calls = parse_tool_calls(output)
    assert len(calls) == 0
