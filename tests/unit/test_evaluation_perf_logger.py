"""Tests for evaluation/perf_logger.py — per-stage timing."""

import json
import os

from evaluation.perf_logger import (
    read_perf_log,
    record_stage,
    summarize_job_perf,
)


def test_record_and_read(tmp_path, monkeypatch):
    """Record stages and read them back."""
    monkeypatch.chdir(tmp_path)
    os.makedirs("outputs/test-job", exist_ok=True)

    record_stage("test-job", "scout", "start")
    record_stage("test-job", "scout", "end")
    record_stage("test-job", "forge", "start")
    record_stage("test-job", "forge", "end")

    entries = read_perf_log("test-job")
    assert len(entries) == 4
    assert entries[0]["stage"] == "scout"
    assert entries[0]["status"] == "start"
    assert entries[1]["stage"] == "scout"
    assert entries[1]["status"] == "end"


def test_record_with_metadata(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    os.makedirs("outputs/test-job", exist_ok=True)

    record_stage("test-job", "llm", "end", metadata={"tokens": 150, "cost": 0.003})
    entries = read_perf_log("test-job")
    assert len(entries) == 1
    assert entries[0]["tokens"] == 150
    assert entries[0]["cost"] == 0.003


def test_read_perf_log_empty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    entries = read_perf_log("nonexistent-job")
    assert entries == []


def test_summarize_job_perf(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    os.makedirs("outputs/test-job", exist_ok=True)

    record_stage("test-job", "scout", "start")
    record_stage("test-job", "scout", "end")
    record_stage("test-job", "planner", "skipped")

    summary = summarize_job_perf("test-job")
    assert "scout" in summary
    assert "planner" in summary
    assert summary["planner"]["status"] == "skipped"
    assert summary["planner"]["duration_s"] == 0.0
    assert summary["scout"]["status"] == "completed"
    assert summary["scout"]["duration_s"] >= 0.0


def test_summarize_incomplete(tmp_path, monkeypatch):
    """A stage with only start (no end) should be 'incomplete'."""
    monkeypatch.chdir(tmp_path)
    os.makedirs("outputs/test-job", exist_ok=True)

    record_stage("test-job", "furnace", "start")

    summary = summarize_job_perf("test-job")
    assert summary["furnace"]["status"] == "incomplete"


def test_multiple_jobs_separate(tmp_path, monkeypatch):
    """Multiple jobs should not interfere."""
    monkeypatch.chdir(tmp_path)
    os.makedirs("outputs/job-a", exist_ok=True)
    os.makedirs("outputs/job-b", exist_ok=True)

    record_stage("job-a", "scout", "start")
    record_stage("job-b", "scout", "start")
    record_stage("job-b", "scout", "end")

    summary_a = summarize_job_perf("job-a")
    summary_b = summarize_job_perf("job-b")

    assert summary_a["scout"]["status"] == "incomplete"
    assert summary_b["scout"]["status"] == "completed"
