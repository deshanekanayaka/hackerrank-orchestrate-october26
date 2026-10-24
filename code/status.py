"""Stages 3 to 5: decide each state, apply the policy, write the steps.

The state of a resource at audit_at comes from the newest evidence captured
at or before audit_at. Reported statuses and operation results are claims and
never set a state. The required action comes from policy.TABLE. A resource
whose state matches its required action yields one verification step. A
resource that breaks it yields a finding, a fix, and a verification step.
"""

import identity
import evidence
import policy

# A state written in words. Evidence files say these outright, and an
# explicit word beats any guess from the record's shape.
WORD_STATE = {
    "not_found": "ABSENT", "absent": "ABSENT", "deleted": "ABSENT",
    "removed": "ABSENT", "miss": "ABSENT", "no_record": "ABSENT",
    "purged": "ABSENT",
    "identifiable": "PRESENT", "found": "PRESENT", "present": "PRESENT",
    "hit": "PRESENT", "exposed": "PRESENT",
    "redacted": "REDACTED", "anonymized": "ANONYMIZED",
    "active": "ACTIVE", "enabled": "ACTIVE",
    "disabled": "DISABLED", "stopped": "DISABLED",
    "blocked": "BLOCKED",
}
# States that only a process can report.
PROCESS_STATES = {"ACTIVE", "DISABLED", "BLOCKED"}

PHASE_ORDER = ["FINDING", "REMEDIATION", "VERIFICATION"]
OP_ORDER = {
    "FINDING": ["REPORT_REMAINING_RECORD", "REPORT_EXPOSED_PII",
                "REPORT_ACTIVE_DATA_FLOW", "REPORT_RESTORE_RISK"],
    "REMEDIATION": ["DISABLE_DATA_FLOW", "BLOCK_RESTORE", "DELETE_RECORD",
                    "REDACT_RECORD", "ANONYMIZE_RECORD"],
    "VERIFICATION": ["VERIFY_RECORD_ABSENT", "VERIFY_RECORD_PRESENT",
                     "VERIFY_RECORD_REDACTED", "VERIFY_RECORD_ANONYMIZED",
                     "VERIFY_DATA_FLOW_DISABLED", "VERIFY_RESTORE_BLOCKED"],
}
STATE_OF_OP = {
    "REPORT_REMAINING_RECORD": "PRESENT", "REPORT_EXPOSED_PII": "PRESENT",
    "REPORT_ACTIVE_DATA_FLOW": "ACTIVE", "REPORT_RESTORE_RISK": "ACTIVE",
    "DISABLE_DATA_FLOW": "DISABLED", "BLOCK_RESTORE": "BLOCKED",
    "DELETE_RECORD": "ABSENT", "REDACT_RECORD": "REDACTED",
    "ANONYMIZE_RECORD": "ANONYMIZED",
    "VERIFY_RECORD_ABSENT": "ABSENT", "VERIFY_RECORD_PRESENT": "PRESENT",
    "VERIFY_RECORD_REDACTED": "REDACTED",
    "VERIFY_RECORD_ANONYMIZED": "ANONYMIZED",
    "VERIFY_DATA_FLOW_DISABLED": "DISABLED",
    "VERIFY_RESTORE_BLOCKED": "BLOCKED",
}


def truthy(value):
    return str(value).strip().lower() in {"true", "1", "yes", "enabled"}


def falsy(value):
    return str(value).strip().lower() in {"false", "0", "no", "disabled",
                                          "stopped", "blocked"}


def exposes_identifier(obs, directory, user_id):
    """Does this record still carry a direct identifier of the subject?

    The stable user_id is not a direct identifier: a tombstone and a retained
    record are allowed to keep it. Field names vary by format, and a log line
    has no names at all, so the values are what we test.
    """
    direct = {v for v in directory.identifiers_of(user_id) if v != user_id}
    for _, value in obs.fields:
        if len(value) > 200:
            continue
        if value.strip().lower() in direct:
            return True
        if directory.owners_of(value) == frozenset({user_id}) \
                and value.strip().lower() != user_id:
            return True
    return False


def stated_state(obs, prefix=None):
    """The state this record states in words or in a status field.

    account_status says what happened to the account, not to the record
    holding it, so a tombstone that reads DELETED is still present.
    """
    for key, value in obs.fields:
        low, text = key.lower(), str(value).strip().lower()
        if low in ("status_code", "http_status") and text in ("404", "410"):
            return "ABSENT"
        if low in ("rows", "total", "hits.total") and text == "0":
            return "ABSENT"
        if low in ("rows", "total", "hits.total") and text.isdigit():
            return "PRESENT"
    for key, value in obs.fields:
        if key.lower() == "account_status" and prefix != "account":
            continue
        word = WORD_STATE.get(str(value).strip().lower())
        if word:
            return word
    return None


def state_of(obs, prefix, directory, user_id):
    """The state this one observation reports."""
    stated = stated_state(obs, prefix)
    if prefix == "data_flow":
        enabled = obs.get("enabled")
        if enabled is not None:
            return "ACTIVE" if truthy(enabled) else "DISABLED"
        return stated if stated in PROCESS_STATES else "ACTIVE"
    if prefix == "backup":
        allowed = obs.get("restore_allowed")
        if allowed is not None:
            return "ACTIVE" if truthy(allowed) else "BLOCKED"
        if stated in ("DISABLED", "BLOCKED"):
            return "BLOCKED"
        return "ACTIVE"
    if stated in ("ABSENT", "REDACTED", "ANONYMIZED"):
        return stated
    if stated == "PRESENT" and exposes_identifier(obs, directory, user_id):
        return "PRESENT"
    if exposes_identifier(obs, directory, user_id):
        return "PRESENT"
    action = policy.TABLE[prefix][2]
    if stated == "PRESENT" and action in ("REDACT", "ANONYMIZE"):
        # Seen, but with no direct identifier left on it.
        return "REDACTED" if action == "REDACT" else "ANONYMIZED"
    if action == "ANONYMIZE":
        return "ANONYMIZED"
    if action == "REDACT":
        return "REDACTED"
    return "PRESENT"


def resource_states(index, directory, user_id, audit_at,
                    since=None):
    """One state per resource, from the newest usable observation."""
    out = {}
    owned = index.resources_of(user_id, audit_at, since)
    # Newest file per resource, then every record of that resource in that
    # file merged: a readback trace writes the lookup on one line and its
    # result on the next, and only the pair states the whole truth.
    newest, groups = {}, {}
    for obs in index.for_user(user_id, audit_at, since):
        if obs.captured_at >= newest.get(obs.resource_id, ""):
            newest[obs.resource_id] = obs.captured_at
    for obs in index.for_user(user_id, audit_at, since):
        if obs.captured_at == newest[obs.resource_id]:
            groups.setdefault(obs.resource_id, []).append(obs)
    seen = {}
    for resource, group in groups.items():
        merged = dict()
        for obs in sorted(group, key=lambda o: o.observed_at):
            merged.update(dict(obs.fields))
        head = group[0]
        seen[resource] = (None, evidence.Observation(
            head.file_id, head.captured_at, head.observed_at, head.system_id,
            resource, head.source, tuple(sorted(merged.items())),
            frozenset().union(*(o.owners for o in group)), head.raw))
    for resource, files in owned.items():
        prefix = policy.prefix_of(resource)
        if not prefix:
            continue
        entry = seen.get(resource)
        if entry is None:
            # Referenced but never seen: the record is gone, as long as some
            # file looked at that system in time.
            if index.files_covering(policy.TABLE[prefix][0], audit_at):
                out[resource] = ("ABSENT", None, files)
            continue
        obs = entry[1]
        out[resource] = (state_of(obs, prefix, directory, user_id), obs, files)
    return out


def cite(index, resource, state, obs, files, audit_at):
    """The newest file at or before audit_at that proves this step."""
    if state == "ABSENT":
        covering = index.files_covering(policy.system_of(resource), audit_at)
        return covering[0] if covering else ""
    usable = [(index.manifest[f]["captured_at"], f) for f in files
              if index.manifest[f]["captured_at"] <= audit_at]
    if obs is not None and obs.file_id in files:
        usable.append((obs.captured_at, obs.file_id))
    return max(usable)[1] if usable else ""


def plan(index, directory, user_id, audit_at, since=None):
    """Build the ordered steps for one audited case."""
    states = resource_states(index, directory, user_id, audit_at,
                             since)
    findings, fixes, proofs = [], [], []

    for resource, (state, obs, files) in states.items():
        prefix = policy.prefix_of(resource)
        system = policy.TABLE[prefix][0]
        action = policy.TABLE[prefix][2]
        evidence_id = cite(index, resource, state, obs, files, audit_at)
        here = (system, resource, evidence_id)

        if action == "DELETE":
            if state == "ABSENT":
                proofs.append(("VERIFY_RECORD_ABSENT",) + here)
            else:
                findings.append(("REPORT_REMAINING_RECORD",) + here)
                fixes.append(("DELETE_RECORD", system, resource, ""))
                proofs.append(("VERIFY_RECORD_ABSENT", system, resource, ""))
        elif action in ("REDACT", "ANONYMIZE"):
            done = "REDACTED" if action == "REDACT" else "ANONYMIZED"
            verify = ("VERIFY_RECORD_REDACTED" if action == "REDACT"
                      else "VERIFY_RECORD_ANONYMIZED")
            if state == done:
                proofs.append((verify,) + here)
            elif state == "ABSENT":
                proofs.append(("VERIFY_RECORD_ABSENT",) + here)
            else:
                findings.append(("REPORT_EXPOSED_PII",) + here)
                fixes.append((f"{action}_RECORD", system, resource, ""))
                proofs.append((verify, system, resource, ""))
        elif prefix == "data_flow":
            if state == "ACTIVE":
                findings.append(("REPORT_ACTIVE_DATA_FLOW",) + here)
                fixes.append(("DISABLE_DATA_FLOW", system, resource, ""))
                proofs.append(("VERIFY_DATA_FLOW_DISABLED", system, resource,
                               ""))
            else:
                proofs.append(("VERIFY_DATA_FLOW_DISABLED",) + here)
        elif prefix == "backup":
            if state == "ACTIVE":
                findings.append(("REPORT_RESTORE_RISK",) + here)
                fixes.append(("BLOCK_RESTORE", system, resource, ""))
                proofs.append(("VERIFY_RESTORE_BLOCKED", system, resource, ""))
            else:
                proofs.append(("VERIFY_RESTORE_BLOCKED",) + here)
        elif action == "RETAIN":
            if state != "ABSENT":
                proofs.append(("VERIFY_RECORD_PRESENT",) + here)

    status = "INCOMPLETE" if findings else "COMPLETE"
    if status == "INCOMPLETE":
        # Future work cites nothing.
        proofs = [(op, system, resource, "") for op, system, resource, _
                  in proofs]
    steps = []
    for phase, group in (("FINDING", findings), ("REMEDIATION", fixes),
                         ("VERIFICATION", proofs)):
        order = OP_ORDER[phase]
        for op, system, resource, evidence_id in sorted(
                group, key=lambda row: (order.index(row[0]), row[1], row[2])):
            steps.append({
                "step_no": len(steps) + 1,
                "phase": phase,
                "system_id": system,
                "resource_id": resource,
                "operation": op,
                "state": STATE_OF_OP[op],
                "evidence_id": evidence_id,
            })
    if not steps:
        status = "COMPLETE"
    return status, steps


def selftest():
    directory = identity.load()
    index = evidence.build(directory)
    # The worked example: six resources, four of them wrong.
    status, steps = plan(index, directory, "user_32", "2026-10-01T12:00:00Z")
    assert status == "INCOMPLETE", status
    assert len(steps) == 14, len(steps)
    assert steps[0]["resource_id"] == "search_052", steps[0]
    assert steps[4]["operation"] == "DISABLE_DATA_FLOW", steps[4]
    assert steps[8]["resource_id"] == "account_4248", steps[8]
    assert all(s["evidence_id"] == "" for s in steps[4:]), "future work cites"
    print("selftest: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(selftest())
