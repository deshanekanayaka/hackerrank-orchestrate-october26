# 01: Read the screenshots and PDFs into the index

**What to build:** The 11 screenshots and 4 PDF documents under
`dataset/evidence/` become readable evidence. A one-time pass sends each file
to a vision model, asks for a plain transcription of every visible label,
value, and table row as JSON, and caches the result in `code/cache/`. The
evidence index reads that cache like any other file, so the 9 `COMPLETE`
cases that produce no step today get their steps, and every finding and
verification step can cite an image `file_id`.

**Blocked by:** None (can start immediately).

**Status:** done

- [x] All 15 files are transcribed once and cached as JSON in `code/cache/`
- [x] A rerun with the cache present makes no model call
- [x] The transcription asks for content only, never for a verdict
- [x] The evidence index links resources from the cached text by exact
      identifier, the same rule as text evidence
- [x] `python3 code/evaluation/main.py check output.csv` reports 0 violations
      on all 518 rows
- [ ] Sample score does not fall below status 30 of 32 and step f1 0.845
      (status rose to 31 of 32, step f1 is 0.840: the three steps below
      the floor are case_07 support_001, which issue 02 turns from REDACT
      into DELETE)
- [x] Token counts for the pass are appended to `code/cache/usage.jsonl`
