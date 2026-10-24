# Ghost Data Still Exists: deletion audit

This context covers the deletion audit agent for the HackerRank Orchestrate
challenge. The agent decides, for each request, whether a person's personal
data is really gone, and what must happen next.

## Language

**Case**:
One row of `deletion_requests.csv`, and one row of `output.csv`. The unit of
work. Two cases can share an email, so a case is never keyed by email.
_Avoid_: Request, ticket, row.

**Subject**:
The person whose data the case concerns, identified by the stable `user_id`.
_Avoid_: User, customer, account.

**Identifier**:
One exact string that points at a subject: a `user_id`, an email address, a
phone number, or an `email_hash`.
_Avoid_: PII, key, personal data.

**Identifier universe**:
Every identifier a subject ever had. It is the current row of
`user_identities.csv` plus every `old_value` and `new_value` for that subject
in `user_audit_log.csv`.
_Avoid_: Aliases, history.

**Resource**:
One record or one process in one system, named by a `resource_id`. The prefix
of the `resource_id` fixes both the `system_id` and the data category.
_Avoid_: Record, row, object, entity.

**Link**:
The proof that a resource belongs to a subject. A link exists only when an
identifier appears exactly inside the resource, or when a
`LINK_RESOURCE_IDENTITY` activity row states the link.
_Avoid_: Match, hit.

**Claim**:
A reported value that the agent must not trust: `reported_status` in a
request, and `reported_result` in an activity row.
_Avoid_: Status, result.

**Observation**:
A resource as one evidence file shows it at one capture time. An observation
carries a state and a `file_id`.
_Avoid_: Snapshot, sighting.

**State**:
The condition of a resource at `audit_at`, taken from the newest observation
at or before `audit_at`. One of `PRESENT`, `ABSENT`, `REDACTED`,
`ANONYMIZED`, `ACTIVE`, `DISABLED`, or `BLOCKED`.
_Avoid_: Status, condition.

**Required action**:
The treatment `deletion_rules.csv` demands for a resource's data category:
`DELETE`, `REDACT`, `ANONYMIZE`, or `RETAIN`.
_Avoid_: Policy, rule, treatment.

**Violation**:
A resource whose state at `audit_at` does not match its required action. One
violation anywhere makes the case `INCOMPLETE`.
_Avoid_: Issue, failure, gap.

**Drift**:
The condition where one copy of a system still holds data that another copy
no longer holds, for example a regional replica against the primary.
_Avoid_: Lag, inconsistency.

**Intent**:
What the request text actually asks for. Only a deletion intent starts an
audit. Any other intent gives `NOT_APPLICABLE` and an empty step list.
_Avoid_: Type, category, kind.

**Decoy**:
A record, identity, or activity row that belongs to nobody in the case set,
or to a look-alike identity. 333 of the 850 identities are decoys.
_Avoid_: Noise, distractor.
