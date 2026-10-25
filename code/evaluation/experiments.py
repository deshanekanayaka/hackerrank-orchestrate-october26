"""Candidate rules, each tested against the sample truth and each rejected.

Every rule here looked plausible and would have raised recall if it worked.
Each one runs as a single change to the shipped pipeline, scores the 32
sample cases, and prints the result beside the shipped baseline. Keeping the
experiments in the repository means a later idea can be retested instead of
re-argued.

    python3 code/evaluation/experiments.py

A rule is rejected when it does not raise step f1 and status accuracy
together. The numbers this prints are the ones quoted in
evaluation/evaluation_report.md.
"""

import csv
import io
import json
import re
import sys
import contextlib
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "code"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import identity   # noqa: E402
import evidence   # noqa: E402
import intent     # noqa: E402
import policy     # noqa: E402
import status     # noqa: E402
import main as checker  # noqa: E402

DATA = ROOT / "dataset"
REQUESTS = DATA / "sample_deletion_requests.csv"
TRUTH = DATA / "sample_output.csv"

SURNAME = re.compile(r"\s(\S+)$")


def run_sample(directory, index, tables, since=True):
    """Predict every sample case, the way code/main.py does.

    The intent stage runs here too, from the committed cache, so the row
    labelled the shipped baseline really is the shipped answer. Skipping it
    would score every candidate against a pipeline nobody ships.
    """
    rows = []
    with open(REQUESTS, newline="", encoding="utf-8") as fh:
        requests = sorted(csv.DictReader(fh), key=lambda r: r["case_id"])
    labels = intent.classify(requests)
    for request in requests:
        if labels.get(request["case_id"]) is False:
            rows.append((request["case_id"], "NOT_APPLICABLE", []))
            continue
        user_id = directory.resolve(request["email"], "email")
        if user_id is None:
            rows.append((request["case_id"], "NOT_APPLICABLE", []))
            continue
        case_status, steps = status.plan(
            index, directory, user_id, request["audit_at"],
            request["requested_at"] if since else None, tables)
        rows.append((request["case_id"], case_status, steps))
    return rows


def measure(rows):
    """Score the rows against the sample truth, quietly."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "pred.csv"
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["case_id", "deletion_status", "steps_json"])
            for case_id, case_status, steps in rows:
                writer.writerow([case_id, case_status,
                                 json.dumps(steps, sort_keys=True,
                                            separators=(",", ":"))])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            checker.score(path, TRUTH)
        text = buf.getvalue()
    status_hit = re.search(r"status accuracy:\s+(\d+)/(\d+)", text)
    f1 = re.search(r"f1: ([\d.]+)", text)
    exact = re.search(r"exact row accuracy:\s+(\d+)/", text)
    return {
        "status": f"{status_hit.group(1)}/{status_hit.group(2)}",
        "f1": float(f1.group(1)),
        "exact": int(exact.group(1)),
    }


def loose_owners(directory):
    """Candidate 2: also claim a record whose text carries the surname.

    The evidence prints display names and near-miss email addresses beside
    the real ones, and 143 surnames are shared by more than one real
    subject, so this is the rule the data quality audit warned about. The
    warning is measured here instead of assumed.
    """
    exact = directory.owners_of
    by_surname = {}
    for user_id, row in directory.users.items():
        found = SURNAME.search(row["name"])
        if found:
            by_surname.setdefault(found.group(1).lower(),
                                  set()).add(user_id)
    # Every subject must get a surname, or the rule is measured on only
    # part of the directory and the blast radius it reports is a floor.
    covered = {u for owners in by_surname.values() for u in owners}
    assert covered == set(directory.users), \
        f"{len(directory.users) - len(covered)} subjects have no surname"

    def owners_of(value, field=None):
        hit = exact(value, field)
        if hit:
            return hit
        text = str(value).strip().lower()
        if len(text) > 120:
            return frozenset()
        for word in re.findall(r"[^\W\d_]{2,}", text, re.UNICODE):
            if word in by_surname:
                return frozenset(by_surname[word])
        return frozenset()
    return owners_of


def experiments():
    directory = identity.load()
    index = evidence.build(directory)
    tables = policy.conditions()

    results = [("shipped baseline",
                measure(run_sample(directory, index, tables)),
                "")]

    # Candidate 1: link a resource through an activity row that names one
    # of the subject's identifiers. The index only links through evidence
    # files and the 12 LINK_RESOURCE_IDENTITY rows today.
    requests = {r["case_id"]: r for r in csv.DictReader(
        open(REQUESTS, encoding="utf-8"))}
    truth = {r["case_id"]: r for r in csv.DictReader(
        open(TRUTH, encoding="utf-8"))}
    by_resource = {}
    with open(DATA / "system_activity.csv", newline="",
              encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            by_resource.setdefault(row["resource_id"], []).append(row)
    unreached = winnable = 0
    for case_id, row in truth.items():
        request = requests[case_id]
        user_id = directory.resolve(request["email"], "email")
        reached = set(index.resources_of(user_id, request["audit_at"],
                                         request["requested_at"]))
        wanted = {v.lower() for v in directory.identifiers_of(user_id)}
        for step in json.loads(row["steps_json"]):
            if step["resource_id"] in reached:
                continue
            unreached += 1
            for act in by_resource.get(step["resource_id"], []):
                if act["event_time"] <= request["audit_at"] \
                        and any(w in json.dumps(act).lower()
                                for w in wanted):
                    winnable += 1
                    break
    results.append(("1: link through an activity row naming the subject",
                    None,
                    f"{winnable} of the {unreached} unreached steps become "
                    f"reachable"))

    # Candidate 2: claim a record through a shared surname. The sample
    # score alone cannot reject this, so the extra resources it claims
    # across every evaluation case are counted too.
    strict = {}
    with open(DATA / "deletion_requests.csv", newline="",
              encoding="utf-8") as fh:
        evaluation = sorted(csv.DictReader(fh), key=lambda r: r["case_id"])
    for request in evaluation:
        user_id = directory.resolve(request["email"], "email")
        if user_id is not None:
            strict[request["case_id"]] = set(index.resources_of(
                user_id, request["audit_at"], request["requested_at"]))
    directory.owners_of = loose_owners(directory)
    loose_index = evidence.build(directory)
    extra = cases_touched = 0
    for request in evaluation:
        user_id = directory.resolve(request["email"], "email")
        if user_id is None:
            continue
        if request["case_id"] not in strict:
            continue
        gained = set(loose_index.resources_of(
            user_id, request["audit_at"],
            request["requested_at"])) - strict[request["case_id"]]
        extra += len(gained)
        cases_touched += bool(gained)
    results.append(("2: match evidence on a shared surname",
                    measure(run_sample(directory, loose_index, tables)),
                    f"claims {extra} more resources across "
                    f"{cases_touched} of the 518 evaluation cases, "
                    f"with no sample gain"))
    directory = identity.load()
    index = evidence.build(directory)

    # Candidate 3: a referenced record nobody observed is still present.
    original = status.resource_states

    def present_when_unseen(*args, **kwargs):
        out = original(*args, **kwargs)
        return {resource: (("PRESENT" if obs is None else state), obs, files)
                for resource, (state, obs, files) in out.items()}

    status.resource_states = present_when_unseen
    results.append(("3: treat a referenced record nobody saw as present",
                    measure(run_sample(directory, index, tables)), ""))
    status.resource_states = original

    # Candidate 4: ignore the case window and use every earlier file.
    results.append(("4: drop the case window and read all earlier evidence",
                    measure(run_sample(directory, index, tables,
                                       since=False)), ""))

    # Candidate 5: a log line that states a row count proves the record is
    # there, but it never prints the record body, so it cannot prove the
    # body was redacted. This is the cause of the one remaining sample
    # failure, case_10 support_002.
    BODY = ("message_text", "record_json", "document", "full_name", "email",
            "phone", "subject_reference", "customer_reference")
    original_state = status.state_of

    def strict_redaction(obs, prefix, directory, user_id):
        got = original_state(obs, prefix, directory, user_id)
        if got in ("REDACTED", "ANONYMIZED") \
                and status.stated_state(obs, prefix) == "PRESENT" \
                and not any(any(name in key.lower() for name in BODY)
                            for key, _ in obs.fields):
            return "PRESENT"
        return got

    status.state_of = strict_redaction
    results.append(("5: a row count alone cannot prove redaction",
                    measure(run_sample(directory, index, tables)), ""))
    status.state_of = original_state

    print(f"{'rule':<52} {'status':>7} {'f1':>6} {'exact':>6}")
    for name, got, note in results:
        if got is None:
            print(f"{name:<52} {'-':>7} {'-':>6} {'-':>6}")
        else:
            print(f"{name:<52} {got['status']:>7} {got['f1']:>6.3f} "
                  f"{got['exact']:>6d}")
        if note:
            print(f"{'':<52} {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(experiments())
