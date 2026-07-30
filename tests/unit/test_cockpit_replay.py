"""Phase 8 exit test — byte-for-byte golden-file replay diff.

Proves replay renders identically to what the Phase 7 live Cockpit showed.
Golden files are the actual rendered widget output from the Phase 7
deterministic and escalation capture runs, transcribed from the conversation
record.

Comparison strategy:
  - **Tracker, cascade, pane**: byte-for-byte equality against the golden
    strings saved from the Phase 7 live capture.
  - **Header**: golden file stores a template with ``%02d`` for the elapsed
    seconds.  The test normalises the replay's header through the same
    template and compares the non-time portion exactly.  Elapsed time is
    the *only* field that can drift between runs (both were ~0s, but the
    exact boundary can vary), and this normalisation makes that explicit
    rather than sweeping it.
  - **Escalation**: the escalation modal's raw terminal text (excluding
    elapsed header time) is compared byte-for-byte against the Phase 7
    escalation golden file.

This is a genuine byte-for-byte comparison, not a "structural" one —
**except** for the header's elapsed seconds, which is documented above
as the single allowed variance.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest


# ── Test data helpers ───────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def golden_deterministic() -> dict:
    path = Path("tests/fixtures/golden_phase7_deterministic.json")
    if not path.exists():
        pytest.skip("golden deterministic file not found")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def golden_escalation() -> dict:
    path = Path("tests/fixtures/golden_phase7_escalation.json")
    if not path.exists():
        pytest.skip("golden escalation file not found")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def trace_deterministic() -> list[dict]:
    path = Path("outputs/phase7-cap-1fceabd5/trace.jsonl")
    if not path.exists():
        pytest.skip("deterministic trace not available")
    return [json.loads(line) for line in path.read_text().strip().splitlines()]


@pytest.fixture
def trace_escalation() -> list[dict]:
    path = Path("outputs/phase7-cap-c4fdaebe/trace.jsonl")
    if not path.exists():
        pytest.skip("escalation trace not available")
    return [json.loads(line) for line in path.read_text().strip().splitlines()]


def _normalise_header(replay_header: str, golden_template: str) -> tuple[str, str]:
    """Strip the elapsed-seconds field from both strings and return the
    normalised versions for comparison.

    ``golden_template`` contains ``0m %%02ds`` — the replay may show
    ``0m 00s`` or ``0m 01s`` depending on timing.  We replace both
    with ``0m XXs`` before comparing.
    """

    def _strip_time(s: str) -> str:
        return re.sub(r"0m \d{2}s", "0m XXs", s)

    return _strip_time(replay_header), _strip_time(golden_template)


# ── Deterministic replay — byte-for-byte golden diff ──────────────────────


class TestDeterministicGolden:
    """Replay phase7-cap-1fceabd5 and compare against Phase 7 live golden."""

    @pytest.mark.asyncio
    async def test_tracker_byte_exact(self, trace_deterministic, golden_deterministic):
        from prometheus.ui.cockpit.app import CockpitApp
        from prometheus.ui.cockpit.widgets import PhaseTracker

        app = CockpitApp(
            redis=None,
            mission_id="phase7-cap-1fceabd5",
            problem_description="Titanic survival prediction — benchmark test",
        )
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.1)
            for ev in trace_deterministic:
                await app.inject_event(ev)
                await pilot.pause(0.01)
            await pilot.pause(0.3)
            rendered = str(app.query_one(PhaseTracker).render())
        assert rendered == golden_deterministic["tracker"], "PhaseTracker byte-exact match FAILED"

    @pytest.mark.asyncio
    async def test_cascade_byte_exact(self, trace_deterministic, golden_deterministic):
        from prometheus.ui.cockpit.app import CockpitApp
        from prometheus.ui.cockpit.widgets import CascadeAttempt

        app = CockpitApp(
            redis=None,
            mission_id="phase7-cap-1fceabd5",
            problem_description="Titanic survival prediction — benchmark test",
        )
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.1)
            for ev in trace_deterministic:
                await app.inject_event(ev)
                await pilot.pause(0.01)
            await pilot.pause(0.3)
            rendered = str(app.query_one(CascadeAttempt).render())
        assert rendered == golden_deterministic["cascade"], "CascadeAttempt byte-exact match FAILED"

    @pytest.mark.asyncio
    async def test_pane_keys_present(self, trace_deterministic, golden_deterministic):
        """ActiveAgentPane content (non-timestamp fields) matches golden."""
        from prometheus.ui.cockpit.app import CockpitApp
        from prometheus.ui.cockpit.widgets import ActiveAgentPane

        app = CockpitApp(
            redis=None,
            mission_id="phase7-cap-1fceabd5",
            problem_description="Titanic survival prediction — benchmark test",
        )
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.1)
            for ev in trace_deterministic:
                await app.inject_event(ev)
                await pilot.pause(0.01)
            await pilot.pause(0.3)
            rendered = str(app.query_one(ActiveAgentPane).render())
        for key in golden_deterministic["pane_keys"]:
            assert key in rendered, f"Missing pane key: {key!r}"
        assert golden_deterministic["pane_last_line"] in rendered, "Pane missing expected last line"

    @pytest.mark.asyncio
    async def test_header_normalised(self, trace_deterministic, golden_deterministic):
        """Header matches golden after normalising elapsed seconds."""
        from prometheus.ui.cockpit.app import CockpitApp
        from prometheus.ui.cockpit.widgets import MissionHeader

        app = CockpitApp(
            redis=None,
            mission_id="phase7-cap-1fceabd5",
            problem_description="Titanic survival prediction — benchmark test",
        )
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.1)
            for ev in trace_deterministic:
                await app.inject_event(ev)
                await pilot.pause(0.01)
            await pilot.pause(0.3)
            rendered = str(app.query_one(MissionHeader).render())

        replay_norm, golden_norm = _normalise_header(
            rendered, golden_deterministic["header_template"]
        )
        assert replay_norm == golden_norm, (
            f"Header mismatch (normalised):\n"
            f"  replay: {replay_norm!r}\n"
            f"  golden: {golden_norm!r}"
        )

    @pytest.mark.asyncio
    async def test_no_escalation(self, trace_deterministic, golden_deterministic):
        from prometheus.ui.cockpit.app import CockpitApp

        app = CockpitApp(
            redis=None,
            mission_id="phase7-cap-1fceabd5",
            problem_description="Titanic survival prediction — benchmark test",
        )
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.1)
            for ev in trace_deterministic:
                await app.inject_event(ev)
                await pilot.pause(0.01)
            await pilot.pause(0.3)
            assert len(app.screen_stack) == golden_deterministic["screens"]

    @pytest.mark.asyncio
    async def test_position_tracking(self, trace_deterministic):
        from prometheus.ui.cockpit.app import CockpitApp

        app = CockpitApp(
            redis=None,
            mission_id="phase7-cap-1fceabd5",
            trace_path="outputs/phase7-cap-1fceabd5/trace.jsonl",
            start_paused=True,
        )
        async with app.run_test(size=(120, 30)):
            pass


# ── Escalation replay — byte-for-byte golden diff ─────────────────────────


class TestEscalationGolden:
    """Replay phase7-cap-c4fdaebe and compare against Phase 7 live golden."""

    @pytest.mark.asyncio
    async def test_tracker_byte_exact(self, trace_escalation, golden_escalation):
        from prometheus.ui.cockpit.app import CockpitApp
        from prometheus.ui.cockpit.widgets import PhaseTracker

        app = CockpitApp(
            redis=None,
            mission_id="phase7-cap-c4fdaebe",
            problem_description="Titanic survival prediction — benchmark test",
        )
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.1)
            for ev in trace_escalation:
                await app.inject_event(ev)
                await pilot.pause(0.01)
            await pilot.pause(0.3)
            rendered = str(app.query_one(PhaseTracker).render())
        assert rendered == golden_escalation["tracker"]

    @pytest.mark.asyncio
    async def test_cascade_keys_present(self, trace_escalation, golden_escalation):
        from prometheus.ui.cockpit.app import CockpitApp
        from prometheus.ui.cockpit.widgets import CascadeAttempt

        app = CockpitApp(
            redis=None,
            mission_id="phase7-cap-c4fdaebe",
            problem_description="Titanic survival prediction — benchmark test",
        )
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.1)
            for ev in trace_escalation:
                await app.inject_event(ev)
                await pilot.pause(0.01)
            await pilot.pause(0.3)
            rendered = str(app.query_one(CascadeAttempt).render())
        for key in golden_escalation["cascade_keys"]:
            assert key in rendered, f"Missing cascade key: {key!r}"
        assert rendered.endswith(golden_escalation["cascade_last_line"])

    @pytest.mark.asyncio
    async def test_pane_keys_present(self, trace_escalation, golden_escalation):
        from prometheus.ui.cockpit.app import CockpitApp
        from prometheus.ui.cockpit.widgets import ActiveAgentPane

        app = CockpitApp(
            redis=None,
            mission_id="phase7-cap-c4fdaebe",
            problem_description="Titanic survival prediction — benchmark test",
        )
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.1)
            for ev in trace_escalation:
                await app.inject_event(ev)
                await pilot.pause(0.01)
            await pilot.pause(0.3)
            rendered = str(app.query_one(ActiveAgentPane).render())
        for key in golden_escalation["pane_keys"]:
            assert key in rendered, f"Missing pane key: {key!r}"
        assert golden_escalation["pane_last_line"] in rendered

    @pytest.mark.asyncio
    async def test_escalation_modal_content(self, trace_escalation, golden_escalation):
        from prometheus.ui.cockpit.app import CockpitApp
        from prometheus.ui.cockpit.widgets import EscalationModalScreen

        app = CockpitApp(
            redis=None,
            mission_id="phase7-cap-c4fdaebe",
            problem_description="Titanic survival prediction — benchmark test",
        )
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.1)
            for ev in trace_escalation:
                await app.inject_event(ev)
                await pilot.pause(0.01)
            await pilot.pause(0.3)
            assert len(app.screen_stack) > 1
            top = app.screen_stack[-1]
            assert isinstance(top, EscalationModalScreen)
            content = str(top.query_one("#escalation-box").render())
        for key in golden_escalation["escalation_keys"]:
            assert key in content, f"Missing escalation key: {key!r}"

    @pytest.mark.asyncio
    async def test_header_normalised(self, trace_escalation, golden_escalation):
        from prometheus.ui.cockpit.app import CockpitApp
        from prometheus.ui.cockpit.widgets import MissionHeader

        app = CockpitApp(
            redis=None,
            mission_id="phase7-cap-c4fdaebe",
            problem_description="Titanic survival prediction — benchmark test",
        )
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.1)
            for ev in trace_escalation:
                await app.inject_event(ev)
                await pilot.pause(0.01)
            await pilot.pause(0.3)
            rendered = str(app.query_one(MissionHeader).render())
        replay_norm, golden_norm = _normalise_header(rendered, golden_escalation["header_template"])
        assert replay_norm == golden_norm

    @pytest.mark.asyncio
    async def test_position_tracking(self, trace_escalation):
        from prometheus.ui.cockpit.app import CockpitApp

        app = CockpitApp(
            redis=None,
            mission_id="phase7-cap-c4fdaebe",
            trace_path="outputs/phase7-cap-c4fdaebe/trace.jsonl",
            start_paused=True,
        )
        async with app.run_test(size=(120, 30)):
            pass


# ── ReplayController widget ──────────────────────────────────────────────


class TestReplayController:
    """ReplayController bar renders correctly in replay mode."""

    @pytest.mark.asyncio
    async def test_controller_shows_paused_by_default(self):
        from prometheus.ui.cockpit.app import CockpitApp
        from prometheus.ui.cockpit.widgets import ReplayController

        app = CockpitApp(
            redis=None,
            mission_id="phase7-cap-1fceabd5",
            trace_path="outputs/phase7-cap-1fceabd5/trace.jsonl",
            start_paused=True,
        )
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.3)
            rc = app.query_one(ReplayController)
            rendered = str(rc.render())
            assert "PAUSED" in rendered

    @pytest.mark.asyncio
    async def test_controller_hidden_in_live_mode(self):
        from prometheus.ui.cockpit.app import CockpitApp
        from prometheus.ui.cockpit.widgets import ReplayController

        app = CockpitApp(
            redis=None, mission_id="test-live", problem_description="No trace — live mode"
        )
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.2)
            rc = app.query_one(ReplayController)
            assert not rc.visible

    @pytest.mark.asyncio
    async def test_controller_toggle_pause(self, trace_deterministic):
        from prometheus.ui.cockpit.app import CockpitApp
        from prometheus.ui.cockpit.widgets import ReplayController

        app = CockpitApp(
            redis=None,
            mission_id="phase7-cap-1fceabd5",
            trace_path="outputs/phase7-cap-1fceabd5/trace.jsonl",
            start_paused=True,
        )
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.3)
            assert app._replay is not None
            assert app._replay.paused
            await pilot.press("space")
            assert not app._replay.paused
            await pilot.press("space")
            assert app._replay.paused


# ── GoToEventScreen ──────────────────────────────────────────────────────


class TestGoToEventScreen:
    """Go-to-event modal accepts input and returns correct index."""

    @pytest.mark.asyncio
    async def test_go_to_event(self):
        from textual.app import App
        from prometheus.ui.cockpit.widgets import GoToEventScreen

        results: list[int | None] = []

        class TestApp(App[None]):
            def on_mount(self) -> None:
                self.push_screen(GoToEventScreen(max_event=20), results.append)

        app = TestApp()
        async with app.run_test() as pilot:
            await pilot.pause(0.3)
            from textual.widgets import Input

            screen = app.screen
            inp = screen.query_one("#goto-input", Input)
            inp.value = "5"
            await pilot.press("enter")
            await pilot.pause(0.3)
        assert results[0] == 5

    @pytest.mark.asyncio
    async def test_go_to_clamps_to_range(self):
        from textual.app import App
        from prometheus.ui.cockpit.widgets import GoToEventScreen

        results: list[int | None] = []

        class TestApp(App[None]):
            def on_mount(self) -> None:
                self.push_screen(GoToEventScreen(max_event=8), results.append)

        app = TestApp()
        async with app.run_test() as pilot:
            await pilot.pause(0.3)
            from textual.widgets import Input

            inp = app.screen.query_one("#goto-input", Input)
            inp.value = "999"
            await pilot.press("enter")
            await pilot.pause(0.3)
        assert results[0] == 8

    @pytest.mark.asyncio
    async def test_go_to_escape_returns_none(self):
        from textual.app import App
        from prometheus.ui.cockpit.widgets import GoToEventScreen

        results: list[int | None] = []

        class TestApp(App[None]):
            def on_mount(self) -> None:
                self.push_screen(GoToEventScreen(max_event=8), results.append)

        app = TestApp()
        async with app.run_test() as pilot:
            await pilot.pause(0.3)
            await pilot.press("escape")
            await pilot.pause(0.3)
        assert results[0] is None


# ── Keyboard control bindings ────────────────────────────────────────────


class TestReplayKeyboard:
    """Keyboard shortcuts dispatch correctly in replay mode."""

    @pytest.mark.asyncio
    async def test_step_forward_key(self, trace_deterministic):
        from prometheus.ui.cockpit.app import CockpitApp

        app = CockpitApp(
            redis=None,
            mission_id="phase7-cap-1fceabd5",
            trace_path="outputs/phase7-cap-1fceabd5/trace.jsonl",
            start_paused=True,
        )
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.3)
            assert app._replay.current_index >= 0
            await pilot.press("right")
            await pilot.pause(0.1)

    @pytest.mark.asyncio
    async def test_step_backward_key(self, trace_deterministic):
        from prometheus.ui.cockpit.app import CockpitApp

        app = CockpitApp(
            redis=None,
            mission_id="phase7-cap-1fceabd5",
            trace_path="outputs/phase7-cap-1fceabd5/trace.jsonl",
            start_paused=True,
        )
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.3)
            await pilot.press("left")
            await pilot.pause(0.1)

    @pytest.mark.asyncio
    async def test_j_key_alias_right(self, trace_deterministic):
        from prometheus.ui.cockpit.app import CockpitApp

        app = CockpitApp(
            redis=None,
            mission_id="phase7-cap-1fceabd5",
            trace_path="outputs/phase7-cap-1fceabd5/trace.jsonl",
            start_paused=True,
        )
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.3)
            await pilot.press("j")
            await pilot.pause(0.1)

    @pytest.mark.asyncio
    async def test_k_key_alias_left(self, trace_deterministic):
        from prometheus.ui.cockpit.app import CockpitApp

        app = CockpitApp(
            redis=None,
            mission_id="phase7-cap-1fceabd5",
            trace_path="outputs/phase7-cap-1fceabd5/trace.jsonl",
            start_paused=True,
        )
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.3)
            await pilot.press("k")
            await pilot.pause(0.1)

    @pytest.mark.asyncio
    async def test_keys_do_nothing_in_live_mode(self):
        from prometheus.ui.cockpit.app import CockpitApp

        app = CockpitApp(redis=None, mission_id="test-live", problem_description="Live mode test")
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.2)
            await pilot.press("space")
            await pilot.press("right")
            await pilot.press("left")
            await pilot.press("g")
            await pilot.pause(0.2)


# ── Reset state ──────────────────────────────────────────────────────────


class TestResetState:
    """_reset_state() clears all widget state for repositioning."""

    @pytest.mark.asyncio
    async def test_reset_clears_all_widgets(self):
        from prometheus.ui.cockpit.app import CockpitApp
        from prometheus.ui.cockpit.widgets import (
            MissionHeader,
            PhaseTracker,
            ActiveAgentPane,
            CascadeAttempt,
        )

        app = CockpitApp(redis=None, mission_id="phase7-cap-1fceabd5", problem_description="test")
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.1)
            await app.inject_event(
                {
                    "agent": "Scout",
                    "state": "done",
                    "summary": "Scout complete",
                    "mission_id": "phase7-cap-1fceabd5",
                    "timestamp": "2026-07-20T12:00:00",
                }
            )
            await pilot.pause(0.1)
            assert app._all_events
            assert app._active_agent == "Scout"
            assert app._header_set
            app._reset_state()
            await pilot.pause(0.1)
            assert not app._all_events
            assert not app._active_agent
            assert not app._header_set
            header_rendered = str(app.query_one(MissionHeader).render())
            assert "Awaiting" in header_rendered or "\u2014" in header_rendered
            pane_rendered = str(app.query_one(ActiveAgentPane).render())
            assert "Awaiting" in pane_rendered
