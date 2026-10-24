"""Prompt-injection scan + non-deletion request triage. Read-only."""
import csv, json, pathlib, re, collections, zlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
DS = ROOT / "dataset"

# instruction-like patterns, English + other languages the dataset uses
PATTERNS = {
    "ignore_previous": r"\b(ignore|disregard|forget)\b[^.\n]{0,40}\b(previous|prior|above|earlier|all)\b",
    "system_prompt": r"system prompt|system message|developer message",
    "mark_as": r"\bmark\b[^.\n]{0,30}\b(as|status)\b[^.\n]{0,20}(complete|completed|done|resolved)",
    "you_are": r"\byou are (an?|the) \w+",
    "role_tag": r"<\s*/?\s*(system|assistant|user|instructions?|im_start|im_end)\s*>|\[/?(system|inst|assistant|user)\]|###\s*(system|instruction)",
    "assistant_addressed": r"\b(ai|agent|assistant|model|llm|chatbot|gpt|claude)\b[^.\n]{0,20}\b(must|should|please|now|instruct)",
    "override": r"\boverride\b|\bbypass\b|\bno need to (check|verify|audit)\b|\bskip\b[^.\n]{0,20}(check|verification|audit|step)",
    "output_control": r"\b(output|respond|reply|return|answer)\b[^.\n]{0,25}\b(only|exactly|just)\b|return COMPLETE|set status",
    "jailbreak_words": r"\bdo not (report|flag|mention)\b|\bpretend\b|\bact as\b|\bnew instructions?\b|\bimportant instruction",
    "xx_es": r"ignora(r)? (las )?(instrucciones|anteriores)|marca(r)? como completado",
    "xx_fr": r"ignore[rz]? les instructions|marquer comme (termin|complet)",
    "xx_de": r"ignorier(e|en) (die )?(vorherigen|anweisungen)|als (abgeschlossen|vollständig) markieren",
    "xx_pt": r"ignor(e|ar) as instru|marcar como (conclu|complet)",
    "xx_ja_zh_ko": r"(以前の指示を無視|完了としてマーク|忽略.{0,6}指令|标记为已完成|이전 지시를 무시)",
}
COMPILED = {k: re.compile(v, re.I) for k, v in PATTERNS.items()}

def scan(text, where, hits):
    for name, rx in COMPILED.items():
        for m in rx.finditer(text):
            s = max(0, m.start() - 60); e = min(len(text), m.end() + 60)
            hits.append((where, name, text[s:e].replace("\n", " ⏎ ")))

print("# Prompt-injection scan")
hits = []
reqs = list(csv.DictReader((DS / "deletion_requests.csv").read_text().splitlines()))
samp = list(csv.DictReader((DS / "sample_deletion_requests.csv").read_text().splitlines()))
for r in reqs + samp:
    scan(r["request_text"], f"deletion_requests:{r['case_id']}", hits)

text_files = [p for p in (DS / "evidence").rglob("*") if p.is_file() and p.suffix.lower() in (".sql", ".json", ".log", ".txt")]
for p in text_files:
    scan(p.read_text("utf-8", "replace"), str(p.relative_to(DS)), hits)

# PDFs: decompress FlateDecode streams and scan extracted text
for p in sorted((DS / "documents" if False else DS / "evidence" / "documents").glob("*.pdf")):
    raw = p.read_bytes()
    chunks = []
    for m in re.finditer(rb"stream\r?\n(.*?)endstream", raw, re.S):
        try: chunks.append(zlib.decompress(m.group(1)).decode("latin-1"))
        except Exception: pass
    txt = " ".join(re.sub(r"[^\x20-\x7e]+", " ", c) for c in chunks)
    scan(txt, str(p.relative_to(DS)) + " (decoded streams)", hits)

print(f"\ntotal_hits={len(hits)}")
print(f"by_pattern={dict(collections.Counter(h[1] for h in hits))}")
print(f"by_location={dict(collections.Counter(h[0] for h in hits))}")
print("\n### every hit")
for where, name, ctx in hits:
    print(f"- [{name}] {where}: ...{ctx[:220]}...")

print("\n\n# Non-deletion request triage")
DEL_WORDS = [
    # en
    "delete", "deletion", "erase", "erasure", "remove", "wipe", "purge", "close my account",
    "close the account", "right to be forgotten", "forget me", "scrub",
    # es/pt
    "eliminar", "elimine", "eliminación", "borrar", "borre", "supresión", "suprimir", "excluir", "exclusão", "apagar", "remover",
    # fr
    "supprimer", "suppression", "effacer", "effacement",
    # de
    "löschen", "löschung", "entfernen",
    # it/nl/pl/tr/sv
    "cancellare", "cancellazione", "verwijderen", "usuń", "usunięcie", "sil", "silinmesi", "ta bort", "radera",
    # ja/zh/ko/ar/hi/ru
    "削除", "消去", "删除", "刪除", "삭제", "حذف", "मिटा", "हटा", "удалит", "удаление",
]
NON_DEL_WORDS = {
    "access/copy": ["copy of my data", "copy of the data", "access request", "what data", "which data", "data you hold",
                    "acceso", "acceder", "copia de", "accès", "copie de", "zugang", "kopie", "アクセス", "開示", "访问", "열람",
                    "send me my", "provide me with", "informe", "información que"],
    "export/portability": ["export", "portability", "machine-readable", "exportar", "exportación", "portabilidad",
                           "exportation", "portabilité", "exportieren", "エクスポート", "导出", "내보내기", "download my"],
    "correction": ["correct", "correction", "update my", "change my", "rectif", "corregir", "corrección", "actualizar",
                   "corriger", "berichtig", "korrigieren", "訂正", "修正", "更正", "정정", "fix my", "wrong address",
                   "misspell", "typo"],
    "marketing opt-out": ["unsubscribe", "opt out", "opt-out", "marketing emails", "newsletter", "stop sending",
                          "baja de", "darse de baja", "désabonn", "abmelden", "配信停止", "退订", "구독 취소",
                          "promotional", "no more emails"],
    "restriction/objection": ["restrict processing", "object to", "objection", "limitar el tratamiento", "widerspruch",
                              "limitation du traitement", "処理の制限", "限制处理"],
    "complaint/question": ["complaint", "question about", "how do you", "why did", "queja", "reclamation", "beschwerde"],
}

def has_delete(t):
    low = t.lower()
    return any(w in low for w in DEL_WORDS)

def non_del_kinds(t):
    low = t.lower()
    return [k for k, ws in NON_DEL_WORDS.items() if any(w in low for w in ws)]

rows = []
for r in reqs:
    t = r["request_text"]
    rows.append((r["case_id"], has_delete(t), non_del_kinds(t), t))

no_del = [r for r in rows if not r[1]]
del_but_other = [r for r in rows if r[1] and r[2]]
print(f"total_eval_cases={len(rows)}")
print(f"no_deletion_verb_in_any_language={len(no_del)}")
print(f"kind_mix_of_those={dict(collections.Counter(k for r in no_del for k in (r[2] or ['unclassified'])))}")
print(f"has_deletion_verb_AND_non_deletion_signal={len(del_but_other)} (ambiguous, needs a model)")
print("\n### five examples that do NOT look like deletion requests")
for cid, _, kinds, t in no_del[:5]:
    print(f"\n{cid} kinds={kinds or ['unclassified']}\n  {t[:500]}")
print("\n### all case_ids with no deletion verb")
print(", ".join(r[0] for r in no_del))
print("\n### sample set check (samples are said to contain no NOT_APPLICABLE)")
sn = [r["case_id"] for r in samp if not has_delete(r["request_text"])]
print(f"sample_cases_without_deletion_verb={sn}")
so = {r["case_id"]: r["deletion_status"] for r in csv.DictReader((DS / "sample_output.csv").read_text().splitlines())}
print(f"sample_statuses={dict(collections.Counter(so.values()))}")

print("\n\n# Raw keyword pass (literal substrings, case-insensitive)")
RAW = ["ignore", "disregard", "system prompt", "mark as complete", "mark it complete", "you are",
       "<system", "</system", "[system", "###", "{{", "}}", "prompt", "instruction", "override",
       "no need to verify", "assistant", "as an ai", "jailbreak", "act as", "pretend"]
blobs = {"deletion_requests.request_text": "\n".join(r["request_text"] for r in reqs),
         "sample_requests.request_text": "\n".join(r["request_text"] for r in samp)}
for p in text_files:
    blobs[str(p.relative_to(DS))] = p.read_text("utf-8", "replace")
tot = collections.Counter()
for kw in RAW:
    locs = {k: v.lower().count(kw) for k, v in blobs.items() if kw in v.lower()}
    tot[kw] = sum(locs.values())
    if locs:
        print(f"- '{kw}': {sum(locs.values())} hits in {len(locs)} files -> {dict(list(locs.items())[:6])}")
print(f"raw_keywords_with_zero_hits={[k for k, v in tot.items() if v == 0]}")

print("\n\n# Negated deletion mentions (keyword matching alone is unsafe)")
NEG = re.compile(r"(not a (deletion|removal) request|not a request to (erase|delete)|"
                 r"not asking (you )?(for|to) (deletion|delete)|don'?t delete|do not delete|"
                 r"without (removing|deleting)|leave (my|the) (account|profile|purchase)|"
                 r"keep the account|keep my account|do not close|don'?t close|"
                 r"only\.? I still|i still (need|want|use) the account|remove me from marketing)", re.I)
neg = [(r["case_id"], r["request_text"]) for r in reqs if NEG.search(r["request_text"])]
print(f"cases_with_explicit_non_deletion_language={len(neg)}")
for cid, t in neg:
    print(f"- {cid}: {t[:160]}")


cands = sorted({r[0] for r in no_del} | {c for c, _ in neg}, key=lambda c: int(c.split("_")[1]))
print(f"\n\n# Final non-deletion candidate set")
print(f"count={len(cands)}")
print(", ".join(cands))
byid = {r["case_id"]: r for r in reqs}
print("\nfull text of each candidate:")
for c in cands:
    print(f"- {c} [{byid[c]['reported_status']}] {byid[c]['request_text']}")
