"""Mirror of Inbound assignee matching logic (Requirement 7.2, 7.5).

This module is part of the pure core: it imports only the standard library,
takes and returns built-in values, reads no clock and performs no I/O
(Requirement 14.1).

It extracts the email-matching logic from ``processor/utils.preprocess_task``
so that Outbound assignee resolution and inbound synchronization share
identical semantics ("last user wins" when duplicate emails exist in AYON,
case-sensitive matching).
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List


def match_assignees_by_email(
    person_emails: Iterable[str], ayon_users: Iterable[Dict[str, Any]]
) -> List[str]:
    """Match Kitsu person emails to AYON usernames (Requirement 7.2, 7.5).

    Preserves the pre-refactor matching logic of ``utils.preprocess_task``:
    - Builds an email-to-name dictionary from ``ayon_users``:
      ``{u["attrib"]["email"]: u["name"] for u in ayon_users}``.
      When multiple AYON users share the same email, the last user
      encountered overwrites earlier users ("last user wins" semantics,
      Finding F13).
    - Email comparison is exact and case-sensitive.
    - Matches person emails against the email dictionary.
    - Deduplicates person emails as a set (matching the set comprehension
      in ``preprocess_task``).
    - Unmatched emails are silently omitted.

    Args:
        person_emails: Collection of email strings from Kitsu persons.
        ayon_users: Collection of AYON user dicts with ``name`` and
            ``attrib.email``.

    Returns:
        List of matched AYON usernames.
    """
    user_map: Dict[str, str] = {}
    for user in ayon_users:
        if not isinstance(user, dict):
            continue
        attrib = user.get("attrib") or {}
        email = attrib.get("email") if isinstance(attrib, dict) else None
        name = user.get("name")
        if email and name:
            user_map[email] = str(name)

    # Deduplicate while preserving email order (Requirement 7.2)
    task_emails = list(
        dict.fromkeys(
            email
            for email in person_emails
            if email and isinstance(email, str)
        )
    )

    return [user_map[email] for email in task_emails if email in user_map]
