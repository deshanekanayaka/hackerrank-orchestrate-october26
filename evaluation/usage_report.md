# Usage report: Ghost Data Still Exists

This file is generated. Run `python3 code/evaluation/usage.py` to
rewrite it. The source is `code/cache/usage.jsonl`, which gains one
line for every model call.

Calls recorded from 2026-10-24T22:34:10Z to 2026-10-24T23:06:26Z.

## The run that produced output.csv

The caches in `code/cache/` are committed. A clean checkout
therefore reproduces `output.csv` with no API key and no model
call. The figures below cover the 85 calls that built those
caches.

| Quantity | Value |
| --- | --- |
| Model provider | Anthropic |
| Models used | 2 |
| Model calls | 85 |
| Input tokens | 169,948 |
| Output tokens | 70,053 |
| Total tokens | 240,001 |
| Evaluation requests | 518 |
| Average tokens per request | 463.3 |
| Estimated total cost | $0.7039 |
| Estimated cost per request | $0.0014 |

## Per model

| Model | Calls | Input tokens | Output tokens | Total tokens | Input $/MTok | Output $/MTok | Cost |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `claude-haiku-4-5-20251001` | 69 | 117,437 | 43,811 | 161,248 | $1.00 | $5.00 | $0.3365 |
| `claude-sonnet-5` | 16 | 52,511 | 26,242 | 78,753 | $2.00 | $10.00 | $0.3674 |
| **Overall** | 85 | 169,948 | 70,053 | 240,001 | | | $0.7039 |

## Per stage

| Stage | What it does | Calls | Total tokens |
| --- | --- | --- | --- |
| `intent` | Decide whether each request authorizes deletion. | 69 | 161,248 |
| `vision` | Transcribe each screenshot and PDF document once. | 16 | 78,753 |

## How the cost is derived

Prices are United States dollars per million tokens, from the
Anthropic price list on 2026-10-25. The table sits in
`PRICES` in `code/evaluation/usage.py`. A model the table does not
carry makes the run fail, so a missing price can never appear as a
cost of zero.

The cost of one call is the input tokens times the input rate plus
the output tokens times the output rate, divided by one million.
The figures are an estimate. They do not include prompt caching
discounts, and the pipeline does not use the Batch API.

## What the model does, and what it never does

Two stages call a model. Every other stage is deterministic code.

1. `intent`: Decide whether each request authorizes deletion.
1. `vision`: Transcribe each screenshot and PDF document once.

The model never decides a case status, never chooses an operation,
and never reads the policy. It reads a request text, and it
transcribes a page. Policy, state, and step order are code.

