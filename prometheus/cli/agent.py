from __future__ import annotations

import click

from prometheus.ui.renderers import renderer_from_ctx
from prometheus.ui.theme import Theme
from prometheus.utils.commands import AliasedGroup
from prometheus.utils.exit_codes import ExitCode


def _app(ctx: click.Context):
    return ctx.find_root().obj["app"]


@click.group(
    cls=AliasedGroup,
    name="agent",
    aliases={"ag": "agent", "ls": "list"},
    context_settings=dict(help_option_names=["--help", "-h"]),
)
def agent():
    """Manage AI agents in the swarm."""


@agent.command(name="list")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed info")
@click.option("--role", default=None, help="Filter by agent role")
@click.option("--status", default=None, help="Filter by agent status")
@click.pass_context
def agent_list(ctx, verbose, role, status):
    """List all registered agents with their status."""
    renderer = renderer_from_ctx(ctx)
    svc = _app(ctx).agents
    agents = svc.list_agents()
    if not agents:
        renderer.print("[dim]No agents registered.[/dim]")
        return ExitCode.SUCCESS

    if role:
        agents = [a for a in agents if (a.role or "").lower() == role.lower()]
    if status:
        agents = [a for a in agents if (a.status or "").lower() == status.lower()]

    if not agents:
        renderer.print("[dim]No agents match filters.[/dim]")
        return ExitCode.SUCCESS

    for a in agents:
        role_str = a.role or ""
        status_str = a.status or "idle"
        renderer.console.print(f"  {a.name:<8} {role_str:<40} {status_str}")
    return ExitCode.SUCCESS


@agent.command(name="inspect")
@click.argument("agent_name")
@click.option("--mission", "-m", default=None, help="Deep-link to a specific mission")
@click.pass_context
def agent_inspect(ctx, agent_name, mission):
    """Inspect a specific agent in detail."""
    renderer = renderer_from_ctx(ctx)
    svc = _app(ctx).agents
    detail = svc.inspect_agent(agent_name)
    if detail is None:
        renderer.error(f"Agent '{agent_name}' not found.", hint="prometheus agent list")
        return ExitCode.ERROR_NOT_FOUND

    items = [
        ("Name", detail.name),
        ("Display", detail.display_name),
        ("Role", detail.role),
        ("Status", detail.status),
        ("Version", detail.version),
        ("Tools", str(len(detail.tools))),
    ]
    if detail.capabilities:
        items.append(("Capabilities", ", ".join(detail.capabilities)))

    # Mission context: show agent events for that mission
    if mission:
        import json
        from pathlib import Path

        trace_file = Path("outputs") / mission / "trace.jsonl"
        mission_events = []
        if trace_file.exists():
            try:
                with open(trace_file, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            ev = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if (ev.get("agent") or "").lower() == agent_name.lower():
                            mission_events.append(ev)
            except OSError:
                pass
        items.append(("Mission events", str(len(mission_events)) if mission_events else "none"))
        items.append(("Mission ID", mission[:24]))

    renderer.status(items, title=f"Agent: {detail.name}")

    if detail.tools:
        renderer.print(f"\n  [bold]Tools ({len(detail.tools)}):[/]")
        for t in detail.tools:
            renderer.print(f"    \u2514\u2500 [dim]{t}[/dim]")
        renderer.print()
    return ExitCode.SUCCESS


@agent.command(name="logs")
@click.argument("agent_name")
@click.option("--lines", "-n", default=20, type=int)
@click.pass_context
def agent_logs(ctx, agent_name, lines):
    """Show agent execution logs."""
    renderer = renderer_from_ctx(ctx)
    renderer.print(f"[dim]Logs for {agent_name} ({lines} lines):[/dim]")
    try:
        log_path = _app(ctx).agents.root / agent_name / "agent.py"
        if log_path.exists():
            content = log_path.read_text().splitlines()
            start = max(0, len(content) - lines)
            for line in content[start:]:
                renderer.print(f"  [dim]{line}[/dim]")
        else:
            renderer.print(f"  [dim](no log data for {agent_name})[/dim]")
    except Exception:
        renderer.print(f"  [dim](no log data for {agent_name})[/dim]")
    return ExitCode.SUCCESS


@agent.command(name="metrics")
@click.pass_context
def agent_metrics(ctx):
    """Show agent performance metrics."""
    renderer = renderer_from_ctx(ctx)
    svc = _app(ctx).agents
    agents = svc.list_agents()
    if not agents:
        renderer.print("[dim]No agent metrics available.[/dim]")
        return ExitCode.SUCCESS
    items = [(a.name, f"{a.tools} tools, v{a.version}") for a in agents]
    renderer.status(items)
    return ExitCode.SUCCESS


def _state_color(state: str) -> str:
    """Map a trace event state to a terminal color."""
    if state in ("done", "complete", "success"):
        return "green"
    if state in ("error", "failed", "crashed"):
        return "red"
    return "yellow"


def _build_event_tree(
    events: list[tuple[str, dict]],
) -> list[dict]:
    """Build a tree from flat events using parent_event_id links.

    Returns a list of root nodes, each with a ``_children`` list of
    child nodes (same structure, recursive).  Each node is:
    ``{"mission_id": str, "event": dict, "_children": [...]}``.

    Events within the same mission are linked by ``parent_event_id``.
    Events with no parent or whose parent is not in the collection
    become root nodes.
    """
    # Index by event_id scoped to mission_id
    by_key: dict[tuple[str, str], dict] = {}
    for mid, ev in events:
        eid = ev.get("event_id") or ev.get("id", "")
        if eid:
            by_key[(mid, eid)] = {"mission_id": mid, "event": ev, "_children": []}

    roots: list[dict] = []
    orphan_ids: set[str] = set()

    for mid, ev in events:
        node_key = (mid, ev.get("event_id") or ev.get("id", ""))
        node = by_key.get(node_key)
        if node is None:
            # Event has no event_id — treat as root
            roots.append({"mission_id": mid, "event": ev, "_children": []})
            continue

        parent_id = ev.get("parent_event_id")
        if parent_id:
            parent_key = (mid, parent_id)
            parent = by_key.get(parent_key)
            if parent is not None:
                parent["_children"].append(node)
            else:
                # Parent not in collection or no event_id — orphan
                orphan_ids.add(node_key[1])
                roots.append(node)
        else:
            roots.append(node)

    return roots


def _render_event_tree(
    roots: list[dict],
    prefix: str = "",
    is_last: bool = True,
    depth: int = 0,
) -> list[str]:
    """Recursively render an event tree with tree-drawn connectors.

    Renders each root/child as::

        ── timestamp  STATE  summary
            ↳ ── timestamp  STATE  summary  (depth 1)
               ↳ ── timestamp  STATE  summary  (depth 2)
    """
    lines: list[str] = []
    for i, node in enumerate(roots):
        ev = node["event"]
        children = node["_children"]
        is_last_child = i == len(roots) - 1

        ts = (ev.get("timestamp") or "")[:19] if ev.get("timestamp") else ""
        state = ev.get("state", "")
        summary = (ev.get("summary") or ev.get("event") or "")[:80]
        dur = ev.get("duration_ms", 0)
        dur_str = f"  [{Theme.muted}]({dur}ms)[/]" if dur else ""
        parent_id = ev.get("parent_event_id", "")
        parent_str = f"  [{Theme.muted}]parent: {parent_id[:16]}[/]" if parent_id else ""

        state_color = _state_color(state)

        if depth == 0:
            connector = f"[{Theme.muted}]\u2500\u2500[/]"
        else:
            connector = f"[{Theme.muted}]\u21b3[/]"

        indent = "  " * depth
        line = (
            f"  {indent}{connector}"
            f"  [{Theme.muted}]{ts}[/]"
            f"  [{state_color}]{state}[/]"
            f"  {summary}"
            f"{dur_str}{parent_str}"
        )
        lines.append(line)

        if children:
            lines.extend(_render_event_tree(children, prefix, is_last_child, depth + 1))

    return lines


@agent.command(name="trace")
@click.argument("agent_name")
@click.option("--mission", "-m", required=True, help="Filter by mission ID")
@click.option("--lines", "-n", default=20, type=int, help="Number of recent events to show")
@click.option("--follow", "-f", is_flag=True, help="Follow new events in real time")
@click.option(
    "--export", "-o", default=None, type=click.Path(dir_okay=False), help="Export trace to file"
)
@click.pass_context
def agent_trace(
    ctx, agent_name: str, mission: str | None, lines: int, follow: bool, export: str | None
) -> ExitCode:
    """Show event trace for a specific agent across missions.

    Renders events as a tree with parent_event_id chains, showing
    the causal relationship between events (e.g., a crash event
    linking to its cascade attempts and resolution).
    """
    import json
    import time
    from pathlib import Path

    renderer = renderer_from_ctx(ctx)

    agent_lower = agent_name.lower()
    matched_events: list[tuple[str, dict]] = []

    for mid in [mission]:
        trace_file = Path("outputs") / mid / "trace.jsonl"
        if not trace_file.exists():
            continue
        try:
            with open(trace_file, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if (ev.get("agent") or "").lower() == agent_lower:
                        matched_events.append((mid, ev))
        except OSError:
            pass

    if not matched_events:
        renderer.error(
            f"No events found for agent '{agent_name}'. Start a mission first with `prometheus mission new`."
        )
        return ExitCode.ERROR_NOT_FOUND

    # Build tree and render
    roots = _build_event_tree(matched_events)
    tree_lines = _render_event_tree(roots)

    # Title
    if mission:
        renderer.print(f"  [bold]Agent: {agent_name}[/]  [{Theme.muted}]mission {mission[:24]}[/]")
    else:
        renderer.print(f"  [bold]Agent: {agent_name}[/]")

    renderer.print("")
    for line in tree_lines:
        renderer.print(line)

    label = f"  [{Theme.muted}]{len(matched_events)} event(s) in {len(roots)} chain(s)[/]"
    renderer.print(label)

    # Export mode: write matched events to file
    if export:
        import json as _json

        try:
            export_data = [{"mission_id": mid, **ev} for mid, ev in matched_events]
            with open(export, "w", encoding="utf-8") as ef:
                _json.dump(export_data, ef, indent=2)
            renderer.print(f"  [dim]Exported {len(export_data)} event(s) to {export}[/dim]")
        except OSError as e:
            renderer.error(f"Cannot write to {export}: {e}")
            return ExitCode.ERROR_GENERIC

    # Follow mode: tail new events from latest trace file
    if follow:
        latest_mid = matched_events[-1][0]
        trace_file = Path("outputs") / latest_mid / "trace.jsonl"
        if trace_file.exists():
            renderer.print(f"  [dim]Following new events for {agent_name}... Ctrl+C to stop[/dim]")
            try:
                pos = trace_file.stat().st_size
                while True:
                    time.sleep(1)
                    current_size = trace_file.stat().st_size
                    if current_size > pos:
                        with open(trace_file, encoding="utf-8") as f:
                            f.seek(pos)
                            for line in f:
                                line = line.strip()
                                if not line:
                                    continue
                                try:
                                    ev = json.loads(line)
                                except json.JSONDecodeError:
                                    continue
                                if (ev.get("agent") or "").lower() == agent_lower:
                                    ts = (ev.get("timestamp") or "")[:19]
                                    state = ev.get("state", "")
                                    summary = (ev.get("summary") or ev.get("event") or "")[:80]
                                    renderer.print(
                                        f"  [dim]{ts}[/dim] "
                                        f"[{_state_color(state)}]{state}[/] "
                                        f"{summary}"
                                    )
                        pos = current_size
            except KeyboardInterrupt:
                renderer.print("  [dim]Stopped.[/dim]")

    return ExitCode.SUCCESS
