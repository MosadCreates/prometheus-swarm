from __future__ import annotations

from difflib import SequenceMatcher

from prometheus.registry.command import Command
from prometheus.registry.registry import _get_commands


def _score(text: str, query: str) -> float:
    text_lower = text.lower()
    query_lower = query.lower()

    if query_lower == text_lower:
        return 1.0
    if query_lower in text_lower:
        return 0.9
    if text_lower.startswith(query_lower):
        return 0.85
    if any(word in text_lower for word in query_lower.split()):
        return 0.7
    return SequenceMatcher(None, query_lower, text_lower).ratio()


def _star_rating(score: float) -> str:
    if score >= 0.95:
        return "\u2605\u2605\u2605\u2605\u2605"
    if score >= 0.8:
        return "\u2605\u2605\u2605\u2605"
    if score >= 0.6:
        return "\u2605\u2605\u2605"
    if score >= 0.45:
        return "\u2605\u2605"
    return "\u2605"


def search_commands(
    query: str,
    threshold: float = 0.45,
    limit: int | None = None,
) -> list[tuple[Command, float]]:
    results: list[tuple[Command, float]] = []
    for cmd in _get_commands():
        if cmd.hidden:
            continue
        best = max(
            _score(field, query)
            for field in [
                cmd.name,
                cmd.description,
                " ".join(cmd.aliases),
                " ".join(cmd.examples),
                " ".join(cmd.related),
                cmd.category,
            ]
        )
        if best >= threshold:
            results.append((cmd, best))
    results.sort(key=lambda x: (-x[1], x[0].name))
    if limit:
        results = results[:limit]
    return results


def suggest_command(bad_name: str) -> str | None:
    for cmd in _get_commands():
        if cmd.hidden:
            continue
        ratio = SequenceMatcher(None, bad_name.lower(), cmd.name.lower()).ratio()
        if ratio > 0.5:
            return cmd.name
        for alias in cmd.aliases:
            ratio = SequenceMatcher(None, bad_name.lower(), alias.lower()).ratio()
            if ratio > 0.5:
                return cmd.name
    return None
