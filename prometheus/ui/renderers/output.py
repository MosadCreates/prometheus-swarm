from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from typing import Any

import yaml

from prometheus.ui.console import console as rich_console
from prometheus.ui.components import ErrorPanel, SuccessPanel
from prometheus.ui.renderers import (
    CategorizedCommandTable,
    HelpPanel,
    StatusPanel,
    CategoryPanels,
    SearchPanel,
)


def _strip_markup(text: str) -> str:
    return re.sub(r"\[/?[\w#]*[^]]*\]", "", text)


class Renderer(ABC):
    @abstractmethod
    def print(self, text: str = "", *, style: str | None = None, end: str = "\n") -> None: ...

    @abstractmethod
    def success(self, message: str, *, title: str | None = None) -> None: ...

    @abstractmethod
    def error(self, message: str, *, title: str | None = None, hint: str | None = None) -> None: ...

    @abstractmethod
    def empty(self, title: str, *, hint: str | None = None) -> None: ...

    @abstractmethod
    def status(self, items: list[tuple[str, str]], *, title: str | None = None) -> None: ...

    @abstractmethod
    def table(
        self, headers: list[str], rows: list[list[str]], *, title: str | None = None
    ) -> None: ...

    @abstractmethod
    def command_table(self, categorized: dict[str, list[Any]]) -> None: ...

    @abstractmethod
    def category_panels(self, categorized: dict[str, list[Any]]) -> None: ...

    @abstractmethod
    def search_results(self, results: list[tuple[Any, float]], query: str) -> None: ...

    @abstractmethod
    def help_panel(self, cmd: Any) -> None: ...

    @abstractmethod
    def raw_json(self, data: Any) -> None: ...


class RichRenderer(Renderer):
    def __init__(self, *, no_color: bool = False) -> None:
        self.console = rich_console
        if no_color:
            from rich.console import Console
            from prometheus.ui.theme import Theme

            self.console = Console(
                theme=Theme.rich_theme(), emoji=False, safe_box=True, no_color=True, log_time=False
            )

    def print(self, text: str = "", *, style: str | None = None, end: str = "\n") -> None:
        self.console.print(text, style=style, end=end)

    def success(self, message: str, *, title: str | None = None) -> None:
        self.console.print(SuccessPanel(title or "Success", message))

    def error(self, message: str, *, title: str | None = None, hint: str | None = None) -> None:
        self.console.print(ErrorPanel(title or "Error", message, hint))

    def empty(self, title: str, *, hint: str | None = None) -> None:
        self.console.print(f"  [dim]{title}[/dim]")
        if hint:
            self.console.print(f"  {hint}")

    def status(self, items: list[tuple[str, str]], *, title: str | None = None) -> None:
        self.console.print(StatusPanel(items, title=title))

    def table(self, headers: list[str], rows: list[list[str]], *, title: str | None = None) -> None:
        from rich.table import Table

        from prometheus.ui.theme import Theme as _Theme

        table = Table(title=title, title_style="bold", border_style=str(_Theme.border))
        for h in headers:
            table.add_column(h)
        for row in rows:
            table.add_row(*row)
        self.console.print(table)

    def command_table(self, categorized: dict[str, list[Any]]) -> None:
        self.console.print(CategorizedCommandTable(categorized))

    def category_panels(self, categorized: dict[str, list[Any]]) -> None:
        self.console.print(CategoryPanels(categorized))

    def search_results(self, results: list[tuple[Any, float]], query: str) -> None:
        self.console.print(SearchPanel(results, query))

    def help_panel(self, cmd: Any) -> None:
        self.console.print(HelpPanel(cmd))

    def raw_json(self, data: Any) -> None:
        json_str = json.dumps(data, indent=2, default=str)
        self.console.print(json_str)


class JsonRenderer(Renderer):
    def _emit(self, obj: Any) -> None:
        rich_console.print(json.dumps(obj, indent=2, default=str), markup=False)

    def print(self, text: str = "", *, style: str | None = None, end: str = "\n") -> None:
        if text:
            self._emit({"output": _strip_markup(text)})

    def success(self, message: str, *, title: str | None = None) -> None:
        self._emit({"success": message, "title": title})

    def error(self, message: str, *, title: str | None = None, hint: str | None = None) -> None:
        obj: dict[str, Any] = {"error": message}
        if title:
            obj["title"] = title
        if hint:
            obj["hint"] = hint
        self._emit(obj)

    def empty(self, title: str, *, hint: str | None = None) -> None:
        obj: dict[str, Any] = {"schema": "prometheus.empty.v1", "title": title}
        if hint:
            obj["hint"] = hint
        self._emit(obj)

    def status(self, items: list[tuple[str, str]], *, title: str | None = None) -> None:
        obj = {label: value for label, value in items}
        if title:
            obj["_title"] = title
        self._emit(obj)

    def table(self, headers: list[str], rows: list[list[str]], *, title: str | None = None) -> None:
        result = [dict(zip(headers, row)) for row in rows]
        if title:
            self._emit({"title": title, "rows": result})
        else:
            self._emit(result)

    def command_table(self, categorized: dict[str, list[Any]]) -> None:
        result: dict[str, list[dict[str, Any]]] = {}
        for category, commands in categorized.items():
            result[category] = [
                {"name": c.name, "description": c.description, "tier": c.tier} for c in commands
            ]
        self._emit(result)

    def category_panels(self, categorized: dict[str, list[Any]]) -> None:
        self.command_table(categorized)

    def search_results(self, results: list[tuple[Any, float]], query: str) -> None:
        self._emit(
            {
                "query": query,
                "results": [
                    {"name": c.name, "score": round(s, 2), "description": c.description}
                    for c, s in results
                ],
            }
        )

    def help_panel(self, cmd: Any) -> None:
        self._emit(
            {
                "name": cmd.name,
                "description": cmd.description,
                "aliases": cmd.aliases,
                "tier": cmd.tier,
                "examples": cmd.examples,
                "related": cmd.related,
            }
        )

    def raw_json(self, data: Any) -> None:
        self._emit(data)


class PlainRenderer(Renderer):
    @property
    def console(self):
        from prometheus.ui.console import console as _console

        return _console

    def print(self, text: str = "", *, style: str | None = None, end: str = "\n") -> None:
        clean = _strip_markup(text)
        rich_console.print(clean, end=end)

    def success(self, message: str, *, title: str | None = None) -> None:
        label = f"[{title}] " if title else ""
        rich_console.print(f"OK: {label}{message}")

    def error(self, message: str, *, title: str | None = None, hint: str | None = None) -> None:
        label = f"[{title}] " if title else ""
        msg = f"ERROR: {label}{message}"
        if hint:
            msg += f" (hint: {hint})"
        rich_console.print(msg)

    def empty(self, title: str, *, hint: str | None = None) -> None:
        msg = f"INFO: {title}"
        if hint:
            msg += f"  -> {hint}"
        rich_console.print(msg)

    def status(self, items: list[tuple[str, str]], *, title: str | None = None) -> None:
        if title:
            rich_console.print(f"--- {title} ---")
        for label, value in items:
            rich_console.print(f"  {label}: {value}")

    def table(self, headers: list[str], rows: list[list[str]], *, title: str | None = None) -> None:
        if title:
            rich_console.print(f"--- {title} ---")
        rich_console.print("  " + "\t".join(headers))
        for row in rows:
            rich_console.print("  " + "\t".join(row))

    def command_table(self, categorized: dict[str, list[Any]]) -> None:
        for category, commands in categorized.items():
            rich_console.print(f"\n  [{category}]")
            for c in commands:
                rich_console.print(f"    {c.name:<28} {c.description}")

    def category_panels(self, categorized: dict[str, list[Any]]) -> None:
        self.command_table(categorized)

    def search_results(self, results: list[tuple[Any, float]], query: str) -> None:
        rich_console.print(f"Search results for '{query}':")
        for cmd, score in results:
            rich_console.print(f"  {cmd.name:<28} (score: {score:.2f}) {cmd.description}")

    def help_panel(self, cmd: Any) -> None:
        rich_console.print(f"  {cmd.name}: {cmd.description}")
        if cmd.aliases:
            rich_console.print(f"  Aliases: {', '.join(cmd.aliases)}")
        if cmd.examples:
            rich_console.print(f"  Examples: {'; '.join(cmd.examples)}")
        if cmd.related:
            rich_console.print(f"  Related: {', '.join(cmd.related)}")

    def raw_json(self, data: Any) -> None:
        import json as _json

        rich_console.print(_json.dumps(data, indent=2, default=str))


class YamlRenderer(Renderer):
    def _emit(self, obj: Any) -> None:
        rich_console.print(
            yaml.dump(obj, default_flow_style=False, sort_keys=False).rstrip(), markup=False
        )

    def raw_json(self, data: Any) -> None:
        self._emit(data)

    def print(self, text: str = "", *, style: str | None = None, end: str = "\n") -> None:
        if text:
            self._emit({"output": _strip_markup(text)})

    def success(self, message: str, *, title: str | None = None) -> None:
        obj: dict[str, Any] = {"success": message}
        if title:
            obj["title"] = title
        self._emit(obj)

    def error(self, message: str, *, title: str | None = None, hint: str | None = None) -> None:
        obj: dict[str, Any] = {"error": message}
        if title:
            obj["title"] = title
        if hint:
            obj["hint"] = hint
        self._emit(obj)

    def empty(self, title: str, *, hint: str | None = None) -> None:
        obj: dict[str, Any] = {"schema": "prometheus.empty.v1", "title": title}
        if hint:
            obj["hint"] = hint
        self._emit(obj)

    def status(self, items: list[tuple[str, str]], *, title: str | None = None) -> None:
        obj = {label: value for label, value in items}
        if title:
            obj["_title"] = title
        self._emit(obj)

    def table(self, headers: list[str], rows: list[list[str]], *, title: str | None = None) -> None:
        result = [dict(zip(headers, row)) for row in rows]
        if title:
            self._emit({"title": title, "rows": result})
        else:
            self._emit(result)

    def command_table(self, categorized: dict[str, list[Any]]) -> None:
        result: dict[str, list[dict[str, Any]]] = {}
        for category, commands in categorized.items():
            result[category] = [
                {"name": c.name, "description": c.description, "tier": c.tier} for c in commands
            ]
        self._emit(result)

    def category_panels(self, categorized: dict[str, list[Any]]) -> None:
        self.command_table(categorized)

    def search_results(self, results: list[tuple[Any, float]], query: str) -> None:
        self._emit(
            {
                "query": query,
                "results": [
                    {"name": c.name, "score": round(s, 2), "description": c.description}
                    for c, s in results
                ],
            }
        )

    def help_panel(self, cmd: Any) -> None:
        self._emit(
            {
                "name": cmd.name,
                "description": cmd.description,
                "aliases": cmd.aliases,
                "tier": cmd.tier,
                "examples": cmd.examples,
                "related": cmd.related,
            }
        )


def get_renderer(fmt: str, *, no_color: bool = False) -> Renderer:
    match fmt:
        case "json":
            return JsonRenderer()
        case "yaml":
            return YamlRenderer()
        case "plain":
            return PlainRenderer()
        case "interactive" | "rich" | _:
            return RichRenderer(no_color=no_color)


def renderer_from_ctx(ctx: Any) -> Renderer:
    root = ctx.find_root()
    fmt = root.obj.get("format", "rich")
    no_color = root.obj.get("no_color", False)
    return get_renderer(fmt, no_color=no_color)
