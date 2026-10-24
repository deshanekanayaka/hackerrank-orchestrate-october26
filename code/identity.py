"""Stage 1: turn one request email into the person behind it.

A request carries a single email. That email can be an address the person
gave up years ago, and older systems still hold the older address. So each
subject gets an identifier universe: every exact string that ever pointed at
them, from the current snapshot and from the audit log.

    python3 code/identity.py selftest
    python3 code/identity.py resolve someone@example.com
"""

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "dataset"

# Audit-log fields that carry an identifier. There is no name change in the
# data, and a name is never used for matching anyway.
IDENTIFIER_FIELDS = {"email", "email_hash", "phone"}


def norm_email(value):
    return value.strip().lower()


def norm_phone(value):
    """Phone numbers appear with spaces, with hyphens, or with both.

    A value with no digit is not a phone number, and returning "+" for one
    would let any text match a subject whose phone is blank.
    """
    digits = "".join(ch for ch in value if ch.isdigit())
    return "+" + digits if digits else ""


def norm_hash(value):
    return value.strip().lower()


NORMALIZERS = {"email": norm_email, "phone": norm_phone,
               "email_hash": norm_hash}


class Directory:
    """Every subject, every identifier they ever had, both ways round."""

    def __init__(self, users, universe, current, by_identifier):
        self.users = users                  # user_id -> snapshot row
        self.universe = universe            # user_id -> {normalized string}
        self.current = current              # user_id -> {field: normalized}
        self.by_identifier = by_identifier  # normalized string -> {user_id}

    def identifiers_of(self, user_id):
        return self.universe[user_id]

    def owners_of(self, value, field=None):
        """Subjects that ever held this exact value."""
        for norm in ([NORMALIZERS[field]] if field else NORMALIZERS.values()):
            owners = self.by_identifier.get(norm(value))
            if owners:
                return owners
        return frozenset()

    def resolve(self, value, field=None):
        """The one subject this value belongs to, or None.

        No identifier in this dataset is held by two subjects, which `load`
        asserts, so a hit is always unambiguous.
        """
        owners = self.owners_of(value, field)
        return next(iter(owners)) if len(owners) == 1 else None

    def resolved_through(self, value, user_id):
        """'current' when the snapshot still shows this value, else 'history'."""
        if any(NORMALIZERS[f](value) == v
               for f, v in self.current[user_id].items() if f in NORMALIZERS):
            return "current"
        return "history"


def load(data_dir=DATA):
    users, universe, current = {}, {}, {}
    by_identifier = {}

    def add(user_id, field, raw):
        value = NORMALIZERS[field](raw)
        if not value:
            return
        universe[user_id].add(value)
        by_identifier.setdefault(value, set()).add(user_id)

    with open(data_dir / "user_identities.csv", newline="",
              encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            uid = row["user_id"]
            if uid in users:
                raise ValueError(f"duplicate user_id {uid}")
            users[uid] = row
            universe[uid] = set()
            current[uid] = {f: NORMALIZERS[f](row[f])
                            for f in IDENTIFIER_FIELDS}
            universe[uid].add(uid)
            by_identifier.setdefault(uid, set()).add(uid)
            for field in IDENTIFIER_FIELDS:
                add(uid, field, row[field])

    with open(data_dir / "user_audit_log.csv", newline="",
              encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            uid, field = row["user_id"], row["field_name"]
            if uid not in users:
                raise ValueError(f"audit log names unknown {uid}")
            if field not in IDENTIFIER_FIELDS:
                continue
            for key in ("old_value", "new_value"):
                if row[key]:
                    add(uid, field, row[key])

    shared = {v: o for v, o in by_identifier.items() if len(o) > 1}
    if shared:
        raise ValueError(f"{len(shared)} identifiers are held by two "
                         f"subjects, for example {sorted(shared)[:3]}")

    return Directory(users, {u: frozenset(v) for u, v in universe.items()},
                     current,
                     {k: frozenset(v) for k, v in by_identifier.items()})


def selftest():
    d = load()
    assert len(d.users) == 850, len(d.users)

    # Every identifier is reachable both ways round.
    for uid in d.users:
        for value in d.identifiers_of(uid):
            assert uid in d.by_identifier[value]

    # A request email must land on exactly one subject, whether it is the
    # address the person holds now or one they held years ago.
    for name in ("deletion_requests.csv", "sample_deletion_requests.csv"):
        with open(DATA / name, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        unresolved = [r["case_id"] for r in rows
                      if d.resolve(r["email"], "email") is None]
        assert not unresolved, f"{name}: {unresolved[:5]}"
        through = {}
        for r in rows:
            uid = d.resolve(r["email"], "email")
            through[d.resolved_through(r["email"], uid)] = through.get(
                d.resolved_through(r["email"], uid), 0) + 1
        print(f"{name}: {len(rows)} cases, resolved {through}")

    # Capital letters in a request must not matter.
    assert d.resolve("NOVAK.TOMASZ@ICLOUD.COM", "email") == "user_32"
    # A look-alike address belongs to nobody.
    assert d.resolve("karim.elmasri@gmail.com", "email") is None
    # A surname is never an identifier, through any normalizer.
    assert d.resolve("El-Masri", "email") is None
    assert d.resolve("El-Masri") is None
    assert norm_phone("El-Masri") == ""
    # Phone punctuation must not matter.
    row = d.users["user_32"]
    assert d.resolve(row["phone"].replace(" ", "-"), "phone") == "user_32"
    # The stable id resolves to itself, which is how records that carry no
    # email still reach their subject.
    assert d.resolve("user_32") == "user_32"
    assert row["email_hash"] in d.identifiers_of("user_32")

    print(f"identifiers: {len(d.by_identifier)}, none shared")
    print("selftest: PASS")
    return 0


def main(argv):
    if argv and argv[0] == "selftest":
        return selftest()
    if len(argv) == 2 and argv[0] == "resolve":
        d = load()
        uid = d.resolve(argv[1])
        if uid is None:
            print("no subject holds that value")
            return 1
        print(uid, d.users[uid]["name"], d.resolved_through(argv[1], uid))
        print("universe:", ", ".join(sorted(d.identifiers_of(uid))))
        return 0
    raise SystemExit(__doc__)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
