"""Constants of the Outbound_Sync path (AYON to Kitsu).

This module is part of the pure core: it imports only the standard
library, so the pure modules and the offline tests can import it without
``ayon_api`` or ``gazu`` (Requirement 14.1).

It holds the event topics, the Sync_Category names and the topic to
category map, the enrolled topic lists per slice, the origin markers, the
structural Kitsu ids, the skip reason strings and the timing and retry
limits used by the runner.

Skip reasons that carry details are ``str.format`` templates. The runner
prefixes each reason with ``DESCRIPTION_SKIPPED`` (Requirement 4.4).
"""

# ---------------------------------------------------------------------------
# Event topics
# ---------------------------------------------------------------------------

#: Topic of every Outbound_Job (Requirement 13.4). It differs from the
#: Inbound_Sync topics ``kitsu.sync`` and ``kitsu.sync_request``.
TARGET_TOPIC = "kitsu.outbound_sync"

#: Topic of the persisted toggle snapshots, heartbeats and gap markers.
GATE_TOPIC = "kitsu.outbound_gate"

#: Inbound_Sync topics, listed so the Outbound topic can be checked against
#: them.
INBOUND_SYNC_TOPIC = "kitsu.sync"
INBOUND_SYNC_REQUEST_TOPIC = "kitsu.sync_request"

#: Topic dispatched by AYON when addon settings are saved (F10).
SETTINGS_CHANGED_TOPIC = "settings.changed"

# Source topics (AYON_Change_Event topics).
TOPIC_TASK_STATUS_CHANGED = "entity.task.status_changed"
TOPIC_TASK_ASSIGNEES_CHANGED = "entity.task.assignees_changed"
TOPIC_FOLDER_ATTRIB_CHANGED = "entity.folder.attrib_changed"
TOPIC_TASK_ATTRIB_CHANGED = "entity.task.attrib_changed"
TOPIC_FOLDER_CREATED = "entity.folder.created"
TOPIC_TASK_CREATED = "entity.task.created"
TOPIC_FOLDER_RENAMED = "entity.folder.renamed"
TOPIC_TASK_RENAMED = "entity.task.renamed"
TOPIC_FOLDER_LABEL_CHANGED = "entity.folder.label_changed"
TOPIC_TASK_LABEL_CHANGED = "entity.task.label_changed"
TOPIC_FOLDER_DELETED = "entity.folder.deleted"
TOPIC_TASK_DELETED = "entity.task.deleted"
TOPIC_PROJECT_DELETED = "entity.project.deleted"
TOPIC_USER_DELETED = "entity.user.deleted"

# ---------------------------------------------------------------------------
# Sync_Category names
# ---------------------------------------------------------------------------

CATEGORY_TASK_STATUS = "task_status"
CATEGORY_TASK_ASSIGNEES = "task_assignees"
CATEGORY_ENTITY_ATTRIBUTES = "entity_attributes"
CATEGORY_ENTITY_CREATION = "entity_creation"
CATEGORY_ENTITY_RENAME = "entity_rename"
CATEGORY_ENTITY_DELETION = "entity_deletion"

#: The six Sync_Category names, in settings order. Each name is also the
#: key of its toggle in ``sync_settings.two_way_sync``.
SYNC_CATEGORIES = (
    CATEGORY_TASK_STATUS,
    CATEGORY_TASK_ASSIGNEES,
    CATEGORY_ENTITY_ATTRIBUTES,
    CATEGORY_ENTITY_CREATION,
    CATEGORY_ENTITY_RENAME,
    CATEGORY_ENTITY_DELETION,
)

#: Settings key of the master toggle in ``sync_settings.two_way_sync``.
MASTER_TOGGLE_KEY = "enabled"

#: Settings key and allowed values of the conflict policy.
CONFLICT_POLICY_KEY = "conflict_policy"
CONFLICT_POLICY_KITSU_WINS = "kitsu_wins"
CONFLICT_POLICY_AYON_WINS = "ayon_wins"
CONFLICT_POLICIES = (CONFLICT_POLICY_KITSU_WINS, CONFLICT_POLICY_AYON_WINS)
DEFAULT_CONFLICT_POLICY = CONFLICT_POLICY_KITSU_WINS

# ---------------------------------------------------------------------------
# Topic to Sync_Category map
# ---------------------------------------------------------------------------

#: Every known source topic and its Sync_Category. ``None`` marks a topic
#: that is out of scope (project and user deletion, Requirement 12.6).
TOPIC_CATEGORIES = {
    TOPIC_TASK_STATUS_CHANGED: CATEGORY_TASK_STATUS,
    TOPIC_TASK_ASSIGNEES_CHANGED: CATEGORY_TASK_ASSIGNEES,
    TOPIC_FOLDER_ATTRIB_CHANGED: CATEGORY_ENTITY_ATTRIBUTES,
    TOPIC_TASK_ATTRIB_CHANGED: CATEGORY_ENTITY_ATTRIBUTES,
    TOPIC_FOLDER_CREATED: CATEGORY_ENTITY_CREATION,
    TOPIC_TASK_CREATED: CATEGORY_ENTITY_CREATION,
    TOPIC_FOLDER_RENAMED: CATEGORY_ENTITY_RENAME,
    TOPIC_TASK_RENAMED: CATEGORY_ENTITY_RENAME,
    TOPIC_FOLDER_LABEL_CHANGED: CATEGORY_ENTITY_RENAME,
    TOPIC_TASK_LABEL_CHANGED: CATEGORY_ENTITY_RENAME,
    TOPIC_FOLDER_DELETED: CATEGORY_ENTITY_DELETION,
    TOPIC_TASK_DELETED: CATEGORY_ENTITY_DELETION,
    TOPIC_PROJECT_DELETED: None,
    TOPIC_USER_DELETED: None,
}

#: Topics that are enrolled but never written to Kitsu (Requirement 12.6).
OUT_OF_SCOPE_TOPICS = frozenset(
    topic for topic, category in TOPIC_CATEGORIES.items() if category is None
)

#: Creation and deletion topics that get the sender-type exclusion filter
#: at enrollment (Requirement 5.13, F18).
ENROLL_EXCLUSION_TOPICS = frozenset(
    (
        TOPIC_FOLDER_CREATED,
        TOPIC_TASK_CREATED,
        TOPIC_FOLDER_DELETED,
        TOPIC_TASK_DELETED,
    )
)

# ---------------------------------------------------------------------------
# Enrolled topics per slice
# ---------------------------------------------------------------------------

SLICE_1_TOPICS = (TOPIC_TASK_STATUS_CHANGED,)

SLICE_2_TOPICS = (
    TOPIC_TASK_ASSIGNEES_CHANGED,
    TOPIC_FOLDER_ATTRIB_CHANGED,
    TOPIC_TASK_ATTRIB_CHANGED,
)

SLICE_3_TOPICS = (
    TOPIC_FOLDER_CREATED,
    TOPIC_TASK_CREATED,
    TOPIC_FOLDER_RENAMED,
    TOPIC_TASK_RENAMED,
    TOPIC_FOLDER_LABEL_CHANGED,
    TOPIC_TASK_LABEL_CHANGED,
    TOPIC_FOLDER_DELETED,
    TOPIC_TASK_DELETED,
    TOPIC_PROJECT_DELETED,
    TOPIC_USER_DELETED,
)

#: Topics per slice, keyed by slice number.
SLICE_TOPICS = {
    1: SLICE_1_TOPICS,
    2: SLICE_2_TOPICS,
    3: SLICE_3_TOPICS,
}

#: Topics enrolled in the single enroll call (Requirement 4.14). This is
#: the union of the implemented slices (Slices 1, 2 and 3).
ENROLLED_TOPICS = SLICE_1_TOPICS + SLICE_2_TOPICS + SLICE_3_TOPICS

# ---------------------------------------------------------------------------
# Origin markers (Requirements 5.6, 5.7)
# ---------------------------------------------------------------------------

#: ``sender_type`` set on every AYON write of Inbound_Sync and Full_Sync.
KITSU_SYNC_SENDER_TYPE = "kitsu_sync"

#: Prefix of the Processor sender name (``kitsu-processor-<hostname>``).
KITSU_SYNC_SENDER_PREFIX = "kitsu-processor-"

#: Summary key set to ``True`` on every event the Server_Addon dispatches.
KITSU_SYNC_SUMMARY_KEY = "kitsuSyncOrigin"

#: Marker dict in the form ``origin.classify_origin`` expects.
ORIGIN_MARKERS = {
    "sender_type": KITSU_SYNC_SENDER_TYPE,
    "sender_prefix": KITSU_SYNC_SENDER_PREFIX,
    "summary_key": KITSU_SYNC_SUMMARY_KEY,
}

# Origin classes returned by ``origin.classify_origin``.
ORIGIN_SYNC_ORIGINATED = "sync_originated"
ORIGIN_USER_CHANGE = "user_change"
ORIGIN_UNKNOWN = "origin_unknown"

# ---------------------------------------------------------------------------
# Structural Kitsu ids (Requirement 3.6)
# ---------------------------------------------------------------------------

#: Kitsu ids of the structural folders Inbound_Sync creates. A folder with
#: one of these ids (or the id of a Kitsu asset type of the paired project)
#: is never synced to Kitsu.
STRUCTURAL_KITSU_IDS = frozenset(
    ("asset", "shot", "sequence", "episode", "edit", "concept")
)

#: Supported AYON folder types for Kitsu creation (Requirement 11.1).
CREATION_FOLDER_TYPES = frozenset(("Episode", "Sequence", "Shot", "Asset"))

# ---------------------------------------------------------------------------
# Decisions and description prefixes (Requirements 4.3, 4.4, 13.1)
# ---------------------------------------------------------------------------

DECISION_APPLIED = "applied"
DECISION_SKIPPED = "skipped"
DECISION_CONFLICT = "conflict"
DECISION_FAILED = "failed"
DECISIONS = (
    DECISION_APPLIED,
    DECISION_SKIPPED,
    DECISION_CONFLICT,
    DECISION_FAILED,
)

DESCRIPTION_APPLIED = "Applied:"
DESCRIPTION_SKIPPED = "Skipped:"
DESCRIPTION_CONFLICT = "Conflict:"
DESCRIPTION_FAILED = "Failed:"

#: Printed for an unset value or a missing Kitsu id (Requirements 10.6,
#: 13.1, 13.2).
NONE_VALUE = "none"

#: Recorded as the source user when the event carries none (13.5).
UNKNOWN_USER = "unknown"

#: Kitsu fields whose list values are unordered sets of person ids. They
#: compare as sets (5.4, 9.1) and print sorted by person name (13.2).
UNORDERED_FIELDS = frozenset(("assignees",))

# ---------------------------------------------------------------------------
# Skip reasons (Requirement 4.4). Templates use ``str.format`` fields.
# ---------------------------------------------------------------------------

#: Requirement 5.1.
SKIP_SYNC_ORIGINATED = "sync originated"
#: Requirement 5.8.
SKIP_ORIGIN_UNKNOWN = "origin unknown"
#: Requirement 5.4 (whole event) and per-field label.
SKIP_ALREADY_IN_SYNC = "already in sync"
#: Requirement 5.9.
SKIP_LOOP_SUSPECTED = "loop suspected"
#: Requirement 11.7.
SKIP_ALREADY_PAIRED = "entity is already paired"
#: Requirement 3.2. Fields: ``entity_id``.
SKIP_NO_KITSU_ID = "AYON entity {entity_id} has no Kitsu id"
#: Requirement 3.3. Fields: ``project_name``.
SKIP_NOT_PAIRED = "project {project_name} is not a paired project"
#: Requirement 3.6. Fields: ``entity_id``, ``kitsu_id``.
SKIP_STRUCTURAL_FOLDER = (
    "structural folder {entity_id} (Kitsu id {kitsu_id}) is not synced"
)
#: Requirement 4.10. Fields: ``entity_id``.
SKIP_ENTITY_GONE = "AYON entity {entity_id} no longer exists"
#: Requirements 2.8, 4.8. Fields: ``category``.
SKIP_DISABLED_AT_CREATION = "{category} disabled at event creation time"
#: Design gap 1: no toggle observation before the event. Fields:
#: ``category``.
SKIP_DISABLED_NO_HISTORY = (
    "{category} disabled at event creation time (no recorded toggle state)"
)
#: Requirement 4.12.
SKIP_UNKNOWN_TOGGLE_STATE = (
    "toggle state was unknown while the Processor was stopped"
)
#: Requirement 2.3. Fields: ``project_name``.
SKIP_MASTER_DISABLED = "outbound sync disabled for project {project_name}"
#: Requirement 2.4. Fields: ``category``.
SKIP_CATEGORY_DISABLED = "{category} disabled"
#: Requirement 2.10: settings invalid, treated as disabled. Fields:
#: ``project_name``, ``error``.
SKIP_SETTINGS_INVALID = (
    "outbound sync settings invalid for project {project_name}: {error}"
)
#: Requirement 10.7. Fields: ``job_ids`` (comma separated).
SKIP_SUPERSEDED = "every retried field was written by newer job {job_ids}"
#: Requirement 12.6.
SKIP_OUT_OF_SCOPE_DELETION = "project and person deletion is out of scope"
#: Topic without a Sync_Category mapping. Fields: ``topic``.
SKIP_UNHANDLED_TOPIC = "topic {topic} carries no Sync_Category"

# ---------------------------------------------------------------------------
# Error kinds (design "Data Models", "Error kinds")
# ---------------------------------------------------------------------------

ERROR_UNREACHABLE = "unreachable"
ERROR_SERVER = "server_error"
ERROR_SERVER_ERROR = ERROR_SERVER
ERROR_INTERRUPTED = "interrupted"
ERROR_PERMISSION = "permission"
ERROR_NOT_FOUND = "not_found"
ERROR_REJECTED = "rejected"
ERROR_IDENTITY = "identity"
ERROR_MAPPING = "mapping"
ERROR_INVALID_FRAME_RANGE = "invalid_frame_range"
ERROR_INTERNAL = "internal"

#: Retryable kinds: Kitsu unreachable (connection refused, DNS failure,
#: 30 s timeout), Kitsu HTTP 500 to 599, and an attempt interrupted by a
#: Processor stop (Requirements 10.1, 10.2, 10.9).
RETRYABLE_KINDS = (ERROR_UNREACHABLE, ERROR_SERVER, ERROR_INTERRUPTED)

#: Kinds that are final on the attempt where they occur (10.3, 10.4, 10.6).
FINAL_KINDS = (
    ERROR_PERMISSION,
    ERROR_NOT_FOUND,
    ERROR_REJECTED,
    ERROR_IDENTITY,
    ERROR_MAPPING,
    ERROR_INVALID_FRAME_RANGE,
    ERROR_INTERNAL,
)

# ---------------------------------------------------------------------------
# Limits (seconds unless noted)
# ---------------------------------------------------------------------------

#: Attempts per Outbound_Job, counted in ``summary.attempt`` (10.2).
MAX_ATTEMPTS = 4
#: ``max_retries`` for the enroll call. Enroll allows one attempt more than
#: this counter (F17), so the runner decides from ``summary.attempt``.
MAX_RETRIES = MAX_ATTEMPTS - 1
#: retries value set on final failure so enroll never restarts the job (10.6).
FINAL_RETRIES_VALUE = MAX_RETRIES + 1

#: Earliest and latest start of a retry after a failed attempt (10.2).
RETRY_DELAY_S = 10
RETRY_DEADLINE_S = 60

#: An unfinished job of another sender idle this long is reaped (4.9).
STALE_AFTER_S = 300
#: How often the reaper runs.
REAP_INTERVAL_S = 60

#: Retry interval of a failed AYON request, at most 5 s (4.11).
AYON_RETRY_S = 2
#: Timeout of an AYON request (4.11).
AYON_TIMEOUT_S = 30

#: Timeout of every Kitsu request of the dedicated gazu client (10.1).
KITSU_TIMEOUT_S = 30

#: Settings refresh and gate heartbeat interval, at most 60 s (2.7).
SETTINGS_REFRESH_S = 30

#: Idle sleep of the main loop, below the 5 s bound of 4.6.
IDLE_SLEEP_S = 2

#: Cache lifetime of Kitsu statuses and persons read by the handlers.
KITSU_CACHE_S = 60

#: Loop guard (5.9): the 3rd write within 60 s opens a 300 s suppression.
LOOP_GUARD_MAX_WRITES = 3
LOOP_GUARD_WINDOW_S = 60
LOOP_GUARD_SUPPRESS_S = 300
