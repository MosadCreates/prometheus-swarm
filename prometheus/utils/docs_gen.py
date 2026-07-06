from __future__ import annotations

from pathlib import Path

from prometheus.registry.registry import _get_commands


def generate_command_docs(output_dir: str | Path) -> int:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    commands = _get_commands()
    if not commands:
        return 0

    categories: dict[str, list] = {}
    for cmd in commands:
        categories.setdefault(cmd.category, []).append(cmd)

    index_lines = ["# Prometheus Swarm — Command Reference\n", "\n"]
    index_lines.append("| Command | Category | Description | Implemented |\n")
    index_lines.append("|---------|----------|-------------|-------------|\n")

    for cat in sorted(categories):
        cat_cmds = sorted(categories[cat], key=lambda c: c.name)
        cat_file = out / f"{cat.lower().replace(' ', '-')}.md"
        cat_lines = [f"# {cat} Commands\n", "\n"]

        for cmd in cat_cmds:
            status = "\u2713" if cmd.implemented else "\u2717"
            index_lines.append(
                f"| `{cmd.name}` | {cmd.category} | {cmd.description} | {status} |\n"
            )

            cat_lines.append(f"## `{cmd.name}`\n")
            cat_lines.append(f"{cmd.description}\n")
            cat_lines.append(f"- **Category:** {cmd.category}\n")
            cat_lines.append(f"- **Tier:** {cmd.tier}\n")
            cat_lines.append(f"- **Implemented:** {status}\n")
            if cmd.aliases:
                cat_lines.append(f"- **Aliases:** `{'`, `'.join(cmd.aliases)}`\n")
            if cmd.examples:
                cat_lines.append("- **Examples:**\n")
                for ex in cmd.examples:
                    cat_lines.append(f"  - `prometheus {ex}`\n")
            if cmd.related:
                cat_lines.append(f"- **Related:** `{'`, `'.join(cmd.related)}`\n")
            if cmd.since:
                cat_lines.append(f"- **Since:** {cmd.since}\n")
            if cmd.experimental:
                cat_lines.append("- **Experimental:** yes\n")
            if cmd.requires_workspace:
                cat_lines.append("- **Requires workspace:** yes\n")
            if cmd.requires_provider:
                cat_lines.append("- **Requires provider:** yes\n")
            cat_lines.append("\n")

        cat_file.write_text("".join(cat_lines), encoding="utf-8")

    index_path = out / "README.md"
    index_path.write_text("".join(index_lines), encoding="utf-8")
    return len(commands)
