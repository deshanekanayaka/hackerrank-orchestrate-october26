"""Stage 1: turn the screenshots and PDF documents into readable records.

Eleven screenshots and four PDF documents hold evidence that no parser can
reach. A model reads each file once, writes down every label, value, and
table row it can see, and the answer is cached per file. The evidence index
then treats the cache like any other file. The model is asked for the
contents only. It never decides a state, a policy, or a verdict.

    python3 code/vision.py transcribe          # cached, no call on a rerun
    python3 code/vision.py transcribe --force
    python3 code/vision.py selftest            # cache only, no model call
    python3 code/vision.py show evidence_04
"""

import base64
import csv
import hashlib
import json
import sys
from pathlib import Path

import intent

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "dataset"
CACHE = Path(__file__).resolve().parent / "cache" / "vision.json"

MODEL = "claude-sonnet-5"
SUFFIXES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".pdf": "application/pdf"}

SYSTEM = """You transcribe one business document or one application screen. \
You write down what the page shows. You never judge it.

The page holds records. A record is one thing the page names with an \
identifier such as account_5762, support_864, data_flow_1121, backup_207, \
analytics_2034, audit_record_9394, tombstone_17, search_052, export_441, \
object_118, marketing_900, cache_12, or legal_hold_3. One table row is one \
record. One detail panel is one record. A page can show the same identifier \
twice, once in a row and once in a panel: write both.

For every record, copy every label and value you can read for it, exactly as \
printed. Keep email addresses, phone numbers, hashes, user ids, ticket ids, \
order ids, dates, times, counts, and status words character for character. \
Do not correct, translate, round, or summarize anything. Do not add a field \
the page does not show.

Identifiers belong to a record only when the page shows them together. When \
the page is about one subject and names that subject in its header, that \
subject's identifiers belong to every record on the page. When a table lists \
a different subject on each row, the identifiers of a row belong to that row \
alone and to no other row.

Never write a conclusion. No verdict, no compliance opinion, no guess about \
deletion. Only the contents.

Return JSON only, no prose:
{"records": [
  {"resource_id": "account_5762",
   "source": "<table name, panel name, or section heading>",
   "observed_at": "<ISO-8601 time the page gives for this record, or \
empty>",
   "fields": {"<label as printed>": "<value as printed>"}}
]}"""


def fingerprint(data):
    return hashlib.sha256(data).hexdigest()[:16]


def read_cache():
    return json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() \
        else {}


def write_cache(cache):
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, indent=1, sort_keys=True,
                                ensure_ascii=False), encoding="utf-8")


def binary_files(data_dir=DATA):
    """The manifest rows no text parser can read, in manifest order."""
    with open(data_dir / "evidence_files.csv", newline="",
              encoding="utf-8") as fh:
        return [row for row in csv.DictReader(fh)
                if Path(row["file_path"]).suffix.lower() in SUFFIXES]


def block(path):
    media = SUFFIXES[path.suffix.lower()]
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    kind = "document" if media == "application/pdf" else "image"
    return {"type": kind,
            "source": {"type": "base64", "media_type": media, "data": data}}


def ask(client, path):
    response = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        system=SYSTEM,
        messages=[{"role": "user", "content": [
            block(path),
            {"type": "text", "text": "Transcribe this page."},
        ]}],
    )
    intent.record_usage(response, stage="vision", model=MODEL)
    # The model may think first, so the answer is the last text block.
    text = [b.text for b in response.content
            if getattr(b, "text", None)][-1].strip()
    if text.startswith("```"):
        text = text.split("```")[1].removeprefix("json").strip()
    records = json.loads(text).get("records", [])
    return [r for r in records if r.get("resource_id")]


def transcribe(force=False, data_dir=DATA):
    cache = read_cache()
    rows = binary_files(data_dir)
    todo = []
    for row in rows:
        mark = fingerprint((data_dir / row["file_path"]).read_bytes())
        if force or cache.get(row["file_id"], {}).get("fingerprint") != mark:
            todo.append((row, mark))
    if todo:
        import anthropic
        key = intent.load_env()
        if not key:
            raise SystemExit("FAIL: set ANTHROPIC_API_KEY in the environment "
                             "or in .env")
        client = anthropic.Anthropic(api_key=key)
        for done, (row, mark) in enumerate(todo, start=1):
            path = data_dir / row["file_path"]
            cache[row["file_id"]] = {"fingerprint": mark,
                                     "records": ask(client, path)}
            write_cache(cache)
            print(f"transcribed {done}/{len(todo)} {row['file_id']} "
                  f"({len(cache[row['file_id']]['records'])} records)")
    return cache


_loaded = None


def records_for(file_id):
    """Cached records for one file. An absent cache yields nothing."""
    global _loaded
    if _loaded is None:
        _loaded = read_cache()
    return _loaded.get(file_id, {}).get("records", [])


def selftest():
    cache = read_cache()
    rows = binary_files()
    assert cache, "no transcription yet: run `python3 code/vision.py " \
                  "transcribe` first"
    missing = [r["file_id"] for r in rows if r["file_id"] not in cache]
    assert not missing, f"not transcribed: {missing}"

    stale = [r["file_id"] for r in rows
             if cache[r["file_id"]]["fingerprint"]
             != fingerprint((DATA / r["file_path"]).read_bytes())]
    assert not stale, f"file changed since transcription: {stale}"

    # A page prints its own display key, so a transcribed identifier is
    # only useful once the index resolves it to a resource.
    import evidence
    aliases = evidence.vision_aliases(
        {r["file_id"]: r for r in csv.DictReader(
            open(DATA / "evidence_files.csv", newline="", encoding="utf-8"))},
        DATA)
    total, reached = 0, []
    for row in rows:
        file_id = row["file_id"]
        total += len(cache[file_id]["records"])
        if evidence.vision_records(file_id, aliases.get(file_id, {}),
                                   row["captured_at"], file_id,
                                   evidence.identity.load()):
            reached.append(file_id)
    assert total, "every file transcribed to nothing"
    assert len(reached) >= 12, f"only {len(reached)} files resolved: {reached}"

    # The console screenshot of case 11's account is the worked example.
    account = [r for r in cache["evidence_04"]["records"]
               if r["resource_id"] == "account_5762"]
    assert account, "evidence_04 lost account_5762"
    values = " ".join(str(v) for r in account for v in r["fields"].values())
    assert "haruka.s1838@zoho.com" in values, values[:200]

    print(f"files: {len(cache)}, records: {total}, "
          f"files resolved to a resource: {len(reached)}")
    print("selftest: PASS")
    return 0


def show(file_id):
    for record in records_for(file_id):
        print(json.dumps(record, ensure_ascii=False, sort_keys=True))
    return 0


def main(argv):
    if argv and argv[0] == "selftest":
        return selftest()
    if argv and argv[0] == "transcribe":
        cache = transcribe(force="--force" in argv)
        print(f"{len(cache)} files cached, "
              f"{sum(len(e['records']) for e in cache.values())} records")
        return 0
    if len(argv) == 2 and argv[0] == "show":
        return show(argv[1])
    raise SystemExit(__doc__)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
