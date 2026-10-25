# Evaluation report: Ghost Data Still Exists

Every number in this report comes from the scorer in
`code/evaluation/main.py`. No number is written from memory. Each section
states the command that produces it, so a reader can reproduce the figure.

Date of this run: 2026-10-25.

## How to reproduce every number

Run these commands from the repository root. None of them needs an API key,
because the model caches are committed.

```sh
# the 518 evaluation rows and the contract check
python3 code/main.py
python3 code/evaluation/main.py check output.csv

# the 32 public sample cases, scored against the supplied truth
python3 code/main.py --sample --out /tmp/sample.csv
python3 code/evaluation/main.py score /tmp/sample.csv dataset/sample_output.csv

# the 5 extra cases, scored against our own expected answers
python3 code/main.py --requests evaluation/cases/requests.csv --out /tmp/extra.csv
python3 code/evaluation/main.py score /tmp/extra.csv evaluation/cases/expected.csv

# the recall limit the evidence index imposes
python3 code/evaluation/ceiling.py

# the candidate rules that were tested and rejected
python3 code/evaluation/experiments.py

# the rules the supplied data never exercises
python3 code/evaluation/cases.py
```

## Sample set: the 32 public cases

The truth for these cases is `dataset/sample_output.csv`, supplied with the
challenge.

| Metric | Value |
| --- | --- |
| Case-level status accuracy | 31 of 32 = 0.969 |
| Exact row accuracy | 9 of 32 = 0.281 |
| Sequence accuracy | 9 of 32 = 0.281 |
| Step precision | 0.975 |
| Step recall | 0.793 |
| Step f1 | 0.874 |
| True positives, false positives, false negatives | 153, 4, 40 |

Field accuracy over the 157 position-aligned steps:

| Field | Accuracy |
| --- | --- |
| `phase` | 0.994 |
| `system_id` | 0.732 |
| `resource_id` | 0.732 |
| `operation` | 0.771 |
| `state` | 0.777 |
| `evidence_id` | 1.000 |

`system_id` and `resource_id` share one number because the prefix of a
`resource_id` fixes its `system_id`. A wrong resource therefore costs both
fields, and a right resource never costs either.

Precision is far above recall. The answer rarely names a step that does not
belong, and it misses steps it cannot reach. The next section measures why.

## The recall limit the evidence index imposes

Command: `python3 code/evaluation/ceiling.py`.

The sample truth holds 193 steps. For 159 of them the index links the named
resource to the subject inside the case window. For the other 34 the index
links the resource to nobody.

| Quantity | Value |
| --- | --- |
| Sample truth steps | 193 |
| Resource reached inside the case window | 159 |
| Recall limit | 0.824 |
| Measured recall | 0.793 |
| Winnable by a better rule | 0.031 |
| Needs better linking | 0.176 |

All 34 unreachable steps are verification steps: 20 `VERIFY_RECORD_ABSENT`,
7 `VERIFY_RECORD_ANONYMIZED`, and 7 `VERIFY_RECORD_PRESENT`. None of them is
a finding. The limit therefore costs recall and never costs a case status.

The 34 resources carry names such as `account_001` for `case_01` and
`account_007` for `case_07`. The number in the resource matches the number
in the case. Reading the answer out of that pattern is a case-family
shortcut. Section 6.7 of `AGENTS.md` forbids it. The shortcut was not taken,
so the limit stands.

## Candidate rules tested and rejected

Command: `python3 code/evaluation/experiments.py`.

Each rule below looked able to raise recall. Each one runs as a single change
to the shipped pipeline and scores the same 32 cases. A rule is rejected
when it fails to raise step f1 and status accuracy together.

| Candidate rule | Status | f1 | Exact | Verdict |
| --- | --- | --- | --- | --- |
| Shipped baseline | 31/32 | 0.874 | 9 | kept |
| 1. Link a resource through an activity row naming the subject | - | - | - | rejected |
| 2. Match evidence on a shared surname | 31/32 | 0.864 | 8 | rejected |
| 3. Treat a referenced record nobody saw as present | 31/32 | 0.869 | 8 | rejected |
| 4. Drop the case window and read all earlier evidence | 31/32 | 0.862 | 8 | rejected |
| 5. Hold that a row count alone cannot prove redaction | 32/32 | 0.869 | 9 | rejected |

Rule 1 makes 0 of the 34 unreachable steps reachable. The activity stream
names the resource. It never names an identifier of the subject in the same
row, so the link the rule needs does not exist in the data.

Rule 2 is the rule the data quality audit warned about. It claims 18 more
resources across 13 of the 518 evaluation cases, gains no sample step, and
costs 0.010 of f1. The dataset places 22 look-alike emails and 143 shared
surnames next to the real identities for exactly this reason.

Rule 3 replaces a correct absence proof with a false finding. A deleted
record leaves no row of its own, so treating silence as presence inverts the
one case the challenge is about.

Rule 4 lets evidence from before the request decide the answer. A record
deleted after the request then reads as present, and f1 falls by 0.012.

Rule 5 is the rejection worth reading twice. It raises status accuracy to 32
of 32, so a score table alone accepts it. A step-level comparison shows that
it adds 2 steps to `case_10` and both are wrong. It reports exposed
identifiers and plans a redaction, while the truth deletes the whole record.
The rule buys the last status point with two wrong steps, so it was not
shipped. That is why this report quotes step accuracy beside status accuracy
everywhere.

## The five extra evaluation cases

The 32 public cases leave several shapes untested. These five cases cover
them. Each expected answer is a hand reading of participant-visible evidence
and of `deletion_rules.csv`. No organizer truth was used.

The request rows are in `evaluation/cases/requests.csv` and the expected
answers are in `evaluation/cases/expected.csv`.

| Case | Shape it tests | Expected status |
| --- | --- | --- |
| `case_542` | A request for a copy that refuses deletion in the same sentence | `NOT_APPLICABLE` |
| `case_46` | A tombstone that already carries only the stable reference | `COMPLETE` |
| `case_103` | A security audit log inside its retention period | `COMPLETE` |
| `case_105` | A record absent from the primary and alive in a read replica | `INCOMPLETE` |
| `case_128` | An active sync flow after a workflow reported success | `INCOMPLETE` |

What each case proves, and the evidence it rests on:

1. `case_542` reads "please don't delete or change anything" inside a
   request for a copy of the data. A keyword rule sees the deletion verb and
   audits the case. The answer must be `NOT_APPLICABLE` with an empty step
   list.
2. `case_46` rests on `evidence_42`. The tombstone overview panel shows
   order, support, and finance links and shows no name, no email, and no
   phone, which is the state rule_15 requires. `evidence_67` answers the
   profile lookup with HTTP 404 and 0 rows.
3. `case_103` rests on `evidence_10`. The record `audit_record_9522` sits in
   the primary table and in the replica, and rule_12 keeps it. The only step
   is the proof that it is still there.
4. `case_105` rests on `evidence_10`. The record `account_6345` carries the
   full name, the email, and the phone in `customer_data_read_replica` and
   does not appear in `customer_data_primary` of the same file. That gap is
   the replication drift the challenge asks for.
5. `case_128` rests on `evidence_87`. The flow `data_flow_5550` is enabled,
   runs in continuous sync mode, and selects this subject by email, so it can
   recreate the data it copies.

Result of the run:

| Metric | Value |
| --- | --- |
| Case-level status accuracy | 5 of 5 = 1.000 |
| Exact row accuracy | 5 of 5 = 1.000 |
| Sequence accuracy | 5 of 5 = 1.000 |
| Step precision, recall, f1 | 1.000, 1.000, 1.000 |
| True positives | 13 |
| Every field accuracy | 1.000 |

These five numbers are reported apart from the sample numbers on purpose. We
wrote the expected answers, so a perfect score here proves agreement with our
reading of the policy. It does not prove agreement with the organizer.

## Cases for rules the supplied data never exercises

Command: `python3 code/evaluation/cases.py`.

Two policy conditions never flip inside `dataset/`. Every legal hold runs to
2033 and every security audit log sits inside its retention period. A rule
that never runs is a rule nobody can trust. Five more cases therefore take a
real subject and a real record. Each one moves `audit_at` across the one
cutoff the evidence states.

| Case | Record | Expected operation |
| --- | --- | --- |
| `retained_audit_log` | `audit_record_003` | `VERIFY_RECORD_PRESENT` |
| `lapsed_audit_log` | `audit_record_003` | `DELETE_RECORD` |
| `active_legal_hold` | `legal_hold_8017` | `VERIFY_RECORD_PRESENT` |
| `lapsed_legal_hold` | `legal_hold_8017` | `DELETE_RECORD` |
| `support_attachment` | `support_001` | `DELETE_RECORD` |

All five pass, and every case row also goes through the contract checker.

## The evaluation run

Command: `python3 code/main.py` then
`python3 code/evaluation/main.py check output.csv`.

| Quantity | Value |
| --- | --- |
| Rows written | 518 |
| Contract violations | 0 |
| `COMPLETE` | 153 |
| `INCOMPLETE` | 355 |
| `NOT_APPLICABLE` | 10 |
| Steps written | 2662 |
| Mean steps per case | 5.1 |
| Largest case | 14 steps |
| Rows with an empty step list | 10 |

The 10 rows with an empty step list are the 10 `NOT_APPLICABLE` cases, which
is what section 6.3 requires. The count matches the 10 `CLASSIFY_REQUEST`
rows in the activity stream.

## Failures found, and the fix for each

| Failure | How it was found | Fix | Effect |
| --- | --- | --- | --- |
| 11 screenshots and 4 PDF documents were unreadable, so 9 `COMPLETE` cases produced no step | Sample cases with no predicted step | A cached vision pass transcribes each file once, and the index reads the cache like any other file | Status 30 of 32 to 31 of 32 |
| Evidence captured before the request decided answers it must not decide | Sample step comparison | The case window drops evidence older than `requested_at`, with an exception for a record policy retains | Fewer false findings |
| Two policy rules carry a condition that the code never read, so every audit log and legal hold was retained unconditionally | Reading `deletion_rules.csv` against the code | Two lookup tables read from the transcribed documents, and the retain basis drops once the cutoff passes | No sample change, and the rules are now testable |
| Every support record was treated as a message, so attachments were redacted instead of deleted | `case_07` and `case_13` step comparison | The record itself decides between rule_05 and rule_06 | f1 0.840 to 0.874 |
| The attachment signal was read from field values only and matched 2 of 23 attachments | Code review of the branch | Read the field name as well as the value | 11 of the 518 rows corrected |
| `vision.ask` read a name that no line created, so any cache rebuild stopped with `NameError` after the model call was paid for | Code review of the branch | Build the text block list from the response | The rebuild path works |
| A group filter dropped a record that names the subject together with a second person, and then reported it absent | Code review of the branch | The merge only adds records and never removes any | No current row changed, and the latent wrong answer is gone |
| The extra cases scored against themselves, so the guard never failed | Code review of the branch | The cases go through the contract checker instead | The guard can now fail |

## Known failure

One sample case is still wrong. `case_10` predicts `COMPLETE` and the truth
is `INCOMPLETE`.

The record is `support_002`, seen in `evidence_61`. That file is a replica
log. One line reports `contact_query_completed` with `rows=1`, and the next
reports `deletion_marker_check` with `marker_found=false`. The record is
therefore present in the replica and the deletion marker never reached it.

The pipeline reads the row count as proof of presence, finds no identifier in
the log line, and concludes that the record is adequately redacted. A log
line never prints the record body, so the absence of an identifier in the
line proves nothing about the body. The truth deletes the whole record.

Candidate rule 5 above is the narrow fix. The step-level comparison shows
that it adds two wrong steps. The real fix is to decide the treatment of a
support record from the record body, and a replica log carries no body. That
work needs a signal this evidence file does not contain. The case is
therefore recorded here rather than patched.
