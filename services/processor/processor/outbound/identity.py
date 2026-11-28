"""Identity resolution for Outbound_Sync (Task 8.4).

Resolves target Kitsu entities from AYON entity kitsuId at processing time.
Validates: Requirements 3.1, 3.2, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 4.10.
"""

from typing import Any, Dict, Iterable, Optional

from .constants import (
    ERROR_NOT_FOUND,
    ERROR_SERVER_ERROR,
    ERROR_UNREACHABLE,
    SKIP_ENTITY_GONE,
)
from .identity_rules import (
    AYON_KIND_FOLDER,
    AYON_KIND_TASK,
    AYON_KIND_USER,
    KITSU_ID_OK,
    validate_kitsu_id,
    validate_kitsu_target,
)
from .kitsu_writer import KitsuWriter, KitsuWriterError


# Default task fields including attrib + ownAttrib so ayon-python-api 1.2.22
# (which skips _prepare_fields when fields is None in get_tasks) requests
# task attribute ownership metadata.
_TASK_QUERY_FIELDS = frozenset(
    {
        "id",
        "name",
        "label",
        "taskType",
        "thumbnailId",
        "assignees",
        "folderId",
        "status",
        "tags",
        "active",
        "data",
        "attrib",
        "ownAttrib",
    }
)


class IdentityResolver:
    """Resolves AYON entities to Kitsu entities with full validation."""

    def __init__(
        self,
        ayon_client: Any,
        writer: KitsuWriter,
        entrypoint: str = "",
    ):
        """Initialize IdentityResolver.

        Args:
            ayon_client: AYON API client (e.g. ayon_api or a wrapper).
            writer: Dedicated KitsuWriter instance.
            entrypoint: Base endpoint for the addon (e.g. /addons/kitsu/1.2.7).
        """
        self.ayon_client = ayon_client
        self.writer = writer
        self.entrypoint = entrypoint.rstrip("/")

    def get_ayon_entity(
        self, project_name: str, entity_type: str, entity_id: str
    ) -> Optional[Dict[str, Any]]:
        """Fetch the current AYON entity by type and id."""
        ent_type = entity_type.strip().lower()
        try:
            if ent_type == AYON_KIND_TASK:
                task_fields = set(_TASK_QUERY_FIELDS)
                if hasattr(self.ayon_client, "get_default_fields_for_type"):
                    try:
                        defaults = (
                            self.ayon_client.get_default_fields_for_type(
                                "task"
                            )
                        )
                        if defaults:
                            task_fields = set(defaults) | {
                                "attrib",
                                "ownAttrib",
                            }
                    except Exception:
                        pass
                if hasattr(self.ayon_client, "get_task_by_id"):
                    try:
                        return self.ayon_client.get_task_by_id(
                            project_name,
                            entity_id,
                            fields=task_fields,
                            own_attributes=True,
                        )
                    except TypeError:
                        try:
                            return self.ayon_client.get_task_by_id(
                                project_name, entity_id, own_attributes=True
                            )
                        except TypeError:
                            return self.ayon_client.get_task_by_id(
                                project_name, entity_id
                            )
                if hasattr(self.ayon_client, "get_task"):
                    try:
                        return self.ayon_client.get_task(
                            project_name,
                            entity_id,
                            fields=task_fields,
                            own_attributes=True,
                        )
                    except TypeError:
                        try:
                            return self.ayon_client.get_task(
                                project_name, entity_id, own_attributes=True
                            )
                        except TypeError:
                            return self.ayon_client.get_task(
                                project_name, entity_id
                            )
            elif ent_type == AYON_KIND_FOLDER:
                if hasattr(self.ayon_client, "get_folder_by_id"):
                    try:
                        return self.ayon_client.get_folder_by_id(
                            project_name, entity_id, own_attributes=True
                        )
                    except TypeError:
                        return self.ayon_client.get_folder_by_id(
                            project_name, entity_id
                        )
                if hasattr(self.ayon_client, "get_folder"):
                    try:
                        return self.ayon_client.get_folder(
                            project_name, entity_id, own_attributes=True
                        )
                    except TypeError:
                        return self.ayon_client.get_folder(
                            project_name, entity_id
                        )
            elif ent_type == AYON_KIND_USER:
                if hasattr(self.ayon_client, "get_user"):
                    return self.ayon_client.get_user(entity_id)
        except Exception as exc:
            # Check for 404 or not found
            resp = getattr(exc, "response", None)
            status = getattr(resp, "status_code", None)
            if status == 404 or "not found" in str(exc).lower():
                return None
            raise
        return None

    def get_kitsu_owners(
        self, project_name: str, kitsu_id: str
    ) -> Dict[str, list]:
        """Fetch AYON entities that own a kitsuId via /kitsu-owners."""
        url = (
            f"{self.entrypoint}/kitsu-owners?project_name={project_name}"
            f"&kitsu_id={kitsu_id}"
        )
        res = self.ayon_client.get(url)
        status_code = getattr(res, "status_code", None)
        if isinstance(status_code, int) and status_code >= 400:
            raise RuntimeError(
                f"/kitsu-owners query failed with HTTP {status_code}"
            )
        data = getattr(res, "data", res)
        if isinstance(data, dict):
            if "detail" in data and "folders" not in data:
                raise RuntimeError(
                    f"/kitsu-owners query returned error: {data['detail']}"
                )
            return {
                "folders": list(data.get("folders", [])),
                "tasks": list(data.get("tasks", [])),
                "users": list(data.get("users", [])),
            }
        return {"folders": [], "tasks": [], "users": []}

    def resolve(
        self,
        project_name: str,
        entity_type: str,
        entity_id: str,
        expected_kind: str,
        kitsu_project_id: Optional[str] = None,
        asset_type_ids: Optional[Iterable[str]] = None,
    ) -> Dict[str, Any]:
        """Read the AYON entity now, validate kitsuId, check duplicates,

        fetch and validate the Kitsu entity.

        Args:
            project_name: AYON project name.
            entity_type: AYON entity type ('folder', 'task', 'user').
            entity_id: AYON entity id.
            expected_kind: Expected AYON kind ('folder', 'task', 'user').
            kitsu_project_id: Paired Kitsu project id.
            asset_type_ids: Optional Kitsu asset type ids for structural check.

        Returns:
            Dict: ``{"ok": True, "ayon": {...}, "kitsu": {...}}`` on success,
            or ``{"ok": False, "outcome": "skip" | "fail", "reason": str,
            "retryable": bool}`` on failure or skip.
        """
        # Step 1: Read AYON entity at processing time (Requirement 3.1, 4.10)
        try:
            ayon_entity = self.get_ayon_entity(
                project_name, entity_type, entity_id
            )
        except Exception as exc:
            return {
                "ok": False,
                "outcome": "fail",
                "reason": (
                    f"identity resolution could not complete: "
                    f"failed to read AYON entity {entity_id}: {exc}"
                ),
                "retryable": True,
                "error_kind": ERROR_UNREACHABLE,
            }
        if not ayon_entity:
            reason = SKIP_ENTITY_GONE.format(entity_id=entity_id)
            return {
                "ok": False,
                "outcome": "skip",
                "reason": reason,
                "retryable": False,
            }

        # Step 2: Validate kitsuId from data (Requirement 3.2, 3.6)
        data = ayon_entity.get("data") or {}
        raw_kitsu_id = data.get("kitsuId")
        id_res = validate_kitsu_id(raw_kitsu_id, entity_id, asset_type_ids)
        if id_res["result"] != KITSU_ID_OK:
            return {
                "ok": False,
                "outcome": "skip",
                "reason": id_res["reason"],
                "retryable": False,
            }

        kitsu_id = str(id_res["kitsu_id"])

        # Step 3: Fetch duplicate owners (Requirement 3.8)
        try:
            owners = self.get_kitsu_owners(project_name, kitsu_id)
        except Exception as exc:
            return {
                "ok": False,
                "outcome": "fail",
                "reason": (
                    f"identity resolution could not complete: "
                    f"failed to query owners: {exc}"
                ),
                "kitsu_id": kitsu_id,
                "retryable": True,
                "error_kind": ERROR_UNREACHABLE,
            }

        # Step 4: Fetch target Kitsu entity (Requirements 3.4, 3.9)
        kitsu_kind = expected_kind.strip().lower()
        try:
            if kitsu_kind == AYON_KIND_TASK:
                kitsu_entity = self.writer.get_task(kitsu_id)
            else:
                kitsu_entity = self.writer.get_entity(kitsu_id)
        except KitsuWriterError as exc:
            if exc.kind == ERROR_NOT_FOUND or exc.http_status == 404:
                return {
                    "ok": False,
                    "outcome": "fail",
                    "reason": (
                        f"Kitsu entity {kitsu_id} of AYON entity {entity_id} "
                        "does not exist in Kitsu"
                    ),
                    "kitsu_id": kitsu_id,
                    "retryable": False,
                    "http_status": 404,
                }
            if exc.retryable or exc.kind in (
                ERROR_UNREACHABLE,
                ERROR_SERVER_ERROR,
            ):
                return {
                    "ok": False,
                    "outcome": "fail",
                    "reason": (
                        "identity resolution could not complete: "
                        f"{exc.message}"
                    ),
                    "kitsu_id": kitsu_id,
                    "retryable": True,
                    "error_kind": exc.kind,
                    "http_status": exc.http_status,
                }
            return {
                "ok": False,
                "outcome": "fail",
                "reason": (
                    f"identity resolution could not complete: {exc.message}"
                ),
                "kitsu_id": kitsu_id,
                "retryable": False,
                "error_kind": exc.kind,
                "http_status": exc.http_status,
            }
        except Exception as exc:
            return {
                "ok": False,
                "outcome": "fail",
                "reason": f"identity resolution could not complete: {exc}",
                "kitsu_id": kitsu_id,
                "retryable": False,
            }

        # Step 5: Validate Kitsu target (Requirements 3.5, 3.7, 3.8)
        target_res = validate_kitsu_target(
            ayon_kind=expected_kind,
            entity_id=entity_id,
            kitsu_id=kitsu_id,
            kitsu_entity=kitsu_entity,
            kitsu_project_id=kitsu_project_id or "",
            owners=owners,
        )
        if not target_res["ok"]:
            return {
                "ok": False,
                "outcome": "fail",
                "reason": target_res["reason"],
                "error": target_res.get("error"),
                "kitsu_id": kitsu_id,
                "retryable": False,
            }

        return {
            "ok": True,
            "ayon": ayon_entity,
            "kitsu": kitsu_entity,
        }
