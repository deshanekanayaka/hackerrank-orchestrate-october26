# 02: Apply the two conditional policy rules

**What to build:** Two rules in `deletion_rules.csv` hold only while a
condition holds, and both conditions live in PDF evidence. A security audit
log is retained only inside the retention period in
`security_retention_extract.pdf`, and a legal hold record is retained only
while the hold in `legal_retention_register_20260529.pdf` is active. The
transcribed text becomes two small lookup tables, so a record outside its
window stops being treated as retained and is handled by the action its rule
then requires.

**Blocked by:** 01.

**Status:** done

- [x] The retention window and the active holds are read from the cached
      transcriptions, never hardcoded
- [x] A `SECURITY_AUDIT_LOG` inside its window still yields
      `VERIFY_RECORD_PRESENT`
- [x] A record outside its window no longer yields `VERIFY_RECORD_PRESENT`
- [x] A hand-built case for each rule passes through the scorer
      (`python3 code/evaluation/cases.py`, 5 cases)
- [x] Sample score does not fall (status 31 of 32, step f1 0.840 -> 0.874)

## What shipped

`policy.conditions()` scans the transcription cache for any record with a
retain field. An audit journal entry gives a per-record cutoff. Any other
retained row gives a cutoff for every `user_id` it names.
`status.action_for()` compares the cutoff with `audit_at` and falls back to
`DELETE` once the basis that kept the record has lapsed. A legal hold row
that states its own `retained_until` beats the register, because the row is
the stronger statement.

The ticket also absorbed the `support_001` item that ticket 01 left open.
`policy.resolve_category()` splits the support prefix: a record the evidence
shows as a file, or names as `SUPPORT_ATTACHMENT`, falls under rule_06 and is
deleted, while a message stays under rule_05 and is redacted. Reaching the
attachment panel needed one more change in `status.resource_states()`: every
record of one resource in one file now merges, including a panel that names
no subject of its own, because the shared `resource_id` is the link.

## What the dataset never exercises

Every legal hold in `dataset/` runs to 2033 and every audit log sits inside
its period, so neither condition flips on the supplied data. The five cases
in `code/evaluation/cases.py` move `audit_at` across each real cutoff, so the
rules are tested rather than assumed, and every case row also goes through
the contract checker. `status.selftest` tests both conditions directly
against a lookup table written in the test.

## What the review caught

A review of the branch found three real defects, all fixed here.

- `vision.ask` read an undefined name, so any cache rebuild raised
  `NameError` after the model call was already billed. The answer now comes
  from the response text blocks.
- The first attachment pattern read field values only and matched 2 support
  records. The signal sits in the field name as often as the value:
  `storage_class=ticket_attachment`, `collection_name=ticket_attachments`,
  `event=attachment_pii_scan`, `file_name=...pdf`. Reading both finds all 23
  attachments and corrects 11 submission rows, which is the only part of
  this ticket that changes `output.csv`.
- The panel merge filtered the whole group by owner, which could have
  dropped a record that names the subject together with somebody else and
  reported it absent. The merge is now additive: it starts from the records
  an identifier already reached and adds only same-file panels that name
  nobody.

One finding is left open on purpose. `evidence.vision_records` applies its
alias fallback per file instead of per record, so a file where one record
carries a prefixed `resource_id` discards the rest. That drops 6 of 11
records in evidence_28 and 4 of 7 in evidence_42, no PII among them and no
row affected today. It belongs to the evidence index, not to this ticket.
