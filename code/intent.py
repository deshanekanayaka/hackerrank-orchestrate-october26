"""Stage 0: does the request actually authorize deletion?

A request for access, export, correction, or a marketing opt-out is not a
deletion request, and its answer is NOT_APPLICABLE with an empty step list.
The texts arrive in several languages, and some hide a refusal behind
deletion words, so a keyword rule is not safe. A model reads each text, the
answer is cached per case, and every call is recorded for the usage report.

    python3 code/intent.py classify           # all 518 cases, cached
    python3 code/intent.py classify --sample
    python3 code/intent.py selftest           # cache only, no model call
"""

import csv
import hashlib
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "dataset"
CACHE = Path(__file__).resolve().parent / "cache" / "intent.json"
USAGE = Path(__file__).resolve().parent / "cache" / "usage.jsonl"

MODEL = "claude-haiku-4-5-20251001"
BATCH = 25

SYSTEM = """You read privacy requests and decide one thing: is this a \
deletion matter?

It is a deletion matter when the message asks to erase, delete, close, \
remove, or wipe the account or the personal data, and also when the message \
refers to a deletion the person already requested, for example asking you to \
confirm, verify, audit, or re-check that the account is gone.

It is NOT a deletion matter when the person asks for something else instead \
and no deletion is asked for or referred to: access to their data, a copy or \
export, a correction or update, an unsubscribe or marketing opt-out, or a \
question about the service.

It is NOT a deletion matter when the message names deletion only to refuse \
it, for example "I am not asking for deletion", "please keep the account \
active", or "correct it without removing any records". An explicit clause to \
keep the account wins over any deletion word in the same message.

Asking to be told whether the account or the data is gone is a deletion \
matter, not an access request. An access request asks for the content of the \
data. A deletion matter asks about its removal.

Examples that ARE deletion matters:
- "Please erase my account and all personal data."
- "I deleted my account. Could you confirm the profile is gone?"
- "The privacy page says my request failed. Tell me whether the account has \
been removed."
- "Audit the deletion as it stood when my request was reviewed."

Examples that are NOT deletion matters:
- "My surname is misspelled. Correct it without removing any records."
- "Send me a copy of my data in a portable format. Keep the account as it is."
- "Unsubscribe me from marketing email. The account stays open."

Rules:
- Read the message in its own language. Never translate first.
- Judge only the message, never the other fields of the case.
- When the message is unclear, answer true. Only a clear request for another \
action, with no deletion asked for or referred to, is false.

Return JSON only, an array with one object per case, no prose:
[{"case_id": "...", "authorizes_deletion": true, "kind": "deletion"}]
kind is one of: deletion, verification, access, export, correction, \
opt_out, other."""


def load_env():
    """Read .env if present. The value is never printed or logged."""
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())
    for name in ("ANTHROPIC_API_KEY", "ANTHROPHIC_API_KEY"):
        if os.environ.get(name):
            return os.environ[name]
    return None


def fingerprint(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def read_cache():
    return json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() \
        else {}


def write_cache(cache):
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, indent=1, sort_keys=True,
                                ensure_ascii=False), encoding="utf-8")


def record_usage(response, calls=1):
    USAGE.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "stage": "intent",
        "model": MODEL,
        "calls": calls,
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    }
    with open(USAGE, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def ask(client, batch):
    payload = [{"case_id": c["case_id"], "request_text": c["request_text"]}
               for c in batch]
    response = client.messages.create(
        model=MODEL,
        max_tokens=4000,
        temperature=0,
        system=SYSTEM,
        messages=[{"role": "user", "content": json.dumps(
            payload, ensure_ascii=False)}],
    )
    record_usage(response)
    text = response.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("```")[1].removeprefix("json").strip()
    answers = json.loads(text)
    return {a["case_id"]: a for a in answers}


def classify(requests, force=False):
    cache = read_cache()
    todo = [r for r in requests
            if force or cache.get(r["case_id"], {}).get("fingerprint")
            != fingerprint(r["request_text"])]
    if todo:
        import anthropic
        key = load_env()
        if not key:
            raise SystemExit("FAIL: set ANTHROPIC_API_KEY in the environment "
                             "or in .env")
        client = anthropic.Anthropic(api_key=key)
        for start in range(0, len(todo), BATCH):
            batch = todo[start:start + BATCH]
            try:
                answers = ask(client, batch)
            except json.JSONDecodeError:
                answers = {}
                for one in batch:          # retry the batch case by case
                    answers.update(ask(client, [one]))
            for request in batch:
                answer = answers.get(request["case_id"])
                if answer is None:
                    answer = ask(client, [request]).get(request["case_id"])
                cache[request["case_id"]] = {
                    "authorizes_deletion": bool(
                        answer["authorizes_deletion"]),
                    "kind": answer.get("kind", "other"),
                    "fingerprint": fingerprint(request["request_text"]),
                }
            write_cache(cache)
            print(f"classified {min(start + BATCH, len(todo))}/{len(todo)}")
    return {r["case_id"]: cache[r["case_id"]]["authorizes_deletion"]
            for r in requests if r["case_id"] in cache}


def read_requests(sample=False):
    name = "sample_deletion_requests.csv" if sample \
        else "deletion_requests.csv"
    with open(DATA / name, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def selftest():
    """Judge the cache against the one independent signal in the data."""
    cache = read_cache()
    requests = read_requests()
    assert cache, "no cached labels yet: run classify first"
    missing = [r["case_id"] for r in requests
               if r["case_id"] not in cache]
    assert not missing, f"{len(missing)} cases unlabeled, first {missing[:5]}"

    # Intake recorded ten requests as non-deletion. Our labels must agree.
    import identity
    import evidence
    directory = identity.load()
    index = evidence.build(directory)
    stated = set()
    with open(DATA / "system_activity.csv", newline="",
              encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row["event_type"] != "CLASSIFY_REQUEST":
                continue
            for obs in index.by_resource.get(row["resource_id"], []):
                stated |= obs.owners
    by_user = {directory.resolve(r["email"], "email"): r["case_id"]
               for r in requests}
    expected = {by_user[u] for u in stated if u in by_user}
    said_no = {c for c, v in cache.items() if not v["authorizes_deletion"]}
    assert expected <= said_no, f"called these deletion: {expected - said_no}"
    print(f"labels: {len(cache)}, non-deletion: {len(said_no)}, "
          f"intake agreed on all {len(expected)} it recorded")
    print("selftest: PASS")
    return 0


def main(argv):
    if argv and argv[0] == "selftest":
        return selftest()
    if argv and argv[0] == "classify":
        requests = read_requests("--sample" in argv)
        labels = classify(requests, force="--force" in argv)
        no = sorted(c for c, v in labels.items() if not v)
        print(f"{len(labels)} labels, {len(no)} do not authorize deletion: "
              f"{no}")
        return 0
    raise SystemExit(__doc__)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
