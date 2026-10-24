"""Data quality audit of every CSV in dataset/. Read-only. Prints a text report."""
import csv, re, sys, unicodedata, collections, os, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
DS = ROOT / "dataset"
ID_COLS = {"case_id", "user_id", "activity_id", "audit_id", "file_id", "rule_id"}
ZW = {"​", "‌", "‍", "﻿", "⁠", "­", "‪", "‬", " ", " ", "\xa0"}
MOJIBAKE = ("Ã", "â€", "Â", "ï»¿", "Ð", "å¤")
TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")

def load(name):
    p = DS / name
    raw = p.read_bytes()
    try:
        raw.decode("utf-8")
        enc_err = None
    except UnicodeDecodeError as e:
        enc_err = str(e)
    rows = list(csv.DictReader(raw.decode("utf-8", "replace").splitlines()))
    return rows, enc_err, raw

def out(*a):
    print(*a)

def section(t):
    out("\n### " + t)

CSVS = ["deletion_requests.csv", "sample_deletion_requests.csv", "sample_output.csv",
        "user_identities.csv", "user_audit_log.csv", "system_activity.csv",
        "deletion_rules.csv", "evidence_files.csv", "output.csv"]

store = {}
out("# CSV audit")
for name in CSVS:
    rows, enc_err, raw = load(name)
    store[name] = rows
    section(name)
    out(f"rows={len(rows)} cols={list(rows[0].keys()) if rows else []}")
    out(f"utf8_decode_error={enc_err}")
    bom = raw.startswith(b"\xef\xbb\xbf")
    crlf = raw.count(b"\r\n")
    out(f"bom={bom} crlf_lines={crlf}")
    # duplicate whole rows
    sig = [tuple(sorted(r.items())) for r in rows]
    dup_rows = [k for k, v in collections.Counter(sig).items() if v > 1]
    out(f"duplicate_full_rows={len(dup_rows)}")
    # duplicate ids
    for c in (rows[0].keys() if rows else []):
        if c in ID_COLS:
            vals = [r[c] for r in rows]
            d = {k: v for k, v in collections.Counter(vals).items() if v > 1}
            out(f"duplicate_{c}={len(d)} {list(d.items())[:5]}")
    # missing / empty
    miss = {}
    for c in (rows[0].keys() if rows else []):
        n = sum(1 for r in rows if r[c] is None or str(r[c]).strip() == "")
        if n:
            miss[c] = n
    out(f"empty_per_column={miss or 'none'}")
    # encoding hygiene per cell
    zw = collections.Counter(); moj = collections.Counter(); ws = collections.Counter(); ctrl = collections.Counter()
    for i, r in enumerate(rows):
        for c, v in r.items():
            if v is None: continue
            if any(z in v for z in ZW): zw[c] += 1
            if any(m in v for m in MOJIBAKE): moj[c] += 1
            if v != v.strip(): ws[c] += 1
            if any(unicodedata.category(ch) == "Cc" for ch in v): ctrl[c] += 1
    out(f"zero_width_or_nbsp={dict(zw) or 'none'}")
    out(f"mojibake_markers={dict(moj) or 'none'}")
    out(f"stray_whitespace={dict(ws) or 'none'}")
    out(f"control_chars={dict(ctrl) or 'none'}")
    # timestamps
    for c in (rows[0].keys() if rows else []):
        if any(k in c for k in ("_at", "time")):
            bad = [r[c] for r in rows if r[c] and not TS.match(r[c])]
            out(f"timestamp[{c}]: non_iso_utc={len(bad)} examples={bad[:3]}")
    # emails
    for c in (rows[0].keys() if rows else []):
        if c == "email":
            vals = [r[c] for r in rows]
            bad = [v for v in vals if not EMAIL.match(v or "")]
            nonascii = [v for v in vals if any(ord(ch) > 127 for ch in v or "")]
            upper = [v for v in vals if v != (v or "").lower()]
            out(f"email: invalid={len(bad)} {bad[:3]} non_ascii={len(nonascii)} {nonascii[:3]} not_lowercase={len(upper)} {upper[:3]}")

section("user_identities.csv formats")
ui = store["user_identities.csv"]
ph = collections.Counter()
for r in ui:
    p = r["phone"]
    ph["has_plus" if p.startswith("+") else "no_plus"] += 1
    ph["has_space"] = ph["has_space"] + (1 if " " in p else 0)
    ph["has_dash"] = ph["has_dash"] + (1 if "-" in p else 0)
out(f"phone_shapes={dict(ph)}")
out(f"phone_cc_prefixes={collections.Counter(r['phone'].split(' ')[0] for r in ui).most_common(12)}")
out(f"phone_digit_len={sorted(collections.Counter(len(re.sub(r'[^0-9]','',r['phone'])) for r in ui).items())}")
hl = collections.Counter(len(r["email_hash"]) for r in ui)
out(f"email_hash_lengths={dict(hl)}")
out(f"email_hash_not_lower_hex64={sum(1 for r in ui if not HEX64.match(r['email_hash']))}")
dupe_hash = {k: v for k, v in collections.Counter(r["email_hash"] for r in ui).items() if v > 1}
out(f"duplicate_email_hash={len(dupe_hash)}")
dupe_mail = {k: v for k, v in collections.Counter(r["email"].lower() for r in ui).items() if v > 1}
out(f"duplicate_current_email={len(dupe_mail)} {list(dupe_mail)[:3]}")

section("referential integrity")
cur = {r["email"].lower(): r["user_id"] for r in ui}
uids = {r["user_id"] for r in ui}
al = store["user_audit_log.csv"]
hist = collections.defaultdict(set)
for r in al:
    for v in (r["old_value"], r["new_value"]):
        if v and "@" in v:
            hist[v.lower()].add(r["user_id"])
out(f"audit_log_user_ids_missing_from_identities={sorted({r['user_id'] for r in al} - uids)}")
out(f"audit_log_field_names={dict(collections.Counter(r['field_name'] for r in al))}")
for reqname in ("deletion_requests.csv", "sample_deletion_requests.csv"):
    req = store[reqname]
    unmatched = [r["case_id"] for r in req if r["email"].lower() not in cur and r["email"].lower() not in hist]
    via_hist = [r["case_id"] for r in req if r["email"].lower() not in cur and r["email"].lower() in hist]
    out(f"{reqname}: emails_unresolvable={len(unmatched)} {unmatched[:5]}")
    out(f"{reqname}: resolved_only_via_audit_log={len(via_hist)} {via_hist[:5]}")
    ec = collections.Counter(r["email"].lower() for r in req)
    multi = {k: v for k, v in ec.items() if v > 1}
    out(f"{reqname}: emails_used_by_multiple_cases={len(multi)} max_cases_per_email={max(ec.values())}")
    uu = {cur.get(r['email'].lower()) or (sorted(hist[r['email'].lower()])[0] if r['email'].lower() in hist else None) for r in req}
    out(f"{reqname}: distinct_users_covered={len(uu - {None})} of {len(uids)}")
    out(f"{reqname}: reported_status={dict(collections.Counter(r['reported_status'] for r in req))}")
    bad_t = [r["case_id"] for r in req if not (r["requested_at"] <= r["reported_at"] <= r["audit_at"])]
    out(f"{reqname}: timeline_out_of_order(requested<=reported<=audit)={len(bad_t)} {bad_t[:5]}")

ev = store["evidence_files.csv"]
missing = [r["file_id"] for r in ev if not (DS / r["file_path"]).exists()]
on_disk = {str(p.relative_to(DS)) for p in (DS / "evidence").rglob("*") if p.is_file()}
listed = {r["file_path"] for r in ev}
out(f"manifest_rows={len(ev)} missing_on_disk={len(missing)} {missing[:5]}")
out(f"files_on_disk_not_in_manifest={len(on_disk - listed)} {sorted(on_disk - listed)[:5]}")
out(f"manifest_duplicate_paths={len(listed) != len(ev)}")
out(f"manifest_origins={len(set(r['origin'] for r in ev))} distinct")

act = store["system_activity.csv"]
out(f"activity event_type={dict(collections.Counter(r['event_type'] for r in act))}")
out(f"activity reported_result={dict(collections.Counter(r['reported_result'] for r in act))}")
out(f"activity source_system={dict(collections.Counter(r['source_system'] for r in act))}")
out(f"activity target_system={dict(collections.Counter(r['target_system'] for r in act))}")
out(f"activity resource_prefixes={collections.Counter(r['resource_id'].rsplit('_',1)[0] for r in act).most_common(30)}")
out(f"activity distinct_resource_ids={len(set(r['resource_id'] for r in act))}")

rules = store["deletion_rules.csv"]
out(f"rules data_category={dict(collections.Counter(r['data_category'] for r in rules))}")
out(f"rules required_action={dict(collections.Counter(r['required_action'] for r in rules))}")

section("sample_output.csv shape")
import json
so = store["sample_output.csv"]
out(f"status={dict(collections.Counter(r['deletion_status'] for r in so))}")
ops = collections.Counter(); phases = collections.Counter(); states = collections.Counter()
sysc = collections.Counter(); respre = collections.Counter(); evcite = collections.Counter()
badnum = []
for r in so:
    steps = json.loads(r["steps_json"])
    if [s["step_no"] for s in steps] != list(range(1, len(steps) + 1)):
        badnum.append(r["case_id"])
    for s in steps:
        ops[s["operation"]] += 1; phases[s["phase"]] += 1; states[s["state"]] += 1
        sysc[s["system_id"]] += 1; respre[s["resource_id"].rsplit("_", 1)[0]] += 1
        evcite["empty" if s["evidence_id"] == "" else s["evidence_id"].split("_")[0]] += 1
out(f"step_no_not_consecutive={badnum}")
out(f"phases={dict(phases)}")
out(f"operations={dict(ops)}")
out(f"states={dict(states)}")
out(f"system_ids={dict(sysc)}")
out(f"resource_prefixes={dict(respre)}")
out(f"evidence_id_kinds={dict(evcite)}")

section("activity resource ids vs evidence text")
# which resource_ids are never mentioned in any text-readable evidence file
text = []
for p in (DS / "evidence").rglob("*"):
    if p.is_file() and p.suffix.lower() in (".sql", ".json", ".log", ".txt"):
        text.append(p.read_text("utf-8", "replace"))
# add PDF text (FlateDecode streams); PNG screenshots cannot be grepped and are excluded
import zlib
for p2 in sorted((DS / "evidence" / "documents").glob("*.pdf")):
    raw2 = p2.read_bytes()
    for m in re.finditer(rb"stream\r?\n(.*?)endstream", raw2, re.S):
        try: text.append(zlib.decompress(m.group(1)).decode("latin-1"))
        except Exception: pass
blob = "\n".join(text)
res = sorted(set(r["resource_id"] for r in act))
never = [r for r in res if r not in blob]
out(f"activity_resource_ids={len(res)} never_in_text_evidence={len(never)} examples={never[:10]}")
by_pre = collections.Counter(r.rsplit("_", 1)[0] for r in never)
out(f"never_mentioned_by_prefix={dict(by_pre)}")

section("decoy identifiers in evidence (emails not in the identity universe)")
known = set(cur) | set(hist)
emails_in_ev = collections.Counter(e.lower() for e in re.findall(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", blob))
unknown = {e: n for e, n in emails_in_ev.items() if e not in known}
out(f"distinct_emails_in_text_evidence={len(emails_in_ev)} not_in_identity_universe={len(unknown)}")
out(f"examples={sorted(unknown.items(), key=lambda x: -x[1])[:15]}")
req_emails = {r['email'].lower() for r in store['deletion_requests.csv']}
out(f"evidence_emails_that_are_request_emails={len({e for e in emails_in_ev if e in req_emails})} of {len(req_emails)} request emails")
names = {r['name'] for r in ui}
surn = collections.Counter(n.split()[-1] for n in names)
out(f"surnames_shared_by_multiple_users={sum(1 for v in surn.values() if v > 1)} top={surn.most_common(8)}")

section("per-user evidence coverage")
uid_in_ev = collections.Counter()
for m in re.finditer(r"\buser_\d+\b", blob):
    uid_in_ev[m.group(0)] += 1
real = {u for u in uid_in_ev if u in uids}
out(f"user_ids_in_text_evidence={len(uid_in_ev)} real={len(real)} fabricated_looking={len(uid_in_ev) - len(real)}")
out(f"fabricated_examples={[u for u in uid_in_ev if u not in uids][:10]}")
