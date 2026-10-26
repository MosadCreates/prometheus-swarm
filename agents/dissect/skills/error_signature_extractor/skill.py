"""Extract a normalized, human-readable error signature from a crash.

Deterministic, pure. Complements ``compute_fingerprint`` — the opaque hash
used for dedup — with a readable signature (category + whitespace-normalized
message + short digest) that Dissect can surface in events and the patch log
without leaking the full raw message.
"""

from __future__ import annotations

import hashlib
from typing import Any

from agents.skills.base import Skill
from agents.skills.context import SkillContext, SkillResult

MAX_MESSAGE = 200


class ErrorSignatureExtractorSkill(Skill):
    name = "error_signature_extractor"
    description = "Normalize a crash into a readable, stable error signature"
    category = "debugging"
    agents = ("dissect",)
    deterministic = True

    async def run(self, ctx: SkillContext, **kwargs: Any) -> SkillResult:
        category = ctx.kwargs.get("category", "") or ""
        exception_type = ctx.kwargs.get("exception_type", "") or ""
        exception_message = ctx.kwargs.get("exception_message", "") or ""
        stage = ctx.kwargs.get("pipeline_stage", "training") or "training"

        normalized = " ".join(exception_message.strip().split())[:MAX_MESSAGE]
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
        return SkillResult(
            skill=self.name,
            ok=True,
            detail={
                "category": category,
                "exception_type": exception_type,
                "message_normalized": normalized,
                "message_hash": digest,
                "pipeline_stage": stage,
                "signature": f"{category}::{normalized[:60]}::{digest}",
            },
        )
