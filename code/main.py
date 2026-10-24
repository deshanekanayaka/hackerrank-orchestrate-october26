"""Run the deletion audit and write output.csv.

    python3 code/main.py                 # all 518 cases, output.csv at root
    python3 code/main.py --sample        # the 32 sample cases
    python3 code/main.py --out PATH      # write somewhere else
    python3 code/main.py --limit N       # first N cases, for a quick look

Intent labels come from code/cache/intent.json and the transcribed
screenshots and PDF documents come from code/cache/vision.json. Both caches
are committed, so a clean run makes no model call and needs no API key. To
rebuild them, run `python3 code/intent.py classify` and
`python3 code/vision.py transcribe` with ANTHROPIC_API_KEY set.
"""

import csv
import json
import sys
from pathlib import Path

import identity
import evidence
import intent
import status

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "dataset"


def run(requests_path, out_path, limit=None):
    directory = identity.load()
    index = evidence.build(directory)

    with open(requests_path, newline="", encoding="utf-8") as fh:
        requests = list(csv.DictReader(fh))
    requests.sort(key=lambda r: r["case_id"])
    if limit:
        requests = requests[:limit]

    labels = intent.classify(requests)

    rows = []
    for request in requests:
        case_id = request["case_id"]
        if labels.get(case_id) is False:
            # The person asked for something other than deletion.
            rows.append((case_id, "NOT_APPLICABLE", []))
            continue
        user_id = directory.resolve(request["email"], "email")
        if user_id is None:
            rows.append((case_id, "NOT_APPLICABLE", []))
            continue
        case_status, steps = status.plan(index, directory, user_id,
                                         request["audit_at"],
                                         request["requested_at"])
        rows.append((case_id, case_status, steps))

    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["case_id", "deletion_status", "steps_json"])
        for case_id, case_status, steps in rows:
            writer.writerow([case_id, case_status,
                             json.dumps(steps, sort_keys=True,
                                        separators=(",", ":"))])
    tally = {}
    for _, case_status, _ in rows:
        tally[case_status] = tally.get(case_status, 0) + 1
    print(f"wrote {len(rows)} rows to {out_path}")
    print("statuses:", dict(sorted(tally.items())))
    return 0


def main(argv):
    sample = "--sample" in argv
    requests = DATA / ("sample_deletion_requests.csv" if sample
                       else "deletion_requests.csv")
    out = ROOT / "output.csv"
    if "--out" in argv:
        out = Path(argv[argv.index("--out") + 1])
    limit = int(argv[argv.index("--limit") + 1]) if "--limit" in argv else None
    return run(requests, out, limit)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
