"""Property test for enrollment exclusion filter (Property 29).

Validates: Requirements 4.1, 5.13
"""

# Feature: kitsu-two-way-sync, Property 29: Sender-type exclusion is scoped
# to creation and deletion topics (Slice 3)

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from processor.outbound.constants import (
    ENROLL_EXCLUSION_TOPICS,
    KITSU_SYNC_SENDER_TYPE,
    OUT_OF_SCOPE_TOPICS,
    SLICE_1_TOPICS,
    SLICE_2_TOPICS,
    SLICE_3_TOPICS,
    TOPIC_CATEGORIES,
    TOPIC_FOLDER_CREATED,
    TOPIC_FOLDER_DELETED,
    TOPIC_PROJECT_DELETED,
    TOPIC_TASK_CREATED,
    TOPIC_TASK_DELETED,
    TOPIC_USER_DELETED,
)
from processor.outbound.origin import (
    build_enroll_filter,
    excluded_at_enrollment,
)

from .offline import block_network  # noqa: F401

pytestmark = pytest.mark.usefixtures("block_network")


def _resolve_event_val(event: dict, key: str):
    """Resolve field from event dict handling sender_type / senderType."""
    if key in event:
        return event[key]
    if key == "sender_type" and "senderType" in event:
        return event["senderType"]
    if key == "senderType" and "sender_type" in event:
        return event["sender_type"]
    return None


def evaluate_condition(condition: dict, event: dict) -> bool:
    """Evaluate a single leaf QueryCondition against an event dict."""
    key = condition.get("key")
    operator = condition.get("operator", "eq").lower()
    val = _resolve_event_val(event, key)
    target = condition.get("value")

    if operator == "eq":
        return val == target
    if operator == "ne":
        return val != target
    if operator == "in":
        return isinstance(target, list) and val in target
    if operator == "notin":
        return isinstance(target, list) and val not in target
    if operator == "isnull":
        return val is None
    if operator == "notnull":
        return val is not None
    raise ValueError(f"Unsupported operator: {operator}")


def evaluate_query_filter(query_filter: dict | None, event: dict) -> bool:
    """Evaluate a QueryFilter structure against an event dict.

    If query_filter is None, all events are accepted (returns True).
    Handles compound filters with 'and' or 'or' and leaf conditions.
    """
    if query_filter is None:
        return True

    operator = query_filter.get("operator", "and").lower()
    conditions = query_filter.get("conditions", [])
    if not conditions:
        return True

    results = []
    for c in conditions:
        if "conditions" in c:
            results.append(evaluate_query_filter(c, event))
        else:
            results.append(evaluate_condition(c, event))

    if operator == "and":
        return all(results)
    if operator == "or":
        return any(results)
    raise ValueError(f"Unknown filter operator: {operator}")


ALL_KNOWN_TOPICS = sorted(TOPIC_CATEGORIES.keys())

sender_type_st = st.one_of(
    st.none(),
    st.just(KITSU_SYNC_SENDER_TYPE),
    st.just("api"),
    st.just("kitsu-processor-host"),
    st.text(min_size=1, max_size=20),
)

topic_st = st.one_of(
    st.sampled_from(ALL_KNOWN_TOPICS),
    st.text(min_size=1, max_size=30),
)


@settings(max_examples=150, deadline=None)
@given(topic=topic_st, sender_type=sender_type_st)
def test_property_excluded_at_enrollment(topic, sender_type):
    """Property 29: excluded_at_enrollment is True iff topic is creation or
    deletion and sender_type is kitsu_sync.
    """
    res = excluded_at_enrollment(topic, sender_type)
    expected = (
        topic in ENROLL_EXCLUSION_TOPICS
        and sender_type == KITSU_SYNC_SENDER_TYPE
    )
    assert res == expected


@settings(max_examples=150, deadline=None)
@given(
    enrolled_topics=st.lists(
        st.sampled_from(ALL_KNOWN_TOPICS), min_size=0, max_size=10
    ),
    event_topic=st.sampled_from(ALL_KNOWN_TOPICS),
    sender_type=sender_type_st,
    use_camel_case=st.booleans(),
)
def test_property_enroll_filter_equivalence(
    enrolled_topics, event_topic, sender_type, use_camel_case
):
    """Property 29: QueryFilter accepts event iff not excluded.

    For any event whose topic is among enrolled topics, evaluating
    build_enroll_filter(enrolled_topics) with the reference QueryFilter
    evaluator accepts the event iff excluded_at_enrollment is False.
    """
    qfilter = build_enroll_filter(enrolled_topics)
    sender_key = "senderType" if use_camel_case else "sender_type"
    event = {"topic": event_topic, sender_key: sender_type}

    accepted = evaluate_query_filter(qfilter, event)

    if event_topic in enrolled_topics:
        expected_accepted = not excluded_at_enrollment(
            event_topic, sender_type
        )
        assert accepted == expected_accepted


@settings(max_examples=100, deadline=None)
@given(
    topic=st.sampled_from(SLICE_1_TOPICS + SLICE_2_TOPICS),
    sender_type=sender_type_st,
    enrolled_topics=st.lists(
        st.sampled_from(ALL_KNOWN_TOPICS), min_size=1, max_size=10
    ),
    use_camel_case=st.booleans(),
)
def test_property_slice1_and_slice2_never_excluded(
    topic, sender_type, enrolled_topics, use_camel_case
):
    """Property 29: Slice 1 & 2 topics are never excluded at enrollment."""
    # Never excluded by helper function
    assert excluded_at_enrollment(topic, sender_type) is False

    # Never excluded by filter even when enrolled alongside other topics
    qfilter = build_enroll_filter(enrolled_topics)
    sender_key = "senderType" if use_camel_case else "sender_type"
    event = {"topic": topic, sender_key: sender_type}
    assert evaluate_query_filter(qfilter, event) is True


def test_build_enroll_filter_empty_and_none():
    """Empty or None topics produce None filter."""
    assert build_enroll_filter([]) is None
    assert build_enroll_filter(None) is None
    assert build_enroll_filter(["unknown.topic"]) is None


def test_build_enroll_filter_slices():
    """Slices 1 and 2 produce None, Slice 3 produces 4 conditions."""
    assert build_enroll_filter(list(SLICE_1_TOPICS)) is None
    assert build_enroll_filter(list(SLICE_2_TOPICS)) is None
    assert build_enroll_filter(list(SLICE_1_TOPICS + SLICE_2_TOPICS)) is None

    f = build_enroll_filter(list(SLICE_3_TOPICS))
    assert f is not None
    assert f["operator"] == "and"
    assert len(f["conditions"]) == 4

    topics_in_filter = {
        cond["conditions"][0]["value"] for cond in f["conditions"]
    }
    assert topics_in_filter == set(ENROLL_EXCLUSION_TOPICS)

    for cond in f["conditions"]:
        assert cond["operator"] == "or"
        assert len(cond["conditions"]) == 2
        assert cond["conditions"][0]["key"] == "topic"
        assert cond["conditions"][0]["operator"] == "ne"
        assert cond["conditions"][1]["key"] == "sender_type"
        assert cond["conditions"][1]["operator"] == "ne"
        assert cond["conditions"][1]["value"] == KITSU_SYNC_SENDER_TYPE


def test_out_of_scope_topics_not_excluded():
    """Project and user deletion topics are never excluded at enrollment."""
    for topic in (TOPIC_PROJECT_DELETED, TOPIC_USER_DELETED):
        assert topic in OUT_OF_SCOPE_TOPICS
        assert topic not in ENROLL_EXCLUSION_TOPICS
        assert excluded_at_enrollment(topic, KITSU_SYNC_SENDER_TYPE) is False


def test_all_four_exclusion_topics_evaluated():
    """Each of the four exclusion topics is properly excluded."""
    expected_exclusions = {
        TOPIC_FOLDER_CREATED,
        TOPIC_TASK_CREATED,
        TOPIC_FOLDER_DELETED,
        TOPIC_TASK_DELETED,
    }
    assert ENROLL_EXCLUSION_TOPICS == expected_exclusions

    f = build_enroll_filter(list(ENROLL_EXCLUSION_TOPICS))
    for topic in expected_exclusions:
        # Excluded when sender_type == "kitsu_sync"
        assert excluded_at_enrollment(topic, KITSU_SYNC_SENDER_TYPE) is True
        event = {"topic": topic, "sender_type": KITSU_SYNC_SENDER_TYPE}
        assert evaluate_query_filter(f, event) is False

        # Accepted when sender_type != "kitsu_sync"
        assert excluded_at_enrollment(topic, "api") is False
        event_api = {"topic": topic, "sender_type": "api"}
        assert evaluate_query_filter(f, event_api) is True

        # Accepted when sender_type is None
        assert excluded_at_enrollment(topic, None) is False
        event_none = {"topic": topic, "sender_type": None}
        assert evaluate_query_filter(f, event_none) is True
