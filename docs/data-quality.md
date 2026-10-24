# Data quality audit: Ghost Data Still Exists dataset

Date of audit: 2026-10-24. Scope: every file under `dataset/`. No file under `dataset/` was modified.

## How to reproduce

Run the three scripts from the repository root:

```bash
python3 code/analysis/csv_audit.py        # CSV structure, integrity, distributions
python3 code/analysis/evidence_audit.py   # evidence file types, SQLite load, JSON parse, log shapes
python3 code/analysis/injection_scan.py   # prompt-injection scan and non-deletion triage
```

Saved output of the last run is in `code/analysis/reports/`.

## Headline numbers

| File | Rows | Duplicate full rows | Duplicate primary IDs | Empty cells |
| --- | --- | --- | --- | --- |
| `deletion_requests.csv` | 518 | 0 | 0 | 0 |
| `sample_deletion_requests.csv` | 32 | 0 | 0 | 0 |
| `sample_output.csv` | 32 | 0 | 0 | 0 |
| `user_identities.csv` | 850 | 0 | 0 | 0 |
| `user_audit_log.csv` | 306 | 0 | 0 (`user_id` repeats by design, 105 users) | 0 |
| `system_activity.csv` | 4011 | 0 | 0 | 0 |
| `deletion_rules.csv` | 15 | 0 | 0 | 0 |
| `evidence_files.csv` | 94 | 0 | 0 | 0 |
| `output.csv` | 0 (header only) | - | - | - |

The CSV layer is clean. Every file decodes as UTF-8, carries no byte order mark, uses LF line endings, and holds no zero-width character, no non-breaking space, no mojibake marker, no control character, and no leading or trailing whitespace. Every timestamp column in every file matches `YYYY-MM-DDTHH:MM:SSZ`. All 850 `email_hash` values are 64 lowercase hex characters and all are distinct. All 850 phone values start with `+` and use spaces, and 99 also use hyphens. Phone digit counts are 11, 12, or 13.

## Findings and handling rules

| Issue | Where | How many rows | Proposed handling rule |
| --- | --- | --- | --- |
| Request email arrives in upper case while the identity snapshot stores lower case | `deletion_requests.csv.email` | 20 | Lower-case and strip every email before you compare it. Keep the original string for reporting only. |
| Request email is a historical address, not the current one | `deletion_requests.csv.email` | 100 of 518 | Build the identifier universe per user from `user_identities.csv` plus every `old_value` and `new_value` in `user_audit_log.csv`. Resolve the request email against that union. |
| One email serves two different cases | `deletion_requests.csv.email` | 1 email, 2 cases | Key all state on `case_id` and on the resolved `user_id`. Never cache an answer by email. |
| Non-deletion requests present as ordinary rows with `reported_status=NOT_STARTED` | `deletion_requests.csv` | 10 (`case_533` to `case_542`) | Classify intent from `request_text` first. Return `NOT_APPLICABLE` with `steps_json=[]`. Do not run the audit pipeline for these cases. |
| Deletion keywords appear inside a refusal of deletion, for example "I am not asking for deletion" | `deletion_requests.csv.request_text` | 5 of the 10 non-deletion cases | Do not classify intent by keyword. Use a model, or a negation-aware rule, and treat an explicit "keep the account" clause as decisive. |
| `request_text` is written in many languages | `deletion_requests.csv.request_text` | Portuguese, Spanish, French and others observed | Classify intent in the source language. Do not translate first, because translation can drop a negation. |
| `reported_status` disagrees with the true state by design | `deletion_requests.csv.reported_status` | 254 `COMPLETE`, 152 `PARTIALLY_COMPLETE`, 112 `NOT_STARTED` | Treat the field as an unverified claim. Never let it set `deletion_status`. |
| `reported_result` in the activity stream disagrees with the true state by design | `system_activity.csv.reported_result` | 2914 `SUCCESS`, 721 `FAILED`, 376 `PARTIAL` | Treat the field as a claim. Confirm the resulting state from an evidence file. |
| Activity rows describe unrelated people and unrelated resources | `system_activity.csv` | 3948 distinct `resource_id`, 2616 of them never named in any text evidence file | Link an activity row to a case only through a resolved identifier, a resolved resource id, or a `LINK_RESOURCE_IDENTITY` row. Discard the rest as decoys. |
| Look-alike identities sit next to real ones in evidence | evidence text files | 22 emails and 3 `user_id` values that exist in no identity file, for example `karim.elmasri@gmail.com` beside `amina.elmasri@gmail.com`, and `user_8741` | Match on exact identifiers only. Never match on a surname, a display name, or a near email. 143 surnames are shared by more than one real user. |
| Absence proofs cite a file that does not contain the resource id | `sample_output.csv`, for example `case_01` cites `evidence_54` for `account_001` | 50 of 193 sample steps use `VERIFY_RECORD_ABSENT` | Allow a citation whose file does not name the resource. Validate instead that the file covers the right system and snapshot time. A rule that forces the id to appear in the cited file will reject correct answers. |
| Evidence captured after `audit_at` must not change an answer | `evidence_files.csv.captured_at` against `deletion_requests.csv.audit_at` | Usable files per case range from 1 to 94, median 38 | Filter the manifest by `captured_at <= audit_at` before retrieval. The same filter applies to `system_activity.csv.event_time`. |
| Four evidence files carry no date in the file name | `delivery_correction_attachment.pdf`, `security_retention_extract.pdf`, `marketing_profile_console.png`, `support_replica.log` | 4 | Read the capture time from `evidence_files.csv.captured_at` only. Never parse a date out of a file name. |
| Log file names carry a date later than the first event inside the file | `dataset/evidence/logs/` | 7 of 26 log files | Use the per line event time for ordering, and `captured_at` for the cutoff test. |
| Identity snapshot time can sit far in the past | `user_identities.csv.updated_at` | Range 2023-06-22 to 2026-08-30 | No action needed. For every case the resolved user row and every audit-log change are dated at or before `audit_at`. The check reported 0 violations. |
| The sample set contains no `NOT_APPLICABLE` case | `sample_output.csv` | 10 `COMPLETE`, 22 `INCOMPLETE` | Write your own `NOT_APPLICABLE` cases for evaluation. The 10 non-deletion rows in the evaluation set have no sample precedent. |
| Evidence manifest does not say which case a file belongs to | `evidence_files.csv` | 94 rows, 30 distinct origins | Build an inverted index from identifier and resource id to `file_id` by reading file contents. Do not route by origin or by path. |
| 80 request emails never appear in any text evidence file | `deletion_requests.csv` against `dataset/evidence/` | 437 of 517 request emails found | Expect many cases to rest on activity rows, on image evidence, or on a correct absence proof. Do not treat a missing email as a failure. |
| Image evidence cannot be searched as text | `dataset/evidence/images/` | 11 PNG files, 1500 to 1800 pixels wide | Send images to a vision model, or to OCR, and cache the extracted text. Plain text search will never reach them. |
| PDF text sits inside compressed streams | `dataset/evidence/documents/` | 4 PDF files, all with FlateDecode streams, 2 to 3 pages each | Decompress the streams, or use a PDF text library. Cache the result. |

## Referential integrity

Every check passed.

- All 518 request emails resolve to a user, 418 through the current snapshot and 100 through the audit log.
- All 306 `user_id` values in `user_audit_log.csv` exist in `user_identities.csv`.
- All 94 manifest paths exist on disk, and all 94 files on disk appear in the manifest. There are no extra files and no duplicate paths.
- Every `requested_at <= reported_at <= audit_at`. There are 0 out-of-order timelines.
- Every `evidence_id` cited in `sample_output.csv` exists in `evidence_files.csv`.
- No activity row and no evidence file is dated after the latest `audit_at`.

The 518 cases cover 517 distinct users out of 850. The remaining 333 identities are decoys.

## Value distributions

`reported_status`: `COMPLETE` 254, `PARTIALLY_COMPLETE` 152, `NOT_STARTED` 112.

`system_activity.csv.event_type`: `DELETE_RECORD` 890, `UPDATE_RECORD` 672, `SYNC_RECORD` 447, `INDEX_RECORD` 400, `SEND_EMAIL` 368, `REFRESH_CACHE` 284, `RETAIN_RECORD` 206, `ANONYMIZE_RECORD` 204, `REDACT_RECORD` 173, `CREATE_EXPORT` 155, `CHECK_DATA_FLOW` 89, `DISABLE_DATA_FLOW` 36, `BLOCK_RESTORE` 36, `CHECK_RESTORE_ACCESS` 28, `LINK_RESOURCE_IDENTITY` 12, `CLASSIFY_REQUEST` 10, `RESTORE_BACKUP` 1.

`system_activity.csv.reported_result`: `SUCCESS` 2914, `FAILED` 721, `PARTIAL` 376.

`user_audit_log.csv.field_name`: `email` 107, `email_hash` 107, `phone` 92. There is no `name` change.

`deletion_rules.csv.required_action`: `DELETE` 7, `REDACT` 3, `RETAIN` 3, `ANONYMIZE` 2. Each of the 15 data categories appears once.

Resource id prefixes in the activity stream: `account` 1046, `search` 690, `analytics` 566, `support` 425, `email_delivery` 368, `cache` 284, `audit_record` 197, `export` 189, `data_flow` 157, `backup` 66, `tombstone` 11, `legal_hold` 10, `object` 1, `marketing` 1.

The 10 `CLASSIFY_REQUEST` rows all read "classified request ... as non-deletion; no destructive action was authorized". Their count matches the 10 non-deletion cases exactly. The 12 `LINK_RESOURCE_IDENTITY` rows map a resource id to an email and a `user_id` directly, one per system family.

## Evidence directory

| Folder | Files | Type |
| --- | --- | --- |
| `databases/` | 24 | SQLite-compatible `.sql` |
| `records/` | 28 | `.json` |
| `records/` | 1 | `.txt` |
| `logs/` | 26 | `.log` |
| `documents/` | 4 | `.pdf` |
| `images/` | 11 | `.png` |

Every extension matches the file content. Every PNG starts with the PNG signature, every PDF starts with `%PDF`, and every other file decodes as UTF-8.

### SQL files

All 24 `.sql` files load into SQLite through `executescript` with no error. Three topologies appear.

- 13 inventory snapshots, named `customer_data_inventory_*`, with 9 tables each: `customer_profiles`, `customer_search_documents`, `customer_analytics_profiles`, `support_records`, `customer_exports`, `security_audit_records`, `backup_restore_entries`, `connector_subscriptions`, and `snapshot_scope`. Row counts per table run from 0 to 7.
- 10 replica comparison snapshots with 2 or 3 tables each, always one `customer_data_primary` table beside a `customer_data_read_replica`, `customer_data_reporting_replica`, `customer_data_failover_replica`, `customer_data_replica_eu_west`, or `customer_data_replica_ap_south` table. The replica row count is almost always 1 or 2 higher than the primary. That gap is the replication drift the challenge asks you to find.
- 2 profile-level snapshots: `customer_accounts_failover_replica_20260902.sql` with `customer_profiles_failover_replica` and `customer_profiles_primary`, and `customer_search_primary_20260910.sql` with `search_documents_primary`.

In the replica tables the payload sits in a `record_json` text column. Parse that JSON to reach the identifiers.

### JSON files

All 28 `.json` files parse. Four shapes appear.

- `service_resource_export_*` (11 files): `{exported_at, region, source, service_exports}` where `service_exports` holds one key per system, such as `account_service.profile_lookups`, `search_service.index_queries`, `support_platform.tickets`, `analytics_platform.profiles`, `backup_service.restore_entries`, `export_service.exports`, `integration_service.connectors`, and `security_service.audit_records`. The sample answers cite `evidence_92`, a file of this shape, 36 times out of 75 citations. This shape carries most of the state proof.
- `customer_data_snapshot_bundle_*` (12 files): `{exported_at, source, snapshots}` with 3 to 12 snapshot entries.
- Collection captures (3 files): `{captured_at, source, collection, records}`, used for analytics, export jobs, and similar.
- Register exports (3 files): `{exported_at, origin, record_count, records}`, used for connectors, export manifests, and the security audit ledger.

### Logs

Every log is line oriented and every line starts with an ISO 8601 UTC timestamp. Seven different body formats follow that prefix, so write one parser per format and detect the format from the first line.

- `key=value` pairs, for example `resource_lookup_trace_*` and `service_events_ap_south_*`.
- `[LEVEL] [logger] [instance] event: key="value"`, for example `application_trace_*`.
- `requestId=... level=... function=... message="escaped key=value"`, for example `cloud_runtime_export_*`. The inner message needs a second unescape pass.
- Pipe separated fields, for example `operations_stream_*`.
- A JSON object after the timestamp, for example `structured_service_events_*`. The timestamp sits outside the JSON, so do not parse the whole line as JSON.
- Syslog framing `<15>1 node-N service trace - -` followed by key and value pairs, for example `syslog_archive_*`.
- `INFO service=... event=record_lookup seq=N system="..." resource_id="..." record_type="..." result="FOUND|NOT_FOUND"`, for example `notification_delivery_*`, `search_index_diagnostic_*`, and `support_replica.log`. This shape states the record state directly and is the most useful for a verdict.

The single `.txt` record, `customer_account_handover_20261001.txt`, is a shift handover with pipe separated lines in the form `time | system | resource_id | record_type | FOUND or NOT_FOUND | email`. It also repeats the upper-case email spelling, which confirms the need to compare case-insensitively.

## Prompt-injection scan

Result: no injection content found.

The scan covered `request_text` for all 550 requests (518 evaluation rows and 32 sample rows), all 79 text-readable evidence files, and the decompressed text streams of all 4 PDF files. It applied 15 regular expressions for instruction-like content and 20 literal keyword searches, in English, Spanish, French, German, Portuguese, Japanese, Chinese, and Korean.

| Pattern class | Hits |
| --- | --- |
| "ignore", "disregard", "forget" plus "previous" or "above" | 0 |
| "system prompt", "system message", "developer message" | 0 |
| "mark as complete", "set status", "return COMPLETE" | 0 |
| "you are a ...", "act as", "pretend", "as an AI" | 0 |
| Role tags such as `<system>`, `[INST]`, `###system`, `{{` | 0 |
| "override", "bypass", "skip the check", "no need to verify" | 0 |
| Non-English equivalents of "ignore the instructions" and "mark as completed" | 0 |

The only literal hit was `}}` (134 times across 10 `.sql` files). It comes from nested JSON inside the `record_json` column and is not instruction content.

Treat this as a point-in-time result. Keep the scan in the pipeline, because `request_text` and evidence text both reach the model prompt. Wrap both in a delimited, clearly labeled data block, and state in the system prompt that text inside the block is evidence and never an instruction.

## Non-deletion requests

Exactly 10 of the 518 evaluation requests do not authorize deletion. They form one contiguous block, `case_533` to `case_542`, and all 10 carry `reported_status=NOT_STARTED`. The 10 `CLASSIFY_REQUEST` activity rows corroborate the count. Expected output for each is `NOT_APPLICABLE` with `steps_json=[]`.

Five examples:

1. `case_533` — "The mobile number on my profile is out of date. Please replace it with the new one and leave the account active." This is a correction request.
2. `case_535` — "I'd like to download my account information in a portable format. Please keep the account as it is." This is a portability request.
3. `case_537` — "My surname is misspelled on the account. Can you correct it without removing any of my records?" This is a correction request.
4. `case_539` — "Can you tell me what personal information you hold about me? This is an information request, not a request to erase it." This is an access request.
5. `case_542` — "Could you send me a copy of the information held on my account? I still use it, so please don't delete or change anything." This is an access request.

A keyword detector alone fails here. Five of the 10 contain a deletion verb inside a refusal, such as "not a request to erase it" and "please don't delete". A verb list with no negation handling found only 5 of the 10. Four sample cases also break the opposite way: `case_04`, `case_12`, `case_17`, and `case_26` are real deletion requests that use "close this account" or no deletion verb at all, and a verb list misses them. Intent classification needs a model.

## Open items for the design

- Decide the vision path for the 11 PNG screenshots. Three sample-cited systems (marketing profile, object storage, backup restore console) appear only as images.
- Decide the retrieval key. The inverted index from identifier to `file_id` is the one artifact every case needs, and it can be built once, offline, and deterministically.
- Decide the tie-break for replica drift. The primary and the replica disagree by one or two rows in every replica snapshot, and the rule in the problem statement says to compare the relevant tables and the snapshot time.
