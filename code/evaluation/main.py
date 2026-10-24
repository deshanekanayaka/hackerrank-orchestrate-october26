"""Format checker and scorer for Ghost Data Still Exists.

    python3 code/evaluation/main.py check  PRED.csv [--requests REQ.csv]
    python3 code/evaluation/main.py score  PRED.csv TRUTH.csv
    python3 code/evaluation/main.py selftest

The checker needs no truth file: it tests PRED.csv against the contract in
problem_statement.md. The scorer compares PRED.csv with a truth file.
"""

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "dataset"

STATUSES = {"COMPLETE", "INCOMPLETE", "NOT_APPLICABLE"}
STEP_KEYS = {"step_no", "phase", "system_id", "resource_id", "operation",
             "state", "evidence_id"}
FIELDS = ["phase", "system_id", "resource_id", "operation", "state",
          "evidence_id"]

# Phase order, operation order within a phase, and the one state each
# operation is allowed to report. Taken from the spec tables.
PHASES = ["FINDING", "REMEDIATION", "VERIFICATION"]
OPS = {
    "FINDING": [
        ("REPORT_REMAINING_RECORD", "PRESENT"),
        ("REPORT_EXPOSED_PII", "PRESENT"),
        ("REPORT_ACTIVE_DATA_FLOW", "ACTIVE"),
        ("REPORT_RESTORE_RISK", "ACTIVE"),
    ],
    "REMEDIATION": [
        ("DISABLE_DATA_FLOW", "DISABLED"),
        ("BLOCK_RESTORE", "BLOCKED"),
        ("DELETE_RECORD", "ABSENT"),
        ("REDACT_RECORD", "REDACTED"),
        ("ANONYMIZE_RECORD", "ANONYMIZED"),
    ],
    "VERIFICATION": [
        ("VERIFY_RECORD_ABSENT", "ABSENT"),
        ("VERIFY_RECORD_PRESENT", "PRESENT"),
        ("VERIFY_RECORD_REDACTED", "REDACTED"),
        ("VERIFY_RECORD_ANONYMIZED", "ANONYMIZED"),
        ("VERIFY_DATA_FLOW_DISABLED", "DISABLED"),
        ("VERIFY_RESTORE_BLOCKED", "BLOCKED"),
    ],
}
OP_RANK = {op: i for ops in OPS.values() for i, (op, _) in enumerate(ops)}
PHASE_RANK = {p: i for i, p in enumerate(PHASES)}

CITATION_SOURCES = [
    ("evidence_files.csv", "file_id", "captured_at"),
    ("system_activity.csv", "activity_id", "event_time"),
    ("user_audit_log.csv", "audit_id", "event_time"),
]


def read_rows(path):
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames != ["case_id", "deletion_status", "steps_json"]:
            raise SystemExit(f"FAIL: header is {reader.fieldnames}")
        return list(reader)


def evidence_universe(data_dir=DATA):
    """Every citable id, mapped to the time it was captured.

    Every source must be present. A missing file would turn the citation
    tests into silent no-ops, and a bogus submission would then pass.
    """
    seen = {}
    for name, id_col, time_col in CITATION_SOURCES:
        path = data_dir / name
        if not path.exists():
            raise SystemExit(f"FAIL: {path} is missing, so citations cannot "
                             f"be tested")
        with open(path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                seen[row[id_col]] = row[time_col]
    return seen


def check(pred_path, req_path):
    rows = read_rows(pred_path)
    bad = []

    def fail(case, msg):
        bad.append(f"{case}: {msg}")

    requests = {}
    if req_path and Path(req_path).exists():
        with open(req_path, newline="", encoding="utf-8") as fh:
            requests = {r["case_id"]: r for r in csv.DictReader(fh)}
    cited = evidence_universe()

    ids = [r["case_id"] for r in rows]
    if ids != sorted(ids):
        bad.append("rows are not sorted by case_id")
    if len(set(ids)) != len(ids):
        bad.append("duplicate case_id")
    if requests and set(ids) != set(requests):
        missing = sorted(set(requests) - set(ids))[:3]
        extra = sorted(set(ids) - set(requests))[:3]
        bad.append(f"case set differs: missing {missing} extra {extra}")

    for row in rows:
        case = row["case_id"]
        status = row["deletion_status"]
        if status not in STATUSES:
            fail(case, f"status {status!r}")
            continue
        try:
            steps = json.loads(row["steps_json"])
        except json.JSONDecodeError as err:
            fail(case, f"steps_json is not JSON: {err}")
            continue
        if not isinstance(steps, list):
            fail(case, "steps_json is not an array")
            continue
        if status == "NOT_APPLICABLE" and steps:
            fail(case, "NOT_APPLICABLE must carry an empty array")
        if status != "NOT_APPLICABLE" and not steps:
            fail(case, f"{status} must carry at least one step")

        audit_at = requests.get(case, {}).get("audit_at")
        phase_order, within_phase = [], []
        remediated, proven, phases_seen = set(), set(), set()
        for i, step in enumerate(steps, 1):
            if not isinstance(step, dict):
                fail(case, f"step {i} is not an object")
                continue
            if set(step) != STEP_KEYS:
                fail(case, f"step {i} keys are {sorted(step)}")
                continue
            if step["step_no"] != i:
                fail(case, f"step {i} is numbered {step['step_no']}")
            phase, op = step["phase"], step["operation"]
            if phase not in PHASE_RANK:
                fail(case, f"step {i} phase {phase!r}")
                continue
            if op not in OP_RANK or (op, step["state"]) not in OPS[phase]:
                fail(case, f"step {i} has {phase}/{op}/{step['state']}")
                continue
            if not step["system_id"] or not step["resource_id"]:
                fail(case, f"step {i} is missing a system or resource")
            phases_seen.add(phase)
            phase_order.append(PHASE_RANK[phase])
            within_phase.append((PHASE_RANK[phase], OP_RANK[op],
                                 step["system_id"], step["resource_id"]))
            where = (step["system_id"], step["resource_id"])
            if phase == "REMEDIATION":
                remediated.add(where)
            if phase == "VERIFICATION":
                proven.add(where)

            ev = step["evidence_id"]
            wants_proof = status == "COMPLETE" or phase == "FINDING"
            if wants_proof:
                if not ev:
                    fail(case, f"step {i} must cite evidence")
                elif ev not in cited:
                    fail(case, f"step {i} cites unknown {ev}")
                elif audit_at and cited[ev] > audit_at:
                    fail(case, f"step {i} cites {ev} captured after audit_at")
            elif ev:
                fail(case, f"step {i} is future work and must cite nothing")

            if status == "COMPLETE" and phase != "VERIFICATION":
                fail(case, f"step {i} is {phase} in a COMPLETE case")

        if phase_order != sorted(phase_order):
            fail(case, "phases are out of order")
        elif within_phase != sorted(within_phase):
            fail(case, "steps are out of the documented order inside a phase")
        if status == "INCOMPLETE":
            if "FINDING" not in phases_seen:
                fail(case, "INCOMPLETE must report at least one finding")
            for where in sorted(remediated - proven):
                fail(case, f"{where[1]} is remediated but never proven")

    tally = {}
    for row in rows:
        tally[row["deletion_status"]] = tally.get(row["deletion_status"], 0) + 1
    for line in bad[:40]:
        print("  " + line)
    if len(bad) > 40:
        print(f"  ... and {len(bad) - 40} more")
    print(f"{'PASS' if not bad else 'FAIL'}: {len(rows)} rows, "
          f"{len(bad)} violations")
    print("statuses:", dict(sorted(tally.items())))
    return 0 if not bad else 1


def key_of(step):
    return (step["phase"], step["system_id"], step["resource_id"],
            step["operation"])


def score(pred_path, truth_path):
    pred = {r["case_id"]: r for r in read_rows(pred_path)}
    truth = {r["case_id"]: r for r in read_rows(truth_path)}
    total = len(truth) or 1
    missing = sorted(set(truth) - set(pred))
    extra = sorted(set(pred) - set(truth))
    if missing:
        print(f"note: {len(missing)} truth cases absent from the prediction "
              f"and counted wrong, first {missing[:3]}")
    if extra:
        print(f"note: {len(extra)} predicted cases are not in the truth file, "
              f"first {extra[:3]}")

    ok_status = ok_row = ok_seq = 0
    tp = fp = fn = 0
    hits = {f: 0 for f in FIELDS}
    paired = 0
    worst = []

    for case in sorted(truth):
        t = truth[case]
        p = pred.get(case)
        if p is None:
            fn += len(json.loads(t["steps_json"]))
            continue
        if p["deletion_status"] == t["deletion_status"]:
            ok_status += 1
        else:
            worst.append(f"{case}: status {p['deletion_status']} "
                         f"!= {t['deletion_status']}")
        try:
            ps = json.loads(p["steps_json"])
            ts = json.loads(t["steps_json"])
        except json.JSONDecodeError as err:
            worst.append(f"{case}: steps_json is not JSON: {err}")
            fn += len(json.loads(t["steps_json"]))
            continue
        if ps == ts and p["deletion_status"] == t["deletion_status"]:
            ok_row += 1
        if [key_of(s) for s in ps] == [key_of(s) for s in ts]:
            ok_seq += 1

        # Step level: match on identity, so a step in the wrong place still
        # counts as found.
        pool = {}
        for step in ts:
            pool.setdefault(key_of(step), []).append(step)
        for step in ps:
            match = pool.get(key_of(step))
            if match:
                match.pop(0)
                tp += 1
            else:
                fp += 1
        fn += sum(len(v) for v in pool.values())

        # Field level: align by position, so every field can differ. Pairing
        # on identity would make four of the six fields equal by
        # construction and report a meaningless 1.000.
        for mine, theirs in zip(ps, ts):
            paired += 1
            for f in FIELDS:
                hits[f] += mine.get(f) == theirs[f]

    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    print(f"cases in truth:      {len(truth)}")
    print(f"status accuracy:     {ok_status}/{len(truth)} = {ok_status/total:.3f}")
    print(f"exact row accuracy:  {ok_row}/{len(truth)} = {ok_row/total:.3f}")
    print(f"sequence accuracy:   {ok_seq}/{len(truth)} = {ok_seq/total:.3f}")
    print(f"step precision:      {prec:.3f}  recall: {rec:.3f}  f1: {f1:.3f}  "
          f"(tp={tp} fp={fp} fn={fn})")
    print(f"field accuracy over {paired} position-aligned steps:")
    print("  " + "  ".join(
        f"{f}={hits[f]/(paired or 1):.3f}" for f in FIELDS))
    for line in worst[:10]:
        print("  " + line)
    return 0 if ok_row == len(truth) and not extra else 1


def selftest():
    """Both tools must react to a file that is wrong in each way."""
    import tempfile

    good = DATA / "sample_output.csv"
    req = DATA / "sample_deletion_requests.csv"
    rows = read_rows(good)
    assert check(good, req) == 0, "the sample file must pass the checker"
    assert score(good, good) == 0, "a file must score perfectly against itself"

    def edit(fn):
        out = [dict(r) for r in rows]
        fn(out)
        return out

    def steps_of(row):
        return json.loads(row["steps_json"])

    def put(row, steps):
        for i, s in enumerate(steps, 1):
            if isinstance(s, dict):
                s["step_no"] = i
        row["steps_json"] = json.dumps(steps, sort_keys=True,
                                       separators=(",", ":"))

    def flip_status(out):
        first = out[0]
        first["deletion_status"] = ("INCOMPLETE" if
                                    first["deletion_status"] == "COMPLETE"
                                    else "COMPLETE")

    def reverse_steps(out):
        for r in out:
            put(r, list(reversed(steps_of(r))))

    def drop_evidence(out):
        for r in out:
            steps = steps_of(r)
            for s in steps:
                s["evidence_id"] = ""
            put(r, steps)

    def scalar_step(out):
        out[0]["steps_json"] = "[1,2]"

    def drop_verification(out):
        for r in out:
            if r["deletion_status"] != "INCOMPLETE":
                continue
            put(r, [s for s in steps_of(r) if s["phase"] != "VERIFICATION"])

    def drop_findings(out):
        for r in out:
            if r["deletion_status"] != "INCOMPLETE":
                continue
            put(r, [s for s in steps_of(r) if s["phase"] != "FINDING"])

    def mangle_resources(out):
        for r in out:
            steps = steps_of(r)
            for s in steps:
                s["resource_id"] = s["resource_id"] + "_x"
            put(r, steps)

    def drop_cases(out):
        del out[1:]

    with tempfile.TemporaryDirectory() as tmp:
        def write(name, fn):
            path = Path(tmp) / name
            with open(path, "w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, ["case_id", "deletion_status",
                                        "steps_json"])
                w.writeheader()
                w.writerows(edit(fn))
            return path

        assert score(write("a.csv", flip_status), good) == 1, \
            "a wrong status must not score perfectly"
        assert check(write("b.csv", reverse_steps), req) == 1, \
            "reversed steps must fail the order test"
        assert check(write("c.csv", drop_evidence), req) == 1, \
            "a missing citation must fail"
        assert check(write("d.csv", scalar_step), req) == 1, \
            "a step that is not an object must fail, not crash"
        assert check(write("e.csv", drop_verification), req) == 1, \
            "a remediated record with no proof must fail"
        assert check(write("f.csv", drop_findings), req) == 1, \
            "an INCOMPLETE case with no finding must fail"

        # Field accuracy has to move when a field is wrong.
        mangled = write("g.csv", mangle_resources)
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            score(mangled, good)
        text = buf.getvalue()
        assert "resource_id=0.000" in text, text
        assert "phase=1.000" in text, text

        # A short file must be counted against the full truth set.
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            score(write("h.csv", drop_cases), good)
        text = buf.getvalue()
        assert "status accuracy:     1/32" in text, text
    print("selftest: PASS")
    return 0


def main(argv):
    if not argv or argv[0] not in {"check", "score", "selftest"}:
        raise SystemExit(__doc__)
    cmd, rest = argv[0], argv[1:]
    if cmd == "selftest":
        return selftest()
    if cmd == "score":
        if len(rest) != 2:
            raise SystemExit("score needs PRED.csv and TRUTH.csv")
        return score(rest[0], rest[1])
    req = DATA / "deletion_requests.csv"
    if "--requests" in rest:
        at = rest.index("--requests")
        if at + 1 >= len(rest):
            raise SystemExit("--requests needs a file path")
        req = rest[at + 1]
        rest = rest[:at] + rest[at + 2:]
    if len(rest) != 1:
        raise SystemExit("check needs exactly one PRED.csv")
    return check(rest[0], req)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
