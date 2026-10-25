"""How much of the sample truth the evidence index can reach at all.

Recall has a hard limit that no policy rule can lift: a step naming a
resource the index never links to the subject can never be produced. This
measures that limit, so the gap between the limit and the score is the part
that rules can still win.

    python3 code/evaluation/ceiling.py
"""

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "code"))

import identity   # noqa: E402
import evidence   # noqa: E402
import policy     # noqa: E402

DATA = ROOT / "dataset"


def load():
    directory = identity.load()
    index = evidence.build(directory)
    requests = {r["case_id"]: r for r in csv.DictReader(
        open(DATA / "sample_deletion_requests.csv", encoding="utf-8"))}
    truth = {r["case_id"]: r for r in csv.DictReader(
        open(DATA / "sample_output.csv", encoding="utf-8"))}
    return directory, index, requests, truth


def report():
    directory, index, requests, truth = load()
    steps = reached = 0
    windowed = 0
    missing = {}
    for case_id, row in sorted(truth.items()):
        request = requests[case_id]
        user_id = directory.resolve(request["email"], "email")
        wide = set(index.resources_of(user_id, request["audit_at"]))
        narrow = set(index.resources_of(user_id, request["audit_at"],
                                        request["requested_at"]))
        for step in json.loads(row["steps_json"]):
            resource = step["resource_id"]
            steps += 1
            if resource in narrow:
                reached += 1
            elif resource in wide:
                windowed += 1
                missing.setdefault("hidden by the case window", []).append(
                    f"{case_id} {resource}")
            else:
                missing.setdefault("never linked", []).append(
                    f"{case_id} {resource}")

    print(f"sample truth steps:            {steps}")
    print(f"resource reached in the window: {reached} "
          f"= {reached / steps:.3f}")
    print(f"reached only outside it:       {windowed}")
    print(f"never linked to the subject:   "
          f"{len(missing.get('never linked', []))}")
    print(f"recall ceiling in the window:  {reached / steps:.3f}")
    print(f"recall ceiling ignoring it:    "
          f"{(reached + windowed) / steps:.3f}")
    for reason, items in sorted(missing.items()):
        print(f"\n{reason}: {len(items)}")
        for item in items[:12]:
            print(f"  {item}")
        if len(items) > 12:
            print(f"  ... {len(items) - 12} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(report())
