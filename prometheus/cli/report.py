from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import click

from prometheus.cli.output import detect_format, Format
from prometheus.ui.components import Spinner
from prometheus.ui.renderers import renderer_from_ctx
from prometheus.utils.exit_codes import ExitCode


@click.command(name="report")
@click.argument("job_id")
@click.option("--view", "-v", is_flag=True, help="Render the report in the terminal")
@click.option(
    "--open", "-o", "open_browser", is_flag=True, help="Open the Markdown report in browser"
)
@click.option(
    "--format",
    "-f",
    "fmt",
    type=click.Choice(["json", "md"]),
    default="md",
    help="Report format to show",
)
@click.option(
    "--output-format",
    "out_fmt",
    type=click.Choice(["interactive", "plain", "json"]),
    default=None,
    help="CLI output format (default: auto-detect)",
)
@click.pass_context
def report(ctx, job_id, view, open_browser, fmt, out_fmt):
    """Generate and view a mission report for a completed job.

    JOB_ID is the job UUID or its 8-character prefix.
    Generates a JSON report at outputs/{job_id}/mission_report_{job_id}.json
    and a Markdown version alongside it.
    """
    if out_fmt:
        ctx.find_root().obj["format"] = out_fmt
    cli_fmt = detect_format(ctx)
    renderer = renderer_from_ctx(ctx)

    async def _generate():
        from memory.redis_client import RedisClient
        from orchestrator.mission_report import generate_mission_report

        redis = RedisClient()
        await redis.connect()
        try:
            json_path = await generate_mission_report(job_id, redis._client)
            return json_path
        finally:
            await redis.close()

    with Spinner("Generating mission report..."):
        try:
            json_path = asyncio.run(_generate())
        except Exception as e:
            renderer.error(str(e), title="Report generation failed")
            return ExitCode.ERROR

    json_path = Path(json_path)
    md_path = json_path.with_suffix(".md")

    if not json_path.exists():
        renderer.error(f"Report not found at {json_path}")
        return ExitCode.ERROR_NOT_FOUND

    data = {
        "job_id": job_id,
        "json_path": str(json_path.resolve()),
        "md_path": str(md_path.resolve()),
    }

    match cli_fmt:
        case Format.JSON:
            print(json.dumps({"schema": "prometheus.report.v1", **data}, indent=2))
        case Format.PLAIN:
            print(f"report_generated={json_path.resolve()}")
        case Format.INTERACTIVE:
            renderer.print("  [green]\u2713 Mission report generated[/green]")
            renderer.print(f"  [dim]File:[/dim] {json_path.resolve()}")
            renderer.print(f"  [dim]View:[/dim] [bold]prometheus report {job_id[:8]} --view[/bold]")

    if view:
        _view_report(renderer, md_path if fmt == "md" else json_path, fmt)
    elif open_browser:
        _open_report(md_path)

    return ExitCode.SUCCESS


def _view_report(renderer, path: Path, fmt: str) -> None:
    """Render the report in the terminal."""
    if fmt == "md":
        try:
            from rich.markdown import Markdown

            md = Markdown(path.read_text(encoding="utf-8"))
            renderer.console.print(md)
        except ImportError:
            renderer.print(path.read_text(encoding="utf-8"))
    else:
        import json

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            import pygments
            from pygments.lexers import JsonLexer
            from pygments.formatters import TerminalFormatter

            highlighted = pygments.highlight(
                json.dumps(data, indent=2), JsonLexer(), TerminalFormatter()
            )
            renderer.print(highlighted)
        except ImportError:
            renderer.print(path.read_text(encoding="utf-8"))


def _open_report(path: Path) -> None:
    """Open the Markdown report in the default browser."""
    abs_path = path.resolve()
    url = abs_path.as_uri()
    try:
        if sys.platform == "win32":
            os.startfile(url)
        elif sys.platform == "darwin":
            subprocess.run(["open", url], check=False)
        else:
            subprocess.run(["xdg-open", url], check=False)
    except Exception:
        print(f"Report at: {abs_path}")
