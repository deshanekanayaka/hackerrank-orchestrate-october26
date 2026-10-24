"""The policy table: what each kind of record is, and what must happen to it.

Every resource_id carries a prefix, and the prefix fixes three things: the
system_id the answer must name, the data category in deletion_rules.csv, and
the action that policy demands. Keeping the table here means one place to
read and one place to correct.
"""

import csv
from pathlib import Path

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

    unused = categories - mine - {"SUPPORT_ATTACHMENT", "PRODUCT_TELEMETRY",
                                  "SECONDARY_IDENTIFIER"}
    print(f"rules: {len(rules)}, prefixes: {len(TABLE)}, "
          f"categories not yet mapped: {sorted(unused)}")
    print("selftest: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(selftest())
