"""Subject resolution and the Subject's Identifier set.

Ticket #2 resolves the request email against current identities only; history
from ``user_audit_log.csv`` is added by the identity-history ticket.
"""

from collections import namedtuple

Subject = namedtuple("Subject", "user_id identifiers")


def normalize(value):
    """Canonical form used for every identifier comparison."""
    return str(value).strip().lower()


def resolve_subject(email, dataset):
    """Return the Subject whose email matches ``email``, or None."""
    wanted = normalize(email)
    for row in dataset.identities:
        if normalize(row["email"]) == wanted:
            return Subject(row["user_id"], identifier_set(row, dataset))
    return None


def identifier_owners(dataset):
    """{normalized identifier: set(user_id)} over every known identity."""
    owners = {}
    for row in dataset.identities:
        for token in identifier_set(row, dataset):
            owners.setdefault(token, set()).add(row["user_id"])
    return owners


def identifier_set(identity_row, dataset):
    """Normalized identifiers that attribute a Resource to the Subject.

    Names are left out on purpose: decoy records share names, so a name alone
    never attributes a Resource.
    """
    values = {identity_row["user_id"], identity_row["email"], identity_row["phone"],
              identity_row["email_hash"]}
    return frozenset(normalize(v) for v in values if v)
