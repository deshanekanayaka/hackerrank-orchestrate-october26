"""Audit dataset/evidence/: file types, SQLite loadability, JSON parse, log structure. Read-only."""
import json, pathlib, re, sqlite3, collections, csv, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
DS = ROOT / "dataset"
EV = DS / "evidence"
man = {r["file_path"]: r for r in csv.DictReader((DS / "evidence_files.csv").read_text().splitlines())}

def out(*a): print(*a)

out("# Evidence audit")
out("\n### file inventory")
by_ext = collections.Counter()
for p in sorted(EV.rglob("*")):
    if p.is_file():
        by_ext[(p.parent.name, p.suffix.lower())] += 1
for k, v in sorted(by_ext.items()):
    out(f"{k[0]}/*{k[1]}: {v}")

out("\n### magic bytes vs extension")
for p in sorted(EV.rglob("*")):
    if not p.is_file(): continue
    head = p.open("rb").read(8)
    ok = True
    if p.suffix == ".png": ok = head.startswith(b"\x89PNG")
    elif p.suffix == ".pdf": ok = head.startswith(b"%PDF")
    else:
        try: p.read_text("utf-8"); ok = True
        except UnicodeDecodeError: ok = False
    if not ok: out(f"MISMATCH {p.relative_to(DS)} head={head!r}")
out("(no MISMATCH lines above means every extension matched its content)")

out("\n### SQL files in SQLite")
for p in sorted((EV / "databases").glob("*.sql")):
    txt = p.read_text("utf-8", "replace")
    con = sqlite3.connect(":memory:")
    try:
        con.executescript(txt)
        tabs = [r[0] for r in con.execute("select name from sqlite_master where type='table' order by name")]
        info = []
        for t in tabs:
            n = con.execute(f"select count(*) from '{t}'").fetchone()[0]
            cols = [c[1] for c in con.execute(f"PRAGMA table_info('{t}')")]
            info.append(f"{t}(rows={n}; cols={','.join(cols)})")
        out(f"OK   {p.name}: {len(tabs)} tables -> " + " | ".join(info))
    except Exception as e:
        out(f"FAIL {p.name}: {type(e).__name__}: {e}")
    con.close()

out("\n### JSON files")
for p in sorted((EV / "records").glob("*.json")):
    try:
        d = json.loads(p.read_text("utf-8"))
    except Exception as e:
        out(f"FAIL {p.name}: {e}"); continue
    def shape(x, depth=0):
        if isinstance(x, dict):
            return "{" + ", ".join(f"{k}:{shape(v, depth+1)}" for k, v in list(x.items())[:8]) + "}" if depth < 2 else "{...}"
        if isinstance(x, list):
            return f"[{len(x)} x {shape(x[0], depth+1) if x else 'empty'}]" if depth < 2 else f"[{len(x)}]"
        return type(x).__name__
    out(f"OK   {p.name}: top={type(d).__name__} keys={list(d)[:10] if isinstance(d, dict) else len(d)}")
    out(f"       shape={shape(d)[:600]}")

out("\n### text records (.txt)")
for p in sorted((EV / "records").glob("*.txt")):
    t = p.read_text("utf-8")
    out(f"{p.name}: {len(t.splitlines())} lines; first 12:")
    for l in t.splitlines()[:12]: out("    " + l[:160])

out("\n### log structure")
for p in sorted((EV / "logs").glob("*.log")):
    lines = p.read_text("utf-8", "replace").splitlines()
    sample = lines[0] if lines else ""
    kind = "unknown"
    if sample.startswith("{"): kind = "json-lines"
    elif re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", sample): kind = "iso-prefixed"
    elif re.match(r"^[A-Z][a-z]{2} +\d+ \d{2}:\d{2}:\d{2}", sample): kind = "syslog"
    elif re.match(r"^\[", sample): kind = "bracketed"
    nonjson = sum(1 for l in lines if kind == "json-lines" and l.strip() and not l.strip().startswith("{"))
    out(f"{p.name}: lines={len(lines)} kind={kind} malformed_jsonl={nonjson}")
    out(f"    first={sample[:200]}")

out("\n### PDF text extraction check")
for p in sorted((EV / "documents").glob("*.pdf")):
    raw = p.read_bytes()
    out(f"{p.name}: bytes={len(raw)} has_FlateDecode={b'FlateDecode' in raw} pages~{raw.count(b'/Type /Page') or raw.count(b'/Type/Page')}")

out("\n### images")
for p in sorted((EV / "images").glob("*.png")):
    raw = p.open("rb").read(33)
    w = int.from_bytes(raw[16:20], "big"); h = int.from_bytes(raw[20:24], "big")
    out(f"{p.name}: {w}x{h} bytes={p.stat().st_size}")

out("\n### manifest captured_at vs filename date")
for path, r in sorted(man.items()):
    m = re.search(r"(20\d{6})", path)
    if m:
        fd = f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:]}"
        if not r["captured_at"].startswith(fd):
            out(f"MISMATCH {r['file_id']} {path} captured_at={r['captured_at']}")
    else:
        out(f"NO_DATE_IN_NAME {r['file_id']} {path} captured_at={r['captured_at']}")
