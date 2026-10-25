"""Hand-built cases for the rules the supplied dataset never exercises.

Some policy conditions never flip inside dataset/: every legal hold runs to
2033, and every security audit log sits inside its retention period. A rule
that is never tested is a rule nobody can trust, so each case here takes a
real subject and a real record and moves audit_at across the one cutoff the
evidence states. The prediction comes from the real pipeline. Each case
names, by hand, the one operation its record under test must receive.

Every case also goes through the contract checker, so a case can never pass
on a row the grader would reject. There is no truth file to score against,
because these cases are ours and no golden answer exists for them.

    python3 code/evaluation/cases.py

Cases:

  retained_audit_log    audit_record_003 inside its retention period
  lapsed_audit_log      the same record after the period ends
  active_legal_hold     legal_hold_8017 while the hold is active
  lapsed_legal_hold     the same record after the hold ends
  support_attachment    support_001, an attachment and not a message
"""

import csv
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "code"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import identity          # noqa: E402
import evidence          # noqa: E402
import policy            # noqa: E402
import status            # noqa: E402
import main as checker   # noqa: E402

# name -> (subject, audit_at, what the record under test must yield)
# The cutoffs come from the transcribed documents: audit_record_003 is
# retained until 2027-08-25, and legal_hold_8017 until 2033-12-31.
CASES = [
    ("retained_audit_log", "user_03", "2026-09-06T09:00:00Z",
     "audit_record_003", "VERIFY_RECORD_PRESENT"),
    ("lapsed_audit_log", "user_03", "2027-09-01T00:00:00Z",
     "audit_record_003", "DELETE_RECORD"),
    ("active_legal_hold", "user_259", "2026-07-01T00:00:00Z",
     "legal_hold_8017", "VERIFY_RECORD_PRESENT"),
    ("lapsed_legal_hold", "user_259", "2034-01-02T00:00:00Z",
     "legal_hold_8017", "DELETE_RECORD"),
    ("support_attachment", "user_07", "2026-09-15T00:00:00Z",
     "support_001", "DELETE_RECORD"),
]


def predict():
    """Run the real pipeline over every case and return its steps."""
    directory = identity.load()
    index = evidence.build(directory)
    tables = policy.conditions()
    out = {}
    for name, user_id, audit_at, _, _ in CASES:
        out[name] = status.plan(index, directory, user_id, audit_at,
                                tables=tables)
    return out


def write(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["case_id", "deletion_status", "steps_json"])
        for case_id, case_status, steps in sorted(rows):
            writer.writerow([case_id, case_status,
                             json.dumps(steps, sort_keys=True,
                                        separators=(",", ":"))])


def run():
    """Test each case, then put every case through the contract checker."""
    predictions = predict()
    failures = []
    for name, _, _, resource, want in CASES:
        _, steps = predictions[name]
        got = [s["operation"] for s in steps if s["resource_id"] == resource]
        if want not in got:
            failures.append(f"{name}: {resource} gave {got}, wanted {want}")
        if want == "DELETE_RECORD" and "VERIFY_RECORD_PRESENT" in got:
            failures.append(f"{name}: {resource} is still treated as retained")

    # Every row must also satisfy the contract the grader applies, so a case
    # can never pass here on a row the grader would reject.
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        write(tmp / "cases.csv", [(name, predictions[name][0],
                                   predictions[name][1])
                                  for name, _, _, _, _ in CASES])
        with open(tmp / "requests.csv", "w", newline="",
                  encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["case_id", "email", "requested_at",
                             "reported_status", "reported_at", "audit_at",
                             "request_text"])
            for name, user_id, audit_at, _, _ in sorted(CASES):
                writer.writerow([name, f"{user_id}@example.invalid",
                                 audit_at, "COMPLETE", audit_at, audit_at,
                                 "Please delete my personal data."])
        if checker.check(tmp / "cases.csv", tmp / "requests.csv") != 0:
            failures.append("a predicted row fails the contract checker")

    for name, _, _, resource, want in CASES:
        case_status, steps = predictions[name]
        print(f"{name:20s} {case_status:14s} {len(steps):2d} steps  "
              f"{resource} -> {want}")
    for line in failures:
        print("FAIL", line)
    if failures:
        return 1
    print(f"cases: {len(CASES)}, all pass")
    return 0


if __name__ == "__main__":
    sys.exit(run())
