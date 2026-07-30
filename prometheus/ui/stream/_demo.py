"""Visual demo of the scroll-forward streaming renderer.

Run: python prometheus/ui/stream/_demo.py

This simulates a full mission lifecycle to verify the visual output
without needing Redis or an actual pipeline run.
"""
from __future__ import annotations

import sys
import os
import time

# Ensure UTF-8 output on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from prometheus.ui.stream.agent_badge import (
    render_badge, render_subaction, render_thinking_line,
    render_thinking_summary, render_detail_line, text_to_ansi,
)
from prometheus.ui.stream.header import render_header, HEADER_LINE_COUNT, supports_cursor_movement
from prometheus.ui.stream.progress_bar import render_progress
from prometheus.ui.stream.transition import render_transition
from prometheus.ui.stream.summary_card import SummaryData, render_summary
from prometheus.ui.stream.cost_tracker import render_completion_line, emit_bell
from prometheus.ui.stream.thinking_stream import ThinkingStream


def emit(text):
    """Print a line permanently (simulate _emit_permanent)."""
    if hasattr(text, 'plain'):
        text = text_to_ansi(text)
    sys.stdout.write(f"\r\033[K{text}\n")
    sys.stdout.flush()


def main():
    width = 80
    try:
        width = os.get_terminal_size().columns
    except (OSError, AttributeError):
        pass

    tick = time.monotonic()
    agent_states = {a: "pending" for a in ["Scout", "Forge", "Furnace", "Dissect", "Arbiter", "Harbor"]}

    # ── Print header ──
    header = render_header("fraud-detect-a3f9", agent_states, "starting", 0, tick, width)
    sys.stdout.write(header + "\n")
    sys.stdout.flush()
    lines_since = 0

    emit("")
    lines_since += 1
    time.sleep(0.3)

    # ── Scout ──
    agent_states["Scout"] = "running"
    badge = render_badge("Scout", "active", "Profiling dataset…", 0, tick)
    emit(badge)
    lines_since += 1
    time.sleep(0.2)

    emit(render_subaction("Loading CSV: fraud_data.csv (50,000 rows)", state="running"))
    lines_since += 1
    time.sleep(0.2)

    emit(render_subaction("Detected 15 features, 2 categorical", state="planning"))
    lines_since += 1
    time.sleep(0.2)

    emit(render_subaction("Task: binary_classification  Confidence: 94%", state="done"))
    lines_since += 1

    # Finalize Scout
    agent_states["Scout"] = "complete"
    badge = render_badge("Scout", "done", "Dataset profiled", 12.3, tick)
    emit(badge)
    lines_since += 1

    emit(render_detail_line("", "task=binary_classification  modality=tabular  confidence=0.94"))
    lines_since += 1

    # ── Transition ──
    emit("")
    lines_since += 1
    emit(render_transition("Scout", "Forge", "dataset profiled", width))
    lines_since += 1
    emit("")
    lines_since += 1
    time.sleep(0.3)

    # Update header
    header = render_header("fraud-detect-a3f9", agent_states, "running", 13, tick + 13, width)
    if supports_cursor_movement():
        pass

    # ── Forge ──
    agent_states["Forge"] = "running"
    badge = render_badge("Forge", "active", "Selecting architecture…", 0, tick)
    emit(badge)
    lines_since += 1
    time.sleep(0.2)

    emit(render_subaction("Evaluating candidates: LightGBM, XGBoost, RandomForest", state="running"))
    lines_since += 1
    time.sleep(0.2)

    emit(render_subaction("Selected: LightGBM (confidence: 0.92)", state="done"))
    lines_since += 1

    agent_states["Forge"] = "complete"
    badge = render_badge("Forge", "done", "LightGBM selected", 8.7, tick)
    emit(badge)
    lines_since += 1

    emit(render_detail_line("", "architecture=lightgbm  confidence=0.92"))
    lines_since += 1

    # ── Transition ──
    emit("")
    lines_since += 1
    emit(render_transition("Forge", "Furnace", "architecture selected", width))
    lines_since += 1
    emit("")
    lines_since += 1
    time.sleep(0.3)

    # Update header
    header = render_header("fraud-detect-a3f9", agent_states, "running", 22, tick + 22, width)
    if supports_cursor_movement():
        pass

    # ── Furnace ──
    agent_states["Furnace"] = "running"
    badge = render_badge("Furnace", "active", "Training model…", 0, tick)
    emit(badge)
    lines_since += 1

    for pct in [0.1, 0.25, 0.48, 0.72, 0.95, 1.0]:
        fold = int(pct * 5) + 1
        epoch = int(pct * 10) + 1
        bar = render_progress("Training", pct, f"Fold {min(fold,5)}/5  Epoch {min(epoch,10)}/10")
        sys.stdout.write(f"\r\033[K{text_to_ansi(bar)}")
        sys.stdout.flush()
        time.sleep(0.15)

    sys.stdout.write("\n")
    lines_since += 1

    agent_states["Furnace"] = "complete"
    badge = render_badge("Furnace", "done", "Training complete", 45.2, tick)
    emit(badge)
    lines_since += 1

    emit(render_detail_line("", "best=0.9234  epoch=10/10"))
    lines_since += 1

    # ── Transition ──
    emit("")
    lines_since += 1
    emit(render_transition("Furnace", "Dissect", "training complete", width))
    lines_since += 1
    emit("")
    lines_since += 1
    time.sleep(0.3)

    # ── Dissect (with thinking stream) ──
    agent_states["Dissect"] = "running"
    badge = render_badge("Dissect", "active", "Auto-debugging…", 0, tick)
    emit(badge)
    lines_since += 1

    # Simulate thinking tokens
    tokens = (
        "The trained model shows a potential issue with the "
        "transaction_amount column. The distribution is heavily skewed "
        "with outliers beyond 3 standard deviations. I'll apply a "
        "log transform and retrain the affected fold."
    ).split(" ")

    ts = ThinkingStream()
    for token in tokens:
        ts.append_token(token + " ")
        complete = ts.drain_complete_lines(width=width - 16)
        for line in complete:
            emit(render_thinking_line(line))
            lines_since += 1
        tail = ts.render_active_tail(width=width - 16)
        if tail:
            sys.stdout.write(f"\r\033[K{text_to_ansi(render_thinking_line(tail))}")
            sys.stdout.flush()
        time.sleep(0.03)

    sys.stdout.write("\n")
    lines_since += 1

    emit(render_thinking_summary(ts.token_count))
    lines_since += 1

    agent_states["Dissect"] = "complete"
    badge = render_badge("Dissect", "done", "1 patch applied", 6.1, tick)
    emit(badge)
    lines_since += 1

    # ── Transition ──
    emit("")
    lines_since += 1
    emit(render_transition("Dissect", "Arbiter", "auto-patched", width))
    lines_since += 1
    emit("")
    lines_since += 1
    time.sleep(0.3)

    # ── Arbiter ──
    agent_states["Arbiter"] = "running"
    badge = render_badge("Arbiter", "active", "Evaluating model…", 0, tick)
    emit(badge)
    lines_since += 1

    emit(render_subaction("AUC-ROC: 0.9234 (≥ 0.9000 ✔)", state="done"))
    lines_since += 1
    emit(render_subaction("Decision: PASS", state="done"))
    lines_since += 1

    agent_states["Arbiter"] = "complete"
    badge = render_badge("Arbiter", "done", "PASS · AUC-ROC=0.9234", 3.2, tick)
    emit(badge)
    lines_since += 1

    # ── Transition ──
    emit("")
    lines_since += 1
    emit(render_transition("Arbiter", "Harbor", "model approved", width))
    lines_since += 1
    emit("")
    lines_since += 1
    time.sleep(0.3)

    # ── Harbor ──
    agent_states["Harbor"] = "running"
    badge = render_badge("Harbor", "active", "Deploying model…", 0, tick)
    emit(badge)
    lines_since += 1

    emit(render_subaction("Exporting to ONNX format", state="running"))
    lines_since += 1
    time.sleep(0.2)
    emit(render_subaction("Building Docker image", state="running"))
    lines_since += 1
    time.sleep(0.2)
    emit(render_subaction("Container started on port 8000", state="done"))
    lines_since += 1
    emit(render_subaction("Health check: ✔ (23ms)", state="done"))
    lines_since += 1

    agent_states["Harbor"] = "complete"
    badge = render_badge("Harbor", "done", "Model live", 18.5, tick)
    emit(badge)
    lines_since += 1

    emit(render_detail_line("", "endpoint=http://localhost:8000  format=onnx"))
    lines_since += 1

    # ── Final header update ──
    header = render_header("fraud-detect-a3f9", agent_states, "complete", 222, tick + 222, width)
    if supports_cursor_movement():
        pass

    # ── Summary card ──
    emit("")
    lines_since += 1

    data = SummaryData(
        mission_id="fraud-detect-a3f9",
        status="complete",
        winner_architecture="LightGBM",
        metric_name="AUC-ROC",
        metric_value=0.9234,
        threshold=0.9000,
        duration_seconds=222.0,
        dissect_patches=1,
        dissect_categories=["log_transform"],
        endpoint_url="http://localhost:8000",
        model_format="onnx",
        health_status="healthy",
        health_latency_ms=23.0,
    )
    summary = render_summary(data, width=width)
    sys.stdout.write(summary + "\n")

    emit("")

    comp = render_completion_line(222.0, 6, 847, 0.0234, True, width)
    sys.stdout.write(comp + "\n")

    emit_bell()
    print()


if __name__ == "__main__":
    main()
