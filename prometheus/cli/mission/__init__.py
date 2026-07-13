from __future__ import annotations

import click

from prometheus.ui.renderers import renderer_from_ctx
from prometheus.utils.exit_codes import ExitCode


@click.command(name="new-mission")
@click.pass_context
def mission_cmd(ctx: click.Context) -> ExitCode:
    """Start a new machine learning mission.

    Enters Mission Mode where you describe your ML problem.
    The description is collected and stored for the next phase.
    """
    renderer = renderer_from_ctx(ctx)

    from prometheus.cli.mission.controller import enter_mission_mode

    enter_mission_mode(console=renderer.console)
    return ExitCode.SUCCESS
