# Ghost Data Still Exists: deletion audit agent

HackerRank Orchestrate, October 2026.

This solution audits whether a person's personal data was really deleted. For
each request in `dataset/deletion_requests.csv` it writes one row of
`output.csv` with a status and an ordered list of steps.

The challenge contract is in `problem_statement.md` in the repository, and
the rules this repository follows are in `AGENTS.md`. Neither file is part of
`code.zip`, because both belong to the organizer.

## Setup

You need Python 3.11 or later. Nothing else is required to produce
`output.csv`.

The two model caches in `code/cache/` are committed. A clean checkout
therefore reproduces `output.csv` with no API key and no model call.

```sh
python3 --version
```

To rebuild a cache you need the `anthropic` package and an API key. Read
"Rebuilding the caches" below. You do not need either to run the solution.

## Run

One command writes the submission file:

```sh
python3 code/main.py
```

It writes `output.csv` at the repository root, with 518 data rows sorted by
`case_id`.

To make sure that the file satisfies the contract:

```sh
python3 code/evaluation/main.py check output.csv
```

The checker reports `PASS: 518 rows, 0 violations`.

## How it works

The pipeline runs in six stages. One module owns each stage, and every module
has a selftest.

| Stage | Module | What it does |
| --- | --- | --- |
| 0 | `code/intent.py` | Decide whether the request authorizes deletion. |
| 1 | `code/identity.py` | Resolve the request email to a subject and every identifier that subject ever had. |
| 2 | `code/evidence.py` | Read every evidence file once and record what each one shows. |
| 3 | `code/status.py` | Decide the state of each resource at `audit_at`. |
| 4 | `code/policy.py` | Apply `deletion_rules.csv` to each resource. |
| 5 | `code/status.py` | Write the ordered findings, remediation, and verification steps. |

`code/vision.py` supports stage 2. It transcribes the 11 screenshots and the
4 PDF documents, because plain text search never reaches them.

A model is used in two places only. `code/intent.py` reads each request text
and decides whether the person asked for deletion. `code/vision.py`
transcribes each image and PDF page. The model never decides a case status,
never chooses an operation, and never reads the policy. Policy, state, and
step order are deterministic code.

## Tests

Every module tests itself against the real dataset. Run them all:

```sh
for m in identity intent policy evidence vision status; do python3 code/$m.py selftest; done
python3 code/evaluation/main.py selftest
python3 code/evaluation/usage.py selftest
```

Two more tools test the policy rules and the five extra cases:

```sh
python3 code/evaluation/cases.py
python3 code/main.py --requests evaluation/cases/requests.csv --out /tmp/extra.csv
python3 code/evaluation/main.py score /tmp/extra.csv evaluation/cases/expected.csv
```

Score the 32 public sample cases against the supplied truth:

```sh
python3 code/main.py --sample --out /tmp/sample.csv
python3 code/evaluation/main.py score /tmp/sample.csv dataset/sample_output.csv
```

## Reports

| File | Contents |
| --- | --- |
| [`evaluation/evaluation_report.md`](./evaluation/evaluation_report.md) | Every accuracy figure, the recall limit, the rejected candidate rules, and the failures found. |
| [`evaluation/usage_report.md`](./evaluation/usage_report.md) | Model names, call counts, tokens, and estimated cost. |
| [`docs/data-quality.md`](./docs/data-quality.md) | The audit of every dataset file, with the handling rule for each problem found. |
| [`docs/adr/0001-deterministic-core-with-narrow-model-use.md`](./docs/adr/0001-deterministic-core-with-narrow-model-use.md) | Why the model reads text and transcribes pages, and why code decides everything else. |

The usage report is generated. Rewrite it with:

```sh
python3 code/evaluation/usage.py
```

Two tools produce the numbers the evaluation report quotes:

```sh
python3 code/evaluation/ceiling.py      # the recall limit the index imposes
python3 code/evaluation/experiments.py  # the candidate rules, each rejected
```

## Rebuilding the caches

Skip this section unless you want to rebuild a cache. The committed caches
are enough to reproduce `output.csv`.

Both rebuilds call a model and cost money. Install the client and set the key
first:

```sh
pip3 install anthropic
export ANTHROPIC_API_KEY=...
```

Then rebuild either cache:

```sh
python3 code/intent.py classify     # code/cache/intent.json
python3 code/vision.py transcribe   # code/cache/vision.json
```

A rebuild appends one line per call to `code/cache/usage.jsonl`. Regenerate
the usage report afterward.

The key is read from the environment or from an uncommitted `.env` file. No
key is committed, and `.env` is ignored by git.

## Packaging the submission

```sh
python3 code/package.py
```

The script writes `code.zip` at the repository root and then checks it. It
includes `README.md`, `code/`, and `evaluation/`. It excludes `dataset/`,
`.env`, every dependency cache, and every nested archive. If any excluded
item reaches the archive, the script fails and reports it.

## Repository layout

```text
code/
  main.py              the entry point
  intent.py            stage 0
  identity.py          stage 1
  evidence.py          stage 2
  status.py            stages 3 and 5
  policy.py            stage 4
  vision.py            image and PDF transcription
  package.py           build and check code.zip
  cache/               committed model output, so a clean run needs no key
  evaluation/          the scorer, the checker, and the measurement tools
  analysis/            one-off data quality scripts
evaluation/            the two reports and the five extra cases
docs/                  the data quality audit and one decision record
code.zip               the submission archive, built by code/package.py
output.csv             the submission file
log.txt                the chat transcript
```
