# 03: Five extra evaluation cases and the evaluation report

**What to build:** `evaluation/evaluation_report.md`, written from real
scorer output, not from memory. It carries case-level status accuracy,
step-level and field-level accuracy, sequence accuracy, the five evaluation
cases we wrote ourselves, and the failures found with the fixes made. The
five cases cover shapes the 32 samples never show: a non-deletion request
that uses deletion words inside a refusal, a tombstone that is already
correctly redacted, a record absent from the primary but alive in a regional
replica, a security audit log inside its retention window, and an active sync
flow that recreates a record after a successful delete.

**Blocked by:** 01, 02.

**Status:** done

- [x] The five cases live as a small request CSV plus an expected-answer CSV
      (`evaluation/cases/requests.csv`, `evaluation/cases/expected.csv`)
- [x] The same scorer scores them, and the command is written in the report
- [x] The report states the sample numbers and the extra-case numbers apart
- [x] The report records the measured linking ceiling and the four candidate
      rules tested and rejected (five were tested, all rejected)
- [x] The report lists the failures the samples caught and the fix for each

## What shipped

`code/evaluation/ceiling.py` measures the recall limit the evidence index
imposes. 159 of the 193 sample truth steps name a resource the index links
inside the case window, so the recall limit is 0.824 against a measured
0.793. All 34 unreachable steps are verification steps and none is a
finding, so the limit costs recall and never costs a case status.

`code/evaluation/experiments.py` runs five candidate rules as single changes
to the shipped pipeline and scores each against the 32 samples. All five are
rejected, with the numbers in the report.

`code/main.py` gained `--requests PATH`, so the shipped entry point runs any
request file in the same shape. That is how the five extra cases run.

## The rejection worth remembering

Candidate 5 raises status accuracy from 31 of 32 to 32 of 32, so a score
table alone accepts it. A step-level comparison shows that it adds 2 steps
to case_10 and both are wrong. It buys the last status point with two wrong
steps. That is why the report quotes step accuracy beside status accuracy in
every section.

## Known failure left open

case_10 predicts COMPLETE and the truth is INCOMPLETE. The record is
support_002 in evidence_61, a replica log. One line reports rows=1 and the
next reports marker_found=false. The pipeline reads the row count as
presence, finds no identifier in the line, and calls the record adequately
redacted. A log line never prints the record body, so the missing identifier
proves nothing. The real fix needs a signal this file does not carry, so the
case is recorded in the report rather than patched.
