"""The policy table: what each kind of record is, and what must happen to it.

Every resource_id carries a prefix, and the prefix fixes three things: the
system_id the answer must name, the data category in deletion_rules.csv, and
the action that policy demands. Keeping the table here means one place to
read and one place to correct.
"""

import csv
import re
from pathlib import Path

import vision

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "dataset"

# prefix -> (system_id, data_category, required_action)
# SUPPORT and ANALYTICS carry two categories each, so the category below is
# the default and the record itself decides. See resolve_category.
TABLE = {
    "account": ("account_service", "USER_PROFILE", "DELETE"),
    "search": ("search_service", "SEARCH_INDEX_ENTRY", "DELETE"),
    "cache": ("cache_service", "CACHE_ENTRY", "DELETE"),
    "export": ("export_service", "USER_EXPORT", "DELETE"),
    "marketing": ("marketing_platform", "MARKETING_PROFILE", "DELETE"),
    "object": ("object_storage", "SUPPORT_ATTACHMENT", "DELETE"),
    "support": ("support_platform", "SUPPORT_MESSAGE", "REDACT"),
    "email_delivery": ("email_delivery_service", "EMAIL_DELIVERY_LOG",
                       "REDACT"),
    "tombstone": ("identity_service", "ACCOUNT_TOMBSTONE", "REDACT"),
    "analytics": ("analytics_platform", "ANALYTICS_PROFILE", "ANONYMIZE"),
    "audit_record": ("security_service", "SECURITY_AUDIT_LOG", "RETAIN"),
    "legal_hold": ("legal_service", "LEGAL_HOLD_RECORD", "RETAIN"),
    "backup": ("backup_service", "BACKUP_ARCHIVE", "RETAIN"),
    "data_flow": ("integration_service", "DATA_FLOW", "DISABLE"),
}

SYSTEM_TO_PREFIX = {system: prefix for prefix, (system, _, _) in TABLE.items()}

# Names that evidence files use for a system, beyond the canonical one.
SYSTEM_ALIASES = {
    "profile_service": "account",
    "customer_account_service": "account",
    "account_replication_cluster": "account",
    "account_failover_replica": "account",
    "search_index_service": "search",
    "cache_service": "cache",
    "object_store": "object",
    "archive_service": "audit_record",
    "email_delivery_service": "email_delivery",
    "downstream_delivery_service": "account",
}


def prefix_of(resource_id):
    """account_5684 -> account, audit_record_7206 -> audit_record."""
    head = resource_id.rsplit("_", 1)
    if len(head) != 2 or not head[1].isdigit():
        return None
    return head[0] if head[0] in TABLE else None


def system_of(resource_id):
    prefix = prefix_of(resource_id)
    return TABLE[prefix][0] if prefix else None


def prefix_of_system(name):
    """Map a system name written in an evidence file to a prefix."""
    if name in SYSTEM_TO_PREFIX:
        return SYSTEM_TO_PREFIX[name]
    return SYSTEM_ALIASES.get(name)


# A support record is a message by default, but an attachment when the
# evidence says so. Every format says it differently: the category outright,
# a ticket_attachments collection, an attachment_pii_scan event, or a stored
# file name. rule_05 redacts the message, rule_06 deletes the attachment.
# The signal sits in the field name as often as in the value, so both are
# read.
ATTACHMENT = re.compile(
    r"attach(?:ment|ed)"
    r"|[\w.-]+\.(?:pdf|png|jpe?g|csv|txt|zip)\b", re.I)

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"], 1)}

# "25 Aug 2027 04 03 UTC", "04 May 2033", "2033-12-31T23:59:59Z".
WORD_DATE = re.compile(
    r"(\d{1,2})\s+([A-Za-z]{3})[a-z]*\s+(\d{4})"
    r"(?:\s+(\d{1,2})[\s:](\d{2}))?")
ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
USER_ID = re.compile(r"\buser_\d+\b")


def parse_date(text):
    """A date in any shape the retention documents use, as an ISO string.

    The cutoff is compared against audit_at, so a date with no clock time
    becomes the end of that day and keeps the whole day inside the window.
    """
    text = str(text)
    found = ISO_DATE.search(text)
    if found:
        return found.group(0)
    found = WORD_DATE.search(text)
    if not found or found.group(2).lower() not in MONTHS:
        return None
    day, month, year, hour, minute = found.groups()
    if hour is None:
        hour, minute, second = "23", "59", "59"
    else:
        second = "00"
    return (f"{int(year):04d}-{MONTHS[found.group(2).lower()]:02d}-"
            f"{int(day):02d}T{int(hour):02d}:{int(minute):02d}:{second}Z")


def resolve_category(prefix, fields):
    """The data category this one record belongs to.

    Two prefixes carry two categories each, and only the record itself
    says which. An unseen record keeps the prefix default. Takes the
    record's (key, value) pairs, because a field name carries the signal
    as often as a field value does.
    """
    system, category, action = TABLE[prefix]
    if prefix == "support" and any(ATTACHMENT.search(f"{k} {v}")
                                   for k, v in fields):
        return "SUPPORT_ATTACHMENT", "DELETE"
    return category, action


def conditions(cache=None):
    """The two lookup tables the retention documents supply.

    rule_12 keeps a security audit log only inside the supplied retention
    period, and rule_13 keeps a legal hold record only while the hold is
    active. Both conditions live in transcribed documents, so the tables
    are read from the transcription cache and never written down here.

    Returns (windows, holds): resource_id -> cutoff, user_id -> cutoff.
    """
    if cache is None:
        cache = vision.read_cache()
    windows, holds = {}, {}
    for entry in cache.values():
        for record in entry.get("records", []):
            fields = record.get("fields")
            if not isinstance(fields, dict):
                continue
            cutoff = next((parse_date(value) for key, value in fields.items()
                           if "retain" in key.lower()
                           and parse_date(value)), None)
            if cutoff is None:
                continue
            named = str(record.get("resource_id") or "")
            if prefix_of(named) == "audit_record":
                # A signed journal entry states its own retention period.
                windows[named] = min(cutoff, windows.get(named, cutoff))
                continue
            # Any other retained row is a hold on the subject it names.
            for value in fields.values():
                for user_id in USER_ID.findall(str(value)):
                    holds[user_id] = max(cutoff, holds.get(user_id, cutoff))
    return windows, holds


def load_rules(data_dir=DATA):
    with open(data_dir / "deletion_rules.csv", newline="",
              encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def selftest():
    rules = load_rules()
    categories = {r["data_category"] for r in rules}
    assert len(rules) == 15, len(rules)

    # Every category we name must exist in the supplied rules, and DATA_FLOW
    # is ours alone, because a flow is a process and not a record.
    mine = {cat for _, cat, _ in TABLE.values()} - {"DATA_FLOW"}
    assert mine <= categories, mine - categories

    # Both halves of the two split categories must still exist in the rules.
    assert {"SUPPORT_MESSAGE", "SUPPORT_ATTACHMENT"} <= categories
    assert {"ANALYTICS_PROFILE", "PRODUCT_TELEMETRY"} <= categories

    assert prefix_of("audit_record_7206") == "audit_record"
    assert prefix_of("account_5684") == "account"
    assert prefix_of("user_32") is None
    assert prefix_of("NST-2026-0718-1842") is None
    assert system_of("tombstone_17") == "identity_service"
    assert prefix_of_system("profile_service") == "account"
    assert prefix_of_system("privacy_case_management") is None

    assert parse_date("retain until 25 Aug 2027 04 03 UTC") == \
        "2027-08-25T04:03:00Z"
    assert parse_date("Retain until 04 May 2033") == "2033-05-04T23:59:59Z"
    assert parse_date('"retained_until":"2033-12-31T23:59:59Z"') == \
        "2033-12-31T23:59:59Z"
    assert parse_date("no date here") is None

    message = [("message_text", "hello"), ("channel", "email")]
    assert resolve_category("support", message) == \
        ("SUPPORT_MESSAGE", "REDACT")
    for shape in ([("field_3", "SUPPORT_ATTACHMENT")],
                  [("Record", "file receipt_2.pdf")],
                  [("storage_class", "ticket_attachment")],
                  [("collection_name", "ticket_attachments")],
                  [("event", "attachment_pii_scan")],
                  [("file_name", "delivery_confirmation_32.pdf")],
                  [("service", "attachment_preview")]):
        assert resolve_category("support", shape) == \
            ("SUPPORT_ATTACHMENT", "DELETE"), shape
    # The split is the support prefix alone, and a message stays a message.
    assert resolve_category("account", [("Record", "file x.pdf")]) == \
        ("USER_PROFILE", "DELETE")

    windows, holds = conditions()
    assert windows or holds, "no transcription yet: run " \
                             "`python3 code/vision.py transcribe` first"
    assert windows.get("audit_record_003") == "2027-08-25T04:03:00Z", windows
    assert holds.get("user_08") == "2033-05-04T23:59:59Z", holds
    assert len(holds) >= 6, holds
    assert "user_03" not in holds, "an audit entry is not a legal hold"

    unused = categories - mine - {"SUPPORT_ATTACHMENT", "PRODUCT_TELEMETRY",
                                  "SECONDARY_IDENTIFIER"}
    print(f"rules: {len(rules)}, prefixes: {len(TABLE)}, "
          f"categories not yet mapped: {sorted(unused)}")
    print("selftest: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(selftest())
