"""Stage 2: read every evidence file once and write down what it shows.

The manifest does not say which case a file belongs to, so the only way in is
the contents. Each record we see becomes one observation: which file, when,
which system, which resource, which fields, and which subjects it names. A
record reaches a subject only through an exact identifier, never through a
surname or a similar address.

    python3 code/evidence.py selftest
    python3 code/evidence.py show user_32
"""

import csv
import json
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path

import identity
import policy
import vision

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "dataset"

RESOURCE = re.compile(r"\b([a-z_]+_\d+)\b")
BRACKET = re.compile(r"\[([^\]]+)\]")
# A correlation id, not an instance name: node-8 and collector-7 must never
# group unrelated lines together.
TRACE = re.compile(r"^(?:tr|rb)-[\d-]+$")
KV = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:"((?:[^"\\]|\\.)*)"|'
                r"'([^']*)'|([^\s|,\"]+))")
TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
# "linked tombstone_17 (user_17)": the resource, then the key the page shows.
LINKED = re.compile(r"\b([a-z_]+_\d+) \(([^)]+)\)")
NOISE = {"null", "none", "", "-"}


@dataclass(frozen=True)
class Observation:
    file_id: str
    captured_at: str       # when the file was captured, from the manifest
    observed_at: str       # when this record was read, if the file says
    system_id: str
    resource_id: str
    source: str            # table, collection, or log service
    fields: tuple          # (key, value) pairs, strings only
    owners: frozenset      # subjects named by an exact identifier
    raw: str

    def get(self, key, default=None):
        for k, v in self.fields:
            if k == key:
                return v
        return default

    @property
    def values(self):
        return [v for _, v in self.fields]


@dataclass
class Index:
    manifest: dict = field(default_factory=dict)
    observations: list = field(default_factory=list)
    by_user: dict = field(default_factory=dict)
    by_resource: dict = field(default_factory=dict)
    coverage: dict = field(default_factory=dict)  # file_id -> {system: time}
    referenced: dict = field(default_factory=dict)  # user -> {resource: files}

    def resources_of(self, user_id, at=None, since=None):
        """Every resource this subject owns, observed or only referenced.

        A deleted record leaves no row of its own, but another record can
        still name it, so the reference is the only way to reach it.
        """
        out = {}
        for obs in self.for_user(user_id, at, since):
            out.setdefault(obs.resource_id, set()).add(obs.file_id)
        for resource, files in self.referenced.get(user_id, {}).items():
            usable = {f for f in files if self.in_window(
                self.manifest[f]["captured_at"], at, since)}
            if usable:
                out.setdefault(resource, set()).update(usable)
        return out

    @staticmethod
    def in_window(captured, at, since=None):
        """Evidence counts when it is not later than the audit, and not
        older than the request the audit is about."""
        return (at is None or captured <= at) \
            and (since is None or captured >= since)

    def for_user(self, user_id, at=None, since=None):
        """Observations naming this subject, inside the case window."""
        return [o for o in self.by_user.get(user_id, [])
                if self.in_window(o.captured_at, at, since)]

    def files_covering(self, system_id, at=None, since=None):
        """Files that looked at this system, newest first."""
        out = [(self.manifest[f]["captured_at"], f)
               for f, systems in self.coverage.items()
               if system_id in systems
               and self.in_window(self.manifest[f]["captured_at"], at, since)]
        return [f for _, f in sorted(out, reverse=True)]


def scalars(mapping, prefix=""):
    """Flatten one record to string fields, dropping empty values."""
    out = []
    for key, value in mapping.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict):
            out.extend(scalars(value, f"{name}."))
        elif isinstance(value, (list, tuple)):
            for i, item in enumerate(value):
                if isinstance(item, dict):
                    out.extend(scalars(item, f"{name}.{i}."))
                elif item is not None:
                    out.append((f"{name}.{i}", str(item)))
        elif isinstance(value, bool):
            out.append((name, "true" if value else "false"))
        elif value is not None:
            text = str(value)
            if text.strip().lower() in NOISE:
                continue
            out.append((name, text))
            # Some columns and fields hold a whole JSON document.
            if text.startswith("{") and text.endswith("}"):
                try:
                    inner = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if isinstance(inner, dict):
                    out.extend(scalars(inner, f"{name}."))
    return out


def owners_of_record(directory, fields):
    owners = set()
    for _, value in fields:
        if len(value) > 200:
            continue
        owners |= directory.owners_of(value)
    return frozenset(owners)


def parse_sql(path):
    """SQL snapshots load into memory, then every table is read back."""
    con = sqlite3.connect(":memory:")
    try:
        con.executescript(path.read_text(encoding="utf-8"))
        declared, rows = {}, []
        tables = [r[0] for r in con.execute(
            "select name from sqlite_master where type='table'")]
        for table in tables:
            cols = [c[1] for c in con.execute(f'pragma table_info("{table}")')]
            for row in con.execute(f'select * from "{table}"'):
                record = dict(zip(cols, row))
                if table == "snapshot_scope":
                    declared[str(record.get("origin_system"))] = str(
                        record.get("captured_at") or "")
                    continue
                rows.append((table, record))
        return declared, rows
    finally:
        con.close()


def walk_json(node, inherited, out):
    """Every object that carries a resource_id is a record."""
    if isinstance(node, dict):
        if "resource_id" in node:
            out.append((inherited, node))
            return
        for key, value in node.items():
            passed = dict(inherited)
            if key in ("data_store", "collection", "source", "origin"):
                passed["source"] = str(value)
            if policy.prefix_of_system(key):
                passed["source"] = key
            if key in ("captured_at", "observed_at", "exported_at"):
                passed["observed_at"] = str(value)
            if isinstance(value, (dict, list)):
                walk_json(value, passed, out)
    elif isinstance(node, list):
        for item in node:
            walk_json(item, inherited, out)


def parse_json(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    out = []
    walk_json(data, {}, out)
    return out


def parse_lines(path):
    """Logs and text records: one line is one record when it names one.

    A trace writes the identifier on its first line and the resource_id on a
    later one, so every line also reports the trace it belongs to.
    """
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        fields = {}
        # Some logs nest their fields inside an escaped message="..." value,
        # so the line is read again with the escaping removed.
        for text in (line, line.replace('\\"', '"')):
            for key, dq, sq, bare in KV.findall(text):
                value = (dq or sq or bare).replace('\\"', '"')
                if value.strip().lower() not in NOISE:
                    fields.setdefault(key, value)
            if '\\"' not in line:
                break
        parts = [p.strip() for p in line.split("|")]
        if len(parts) > 2:
            for i, part in enumerate(parts):
                if part and "=" not in part:
                    fields.setdefault(f"field_{i}", part)
        # Some logs write one JSON object per line.
        start, end = line.find("{"), line.rfind("}")
        if 0 <= start < end:
            try:
                document = json.loads(line[start:end + 1])
            except json.JSONDecodeError:
                document = None
            if isinstance(document, dict):
                for key, value in scalars(document):
                    fields.setdefault(key, value)
        brackets = BRACKET.findall(line)
        for i, token in enumerate(brackets):
            fields.setdefault(f"bracket_{i}", token)
        trace = (fields.get("trace_id") or fields.get("requestId")
                 or next((t for t in brackets if TRACE.match(t)), "")
                 or next((p for p in parts if TRACE.match(p)), "")
                 or next((t for t in line.split() if TRACE.match(t)), ""))
        stamps = TIMESTAMP.findall(line)
        out.append((fields, stamps[0] if stamps else "", line, trace))
    return out


def resource_in(fields, raw):
    """The resource this record is about, by prefix, field first."""
    for key in ("resource_id", "lookup_key", "target_resource", "field_2",
                "field_3"):
        value = fields.get(key, "")
        if policy.prefix_of(value):
            return value
    for match in RESOURCE.findall(raw):
        if policy.prefix_of(match):
            return match
    return None


def vision_aliases(manifest, data_dir):
    """What a screen calls a resource, against what the resource is called.

    A console shows a display key: a customer key, a file name, a statement
    number. The activity stream states the pair, and its event time sits
    just after the capture time of the file it describes, so each pair
    belongs to one file and never leaks to another.
    """
    screens = sorted((meta["captured_at"], file_id)
                     for file_id, meta in manifest.items()
                     if Path(meta["file_path"]).suffix.lower()
                     in vision.SUFFIXES)
    out = {}
    with open(data_dir / "system_activity.csv", newline="",
              encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row["event_type"] != "LINK_RESOURCE_IDENTITY":
                continue
            found = LINKED.search(row["details"])
            if not found or not policy.prefix_of(found.group(1)):
                continue
            earlier = [pair for pair in screens
                       if pair[0] <= row["event_time"]
                       and pair[0][:10] == row["event_time"][:10]]
            if not earlier:
                continue
            # The same row names the subject the catalog linked, and a
            # console screen often prints no identifier of its own.
            named = tuple(re.findall(r"[\w.+-]+@[\w.-]+|\buser_\d+\b",
                                     row["details"]))
            out.setdefault(max(earlier)[1], {})[found.group(2)] = (
                found.group(1), named)
    return out


def vision_records(file_id, alias, captured, stem, directory):
    """Transcribed records, each under the resource it really names.

    The display key is tried first on the record's own identifier. Only a
    file where that matched nothing falls back to searching the record
    text, so one page's key can never claim another page's rows.
    """
    rows = vision.records_for(file_id)
    read = []
    for record in rows:
        named = str(record.get("resource_id") or "")
        entry = alias.get(named)
        if entry is None and policy.prefix_of(named):
            entry = (named, ())
        read.append((record, entry))
    if alias and not any(entry for _, entry in read):
        read = [(record, next(
            (e for key, e in alias.items()
             if re.search(rf"(?<!\w){re.escape(key)}(?!\w)",
                          json.dumps(record, ensure_ascii=False))), None))
            for record, _ in read]
    out = []
    for record, entry in read:
        if not entry:
            continue
        resource, named = entry
        values = record.get("fields")
        if not isinstance(values, dict):
            continue
        stated = set()
        for value in named:
            stated |= directory.owners_of(value)
        out.append((str(record.get("source") or stem), resource,
                    str(record.get("observed_at") or captured),
                    scalars(values),
                    json.dumps(record, ensure_ascii=False)[:400],
                    frozenset(stated)))
    return out


def build(directory=None, data_dir=DATA):
    directory = directory or identity.load()
    index = Index()
    with open(data_dir / "evidence_files.csv", newline="",
              encoding="utf-8") as fh:
        index.manifest = {r["file_id"]: r for r in csv.DictReader(fh)}
    aliases = vision_aliases(index.manifest, data_dir)

    for file_id, meta in index.manifest.items():
        path = data_dir / meta["file_path"]
        captured = meta["captured_at"]
        systems, records = {}, []

        swept = True
        if path.suffix == ".sql":
            declared, rows = parse_sql(path)
            for name, when in declared.items():
                prefix = policy.prefix_of_system(name)
                if prefix:
                    systems[policy.TABLE[prefix][0]] = when or captured
            for table, record in rows:
                fields = scalars(record)
                records.append((table, record.get("resource_id"),
                                record.get("updated_at") or captured,
                                fields, json.dumps(record, default=str),
                                frozenset()))
        elif path.suffix == ".json":
            for inherited, record in parse_json(path):
                fields = scalars(record)
                records.append((inherited.get("source", path.stem),
                                record.get("resource_id"),
                                record.get("observed_at")
                                or inherited.get("observed_at") or captured,
                                fields, json.dumps(record, default=str),
                                frozenset()))
        elif path.suffix in (".log", ".txt"):
            lines = parse_lines(path)
            trace_owners = {}
            for fields, _, _, trace in lines:
                if trace:
                    trace_owners.setdefault(trace, set()).update(
                        owners_of_record(directory, sorted(fields.items())))
            for fields, stamp, raw, trace in lines:
                resource = resource_in(fields, raw)
                source = (fields.get("service") or fields.get("system")
                          or fields.get("function")
                          or next((b for b in
                                   (fields.get(f"bracket_{i}") for i in
                                    range(4))
                                   if b and policy.prefix_of_system(b)), None)
                          or fields.get("field_1") or fields.get("field_2")
                          or path.stem)
                prefix = policy.prefix_of_system(source)
                if prefix:
                    systems.setdefault(policy.TABLE[prefix][0],
                                       stamp or captured)
                if not resource:
                    continue
                records.append((source, resource, stamp or captured,
                                sorted(fields.items()), raw[:400],
                                frozenset(trace_owners.get(trace, ()))))
        else:
            # Screenshots and PDFs arrive already transcribed, and a cached
            # record reads exactly like a JSON record. A console screen is
            # filtered to one subject, so it proves nothing about anybody
            # else and never counts as a sweep of its system.
            records.extend(vision_records(file_id,
                                          aliases.get(file_id, {}),
                                          captured, path.stem, directory))
            swept = False

        for source, resource, observed, fields, raw, extra in records:
            if not resource or not policy.prefix_of(str(resource)):
                continue
            resource = str(resource)
            system_id = policy.system_of(resource)
            owners = owners_of_record(directory, fields) | extra
            obs = Observation(file_id, captured, str(observed), system_id,
                              resource, str(source), tuple(fields),
                              frozenset(owners), raw)
            index.observations.append(obs)
            index.by_resource.setdefault(resource, []).append(obs)
            for owner in obs.owners:
                index.by_user.setdefault(owner, []).append(obs)
            systems.setdefault(system_id, observed)
        index.coverage[file_id] = systems if swept else {}

    link_through_references(index)
    return index


def link_through_references(index, rounds=3):
    """A resource named inside a subject's record belongs to that subject.

    Records cross-reference each other: a search document carries the
    account it was built from, an export names its object key, a backup
    names its archive. A record whose own identifiers were deleted or
    anonymized can still be reached this way.
    """
    for _ in range(rounds):
        claims, references = {}, {}
        for obs in index.observations:
            if not obs.owners:
                continue
            for _, value in obs.fields:
                for name in RESOURCE.findall(value):
                    if name == obs.resource_id or not policy.prefix_of(name):
                        continue
                    claims.setdefault(name, set()).update(obs.owners)
                    for owner in obs.owners:
                        references.setdefault((name, owner),
                                              set()).add(obs.file_id)
        for (resource, owner), files in references.items():
            index.referenced.setdefault(owner, {}).setdefault(
                resource, set()).update(files)
        grew = False
        for resource, owners in claims.items():
            for obs in index.by_resource.get(resource, []):
                fresh = owners - obs.owners
                if not fresh:
                    continue
                grew = True
                merged = Observation(obs.file_id, obs.captured_at,
                                     obs.observed_at, obs.system_id,
                                     obs.resource_id, obs.source, obs.fields,
                                     frozenset(obs.owners | fresh), obs.raw)
                index.observations[index.observations.index(obs)] = merged
                lst = index.by_resource[resource]
                lst[lst.index(obs)] = merged
                for owner in merged.owners:
                    bucket = index.by_user.setdefault(owner, [])
                    if obs in bucket:
                        bucket[bucket.index(obs)] = merged
                    elif merged not in bucket:
                        bucket.append(merged)
        if not grew:
            break


def selftest():
    directory = identity.load()
    index = build(directory)
    assert len(index.manifest) == 94
    assert index.observations, "no observation was read at all"

    # Case 11 is the worked example: one handover file, six resources.
    case11 = {o.resource_id for o in index.by_user["user_32"]
              if o.file_id == "evidence_03"}
    expected = {"account_4248", "search_052", "support_864", "analytics_2034",
                "audit_record_9394", "data_flow_9522"}
    assert case11 == expected, sorted(case11 ^ expected)

    # A record that names only the stable id must still reach its subject.
    audit = [o for o in index.by_user["user_32"]
             if o.resource_id == "audit_record_9394"]
    assert audit, "audit_record_9394 did not link through user_32"

    # Look-alike identities must own nothing.
    assert not index.by_user.get("user_8741")

    # Absence proofs need to know which files looked at a system.
    files = index.files_covering("account_service", "2026-09-03T11:30:00Z")
    assert "evidence_54" in files, files[:5]

    with open(DATA / "deletion_requests.csv", newline="",
              encoding="utf-8") as fh:
        requests = list(csv.DictReader(fh))
    empty, counts, by_case = [], [], {}
    for row in requests:
        uid = directory.resolve(row["email"], "email")
        by_case[row["case_id"]] = row["email"]
        seen = {o.resource_id for o in index.for_user(uid, row["audit_at"])}
        counts.append(len(seen))
        if not seen:
            empty.append(row["case_id"])
    counts.sort()

    # Every case we cannot link yet must be one the activity stream links by
    # hand, which is the set the image and PDF evidence covers. If a case
    # falls outside that set, a text parser has broken.
    excused = set()
    with open(DATA / "system_activity.csv", newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row["event_type"] == "LINK_RESOURCE_IDENTITY":
                # The activity stream states this link in words, and the
                # state itself sits in a screenshot or a PDF.
                excused |= set(re.findall(r"\buser_\d+\b", row["details"]))
            elif row["event_type"] == "CLASSIFY_REQUEST":
                # Intake recorded a non-deletion request, so no deletion was
                # ever authorized and no evidence is owed.
                for obs in index.by_resource.get(row["resource_id"], []):
                    excused |= obs.owners
    stranded = [c for c in empty
                if directory.resolve(by_case[c], "email") not in excused]
    assert not stranded, f"no evidence path at all for {stranded[:5]}"

    print(f"observations: {len(index.observations)}, "
          f"subjects linked: {len(index.by_user)}, "
          f"resources: {len(index.by_resource)}")
    print(f"resources per case: min {counts[0]}, median "
          f"{counts[len(counts)//2]}, max {counts[-1]}")
    print(f"cases with nothing linked: {len(empty)}"
          + (f", first {empty[:5]}" if empty else ""))
    print("selftest: PASS")
    return 0


def show(user_id):
    index = build()
    for obs in sorted(index.by_user.get(user_id, []),
                      key=lambda o: (o.captured_at, o.resource_id)):
        print(f"{obs.captured_at}  {obs.file_id:>12}  {obs.system_id:>22}  "
              f"{obs.resource_id:>18}  {obs.source}")
    return 0


def main(argv):
    if argv and argv[0] == "selftest":
        return selftest()
    if len(argv) == 2 and argv[0] == "show":
        return show(argv[1])
    raise SystemExit(__doc__)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
