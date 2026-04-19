# LLM Evaluation Plan for Kernel History Chat

## What we're testing

The LLM mode (`%L`) asks a model to do three things:
1. **Generate correct SQL** against our schema (pgvector, TimescaleDB, array ops)
2. **Choose the right query strategy** (semantic vs temporal vs relational vs hybrid)
3. **Interpret results** and produce a useful natural language answer

Different models will vary on all three. We need empirical data.

## Test cases

Each test case has a natural language question, an expected query strategy, and a way to verify the answer. We don't check for exact SQL — we check whether the executed query returns reasonable results and whether the final answer contains key facts.

### Tier 1: Basic (any competent model should pass)

| ID | Question | Expected strategy | Verification |
|----|----------|-------------------|--------------|
| B1 | "How many commits are in the database?" | Simple COUNT | Answer contains a number ~1.4M |
| B2 | "Who has the most commits?" | GROUP BY author, ORDER BY count | Answer names Linus Torvalds |
| B3 | "Show me the commit that introduced io_uring" | Semantic search | Answer contains Jens Axboe, 2019 |
| B4 | "How many commits were there in 2023?" | Date-filtered COUNT | Answer is a plausible number (70k-90k) |
| B5 | "What files did commit abc123 touch?" | Lookup by hash prefix (SQL or git show) | Returns file list |

### Tier 2: Intermediate (requires correct pgvector/TimescaleDB syntax)

| ID | Question | Expected strategy | Verification |
|----|----------|-------------------|--------------|
| I1 | "Find commits related to memory leak fixes in the scheduler" | Semantic search + path filter on kernel/sched/ | Results mention sched, memory/leak in subjects |
| I2 | "How did commit frequency in drivers/gpu change year over year?" | time_bucket + path filter | Returns year-over-year counts, plausible trend |
| I3 | "Who contributed the most to the networking stack in 2024?" | Date range + path filter (net/%, drivers/net/%) + GROUP BY | Top names are plausible (check against known ground truth) |
| I4 | "What were the most significant scheduler changes between 2020 and 2022?" | Hybrid: semantic + date range + path | Results are in date range, related to scheduler |
| I5 | "When did Rust support first appear?" | Semantic search | Answer mentions 2022 (v6.1), Miguel Ojeda |

### Tier 3: Hard (requires multi-step reasoning or follow-up queries)

| ID | Question | Expected strategy | Verification |
|----|----------|-------------------|--------------|
| H1 | "Compare commit activity in mm/ between 2020 and 2024" | Two temporal queries or one with grouping | Answer has numbers for both periods |
| H2 | "Show me the full diff of the commit that introduced BPF" | Semantic search → identify commit → git show | Produces actual diff output |
| H3 | "Who worked on both the scheduler and memory management in 2023?" | Intersection query (two path filters, same author) | Returns author names |
| H4 | "What was the most active subsystem in 2024?" | Needs to reason about file path prefixes as proxy for subsystems | Answer names a plausible top-level directory |
| H5 | "How has Linus's personal commit rate changed over the years?" | Author filter + time_bucket | Shows declining trend (more merges, less direct code) |

## Scoring

Each test case is scored on three dimensions:

- **SQL correctness** (0-2): 0 = syntax error or wrong schema usage, 1 = runs but wrong approach, 2 = correct
- **Result quality** (0-2): 0 = no useful results, 1 = partially relevant, 2 = correct results returned
- **Answer quality** (0-2): 0 = hallucinated or wrong, 1 = vague but directionally correct, 2 = accurate and specific

Max score per test: 6. Max total: 90 (15 tests × 6).

## Models to test

Via OpenRouter, cheapest to most expensive:

| Model | OpenRouter ID | $/M input tokens | Notes |
|-------|---------------|-------------------|-------|
| Gemma 3 27B | `google/gemma-3-27b-it:free` | Free | Our default. May struggle with complex SQL. |
| Gemini 2.0 Flash | `google/gemini-2.0-flash-001` | ~$0.10 | Fast, good at structured output. |
| Claude 3.5 Haiku | `anthropic/claude-3.5-haiku` | ~$0.80 | Good balance of cost and capability. |
| Claude Sonnet 4 | `anthropic/claude-sonnet-4` | ~$3.00 | Strong reasoning, likely best SQL. |
| GPT-4o mini | `openai/gpt-4o-mini` | ~$0.15 | Cheap baseline. |

## Implementation

### Structure

```
tests/
  eval/
    cases.json          # Test case definitions
    run_eval.py         # Evaluation runner
    score.py            # Scoring logic (automated + manual review)
    results/            # Output per model per run
      gemma-3-27b_2026-04-18.json
      gemini-flash_2026-04-18.json
```

### cases.json format

```json
[
  {
    "id": "B1",
    "tier": "basic",
    "question": "How many commits are in the database?",
    "expected_strategy": "count",
    "auto_checks": [
      {"type": "answer_contains_number_range", "min": 1400000, "max": 1500000}
    ],
    "ground_truth_notes": "Should be ~1,429,131"
  },
  {
    "id": "I1",
    "tier": "intermediate",
    "question": "Find commits related to memory leak fixes in the scheduler",
    "expected_strategy": "semantic_with_path",
    "auto_checks": [
      {"type": "sql_executes", "value": true},
      {"type": "result_count_min", "value": 5},
      {"type": "results_contain_path_pattern", "pattern": "kernel/sched/"}
    ],
    "ground_truth_notes": "Results should reference sched subsystem"
  }
]
```

### run_eval.py logic

```
for each model:
    for each test case:
        1. Create a fresh Session with the model
        2. Call session.ask(question)
        3. Capture: generated SQL, tool results, final answer, token usage, latency
        4. Run auto_checks against the captured data
        5. Save everything to results JSON

        Auto-scoring:
        - sql_executes: did the SQL run without error?
        - answer_contains: does the answer contain expected substring?
        - answer_contains_number_range: does the answer mention a number in range?
        - result_count_min: did the query return at least N rows?
        - results_contain_path_pattern: do returned commits touch expected paths?

        Manual scoring (filled in later):
        - answer_quality: human judgment 0-2
```

### What we learn

The results tell us:
- Which models can write valid pgvector/TimescaleDB SQL at all
- Whether free Gemma is viable or if we need to budget for a paid model
- Where the failure modes are (SQL syntax? wrong strategy? hallucinated answers?)
- Cost per query for each model tier

This directly informs whether the OpenRouter approach works or if local Gemma is worth the effort.
