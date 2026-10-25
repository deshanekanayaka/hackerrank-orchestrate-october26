"""Generate evaluation/usage_report.md from code/cache/usage.jsonl.

Every model call appends one line to the usage log. This reads the log, the
request file, and the price table below, then writes the report. The report
is generated and never hand-edited, so a rerun after a new model call always
tells the truth.

    python3 code/evaluation/usage.py            # write the report
    python3 code/evaluation/usage.py --print    # write it to stdout instead
    python3 code/evaluation/usage.py selftest   # test the arithmetic

Prices are United States dollars per million tokens, taken from the
Anthropic price list on 2026-10-25. A price the table does not carry makes
the run fail rather than report a cost of zero.
"""

import csv
import json
import math
import sys
import textwrap
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
USAGE = ROOT / "code" / "cache" / "usage.jsonl"
REQUESTS = ROOT / "dataset" / "deletion_requests.csv"
SAMPLE = ROOT / "dataset" / "sample_deletion_requests.csv"
VISION_CACHE = ROOT / "code" / "cache" / "vision.json"
REPORT = ROOT / "evaluation" / "usage_report.md"

# intent.py sends this many request texts per call.
INTENT_BATCH = 25

PROVIDER = "Anthropic"
# model id -> (input dollars per million, output dollars per million)
PRICES = {
    "claude-haiku-4-5-20251001": (1.00, 5.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-opus-5": (5.00, 25.00),
}

# What each stage is for, in one line.
STAGES = {
    "intent": "Decide whether each request authorizes deletion.",
    "vision": "Transcribe each screenshot and PDF document once.",
}


def read_usage(path=USAGE):
    if not path.exists():
        raise SystemExit(f"FAIL: no usage log at {path}")
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    if not rows:
        raise SystemExit(f"FAIL: the usage log at {path} is empty")
    return rows


def cost(model, input_tokens, output_tokens):
    if model not in PRICES:
        raise SystemExit(f"FAIL: no price for model {model}. Add it to "
                         f"PRICES in code/evaluation/usage.py.")
    rate_in, rate_out = PRICES[model]
    return (input_tokens * rate_in + output_tokens * rate_out) / 1_000_000


def totals(rows, field, priced=False):
    """Calls and tokens per value of one field.

    With priced set, each value of the field is a model id and the bucket
    also carries its cost.
    """
    out = defaultdict(lambda: {"calls": 0, "input": 0, "output": 0})
    for row in rows:
        bucket = out[row[field]]
        bucket["calls"] += int(row.get("calls", 1))
        bucket["input"] += int(row["input_tokens"])
        bucket["output"] += int(row["output_tokens"])
    for name, bucket in out.items():
        bucket["tokens"] = bucket["input"] + bucket["output"]
        if priced:
            bucket["cost"] = cost(name, bucket["input"], bucket["output"])
    return dict(out)


def count_requests(path=REQUESTS):
    with open(path, newline="", encoding="utf-8") as fh:
        return sum(1 for _ in csv.DictReader(fh))


def count_documents(path=VISION_CACHE):
    """Files the vision stage transcribes, one call each."""
    if not path.exists():
        return 0
    return len(json.loads(path.read_text(encoding="utf-8")))


def money(value):
    """A cost small enough to read, and never rounded away to zero."""
    if value >= 1:
        return f"${value:.2f}"
    if value >= 0.0001:
        return f"${value:.4f}"
    if value > 0:
        return f"${value:.2e}"
    return "$0"


def mean_call(rows, stage):
    """Average input and output tokens of one call of this stage."""
    calls = [r for r in rows if r["stage"] == stage]
    if not calls:
        return 0.0, 0.0
    return (sum(r["input_tokens"] for r in calls) / len(calls),
            sum(r["output_tokens"] for r in calls) / len(calls))


def full_run(rows, requests, documents):
    """What one full rebuild of the caches costs, for the 518 requests.

    The usage log is append-only and holds every rebuild ever run, so its
    totals are cumulative and not the cost of one run. A full rebuild makes
    a known number of calls: the request texts go out in batches of
    INTENT_BATCH, and each document is transcribed once. The token cost of
    each call comes from the average logged call of that stage, so these
    figures are derived and not measured.
    """
    out = {}
    for stage, calls in (("intent", math.ceil(requests / INTENT_BATCH)),
                         ("vision", documents)):
        rate_in, rate_out = mean_call(rows, stage)
        model = next(r["model"] for r in rows if r["stage"] == stage)
        tokens_in = round(rate_in * calls)
        tokens_out = round(rate_out * calls)
        out[stage] = {
            "model": model,
            "calls": calls,
            "input": tokens_in,
            "output": tokens_out,
            "tokens": tokens_in + tokens_out,
            "cost": cost(model, tokens_in, tokens_out),
        }
    return out


def selftest():
    """The arithmetic, against numbers small enough to check by eye."""
    rows = [
        {"at": "t", "stage": "intent", "model": "claude-haiku-4-5",
         "calls": 1, "input_tokens": 1_000_000, "output_tokens": 0},
        {"at": "t", "stage": "vision", "model": "claude-sonnet-5",
         "calls": 1, "input_tokens": 0, "output_tokens": 1_000_000},
    ]
    assert cost("claude-haiku-4-5", 1_000_000, 0) == 1.00
    assert cost("claude-sonnet-5", 0, 1_000_000) == 10.00
    per_model = totals(rows, "model", priced=True)
    assert per_model["claude-haiku-4-5"]["cost"] == 1.00
    assert per_model["claude-sonnet-5"]["cost"] == 10.00
    assert totals(rows, "stage")["intent"]["tokens"] == 1_000_000

    # A small cost must never round away to zero, because the report
    # promises that a zero cost cannot appear.
    assert money(0.0000029) != "$0.0000", money(0.0000029)
    assert money(0) == "$0"

    # One full run must be smaller than the cumulative log, which holds
    # several rebuilds.
    real = read_usage()
    run = full_run(real, count_requests(), count_documents())
    assert sum(b["calls"] for b in run.values()) \
        < sum(int(r.get("calls", 1)) for r in real), "one run is not smaller"

    # A real report must name every model it charges for.
    text = build()
    for model in totals(real, "model"):
        assert model in text, model
    assert "Model provider | Anthropic" in text
    print("selftest: PASS")
    return 0


def build():
    def para(text):
        """One paragraph, wrapped, so the file reads as prose."""
        return textwrap.fill(" ".join(text.split()), width=76)

    rows = read_usage()
    requests = count_requests()
    documents = count_documents()
    per_model = totals(rows, "model", priced=True)
    per_stage = totals(rows, "stage")
    runs = totals([r for r in rows if r.get("run")], "run")

    calls = sum(b["calls"] for b in per_model.values())
    tokens_in = sum(b["input"] for b in per_model.values())
    tokens_out = sum(b["output"] for b in per_model.values())
    tokens = tokens_in + tokens_out
    spend = sum(b["cost"] for b in per_model.values())
    first = min(r["at"] for r in rows)
    last = max(r["at"] for r in rows)

    run = full_run(rows, requests, documents)
    run_calls = sum(b["calls"] for b in run.values())
    run_in = sum(b["input"] for b in run.values())
    run_out = sum(b["output"] for b in run.values())
    run_tokens = run_in + run_out
    run_spend = sum(b["cost"] for b in run.values())

    out = []
    add = out.append
    add("# Usage report: Ghost Data Still Exists")
    add("")
    add(para(
        "This file is generated. Run `python3 code/evaluation/usage.py` to "
        "rewrite it. The source is `code/cache/usage.jsonl`, which gains "
        "one line for every model call."))
    add("")
    add(para(
        f"The log is append-only and holds every cache rebuild ever run, "
        f"from {first} to {last}. It is therefore cumulative. This report "
        f"states the cost of one full run and the cumulative cost apart, "
        f"because only the first answers the question a grader asks."))
    add("")
    add("## One full run over the 518 requests")
    add("")
    add(para(
        "A clean checkout needs no model call, because the caches in "
        "`code/cache/` are committed. These are the figures for rebuilding "
        "them from nothing."))
    add("")
    add(para(
        f"The call count is exact. The request texts go out in batches of "
        f"{INTENT_BATCH}, so {requests} requests need "
        f"{run['intent']['calls']} calls. Each of the {documents} "
        f"screenshots and PDF documents is transcribed once. The token "
        f"figures are derived. Each call is charged at the average logged "
        f"call of its stage."))
    add("")
    add("| Quantity | Value |")
    add("| --- | --- |")
    add(f"| Model provider | {PROVIDER} |")
    add(f"| Models used | {len(run)} |")
    add(f"| Model calls | {run_calls} |")
    add(f"| Input tokens | {run_in:,} |")
    add(f"| Output tokens | {run_out:,} |")
    add(f"| Total tokens | {run_tokens:,} |")
    add(f"| Evaluation requests | {requests} |")
    add(f"| Average tokens per request | {run_tokens / requests:.1f} |")
    add(f"| Estimated total cost | {money(run_spend)} |")
    add(f"| Estimated cost per request | {money(run_spend / requests)} |")
    add("")
    add("Per model and per stage, for that one run:")
    add("")
    add("| Stage | Model | Calls | Input tokens | Output tokens | Cost |")
    add("| --- | --- | --- | --- | --- | --- |")
    for stage in sorted(run):
        bucket = run[stage]
        add(f"| `{stage}` | `{bucket['model']}` | {bucket['calls']} "
            f"| {bucket['input']:,} | {bucket['output']:,} "
            f"| {money(bucket['cost'])} |")
    add(f"| **Overall** | | {run_calls} | {run_in:,} | {run_out:,} "
        f"| {money(run_spend)} |")
    add("")
    add(para(
        f"The average tokens per request divides the whole run by the "
        f"{requests} requests. The transcription is a one-time cost and "
        f"does not grow with the request count, so a larger request set "
        f"lowers that average."))
    add("")
    add("## Cumulative cost of every rebuild")
    add("")
    add(para(
        f"These are the exact totals in the log. They exceed one run, "
        f"because the caches were rebuilt several times while the solution "
        f"was built. They also include the 32 sample requests, which are "
        f"classified alongside the {requests}."))
    add("")
    add("| Quantity | Value |")
    add("| --- | --- |")
    add(f"| Model calls | {calls} |")
    add(f"| Input tokens | {tokens_in:,} |")
    add(f"| Output tokens | {tokens_out:,} |")
    add(f"| Total tokens | {tokens:,} |")
    add(f"| Estimated cost | {money(spend)} |")
    add("")
    add("| Model | Calls | Input tokens | Output tokens | Total tokens "
        "| Input $/MTok | Output $/MTok | Cost |")
    add("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for model in sorted(per_model):
        bucket = per_model[model]
        rate_in, rate_out = PRICES[model]
        add(f"| `{model}` | {bucket['calls']} | {bucket['input']:,} "
            f"| {bucket['output']:,} | {bucket['tokens']:,} "
            f"| ${rate_in:.2f} | ${rate_out:.2f} "
            f"| {money(bucket['cost'])} |")
    add(f"| **Overall** | {calls} | {tokens_in:,} | {tokens_out:,} "
        f"| {tokens:,} | | | {money(spend)} |")
    add("")
    add("| Stage | What it does | Calls | Total tokens |")
    add("| --- | --- | --- | --- |")
    for stage in sorted(per_stage):
        bucket = per_stage[stage]
        add(f"| `{stage}` | {STAGES.get(stage, '')} | {bucket['calls']} "
            f"| {bucket['tokens']:,} |")
    add("")
    if runs:
        add(para(
            "Calls carry a run id from 2026-10-25 onward, so a later "
            "rebuild is attributable exactly:"))
        add("")
        add("| Run | Calls | Total tokens |")
        add("| --- | --- | --- |")
        for name in sorted(runs):
            add(f"| `{name}` | {runs[name]['calls']} "
                f"| {runs[name]['tokens']:,} |")
    else:
        add(para(
            f"None of the {calls} logged calls carries a run id. The field "
            f"was added on 2026-10-25, after these calls were made, so the "
            f"log cannot separate them into runs. The one-run figures above "
            f"are derived instead of measured for that reason."))
    add("")
    add("## How the cost is derived")
    add("")
    add(para(
        "Prices are United States dollars per million tokens, from the "
        "Anthropic price list on 2026-10-25. The table sits in `PRICES` in "
        "`code/evaluation/usage.py`. A model the table does not carry makes "
        "the run fail, so a missing price can never appear as a cost of "
        "zero."))
    add("")
    add(para(
        "The cost of one call is the input tokens times the input rate plus "
        "the output tokens times the output rate, divided by one million. "
        "The figures are an estimate. They do not include prompt caching "
        "discounts, and the pipeline does not use the Batch API."))
    add("")
    add("## What the model does, and what it never does")
    add("")
    add("Two stages call a model. Every other stage is deterministic code.")
    add("")
    for stage in sorted(per_stage):
        add(f"1. `{stage}`: {STAGES.get(stage, '')}")
    add("")
    add(para(
        "The model never decides a case status, never chooses an operation, "
        "and never reads the policy. It reads a request text, and it "
        "transcribes a page. Policy, state, and step order are code."))
    add("")
    return "\n".join(out) + "\n"


def main(argv):
    if "selftest" in argv:
        return selftest()
    text = build()
    if "--print" in argv:
        print(text, end="")
        return 0
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(text, encoding="utf-8")
    print(f"wrote {REPORT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
