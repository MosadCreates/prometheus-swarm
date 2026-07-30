"""Forge Agent — The Architect."""

import ast
import asyncio
import importlib
import os
import subprocess
import sys
from typing import Any

from agents.base import BaseAgent
from agents.forge.decision_tree import select_architecture, select_imbalance_strategy
from agents.forge.planner import create_plan, format_plan_summary
from agents.forge.prompts import FORGE_SYSTEM_PROMPT
from agents.forge.tools import write_training_script, define_optuna_space
from bus.agent_events import AgentEventTracker, emit_subaction_progress
from bus.events import TRAINING_SCRIPT_READY, STREAM_FORGE_OUTPUT
from bus.publisher import publish
from prometheus.cli.mission.state_logger import log_mission_state
from contracts import MissionBrief, MissionSpecification, RetryPlan
from runtime.paths import get_job_paths
from shared.metrics import (
    FORGE_ARCHITECTURE_SELECTIONS,
    FORGE_SCRIPTS_GENERATED,
    FORGE_SCRIPTS_GENERATION_DURATION,
    FORGE_PLANS_GENERATED,
    AGENT_RUNS,
    record_heartbeat,
    record_agent_error,
)
from prometheus.ui.detail_types import (
    ForgeArchitectureDetail,
    ForgeCandidatesDetail,
    ForgeRationaleDetail,
    ForgeScriptDetail,
    ForgeSearchSpaceDetail,
    ForgeValidationDetail,
    ForgeImbalanceDetail,
)


_JS_LITERAL_PATTERNS: list[str] = [
    r"(?<![a-zA-Z])true(?![a-zA-Z])",
    r"(?<![a-zA-Z])false(?![a-zA-Z])",
    r"(?<![a-zA-Z])null(?![a-zA-Z])",
]


def _has_js_literals(source: str) -> list[str]:
    import re

    cleaned = re.sub(
        r'""".*?"""|\'\'\'.*?\'\'\'|#.*$|".*?"|\'.*?\'',
        "",
        source,
        flags=re.MULTILINE | re.DOTALL,
    )
    found: list[str] = []
    for pat in _JS_LITERAL_PATTERNS:
        if re.search(pat, cleaned):
            found.append(re.search(pat, cleaned).group())
    return found


def _validate_python_script(
    script_path: str,
    job_id: str,
    logger: Any,
    mission_brief: dict | None = None,
) -> None:
    if not os.path.exists(script_path):
        raise FileNotFoundError(f"Script not found for validation: {script_path}")
    with open(script_path, encoding="utf-8") as f:
        source = f.read()

    # Check 1: JavaScript-style literal detection (LLM hallucination guard)
    js_literals = _has_js_literals(source)
    if js_literals:
        logger.error(f"[job={job_id}] Script contains JavaScript-style literals: {js_literals}")
        os.remove(script_path)
        raise ValueError(
            f"Generated script contains JavaScript-style literals ({js_literals}). "
            f"Use Python True/False/None instead."
        )

    # Check 2: Syntax validation via ast.parse
    try:
        ast.parse(source)
    except SyntaxError as e:
        logger.error(f"[job={job_id}] Script failed ast.parse: {e}")
        os.remove(script_path)
        raise ValueError(f"Generated script has syntax errors: {e}")

    # Check 3: Compilation validation via py_compile
    try:
        subprocess.run(
            [sys.executable, "-m", "py_compile", script_path],
            capture_output=True,
            text=True,
            check=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.CalledProcessError as e:
        logger.error(f"[job={job_id}] Script failed py_compile:\n{e.stderr}")
        os.remove(script_path)
        raise ValueError(f"Generated script failed compilation: {e.stderr}")

    # Check 4: Import resolution — every top-level import must be resolvable
    import_errors: list[str] = []
    try:
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    try:
                        importlib.import_module(top)
                    except ImportError:
                        import_errors.append(
                            f"Import '{alias.name}' could not be resolved "
                            f"(top-level package '{top}' not found)"
                        )
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.level is None:
                    top = node.module.split(".")[0]
                    try:
                        importlib.import_module(top)
                    except ImportError:
                        import_errors.append(
                            f"Import from '{node.module}' could not be resolved "
                            f"(top-level package '{top}' not found)"
                        )
    except SyntaxError:
        pass  # already caught above
    if import_errors:
        logger.error(
            f"[job={job_id}] Script has unresolved imports ({len(import_errors)}):\n"
            + "\n".join(f"  - {e}" for e in import_errors)
        )
        os.remove(script_path)
        raise ValueError(
            f"Generated script has {len(import_errors)} unresolvable imports. "
            f"First error: {import_errors[0]}"
        )

    # Check 5: Dataset path exists (from mission brief)
    if mission_brief:
        try:
            dataset = mission_brief.get("dataset", {})
            file_path = dataset.get("file_path") if isinstance(dataset, dict) else None
            if file_path:
                if not os.path.exists(str(file_path)):
                    # Could be a relative path — try resolving
                    from pathlib import Path

                    resolved = Path(str(file_path)).resolve()
                    if not resolved.exists():
                        logger.warning(
                            f"[job={job_id}] Dataset path '{file_path}' does not exist "
                            f"(resolved: '{resolved}'). Script will fail at runtime."
                        )
                    else:
                        logger.info(f"[job={job_id}] Dataset path resolved: '{resolved}'")
                else:
                    logger.info(f"[job={job_id}] Dataset path exists: '{file_path}'")
        except Exception as e:
            logger.warning(f"[job={job_id}] Could not validate dataset path: {e}")

        # Check 6: Target column exists in dataset (if dataset is available)
        try:
            target_column = mission_brief.get("target_column")
            if not target_column and isinstance(dataset, dict):
                target_column = dataset.get("target_column")
            if target_column and isinstance(dataset, dict):
                file_path = dataset.get("file_path")
                if file_path and os.path.exists(str(file_path)):
                    import pandas as pd

                    try:
                        df = pd.read_csv(str(file_path), nrows=0)
                        if target_column not in df.columns:
                            logger.error(
                                f"[job={job_id}] Target column '{target_column}' "
                                f"not found in dataset columns: "
                                f"{list(df.columns)}"
                            )
                            raise ValueError(
                                f"Target column '{target_column}' not found in dataset. "
                                f"Available columns: {list(df.columns)}"
                            )
                        logger.info(
                            f"[job={job_id}] Target column '{target_column}' "
                            f"confirmed in dataset"
                        )
                    except ValueError:
                        raise
                    except Exception as pe:
                        logger.warning(f"[job={job_id}] Could not verify target column: {pe}")
        except ValueError:
            raise
        except Exception as e:
            logger.warning(f"[job={job_id}] Could not validate target column: {e}")

    logger.info(
        f"[job={job_id}] Script validated: ast.parse + py_compile + "
        f"imports = {len(import_errors)} errors"
    )


class ForgeAgent(BaseAgent):
    @property
    def agent_name(self) -> str:
        return "Forge"

    @property
    def system_prompt(self) -> str:
        return FORGE_SYSTEM_PROMPT

    def _validate_retry_contract(self, retry_context: Any, caller: str = "") -> None:
        if retry_context is None:
            return
        if isinstance(retry_context, dict):
            raise TypeError(
                f"[job={self.job_id}] Contract violation: retry_context must be a "
                f"RetryPlan object, not dict{'. Originating stage: ' + caller if caller else ''}. "
                f"Use RetryPlan.from_dict() to reconstruct before passing to Forge."
            )
        if not isinstance(retry_context, RetryPlan):
            raise TypeError(
                f"[job={self.job_id}] Contract violation: retry_context must be a "
                f"RetryPlan object, got {type(retry_context).__name__}"
                f"{'. Originating stage: ' + caller if caller else ''}."
            )

    def _load_brief(self, raw: dict[str, Any] | None) -> MissionBrief | None:
        if raw is None:
            return None
        try:
            return MissionBrief.model_validate(raw)
        except Exception as e:
            self.logger.warning(f"[job={self.job_id}] Failed to parse MissionBrief: {e}")
            return None

    def _load_spec(self, raw: dict[str, Any] | None) -> MissionSpecification | None:
        if raw is None:
            return None
        try:
            return MissionSpecification.model_validate(raw)
        except Exception as e:
            self.logger.warning(f"[job={self.job_id}] Failed to parse MissionSpec: {e}")
            return None

    async def run(
        self,
        progress_callback: Any = None,
        retry_context: RetryPlan | None = None,
    ) -> None:
        self.logger.info(f"[job={self.job_id}] Forge starting")
        AGENT_RUNS.labels(agent="Forge", job_id=self.job_id).inc()
        record_heartbeat("Forge", self.job_id)

        tracker = AgentEventTracker(self.redis._client, self.job_id, "Forge")
        await tracker.emit(
            "acting", "Reading mission brief...", detail={"is_retry": retry_context is not None}
        )

        self._validate_retry_contract(retry_context, caller="ForgeAgent.run")
        self.logger.debug(
            f"[job={self.job_id}] RetryPlan received: "
            f"type={type(retry_context).__name__}, "
            f"architecture={retry_context.architecture if retry_context else None}, "
            f"attempt={retry_context.attempt if retry_context else 0}"
        )

        is_retry = retry_context is not None
        log_mission_state(
            "FORGE_START",
            self.job_id,
            architecture=retry_context.architecture if retry_context else None,
            imbalance_strategy=retry_context.imbalance_strategy if retry_context else None,
            retry_number=retry_context.attempt if retry_context else 0,
            is_retry=str(is_retry),
        )

        if progress_callback:
            progress_callback("Reading mission brief...")

        brief_key = f"job:{self.job_id}:mission_brief"
        brief_raw = await self.redis.get_json(brief_key)
        brief = self._load_brief(brief_raw)
        if not brief:
            record_agent_error("Forge", self.job_id, "missing_brief")
            raise ValueError(f"Mission brief not found at {brief_key}")

        if progress_callback:
            progress_callback("Loading mission specification...")

        spec_key = f"job:{self.job_id}:mission_spec"
        spec_raw = await self.redis.get_json(spec_key)
        spec = self._load_spec(spec_raw)

        modality = brief.modality
        task_type = brief.task_type
        num_rows = brief.dataset.num_rows if brief.dataset else 0
        class_imbalance_ratio = (
            brief.data_quality.class_imbalance_ratio if brief.data_quality else None
        )

        if spec and spec.engineering_decisions:
            reasoning = spec.engineering_decisions
        else:
            reasoning = brief.engineering_reasoning

        if retry_context:
            architecture = retry_context.architecture
            imbalance_strategy = retry_context.imbalance_strategy or "none"
            from runtime.models import check_architecture_supported

            check_architecture_supported(architecture)
            self.logger.info(
                f"[job={self.job_id}] Using retry strategy: "
                f"architecture={architecture}, imbalance={imbalance_strategy}, "
                f"attempt={retry_context.attempt}"
            )
            FORGE_ARCHITECTURE_SELECTIONS.labels(
                architecture=architecture, job_id=self.job_id
            ).inc()
        else:
            arch_decision = reasoning.get("architecture", {}) if isinstance(reasoning, dict) else {}
            if progress_callback:
                progress_callback("Selecting architecture...")

            similar = []
            if arch_decision and arch_decision.get("selected"):
                architecture = arch_decision["selected"]
                self.logger.info(
                    f"[job={self.job_id}] Using Scout-recommended architecture: {architecture}"
                )
            else:
                try:
                    from memory.collections.architecture_memory import query_similar_architectures

                    similar = query_similar_architectures(modality, task_type, k=3)
                except Exception:
                    self.logger.warning(f"[job={self.job_id}] Architecture memory query failed")
            architecture = select_architecture(
                brief_raw, use_memory=True, similar_architectures=similar
            )

            imbalance_strategy = select_imbalance_strategy(class_imbalance_ratio, brief_raw)

            FORGE_ARCHITECTURE_SELECTIONS.labels(
                architecture=architecture, job_id=self.job_id
            ).inc()

        if progress_callback:
            progress_callback(f"Architecture selected: {architecture}")

        await emit_subaction_progress(
            self.redis._client, self.job_id, "Forge", "Architecture selected", 0.25
        )

        # Emit structured detail for architecture selection
        tracker = AgentEventTracker(self.redis._client, self.job_id, "Forge")
        await tracker.emit(
            "acting",
            f"Architecture selected: {architecture}",
            detail=ForgeArchitectureDetail(
                selected=architecture,
                confidence=0.9,
                rationale=f"Selected for {modality} {task_type} with {num_rows} rows",
                alternatives=[],
                modality=modality,
                task_type=task_type,
                num_rows=num_rows,
            ).model_dump(),
        )

        await tracker.emit(
            "planning",
            f"Architecture selected: {architecture}",
            detail={"architecture": architecture, "imbalance_strategy": imbalance_strategy},
        )

        # ═══════════════════════════════════════════════════════════════════
        # RETRYPLAN OVERRIDE GUARD — NEVER OVERRIDE RetryPlan architecture
        # ═══════════════════════════════════════════════════════════════════
        if retry_context:
            expected = retry_context.architecture
            if architecture != expected:
                raise RuntimeError(
                    f"[job={self.job_id}] CRITICAL: RetryPlan architecture "
                    f"override detected. RetryPlan says '{expected}' but Forge "
                    f"selected '{architecture}'. This must never happen — the "
                    f"RetryPlan is authoritative. Fix the caller."
                )
            retry_arch = retry_context.architecture
            existing = await self.redis.get_json(f"job:{self.job_id}:search_space")
            if existing and retry_arch and retry_arch in str(existing):
                search_space = existing
                self.logger.info(
                    f"[job={self.job_id}] Preserving existing search space "
                    f"({len(search_space)} params) for architecture {retry_arch}"
                )
            else:
                search_space = define_optuna_space(architecture)
                self.logger.info(
                    f"[job={self.job_id}] Regenerated search space "
                    f"({len(search_space)} params) for architecture {architecture}"
                )
        else:
            search_space = define_optuna_space(architecture)

        if not search_space or len(search_space) == 0:
            record_agent_error("Forge", self.job_id, "empty_search_space")
            raise ValueError(
                f"Search space has 0 dimensions for architecture '{architecture}'. "
                f"define_optuna_space returned empty dict. Supported architectures: "
                f"lightgbm, xgboost, tabnet, distilbert, efficientnet."
            )

        if progress_callback:
            progress_callback("Building training strategy...")

        plan_key = f"job:{self.job_id}:engineering_plan"
        plan = None
        try:
            plan = create_plan(reasoning, brief_raw)
            await self.redis.set_json(plan_key, plan)
            FORGE_PLANS_GENERATED.labels(job_id=self.job_id).inc()
            if retry_context and plan and isinstance(plan, dict):
                hp = plan.get("hyperparameters", {})
                if isinstance(hp, dict):
                    rc_trials = retry_context.num_trials
                    if rc_trials:
                        old_trials = hp.get("max_trials", "?")
                        hp["max_trials"] = rc_trials
                        self.logger.info(
                            f"[job={self.job_id}] Overriding max_trials: "
                            f"{old_trials} → {rc_trials}"
                        )
            plan_summary = format_plan_summary(plan)
            await self.redis.set_json(plan_key, plan)
            FORGE_PLANS_GENERATED.labels(job_id=self.job_id).inc()
            self.logger.info(f"[job={self.job_id}] Engineering plan stored at {plan_key}")
        except Exception as exc:
            self.logger.warning(f"[job={self.job_id}] Plan generation failed: {exc}")
            plan = None
            plan_summary = None

        confidence = reasoning.get("overall_confidence") if isinstance(reasoning, dict) else None
        if confidence is not None:
            self.logger.info(
                f"[job={self.job_id}] Scout overall_confidence={confidence} "
                f"— routing generation strategy"
            )

        if progress_callback:
            progress_callback("Generating training script...")

        await tracker.emit(
            "acting", "Generating training script...", detail={"architecture": architecture}
        )

        _start = asyncio.get_event_loop().time()
        jp = get_job_paths(self.job_id)
        script_path = write_training_script(
            brief_raw,
            self.job_id,
            scripts_dir=str(jp._base.scripts),
            design_summary=plan_summary,
            architecture=architecture,
            engineering_plan=plan,
            redis_client=self.redis,
            confidence=confidence,
        )
        _elapsed = asyncio.get_event_loop().time() - _start
        FORGE_SCRIPTS_GENERATED.labels(architecture=architecture, job_id=self.job_id).inc()
        FORGE_SCRIPTS_GENERATION_DURATION.labels(
            architecture=architecture, job_id=self.job_id
        ).observe(_elapsed)
        record_heartbeat("Forge", self.job_id)

        await emit_subaction_progress(
            self.redis._client, self.job_id, "Forge", "Script rendering complete", 0.5
        )

        await emit_subaction_progress(
            self.redis._client, self.job_id, "Forge", "Error prevention applied", 0.7
        )

        if progress_callback:
            progress_callback("Validating generated script...")

        _validate_python_script(
            script_path,
            self.job_id,
            self.logger,
            mission_brief=brief_raw,
        )

        await emit_subaction_progress(
            self.redis._client, self.job_id, "Forge", "Script validated", 1.0, "done"
        )

        await tracker.emit(
            "verifying", "Script validation passed", detail={"script_path": script_path}
        )

        if progress_callback:
            progress_callback("Saving search space...")

        search_key = f"job:{self.job_id}:search_space"
        await self.redis.set_json(search_key, search_space)

        if progress_callback:
            progress_callback("Storing architecture decision...")

        decision_id = f"{self.job_id}:{architecture}"
        try:
            from memory.collections.architecture_memory import store_architecture

            store_architecture(
                decision_id=decision_id,
                job_id=self.job_id,
                modality=modality,
                task_type=task_type,
                num_rows=num_rows,
                class_imbalance_ratio=class_imbalance_ratio,
                model_selected=architecture,
                imbalance_strategy=imbalance_strategy,
            )
            await self.redis.set_str(f"job:{self.job_id}:architecture_decision_id", decision_id)
        except Exception:
            self.logger.warning(f"[job={self.job_id}] Failed to store architecture decision")

        # Emit structured detail for candidates and search space
        await tracker.emit(
            "acting",
            "Search space configured",
            detail=ForgeCandidatesDetail(
                primary={
                    "name": architecture,
                    "confidence": 0.9,
                    "rationale": f"Selected for {modality} {task_type}",
                },
                alternatives=[
                    {"name": a} for a in ["lightgbm", "xgboost", "tabnet"] if a != architecture
                ],
            ).model_dump(),
        )

        await tracker.emit(
            "acting",
            "Search space defined",
            detail=ForgeSearchSpaceDetail(
                architecture=architecture,
                dimensions=len(search_space),
                parameters=search_space,
            ).model_dump(),
        )

        if progress_callback:
            progress_callback("Publishing TRAINING_SCRIPT_READY...")

        from contracts.events import TrainingScriptReadyEvent

        await publish(
            self.redis._client,
            STREAM_FORGE_OUTPUT,
            TRAINING_SCRIPT_READY,
            TrainingScriptReadyEvent(
                job_id=self.job_id,
                script_path=script_path,
                search_space_redis_key=search_key,
            ),
        )

        if progress_callback:
            progress_callback("Complete.")

        await tracker.done(
            "Training script ready",
            detail={"architecture": architecture, "script_path": script_path},
        )

        log_mission_state(
            "FORGE_COMPLETE",
            self.job_id,
            architecture=architecture,
            imbalance_strategy=imbalance_strategy,
            retry_number=retry_context.attempt if retry_context else 0,
            script_path=script_path,
            search_space=search_space,
            is_retry=str(is_retry),
            brief=brief_raw,
        )

        self.logger.info(f"[job={self.job_id}] Training script ready at {script_path}")

    async def run_with_brief(
        self,
        brief: dict,
        progress_callback: Any = None,
        retry_context: RetryPlan | None = None,
    ) -> str:
        brief_key = f"job:{self.job_id}:mission_brief"
        await self.redis.set_json(brief_key, brief)
        await self.run(progress_callback=progress_callback, retry_context=retry_context)
        return str(get_job_paths(self.job_id).script_path)
