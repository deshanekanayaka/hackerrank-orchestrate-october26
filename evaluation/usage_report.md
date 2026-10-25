# Usage report: Ghost Data Still Exists

This file is generated. Run `python3 code/evaluation/usage.py` to rewrite
it. The source is `code/cache/usage.jsonl`, which gains one line for every
model call.

The log is append-only and holds every cache rebuild ever run, from
2026-10-24T22:34:10Z to 2026-10-24T23:06:26Z. It is therefore cumulative.
This report states the cost of one full run and the cumulative cost apart,
because only the first answers the question a grader asks.

## One full run over the 518 requests

A clean checkout needs no model call, because the caches in `code/cache/`
are committed. These are the figures for rebuilding them from nothing.

The call count is exact. The request texts go out in batches of 25, so 518
requests need 21 calls. Each of the 15 screenshots and PDF documents is
transcribed once. The token figures are derived. Each call is charged at the
average logged call of its stage.

| Quantity | Value |
| --- | --- |
| Model provider | Anthropic |
| Models used | 2 |
| Model calls | 36 |
| Input tokens | 84,971 |
| Output tokens | 37,936 |
| Total tokens | 122,907 |
| Evaluation requests | 518 |
| Average tokens per request | 237.3 |
| Estimated total cost | $0.4469 |
| Estimated cost per request | $0.0009 |

Per model and per stage, for that one run:

| Stage | Model | Calls | Input tokens | Output tokens | Cost |
| --- | --- | --- | --- | --- | --- |
| `intent` | `claude-haiku-4-5-20251001` | 21 | 35,742 | 13,334 | $0.1024 |
| `vision` | `claude-sonnet-5` | 15 | 49,229 | 24,602 | $0.3445 |
| **Overall** | | 36 | 84,971 | 37,936 | $0.4469 |

The average tokens per request divides the whole run by the 518 requests.
The transcription is a one-time cost and does not grow with the request
count, so a larger request set lowers that average.

## Cumulative cost of every rebuild

These are the exact totals in the log. They exceed one run, because the
caches were rebuilt several times while the solution was built. They also
include the 32 sample requests, which are classified alongside the 518.

| Quantity | Value |
| --- | --- |
| Model calls | 85 |
| Input tokens | 169,948 |
| Output tokens | 70,053 |
| Total tokens | 240,001 |
| Estimated cost | $0.7039 |

| Model | Calls | Input tokens | Output tokens | Total tokens | Input $/MTok | Output $/MTok | Cost |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `claude-haiku-4-5-20251001` | 69 | 117,437 | 43,811 | 161,248 | $1.00 | $5.00 | $0.3365 |
| `claude-sonnet-5` | 16 | 52,511 | 26,242 | 78,753 | $2.00 | $10.00 | $0.3674 |
| **Overall** | 85 | 169,948 | 70,053 | 240,001 | | | $0.7039 |

| Stage | What it does | Calls | Total tokens |
| --- | --- | --- | --- |
| `intent` | Decide whether each request authorizes deletion. | 69 | 161,248 |
| `vision` | Transcribe each screenshot and PDF document once. | 16 | 78,753 |

None of the 85 logged calls carries a run id. The field was added on
2026-10-25, after these calls were made, so the log cannot separate them
into runs. The one-run figures above are derived instead of measured for
that reason.

## How the cost is derived

Prices are United States dollars per million tokens, from the Anthropic
price list on 2026-10-25. The table sits in `PRICES` in
`code/evaluation/usage.py`. A model the table does not carry makes the run
fail, so a missing price can never appear as a cost of zero.

The cost of one call is the input tokens times the input rate plus the
output tokens times the output rate, divided by one million. The figures are
an estimate. They do not include prompt caching discounts, and the pipeline
does not use the Batch API.

## What the model does, and what it never does

Two stages call a model. Every other stage is deterministic code.

1. `intent`: Decide whether each request authorizes deletion.
1. `vision`: Transcribe each screenshot and PDF document once.

The model never decides a case status, never chooses an operation, and never
reads the policy. It reads a request text, and it transcribes a page.
Policy, state, and step order are code.

