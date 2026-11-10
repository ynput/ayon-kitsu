"""Identity rules of the Outbound_Sync path (Requirement 3).

This module is part of the pure core: it imports only the standard
library, takes and returns built-in values and performs no I/O
(Requirement 14.1). ``IdentityResolver`` in ``identity.py`` reads the
AYON entity, the ``/kitsu-owners`` result and the Kitsu entity, and
passes them to the two functions here.

``validate_kitsu_id`` classifies the ``data.kitsuId`` value of an AYON
entity before any Kitsu call:

* ``missing``: the value is absent, ``None``, an empty string or not a
  string (Requirement 3.2). The runner skips the event.
* ``structural``: the value is exactly one of ``STRUCTURAL_KITSU_IDS`` or
  the id of a Kitsu asset type of the paired project (Requirement 3.6).
  The runner skips the event.
* ``ok``: any other string.

``validate_kitsu_target`` checks the Kitsu entity the id points to, in
this order, and returns the first failure:

1. Exactly one AYON folder, task or user carries the Kitsu id
   (Requirement 3.8).
2. The Kitsu entity kind matches the AYON entity kind: an AYON folder
   maps to a Kitsu asset, shot, sequence, episode, edit or concept, an
   AYON task to a Kitsu task and an AYON user to a Kitsu person
   (Requirement 3.7).
3. The Kitsu entity belongs to the ``kitsuProjectId`` of the
   Paired_Project (Requirement 3.5). Kitsu persons belong to no project,
   so this check does not apply to AYON users.

Every failure is final and its reason carries the ids, kinds or owners
the requirement lists. Reasons carry no ``Failed:`` prefix; the runner
adds it, as it adds ``Skipped:`` to skip reasons (Requirement 4.4).
"""

from typing import Any, Iterable, Optional

from .constants import (
    NONE_VALUE,
    SKIP_NO_KITSU_ID,
    SKIP_STRUCTURAL_FOLDER,
    STRUCTURAL_KITSU_IDS,
)

# ---------------------------------------------------------------------------
# Results of ``validate_kitsu_id``
# ---------------------------------------------------------------------------

KITSU_ID_MISSING = "missing"
KITSU_ID_STRUCTURAL = "structural"
KITSU_ID_OK = "ok"

KITSU_ID_RESULTS = (KITSU_ID_MISSING, KITSU_ID_STRUCTURAL, KITSU_ID_OK)

# ---------------------------------------------------------------------------
# AYON entity kinds and the Kitsu kinds they map to (Requirement 3.7)
# ---------------------------------------------------------------------------

AYON_KIND_FOLDER = "folder"
AYON_KIND_TASK = "task"
AYON_KIND_USER = "user"

AYON_KINDS = (AYON_KIND_FOLDER, AYON_KIND_TASK, AYON_KIND_USER)

#: Kitsu entity ``type`` values that an AYON folder may map to.
KITSU_FOLDER_KINDS = frozenset(
    ("Asset", "Shot", "Sequence", "Episode", "Edit", "Concept")
)
KITSU_TASK_KIND = "Task"
KITSU_PERSON_KIND = "Person"

#: Kitsu kinds accepted for each AYON entity kind.
KITSU_KINDS_BY_AYON_KIND = {
    AYON_KIND_FOLDER: KITSU_FOLDER_KINDS,
    AYON_KIND_TASK: frozenset((KITSU_TASK_KIND,)),
    AYON_KIND_USER: frozenset((KITSU_PERSON_KIND,)),
}

#: AYON kinds whose Kitsu counterpart belongs to a Kitsu project. Kitsu
#: persons are global, so the project check does not apply to users.
PROJECT_SCOPED_AYON_KINDS = frozenset((AYON_KIND_FOLDER, AYON_KIND_TASK))

#: Keys of the ``/kitsu-owners`` result, in description order.
OWNER_KEYS = ("folders", "tasks", "users")

# ---------------------------------------------------------------------------
# Errors and failure reasons of ``validate_kitsu_target``
# ---------------------------------------------------------------------------

TARGET_ERROR_OWNERS = "owners"
TARGET_ERROR_KIND = "kind_mismatch"
TARGET_ERROR_PROJECT = "project_mismatch"

TARGET_ERRORS = (TARGET_ERROR_OWNERS, TARGET_ERROR_KIND, TARGET_ERROR_PROJECT)

#: Requirement 3.8. Fields: ``kitsu_id``, ``entity_id``, ``count``,
#: ``owners``.
FAIL_DUPLICATE_OWNERS = (
    "Kitsu id {kitsu_id} of AYON entity {entity_id} is carried by "
    "{count} AYON entities: {owners}"
)
#: No AYON entity carries the Kitsu id any more. Fields: ``kitsu_id``,
#: ``entity_id``.
FAIL_NO_OWNER = (
    "Kitsu id {kitsu_id} of AYON entity {entity_id} is carried by no "
    "AYON entity"
)
#: Requirement 3.7. Fields: ``kitsu_id``, ``entity_id``, ``ayon_kind``,
#: ``kitsu_kind``, ``expected``.
FAIL_KIND_MISMATCH = (
    "Kitsu entity {kitsu_id} is a {kitsu_kind}, which does not match AYON "
    "{ayon_kind} {entity_id} (expected {expected})"
)
#: Requirement 3.5. Fields: ``kitsu_id``, ``entity_id``,
#: ``kitsu_project_id``, ``paired_project_id``.
FAIL_PROJECT_MISMATCH = (
    "Kitsu entity {kitsu_id} of AYON entity {entity_id} belongs to Kitsu "
    "project {kitsu_project_id}, not to the paired Kitsu project "
    "{paired_project_id}"
)


def _text(value: Any) -> str:
    """Return a printable form of an id or kind.

    Args:
        value: Any value.

    Returns:
        ``"none"`` for ``None`` or an empty string, otherwise ``str(value)``.
    """
    if value is None or value == "":
        return NONE_VALUE
    return str(value)


def validate_kitsu_id(
    kitsu_id: Any,
    entity_id: str,
    asset_type_ids: Optional[Iterable[str]] = None,
) -> dict:
    """Classify the ``data.kitsuId`` value of an AYON entity.

    The comparison with the structural ids is exact and case sensitive,
    with no stripping, so ``" shot"`` or ``"Shot"`` is an ordinary id.

    Args:
        kitsu_id: Value stored under ``data.kitsuId``. Callers pass
            ``None`` when the key is absent.
        entity_id: AYON id of the folder or task, used in the skip reason.
        asset_type_ids: Ids of the Kitsu asset types of the paired Kitsu
            project. Non-string members are ignored.

    Returns:
        ``{"result": "missing" | "structural" | "ok", "kitsu_id": str |
        None, "reason": str | None}``. ``kitsu_id`` is the valid string
        (also for ``structural``) or ``None`` for ``missing``. ``reason``
        is the skip reason for ``missing`` and ``structural`` (without the
        ``Skipped:`` prefix) and ``None`` for ``ok``.
    """
    if not isinstance(kitsu_id, str) or kitsu_id == "":
        return {
            "result": KITSU_ID_MISSING,
            "kitsu_id": None,
            "reason": SKIP_NO_KITSU_ID.format(entity_id=_text(entity_id)),
        }

    asset_types = {
        type_id
        for type_id in (asset_type_ids or ())
        if isinstance(type_id, str)
    }
    if kitsu_id in STRUCTURAL_KITSU_IDS or kitsu_id in asset_types:
        return {
            "result": KITSU_ID_STRUCTURAL,
            "kitsu_id": kitsu_id,
            "reason": SKIP_STRUCTURAL_FOLDER.format(
                entity_id=_text(entity_id), kitsu_id=kitsu_id
            ),
        }

    return {"result": KITSU_ID_OK, "kitsu_id": kitsu_id, "reason": None}


def _owner_list(owners: Any) -> list[tuple[str, str]]:
    """Flatten the ``/kitsu-owners`` result into ``(key, owner)`` pairs.

    Duplicate owners under the same key count once. The order of each
    list is kept.

    Args:
        owners: ``{"folders": [ids], "tasks": [ids], "users": [names]}``,
            or a plain list of owner ids. Missing keys count as empty and
            ``None`` counts as no owner.

    Returns:
        ``(key, owner)`` pairs; the key is ``""`` for a plain list.
    """
    if owners is None:
        return []
    if isinstance(owners, dict):
        groups = [(key, owners.get(key) or ()) for key in OWNER_KEYS]
    else:
        groups = [("", owners)]

    result = []
    seen = set()
    for key, values in groups:
        for value in values:
            pair = (key, str(value))
            if pair not in seen:
                seen.add(pair)
                result.append(pair)
    return result


def _describe_owners(pairs: list[tuple[str, str]]) -> str:
    """Return every owner id, grouped by kind, for a failure reason.

    Args:
        pairs: Result of ``_owner_list``.

    Returns:
        For example ``"folders f1, f2; tasks t1"``.
    """
    parts = []
    for key in OWNER_KEYS + ("",):
        ids = [owner for owner_key, owner in pairs if owner_key == key]
        if ids:
            joined = ", ".join(ids)
            parts.append(f"{key} {joined}" if key else joined)
    return "; ".join(parts)


def _fail(error: str, reason: str) -> dict:
    """Build a failed ``validate_kitsu_target`` result.

    Args:
        error: One of ``TARGET_ERRORS``.
        reason: Failure reason without the ``Failed:`` prefix.

    Returns:
        ``{"ok": False, "error": error, "reason": reason}``.
    """
    return {"ok": False, "error": error, "reason": reason}


def validate_kitsu_target(
    ayon_kind: str,
    entity_id: str,
    kitsu_id: str,
    kitsu_entity: dict,
    kitsu_project_id: Optional[str],
    owners: Any,
) -> dict:
    """Check that the Kitsu entity is a valid target for the AYON entity.

    The checks run in the order owners, kind, project, and the first
    failure is returned. Every failure is final (Requirements 3.5, 3.7,
    3.8).

    Args:
        ayon_kind: ``"folder"``, ``"task"`` or ``"user"``. Any other value
            matches no Kitsu kind.
        entity_id: AYON id of the folder or task, or the AYON user name.
        kitsu_id: Kitsu id read from the AYON entity data.
        kitsu_entity: Kitsu entity with at least ``type`` (``"Task"``,
            ``"Shot"``, ``"Sequence"``, ``"Episode"``, ``"Asset"``,
            ``"Edit"``, ``"Concept"`` or ``"Person"``) and, for folders and
            tasks, ``project_id``.
        kitsu_project_id: ``data.kitsuProjectId`` of the Paired_Project.
            Not used for users.
        owners: Every AYON entity carrying ``kitsu_id``, in the
            ``/kitsu-owners`` shape ``{"folders": [...], "tasks": [...],
            "users": [...]}`` or as a plain list of ids.

    Returns:
        ``{"ok": True, "error": None, "reason": None}``, or ``{"ok":
        False, "error": "owners" | "kind_mismatch" | "project_mismatch",
        "reason": str}``. The reason contains the Kitsu id and the AYON
        entity id, and also every owner, both kinds or both Kitsu project
        ids.
    """
    entity_text = _text(entity_id)
    kitsu_text = _text(kitsu_id)

    # 1. Exactly one AYON owner (Requirement 3.8).
    pairs = _owner_list(owners)
    if not pairs:
        return _fail(
            TARGET_ERROR_OWNERS,
            FAIL_NO_OWNER.format(kitsu_id=kitsu_text, entity_id=entity_text),
        )
    if len(pairs) > 1:
        return _fail(
            TARGET_ERROR_OWNERS,
            FAIL_DUPLICATE_OWNERS.format(
                kitsu_id=kitsu_text,
                entity_id=entity_text,
                count=len(pairs),
                owners=_describe_owners(pairs),
            ),
        )

    # 2. Kind match (Requirement 3.7).
    entity = kitsu_entity if isinstance(kitsu_entity, dict) else {}
    kitsu_kind = entity.get("type")
    allowed = KITSU_KINDS_BY_AYON_KIND.get(ayon_kind, frozenset())
    if kitsu_kind not in allowed:
        expected = " or ".join(sorted(allowed)) if allowed else NONE_VALUE
        return _fail(
            TARGET_ERROR_KIND,
            FAIL_KIND_MISMATCH.format(
                kitsu_id=kitsu_text,
                entity_id=entity_text,
                ayon_kind=_text(ayon_kind),
                kitsu_kind=_text(kitsu_kind),
                expected=expected,
            ),
        )

    # 3. Project match (Requirement 3.5). Persons belong to no project.
    if ayon_kind in PROJECT_SCOPED_AYON_KINDS:
        entity_project_id = entity.get("project_id")
        if (
            not isinstance(kitsu_project_id, str)
            or kitsu_project_id == ""
            or entity_project_id != kitsu_project_id
        ):
            return _fail(
                TARGET_ERROR_PROJECT,
                FAIL_PROJECT_MISMATCH.format(
                    kitsu_id=kitsu_text,
                    entity_id=entity_text,
                    kitsu_project_id=_text(entity_project_id),
                    paired_project_id=_text(kitsu_project_id),
                ),
            )

    return {"ok": True, "error": None, "reason": None}


__all__ = (
    "AYON_KINDS",
    "AYON_KIND_FOLDER",
    "AYON_KIND_TASK",
    "AYON_KIND_USER",
    "FAIL_DUPLICATE_OWNERS",
    "FAIL_KIND_MISMATCH",
    "FAIL_NO_OWNER",
    "FAIL_PROJECT_MISMATCH",
    "KITSU_FOLDER_KINDS",
    "KITSU_ID_MISSING",
    "KITSU_ID_OK",
    "KITSU_ID_RESULTS",
    "KITSU_ID_STRUCTURAL",
    "KITSU_KINDS_BY_AYON_KIND",
    "KITSU_PERSON_KIND",
    "KITSU_TASK_KIND",
    "OWNER_KEYS",
    "PROJECT_SCOPED_AYON_KINDS",
    "TARGET_ERRORS",
    "TARGET_ERROR_KIND",
    "TARGET_ERROR_OWNERS",
    "TARGET_ERROR_PROJECT",
    "validate_kitsu_id",
    "validate_kitsu_target",
)
