"""``prometheus skill`` — install, verify, promote, and manage user skills.

Mirrors ``prometheus/cli/plugin.py``: a ``@click.group`` on ``AliasedGroup``
with a ``skills`` alias, service access via ``_app(ctx).skills`` (the lazy
``AppContext.skills`` property), and the three-mode renderer
(``renderer_from_ctx``). Async platform calls are wrapped in ``asyncio.run`` —
the established CLI pattern (evaluate.py / daemon.py / mission).

Routes every operation through ``SkillService`` so the CLI, the promotion
store, and the evidence gate share one wiring — and tests can drive the whole
surface with temp roots + a fake Redis client.
"""

from __future__ import annotations

import asyncio

import click

from prometheus.ui.renderers import renderer_from_ctx
from prometheus.utils.commands import AliasedGroup
from prometheus.utils.exit_codes import ExitCode


def _app(ctx: click.Context):
    return ctx.find_root().obj["app"]


@click.group(
    cls=AliasedGroup,
    name="skill",
    aliases={"skills": "skill"},
    context_settings=dict(help_option_names=["--help", "-h"]),
)
def skill():
    """Install, verify, and promote user skills for the six agents."""


@skill.command(name="install")
@click.argument("source")
@click.option(
    "--type",
    "source_type",
    type=click.Choice(["local", "git", "registry", "md"], case_sensitive=False),
    default=None,
    help="Source type (auto-detected when omitted)",
)
@click.option(
    "--agent",
    "agents",
    default=None,
    help="Comma-separated agents the skill may route to (default: manifest's own)",
)
@click.option("--trust", is_flag=True, help="Trust an instruction skill (required for .md)")
@click.option("--force", is_flag=True, help="Overwrite an already-installed skill")
@click.option("--no-verify", is_flag=True, help="Skip signature verification (local dev only)")
@click.option("--name", "name", default=None, help="Override the installed skill name")
@click.pass_context
def skill_install(
    ctx: click.Context,
    source: str,
    source_type: str | None,
    agents: str | None,
    trust: bool,
    force: bool,
    no_verify: bool,
    name: str | None,
):
    """Install a skill from a local dir, git URL, registry archive, or trusted .md."""
    renderer = renderer_from_ctx(ctx)
    svc = _app(ctx).skills
    result = asyncio.run(
        svc.install(
            source,
            source_type=source_type,
            agents=agents,
            trust=trust,
            force=force,
            no_verify=no_verify,
            name=name,
        )
    )
    if not result.ok:
        failed = [c for c in result.checks if not c.get("ok")]
        detail = f"{result.reason}" if result.reason else "install failed"
        for c in failed:
            detail += f"\n  ✗ {c.get('step')}: {c.get('detail')}"
        renderer.error(detail, title="skill install")
        return ExitCode.ERROR
    renderer.success(f"Installed skill '{result.name}'", title="skill install")
    return ExitCode.SUCCESS


@skill.command(name="list")
@click.option("--agent", "agent", default=None, help="Only skills routable to this agent")
@click.option("--installed-only", is_flag=True, help="Hide bundled skills")
@click.pass_context
def skill_list(ctx: click.Context, agent: str | None, installed_only: bool):
    """List bundled + installed skills with routing, trust, and status."""
    renderer = renderer_from_ctx(ctx)
    svc = _app(ctx).skills
    manifests = svc.list(agent=agent, installed_only=installed_only)
    if not manifests:
        renderer.empty("No skills found", hint="prometheus skill install <source>")
        return ExitCode.SUCCESS
    rows = []
    for m in sorted(manifests, key=lambda m: m.name):
        active, why = svc.status(m)
        rows.append(
            [
                m.name,
                m.version,
                "instruction" if m.is_instruction() else "code",
                ",".join(m.agents),
                m.root,
                "trusted" if m.trusted else "untrusted",
                active,
            ]
        )
    renderer.table(
        ["name", "version", "type", "agents", "root", "trust", "status"],
        rows,
        title="Skills",
    )
    return ExitCode.SUCCESS


@skill.command(name="info")
@click.argument("name")
@click.pass_context
def skill_info(ctx: click.Context, name: str):
    """Show a skill's manifest, signature, and validation status."""
    renderer = renderer_from_ctx(ctx)
    svc = _app(ctx).skills
    m = svc.info(name)
    if m is None:
        renderer.error(
            f"Skill '{name}' not found", title="skill info", hint="prometheus skill list"
        )
        return ExitCode.ERROR_NOT_FOUND
    active, why = svc.status(m)
    items = [
        ("name", m.name),
        ("version", m.version),
        ("description", m.description),
        ("category", m.category),
        ("type", "instruction" if m.is_instruction() else "code"),
        ("agents", ",".join(m.agents)),
        ("root", m.root),
        ("source", m.source),
        ("trusted", "yes" if m.trusted else "no"),
        ("publisher", m.publisher or "(unsigned)"),
        ("signature", (m.signature or "")[:12] + "…" if m.signature else "none"),
        ("permissions", ",".join(m.permissions) or "(none declared)"),
        ("status", f"{active} ({why})"),
        ("path", m.path),
    ]
    if m.source_url:
        items.append(("source_url", m.source_url))
    if m.max_runtime_s != 30 or m.max_memory_mb != 512:
        items.append(("bounds", f"{m.max_runtime_s}s / {m.max_memory_mb}MB"))
    ok, reason, warnings = svc.structural(m)
    items.append(("structural", "ok" if ok else f"FAIL: {reason}"))
    for w in warnings[:3]:
        items.append(("warning", w))
    renderer.status(items, title=f"Skill: {m.name}")
    return ExitCode.SUCCESS


@skill.command(name="verify")
@click.argument("name")
@click.pass_context
def skill_verify(ctx: click.Context, name: str):
    """Re-verify a skill's publisher signature on demand."""
    renderer = renderer_from_ctx(ctx)
    svc = _app(ctx).skills
    ok, reason = svc.verify(name)
    if ok:
        renderer.success(f"Signature verified for '{name}'", title="skill verify")
        return ExitCode.SUCCESS
    renderer.error(reason, title="skill verify", hint="prometheus skill trust <publisher>")
    return ExitCode.ERROR


@skill.command(name="test")
@click.argument("name")
@click.option("--agent", "agent", default=None, help="Agent whose fixture to run against")
@click.pass_context
def skill_test(ctx: click.Context, name: str, agent: str | None):
    """Re-run the dry-run / agent-compat smoke test for a skill."""
    renderer = renderer_from_ctx(ctx)
    svc = _app(ctx).skills
    manifest, result = asyncio.run(svc.test(name, agent=agent))
    if manifest is None:
        renderer.error(result, title="skill test")
        return ExitCode.ERROR_NOT_FOUND
    if result is None:
        renderer.success(
            f"'{name}' is an instruction skill — body is valid, nothing to execute",
            title="skill test",
        )
        return ExitCode.SUCCESS
    if result.ok:
        renderer.success(f"'{name}' ran cleanly", title="skill test")
        if result.detail:
            renderer.print(f"  [dim]{result.detail}[/dim]")
        return ExitCode.SUCCESS
    renderer.error(f"Smoke test failed: {result.reason}", title="skill test")
    return ExitCode.ERROR


@skill.command(name="remove")
@click.argument("name")
@click.pass_context
def skill_remove(ctx: click.Context, name: str):
    """Uninstall a skill from the user root (bundled skills are never removed)."""
    renderer = renderer_from_ctx(ctx)
    svc = _app(ctx).skills
    ok, reason = svc.remove(name)
    if ok:
        renderer.success(reason, title="skill remove")
        return ExitCode.SUCCESS
    renderer.error(reason, title="skill remove")
    return ExitCode.ERROR


@skill.command(name="update")
@click.argument("name")
@click.pass_context
def skill_update(ctx: click.Context, name: str):
    """Re-pull a git-sourced skill, re-validate, and atomically reinstall."""
    renderer = renderer_from_ctx(ctx)
    svc = _app(ctx).skills
    ok, reason = asyncio.run(svc.update(name))
    if ok:
        renderer.success(reason, title="skill update")
        return ExitCode.SUCCESS
    renderer.error(reason, title="skill update")
    return ExitCode.ERROR


@skill.command(name="create")
@click.argument("name")
@click.option("--agent", "agent", default="scout", help="Agent the scaffold routes to")
@click.pass_context
def skill_create(ctx: click.Context, name: str, agent: str):
    """Scaffold a SKILL.md + skill.py starter for authoring a new skill."""
    renderer = renderer_from_ctx(ctx)
    svc = _app(ctx).skills
    ok, path = svc.create(name, agent=agent)
    if ok:
        renderer.success(f"Created skill scaffold at {path}", title="skill create")
        return ExitCode.SUCCESS
    renderer.error(path, title="skill create")
    return ExitCode.ERROR


@skill.command(name="trust")
@click.argument("publisher")
@click.option(
    "--key",
    "key_path",
    type=click.Path(exists=True, dir_okay=False),
    required=True,
    help="Path to the publisher's ed25519 public key (PEM)",
)
@click.pass_context
def skill_trust(ctx: click.Context, publisher: str, key_path: str):
    """Trust a publisher's public key for signature verification."""
    renderer = renderer_from_ctx(ctx)
    svc = _app(ctx).skills
    from pathlib import Path

    pem = Path(key_path).read_text(encoding="utf-8")
    svc.trust_publisher(publisher, pem)
    renderer.success(f"Trusted publisher '{publisher}'", title="skill trust")
    return ExitCode.SUCCESS


@skill.command(name="untrust")
@click.argument("publisher")
@click.pass_context
def skill_untrust(ctx: click.Context, publisher: str):
    """Remove a publisher's key; their skills will no longer verify."""
    renderer = renderer_from_ctx(ctx)
    svc = _app(ctx).skills
    if not svc.untrust_publisher(publisher):
        renderer.error(f"Publisher '{publisher}' is not trusted", title="skill untrust")
        return ExitCode.ERROR_NOT_FOUND
    renderer.success(f"Untrusted publisher '{publisher}'", title="skill untrust")
    return ExitCode.SUCCESS


@skill.command(name="promote")
@click.argument("name")
@click.option("--agent", "agent", required=True, help="Agent the evidence applies to")
@click.pass_context
def skill_promote(ctx: click.Context, name: str, agent: str):
    """Mark a skill stable for an agent — only if the evidence gate is met.

    Requires >= N consecutive ok real-job runs with zero fallbacks (recorded in
    Redis ``skill:{name}:{agent}:stats``). Writes the promotion to
    ``~/.prometheus/promotions.json``; ``stable`` never touches the signed
    SKILL.md.
    """
    renderer = renderer_from_ctx(ctx)
    svc = _app(ctx).skills
    ok, reason, evidence = asyncio.run(svc.promote(name, agent))
    if ok:
        renderer.success(reason, title="skill promote")
        if evidence:
            renderer.status(
                [
                    ("consecutive_ok", str(evidence.get("consecutive_ok", 0))),
                    ("total_runs", str(evidence.get("total_runs", 0))),
                    ("ok_runs", str(evidence.get("ok_runs", 0))),
                    ("fallback_fired", str(evidence.get("fallback_fired", 0))),
                ],
                title="Evidence",
            )
        return ExitCode.SUCCESS
    renderer.error(reason, title="skill promote")
    return ExitCode.ERROR


@skill.command(name="check-orphans")
@click.pass_context
def skill_check_orphans(ctx: click.Context):
    """List stable skills whose agent call site still carries a fallback branch.

    Promotion says "proven stable → fallback removed is a deliberate code
    edit". This is the CI signal that the edit is still pending.
    """
    renderer = renderer_from_ctx(ctx)
    svc = _app(ctx).skills
    orphans = svc.check_orphans()
    if not orphans:
        renderer.success("No stable skill is waiting on a fallback cleanup", title="check-orphans")
        return ExitCode.SUCCESS
    renderer.table(
        ["key", "agent", "promoted_at"],
        [[o["key"], o["agent"], o["promoted_at"]] for o in orphans],
        title="Orphans — stable skill still has a fallback branch",
    )
    return ExitCode.ERROR
