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

**Status:** ready-for-agent

- [ ] The five cases live as a small request CSV plus an expected-answer CSV
- [ ] The same scorer scores them, and the command is written in the report
- [ ] The report states the sample numbers and the extra-case numbers apart
- [ ] The report records the measured linking ceiling and the four candidate
      rules tested and rejected
- [ ] The report lists the failures the samples caught and the fix for each
