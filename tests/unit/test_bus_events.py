"""Unit tests for bus event type constants and stream/group names."""

from bus.events import (
    MISSION_BRIEF_READY,
    TRAINING_SCRIPT_READY,
    EPOCH_COMPLETE,
    TRAINING_COMPLETE,
    CRASH_EVENT,
    RESUME_TRAINING,
    EVALUATION_PASS,
    EVALUATION_RETRY,
    ESCALATE,
    ENDPOINT_LIVE,
    DRIFT_ALERT,
    JOB_FAILED,
    STREAM_SCOUT_OUTPUT,
    STREAM_FORGE_OUTPUT,
    STREAM_FURNACE_FEED,
    STREAM_FURNACE_OUTPUT,
    STREAM_FURNACE_CRASH,
    STREAM_DISSECT_OUTPUT,
    STREAM_ARBITER_OUTPUT,
    STREAM_HARBOR_OUTPUT,
    STREAM_ORCHESTRATOR_OUT,
    GROUP_ORCHESTRATOR,
)


def test_all_event_type_strings_match_expected():
    assert MISSION_BRIEF_READY == "MISSION_BRIEF_READY"
    assert TRAINING_SCRIPT_READY == "TRAINING_SCRIPT_READY"
    assert EPOCH_COMPLETE == "EPOCH_COMPLETE"
    assert TRAINING_COMPLETE == "TRAINING_COMPLETE"
    assert CRASH_EVENT == "CRASH_EVENT"
    assert RESUME_TRAINING == "RESUME_TRAINING"
    assert EVALUATION_PASS == "EVALUATION_PASS"
    assert EVALUATION_RETRY == "EVALUATION_RETRY"
    assert ESCALATE == "ESCALATE"
    assert ENDPOINT_LIVE == "ENDPOINT_LIVE"
    assert DRIFT_ALERT == "DRIFT_ALERT"
    assert JOB_FAILED == "JOB_FAILED"


def test_all_stream_names_are_non_empty():
    streams = [
        STREAM_SCOUT_OUTPUT,
        STREAM_FORGE_OUTPUT,
        STREAM_FURNACE_FEED,
        STREAM_FURNACE_OUTPUT,
        STREAM_FURNACE_CRASH,
        STREAM_DISSECT_OUTPUT,
        STREAM_ARBITER_OUTPUT,
        STREAM_HARBOR_OUTPUT,
        STREAM_ORCHESTRATOR_OUT,
    ]
    for s in streams:
        assert s, "Stream name is empty"
        assert len(s) > 0


def test_consumer_group_name():
    assert GROUP_ORCHESTRATOR == "orchestrator_consumers"


def test_event_types_are_unique():
    events = [
        MISSION_BRIEF_READY,
        TRAINING_SCRIPT_READY,
        EPOCH_COMPLETE,
        TRAINING_COMPLETE,
        CRASH_EVENT,
        RESUME_TRAINING,
        EVALUATION_PASS,
        EVALUATION_RETRY,
        ESCALATE,
        ENDPOINT_LIVE,
        DRIFT_ALERT,
        JOB_FAILED,
    ]
    assert len(events) == len(set(events)), "Event types must be unique"
