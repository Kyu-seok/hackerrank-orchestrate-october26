"""Subject resolution and the Subject's Identifier set.

The request email may be the Subject's current email or one they used before:
``user_audit_log.csv`` records every change of email, email hash and phone. The
Identifier set joins the current identity with every historical value, so a
ghost copy still carrying an old email or its hash is attributed to the Subject.
"""

import weakref
from collections import namedtuple

Subject = namedtuple("Subject", "user_id identifiers")


def normalize(value):
    """Canonical form used for every identifier comparison."""
    return str(value).strip().lower()


def resolve_subject(email, dataset):
    """Return the Subject whose current or historical email matches ``email``, or None.

    A current email wins over a historical one, so an address that was later
    taken by someone else resolves to its present owner.
    """
    wanted = normalize(email)
    for row in dataset.identities:
        if normalize(row["email"]) == wanted:
            return Subject(row["user_id"], identifier_set(row["user_id"], dataset))
    for row in dataset.audit_log:
        if row["field_name"] == "email" and normalize(row["old_value"]) == wanted:
            return Subject(row["user_id"], identifier_set(row["user_id"], dataset))
    return None


def identifier_owners(dataset):
    """{normalized identifier: set(user_id)} over every known identity."""
    owners = {}
    for row in dataset.identities:
        for token in identifier_set(row["user_id"], dataset):
            owners.setdefault(token, set()).add(row["user_id"])
    return owners


def identifier_set(user_id, dataset):
    """Normalized identifiers that attribute a Resource to the Subject: the
    ``user_id`` plus every current and historical email, phone and email hash.

    Names are left out on purpose: decoy records share names, so a name alone
    never attributes a Resource.
    """
    sets = _IDENTIFIER_SETS.get(dataset)
    if sets is None:
        sets = _IDENTIFIER_SETS[dataset] = _all_identifier_sets(dataset)
    return sets.get(user_id, frozenset({normalize(user_id)}))


_IDENTIFIER_SETS = weakref.WeakKeyDictionary()  # Dataset -> {user_id: Identifier set}


def _all_identifier_sets(dataset):
    values = {}
    for row in dataset.identities:
        values.setdefault(row["user_id"], set()).update(
            (row["user_id"], row["email"], row["phone"], row["email_hash"]))
    for row in dataset.audit_log:
        values.setdefault(row["user_id"], set()).update((row["old_value"], row["new_value"]))
    return {uid: frozenset(normalize(v) for v in vals if v) for uid, vals in values.items()}
