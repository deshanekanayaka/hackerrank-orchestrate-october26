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
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
USAGE = ROOT / "code" / "cache" / "usage.jsonl"
REQUESTS = ROOT / "dataset" / "deletion_requests.csv"
REPORT = ROOT / "evaluation" / "usage_report.md"

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


def money(value):
    """A cost small enough to read, without pretending to false precision."""
    return f"${value:.4f}" if value < 1 else f"${value:.2f}"


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

    # A real report must name every model it charges for.
    text = build()
    for model in totals(read_usage(), "model"):
        assert model in text, model
    assert "Model provider | Anthropic" in text
    print("selftest: PASS")
    return 0


def build():
    rows = read_usage()
    requests = count_requests()
    per_model = totals(rows, "model", priced=True)
    per_stage = totals(rows, "stage")

    calls = sum(b["calls"] for b in per_model.values())
    tokens_in = sum(b["input"] for b in per_model.values())
    tokens_out = sum(b["output"] for b in per_model.values())
    tokens = tokens_in + tokens_out
    spend = sum(b["cost"] for b in per_model.values())
    first = min(r["at"] for r in rows)
    last = max(r["at"] for r in rows)

    out = []
    add = out.append
    add("# Usage report: Ghost Data Still Exists")
    add("")
    add("This file is generated. Run `python3 code/evaluation/usage.py` to")
    add("rewrite it. The source is `code/cache/usage.jsonl`, which gains one")
    add("line for every model call.")
    add("")
    add(f"Calls recorded from {first} to {last}.")
    add("")
    add("## The run that produced output.csv")
    add("")
    add("The caches in `code/cache/` are committed. A clean checkout")
    add("therefore reproduces `output.csv` with no API key and no model")
    add(f"call. The figures below cover the {calls} calls that built those")
    add("caches.")
    add("")
    add("| Quantity | Value |")
    add("| --- | --- |")
    add(f"| Model provider | {PROVIDER} |")
    add(f"| Models used | {len(per_model)} |")
    add(f"| Model calls | {calls} |")
    add(f"| Input tokens | {tokens_in:,} |")
    add(f"| Output tokens | {tokens_out:,} |")
    add(f"| Total tokens | {tokens:,} |")
    add(f"| Evaluation requests | {requests} |")
    add(f"| Average tokens per request | {tokens / requests:.1f} |")
    add(f"| Estimated total cost | {money(spend)} |")
    add(f"| Estimated cost per request | {money(spend / requests)} |")
    add("")
    add("## Per model")
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
    add("## Per stage")
    add("")
    add("| Stage | What it does | Calls | Total tokens |")
    add("| --- | --- | --- | --- |")
    for stage in sorted(per_stage):
        bucket = per_stage[stage]
        add(f"| `{stage}` | {STAGES.get(stage, '')} | {bucket['calls']} "
            f"| {bucket['tokens']:,} |")
    add("")
    add("## How the cost is derived")
    add("")
    add("Prices are United States dollars per million tokens, from the")
    add("Anthropic price list on 2026-10-25. The table sits in")
    add("`PRICES` in `code/evaluation/usage.py`. A model the table does not")
    add("carry makes the run fail, so a missing price can never appear as a")
    add("cost of zero.")
    add("")
    add("The cost of one call is the input tokens times the input rate plus")
    add("the output tokens times the output rate, divided by one million.")
    add("The figures are an estimate. They do not include prompt caching")
    add("discounts, and the pipeline does not use the Batch API.")
    add("")
    add("## What the model does, and what it never does")
    add("")
    add("Two stages call a model. Every other stage is deterministic code.")
    add("")
    for stage in sorted(per_stage):
        add(f"1. `{stage}`: {STAGES.get(stage, '')}")
    add("")
    add("The model never decides a case status, never chooses an operation,")
    add("and never reads the policy. It reads a request text, and it")
    add("transcribes a page. Policy, state, and step order are code.")
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
