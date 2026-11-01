"""Dedicated Kitsu writer client with error classification (Task 8.2).

Validates: Requirements 6.1, 6.4, 6.8, 10.1, 10.3, 10.4, 13.6.
"""

import time
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

import gazu
import requests

from .constants import (
    ERROR_NOT_FOUND,
    ERROR_PERMISSION,
    ERROR_REJECTED,
    ERROR_SERVER_ERROR,
    ERROR_UNREACHABLE,
    KITSU_TIMEOUT_S,
)
from .describe import redact
from .planning import merge_kitsu_data


class KitsuWriterError(Exception):
    """Classified Kitsu error raised by KitsuWriter calls."""

    def __init__(
        self,
        kind: str,
        message: str,
        http_status: Optional[int] = None,
        retryable: Optional[bool] = None,
    ):
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.http_status = http_status
        if retryable is None:
            self.retryable = kind in (ERROR_UNREACHABLE, ERROR_SERVER_ERROR)
        else:
            self.retryable = bool(retryable)

    def __str__(self) -> str:
        if self.http_status:
            return f"{self.kind} (HTTP {self.http_status}): {self.message}"
        return f"{self.kind}: {self.message}"


def classify_kitsu_error(
    exc: Exception, secrets: Optional[Iterable[str]] = None
) -> KitsuWriterError:
    """Classify a gazu or requests exception into KitsuWriterError.

    Args:
        exc: The caught exception.
        secrets: Secrets to redact from the error message.

    Returns:
        KitsuWriterError with classified kind, status and retryable flag.
    """
    if isinstance(exc, KitsuWriterError):
        return exc

    msg = redact(str(exc), secrets)

    # Check for HTTP status on requests.Response or exception
    status_code: Optional[int] = None
    response = getattr(exc, "response", None)
    if response is not None and hasattr(response, "status_code"):
        status_code = getattr(response, "status_code")
    elif hasattr(exc, "status_code"):
        status_code = getattr(exc, "status_code")

    # Specific requests network exceptions
    if isinstance(exc, requests.exceptions.Timeout):
        return KitsuWriterError(
            ERROR_UNREACHABLE, msg or "Request timed out", retryable=True
        )

    if isinstance(exc, requests.exceptions.ConnectionError):
        return KitsuWriterError(
            ERROR_UNREACHABLE, msg or "Connection error", retryable=True
        )

    # Specific gazu exceptions
    if isinstance(exc, gazu.exception.RouteNotFoundException):
        return KitsuWriterError(
            ERROR_NOT_FOUND, msg, http_status=404, retryable=False
        )

    if isinstance(
        exc,
        (
            gazu.exception.NotAllowedException,
            gazu.exception.NotAuthenticatedException,
            gazu.exception.AuthFailedException,
        ),
    ):
        code = status_code or (
            403
            if isinstance(exc, gazu.exception.NotAllowedException)
            else 401
        )
        return KitsuWriterError(
            ERROR_PERMISSION, msg, http_status=code, retryable=False
        )

    if isinstance(exc, gazu.exception.ServerErrorException):
        code = status_code or 500
        return KitsuWriterError(
            ERROR_SERVER_ERROR, msg, http_status=code, retryable=True
        )

    val_exc = getattr(gazu.exception, "ValidationException", None)
    rejected_types = tuple(
        cls
        for cls in (
            getattr(gazu.exception, "ParameterException", None),
            getattr(gazu.exception, "MethodNotAllowedException", None),
            getattr(gazu.exception, "TooBigFileException", None),
            val_exc,
        )
        if cls is not None
    )

    if rejected_types and isinstance(exc, rejected_types):
        is_meth = isinstance(
            exc,
            getattr(
                gazu.exception, "MethodNotAllowedException", ()
            ),
        )
        code = status_code or (
            405
            if is_meth
            else (
                422
                if val_exc and isinstance(exc, val_exc)
                else 400
            )
        )
        return KitsuWriterError(
            ERROR_REJECTED, msg, http_status=code, retryable=False
        )

    # Check status code ranges
    if status_code is not None:
        if 500 <= status_code <= 599:
            return KitsuWriterError(
                ERROR_SERVER_ERROR,
                msg,
                http_status=status_code,
                retryable=True,
            )
        if status_code == 404:
            return KitsuWriterError(
                ERROR_NOT_FOUND, msg, http_status=404, retryable=False
            )
        if status_code in (401, 403):
            return KitsuWriterError(
                ERROR_PERMISSION, msg, http_status=status_code, retryable=False
            )
        if 400 <= status_code < 500:
            return KitsuWriterError(
                ERROR_REJECTED, msg, http_status=status_code, retryable=False
            )

    # Message-based heuristics for unreachable/network issues
    lower_msg = msg.lower()
    if any(
        term in lower_msg
        for term in (
            "unreachable",
            "timed out",
            "timeout",
            "connection refused",
            "connection error",
            "name resolution",
            "dns",
            "getaddrinfo",
            "host is down",
            "network is unreachable",
        )
    ):
        return KitsuWriterError(
            ERROR_UNREACHABLE, msg, retryable=True
        )

    # Default fallback for unknown client errors
    return KitsuWriterError(
        ERROR_REJECTED, msg, http_status=status_code, retryable=False
    )


class KitsuWriter:
    """Dedicated gazu client wrapper for Outbound_Sync writes."""

    def __init__(
        self,
        host: Optional[str] = None,
        login: Optional[str] = None,
        password: Optional[str] = None,
        timeout: float = KITSU_TIMEOUT_S,
        client: Optional[Any] = None,
        secrets: Optional[Iterable[str]] = None,
        clock: Optional[Any] = None,
    ):
        """Initialize KitsuWriter with a dedicated gazu client.

        Args:
            host: Kitsu server URL.
            login: Login email.
            password: Login password.
            timeout: Session timeout in seconds (default: 30s).
            client: Pre-configured KitsuClient (optional, for testing).
            secrets: Additional secrets to redact from error messages.
            clock: Injected clock callable (returns float epoch seconds).
        """
        self.timeout = float(timeout)
        self.clock = clock or time.time
        self.secrets = set(secrets or ())
        if login:
            self.secrets.add(str(login))
        if password:
            self.secrets.add(str(password))

        self._task_statuses_cache: Optional[List[Dict[str, Any]]] = None
        self._task_statuses_cache_time: float = 0.0
        self._all_persons_cache: Optional[List[Dict[str, Any]]] = None
        self._all_persons_cache_time: float = 0.0
        self._task_types_cache: Optional[List[Dict[str, Any]]] = None
        self._task_types_cache_time: float = 0.0
        self._project_task_types_cache: Dict[
            str, Tuple[float, List[Dict[str, Any]]]
        ] = {}

        if client is not None:
            self.client = client
        else:
            if not host:
                raise ValueError("Kitsu host is required")
            self.client = gazu.client.create_client(host)
            orig_request = self.client.session.request

            def _request_with_timeout(*args: Any, **kwargs: Any) -> Any:
                kwargs.setdefault("timeout", self.timeout)
                return orig_request(*args, **kwargs)

            self.client.session.request = _request_with_timeout

            if login and password:
                try:
                    gazu.log_in(login, password, client=self.client)
                except Exception as exc:
                    raise classify_kitsu_error(exc, self.secrets) from exc

    def _call(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        """Execute a gazu function and classify any exception."""
        kwargs["client"] = self.client
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            raise classify_kitsu_error(exc, self.secrets) from exc

    def get_task(self, kitsu_id: str) -> Dict[str, Any]:
        """Fetch a Kitsu task by id."""
        return self._call(gazu.task.get_task, kitsu_id)

    def get_entity(self, kitsu_id: str) -> Dict[str, Any]:
        """Fetch a Kitsu entity (Asset, Shot, etc.) by id."""
        return self._call(gazu.entity.get_entity, kitsu_id)

    def task_statuses(self) -> List[Dict[str, Any]]:
        """Fetch all Kitsu task statuses with a 60s cache."""
        now = float(self.clock())
        if (
            self._task_statuses_cache is not None
            and (now - self._task_statuses_cache_time) < 60.0
        ):
            return self._task_statuses_cache

        statuses = self._call(gazu.task.all_task_statuses)
        self._task_statuses_cache = statuses
        self._task_statuses_cache_time = now
        return statuses

    def comment_status(
        self,
        task: Dict[str, Any],
        status: Dict[str, Any],
        text: str,
    ) -> Dict[str, Any]:
        """Add a task status comment in Kitsu (Requirement 6.1, 6.4).

        Only passes task, status and text to add_comment.
        """
        task_id = task.get("id") if isinstance(task, dict) else task
        status_id = status.get("id") if isinstance(status, dict) else status
        return self._call(
            gazu.task.add_comment,
            task=task_id,
            task_status=status_id,
            comment=text,
        )

    def all_persons(self) -> List[Dict[str, Any]]:
        """Fetch all Kitsu persons with a 60s cache (Requirement 7.1, 7.4)."""
        now = float(self.clock())
        if (
            self._all_persons_cache is not None
            and (now - self._all_persons_cache_time) < 60.0
        ):
            return self._all_persons_cache

        persons = self._call(gazu.person.all_persons)
        self._all_persons_cache = persons
        self._all_persons_cache_time = now
        return persons

    def assign(
        self, task: Dict[str, Any] | str, person_id: str
    ) -> None:
        """Assign a person to a Kitsu task (Requirement 7.4, 7.7)."""
        task_id = task.get("id") if isinstance(task, dict) else task
        self._call(gazu.task.assign_task, task_id, person_id)

    def unassign(
        self, task: Dict[str, Any] | str, person_id: str
    ) -> None:
        """Unassign a person from a Kitsu task (Requirement 7.4, 7.7)."""
        task_id = task.get("id") if isinstance(task, dict) else task
        self._call(gazu.task.clear_assignations, task_id, person_id)

    def update_entity_fields(
        self,
        entity: Dict[str, Any] | str,
        fields: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Update Kitsu entity with planned attribute fields (8.4, 8.11).

        Reads the entity, overlays planned data.* keys using merge_kitsu_data,
        and sends one PUT request with data and top-level fields (nb_frames,
        description).

        Args:
            entity: Kitsu entity dict or Kitsu ID string.
            fields: Planned fields from plan_attribute_write.

        Returns:
            API response from Kitsu.
        """
        if isinstance(entity, dict):
            kitsu_id = str(entity.get("id", ""))
            is_task = (
                entity.get("type") == "Task"
                or "task_type_id" in entity
            )
            fresh_entity = (
                self.get_task(kitsu_id)
                if is_task
                else self.get_entity(kitsu_id)
            )
        else:
            kitsu_id = str(entity)
            is_task = False
            try:
                fresh_entity = self.get_entity(kitsu_id)
            except KitsuWriterError as exc:
                if exc.kind == ERROR_NOT_FOUND:
                    fresh_entity = self.get_task(kitsu_id)
                    is_task = True
                else:
                    raise

        current_data = (
            fresh_entity.get("data")
            if isinstance(fresh_entity, dict)
            else {}
        )
        new_data = merge_kitsu_data(current_data, fields)
        payload: Dict[str, Any] = {"data": new_data}
        if "description" in fields:
            payload["description"] = fields["description"]
        if "nb_frames" in fields:
            payload["nb_frames"] = fields["nb_frames"]

        path = (
            f"data/tasks/{kitsu_id}"
            if is_task
            else f"data/entities/{kitsu_id}"
        )
        return self._call(gazu.raw.put, path, payload)

    # ------------------------------------------------------------------
    # Slice 3 calls: creation, siblings, rename, removal, counts
    # ------------------------------------------------------------------

    def task_types(
        self, project_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Fetch Kitsu task types with a 60s cache (Requirement 11.2)."""
        now = float(self.clock())
        if project_id and hasattr(gazu.task, "all_task_types_for_project"):
            cached = self._project_task_types_cache.get(project_id)
            if cached is not None and (now - cached[0]) < 60.0:
                return cached[1]
            types = self._call(
                gazu.task.all_task_types_for_project, project_id
            )
            self._project_task_types_cache[project_id] = (now, types)
            return types

        if (
            self._task_types_cache is not None
            and (now - self._task_types_cache_time) < 60.0
        ):
            return self._task_types_cache

        types = self._call(gazu.task.all_task_types)
        self._task_types_cache = types
        self._task_types_cache_time = now
        return types

    def create_entity(
        self,
        entity_type: str,
        project_id: str,
        name: str,
        parent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a Kitsu folder entity (Episode, Sequence, Shot, Asset)."""
        if entity_type == "Episode":
            return self._call(gazu.shot.new_episode, project_id, name)
        if entity_type == "Sequence":
            return self._call(
                gazu.shot.new_sequence,
                project_id,
                name,
                episode=parent_id,
            )
        if entity_type == "Shot":
            return self._call(
                gazu.shot.new_shot, project_id, parent_id, name
            )
        if entity_type == "Asset":
            return self._call(
                gazu.asset.new_asset, project_id, parent_id, name
            )
        raise KitsuWriterError(
            ERROR_REJECTED,
            f"Unsupported entity_type for creation: {entity_type}",
            retryable=False,
        )

    def create_task(
        self,
        entity_id: str,
        task_type_id: str,
        name: Optional[str] = None,
        project_id: Optional[str] = None,
        task_status: Optional[Union[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Create a Kitsu task on a parent entity (Requirement 11.2)."""
        entity_arg: Union[str, Dict[str, Any]] = entity_id
        if project_id:
            entity_arg = {"id": entity_id, "project_id": project_id}
        elif isinstance(entity_id, str):
            try:
                parent = self.get_entity(entity_id)
                if isinstance(parent, dict) and parent.get("project_id"):
                    entity_arg = parent
            except Exception:
                pass

        if not task_status:
            try:
                statuses = self.task_statuses() or []
                for st in statuses:
                    if isinstance(st, dict):
                        if st.get("is_default") or st.get("default"):
                            task_status = st
                            break
                        st_name = str(st.get("name") or "").lower()
                        if st_name in ("todo", "to do"):
                            task_status = st
                            break
                if not task_status and statuses:
                    task_status = statuses[0]
            except Exception:
                task_status = None

        call_kwargs: Dict[str, Any] = {}
        if name:
            call_kwargs["name"] = name
        if task_status:
            call_kwargs["task_status"] = task_status

        return self._call(
            gazu.task.new_task, entity_arg, task_type_id, **call_kwargs
        )

    def get_siblings(
        self,
        entity_type: str,
        project_id: str,
        parent_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch sibling Kitsu entities under the given parent (11.9)."""
        if entity_type == "Episode":
            raw_list = self._call(
                gazu.shot.all_episodes_for_project, project_id
            )
        elif entity_type == "Sequence":
            if parent_id and parent_id not in ("sequence", "asset"):
                raw_list = self._call(
                    gazu.shot.all_sequences_for_episode, parent_id
                )
            else:
                all_seqs = self._call(
                    gazu.shot.all_sequences_for_project, project_id
                )
                raw_list = [
                    s
                    for s in (all_seqs or [])
                    if isinstance(s, dict)
                    and not s.get("parent_id")
                    and not s.get("episode_id")
                ]
        elif entity_type == "Shot":
            raw_list = self._call(
                gazu.shot.all_shots_for_sequence, parent_id
            )
        elif entity_type == "Asset":
            raw_list = self._call(
                gazu.asset.all_assets_for_project_and_type,
                project_id,
                parent_id,
            )
        else:
            raw_list = []

        result: List[Dict[str, Any]] = []
        for item in raw_list or []:
            if isinstance(item, dict):
                copy_item = dict(item)
                copy_item.setdefault("type", entity_type)
                result.append(copy_item)
        return result

    def get_tasks_for_entity(
        self,
        entity_id: str,
        parent_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch Kitsu tasks belonging to an entity (Requirement 11.9)."""
        p_type = (parent_type or "").strip()
        if p_type == "Asset":
            return self._call(gazu.task.all_tasks_for_asset, entity_id)
        if p_type == "Shot":
            return self._call(gazu.task.all_tasks_for_shot, entity_id)
        if p_type == "Sequence":
            return self._call(gazu.task.all_tasks_for_sequence, entity_id)
        if p_type == "Episode":
            return self._call(gazu.task.all_tasks_for_episode, entity_id)
        return self._call(
            gazu.raw.fetch_all, f"data/entities/{entity_id}/tasks"
        )

    def rename_entity(
        self,
        entity: Dict[str, Any] | str,
        new_name: str,
        is_task: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Update only the 'name' field of a Kitsu entity or task (12.1)."""
        if isinstance(entity, dict):
            kitsu_id = str(entity.get("id", ""))
            if is_task is None:
                is_task = (
                    entity.get("type") == "Task"
                    or "task_type_id" in entity
                )
        else:
            kitsu_id = str(entity)
            if is_task is None:
                is_task = False

        path = (
            f"data/tasks/{kitsu_id}"
            if is_task
            else f"data/entities/{kitsu_id}"
        )
        return self._call(gazu.raw.put, path, {"name": new_name})

    def remove_entity(
        self,
        entity: Dict[str, Any] | str,
        entity_type: Optional[str] = None,
    ) -> Any:
        """Remove a Kitsu entity or task without force=True (12.2, 12.3)."""
        if isinstance(entity, dict):
            kitsu_id = str(entity.get("id", ""))
            ent_type = entity_type or str(entity.get("type", ""))
            if not ent_type and "task_type_id" in entity:
                ent_type = "Task"
        else:
            kitsu_id = str(entity)
            ent_type = entity_type or ""

        if ent_type.lower() == "task":
            return self._call(
                gazu.raw.delete, f"data/tasks/{kitsu_id}", {}
            )
        if ent_type == "Asset":
            return self._call(
                gazu.asset.remove_asset, kitsu_id, force=False
            )
        if ent_type == "Shot":
            return self._call(
                gazu.shot.remove_shot, kitsu_id, force=False
            )
        if ent_type == "Sequence":
            return self._call(
                gazu.shot.remove_sequence, kitsu_id, force=False
            )
        if ent_type == "Episode":
            return self._call(
                gazu.shot.remove_episode, kitsu_id, force=False
            )
        return self._call(
            gazu.entity.remove_entity, kitsu_id, force=False
        )

    def _get_previews_for_task(
        self, task_id: str
    ) -> List[Dict[str, Any]]:
        """Fetch previews for a task across gazu versions (12.3)."""
        if hasattr(gazu.task, "all_previews_for_task"):
            return self._call(
                gazu.task.all_previews_for_task, task_id
            ) or []
        if hasattr(gazu, "files") and hasattr(
            gazu.files, "get_all_preview_files_for_task"
        ):
            return self._call(
                gazu.files.get_all_preview_files_for_task, task_id
            ) or []
        return self._call(
            gazu.raw.fetch_all, f"tasks/{task_id}/previews"
        ) or []

    def get_deletion_counts(
        self, kitsu_id: str, entity_type: str
    ) -> Dict[str, int]:
        """Count comments, previews and children for deletion guard (12.3)."""
        ent_type = (entity_type or "").strip()
        if ent_type.lower() == "task":
            comments = (
                self._call(gazu.task.all_comments_for_task, kitsu_id) or []
            )
            previews = self._get_previews_for_task(kitsu_id)
            return {
                "comments": len(comments),
                "previews": len(previews),
                "children": 0,
            }

        tasks = self.get_tasks_for_entity(kitsu_id, ent_type) or []
        comments_cnt = 0
        preview_ids = set()

        for t in tasks:
            if not isinstance(t, dict) or not t.get("id"):
                continue
            t_id = str(t["id"])
            t_comments = (
                self._call(gazu.task.all_comments_for_task, t_id) or []
            )
            comments_cnt += len(t_comments)
            t_previews = self._get_previews_for_task(t_id)
            for p in t_previews:
                if isinstance(p, dict) and p.get("id"):
                    preview_ids.add(str(p["id"]))
                else:
                    preview_ids.add(f"{t_id}:{len(preview_ids)}")

        if ent_type == "Shot":
            shot_previews = (
                self._call(gazu.shot.all_previews_for_shot, kitsu_id) or []
            )
            for p in shot_previews:
                if isinstance(p, dict) and p.get("id"):
                    preview_ids.add(str(p["id"]))
                else:
                    preview_ids.add(f"shot:{len(preview_ids)}")
            children_cnt = len(tasks)
        elif ent_type == "Asset":
            children_cnt = len(tasks)
        elif ent_type == "Sequence":
            shots = (
                self._call(gazu.shot.all_shots_for_sequence, kitsu_id) or []
            )
            children_cnt = len(shots) + len(tasks)
        elif ent_type == "Episode":
            seqs = (
                self._call(gazu.shot.all_sequences_for_episode, kitsu_id)
                or []
            )
            shots = (
                self._call(gazu.shot.all_shots_for_episode, kitsu_id) or []
            )
            children_cnt = len(seqs) + len(shots) + len(tasks)
        else:
            children_cnt = len(tasks)

        return {
            "comments": comments_cnt,
            "previews": len(preview_ids),
            "children": children_cnt,
        }

