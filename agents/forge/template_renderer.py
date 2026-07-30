"""Forge template renderer — deterministic script generation from Jinja templates.

Pipeline:
    1. Jinja renders template with mission variables
    2. ast.parse() validates syntactic correctness
    3. Static prevention applies deterministic fixes (encoding, dtypes, validation)
    4. ast.parse() validates post-fix correctness
    5. Redis-based prevention rules from Dissect history are applied
    6. Final validation + script returned

Usage:
    script = select_and_render(mission_brief, job_id, data_path, architecture)
    if script:
        write_file(script)
    else:
        fallback_to_fstring_generator()
"""

import ast
import logging
import os
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, TemplateNotFound

logger = logging.getLogger(__name__)

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")

_env = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    trim_blocks=True,
    lstrip_blocks=True,
    undefined=StrictUndefined,
    autoescape=False,
)

_TEMPLATE_MAP: dict[tuple[str, str], str] = {
    ("lightgbm", "binary"): "lightgbm_binary.py.jinja",
    ("lightgbm", "multiclass"): "lightgbm_multiclass.py.jinja",
    ("lightgbm", "regression"): "lightgbm_regression.py.jinja",
    ("xgboost", "binary"): "xgboost_binary.py.jinja",
    ("xgboost", "multiclass"): "xgboost_multiclass.py.jinja",
    ("xgboost", "regression"): "xgboost_regression.py.jinja",
    ("tabnet", "binary"): "tabnet.py.jinja",
    ("tabnet", "multiclass"): "tabnet.py.jinja",
    ("tabnet", "regression"): "tabnet.py.jinja",
    ("distilbert", "binary"): "distilbert.py.jinja",
    ("distilbert", "multiclass"): "distilbert.py.jinja",
    ("efficientnet", "binary"): "efficientnet.py.jinja",
    ("efficientnet", "multiclass"): "efficientnet.py.jinja",
}

ARCHITECTURE_TASK_MAP: dict[str, list[str]] = {
    "lightgbm": ["binary", "multiclass", "regression"],
    "xgboost": ["binary", "multiclass", "regression"],
    "tabnet": ["binary", "multiclass", "regression"],
    "distilbert": ["binary", "multiclass"],
    "efficientnet": ["binary", "multiclass"],
}


def _classify_task_type(task_type: str) -> str:
    task_lower = task_type.lower().strip()
    if task_lower == "regression":
        return "regression"
    if task_lower in ("multiclass", "multi_class", "multi-class"):
        return "multiclass"
    return "binary"


def has_template(architecture: str, task_type: str) -> bool:
    subtask = _classify_task_type(task_type)
    template_name = _TEMPLATE_MAP.get((architecture, subtask))
    if template_name is None:
        return False
    template_path = os.path.join(TEMPLATES_DIR, template_name)
    return os.path.isfile(template_path)


def available_templates() -> list[dict[str, str]]:
    """Return metadata about all available templates for discovery."""
    result = []
    for (arch, subtask), tpl in _TEMPLATE_MAP.items():
        template_path = os.path.join(TEMPLATES_DIR, tpl)
        if os.path.isfile(template_path):
            result.append(
                {
                    "architecture": arch,
                    "task": subtask,
                    "template": tpl,
                    "size_bytes": os.path.getsize(template_path),
                }
            )
    return result


def _resolve_template_name(architecture: str, task_subtype: str) -> str | None:
    return _TEMPLATE_MAP.get((architecture, task_subtype))


def _build_variables(
    mission_brief: dict,
    job_id: str,
    data_path: str | None = None,
    design_summary: str | None = None,
) -> dict:
    dataset = mission_brief.get("dataset", {})
    column_types = dataset.get("column_types", {})

    categorical_cols = sorted(col for col, typ in column_types.items() if typ == "categorical")
    numeric_cols = sorted(col for col, typ in column_types.items() if typ == "numeric")

    imbalance = mission_brief.get("imbalance_strategy", "none")
    num_rows = dataset.get("num_rows", 0) or 0

    file_path = data_path or dataset.get("file_path", "data.csv")
    data_filename = os.path.basename(file_path)
    data_delimiter = dataset.get("delimiter", ",")

    target_column = mission_brief.get("target_column")
    if not target_column:
        candidates = [
            "target",
            "label",
            "y",
            "Survived",
            "survived",
            "class",
            "outcome",
            "result",
            "answer",
            "class_label",
        ]
        target_column = "target"
        for col in column_types:
            if col in candidates:
                target_column = col
                break
        if target_column == "target" and column_types:
            numeric_cols_inferred = [c for c in column_types if column_types[c] == "numeric"]
            if numeric_cols_inferred:
                target_column = numeric_cols_inferred[0]

    config = {
        "job_id": job_id,
        "data_filename": data_filename,
        "data_delimiter": data_delimiter,
        "target_column": target_column,
        "task_type": _classify_task_type(mission_brief.get("task_type", "classification")),
        "evaluation_metric": mission_brief.get("evaluation_metric") or "auc_roc",
        "categorical_cols": categorical_cols,
        "numeric_cols": numeric_cols,
        "imbalance_strategy": imbalance,
        "use_smote": imbalance == "smote",
        "use_class_weight": imbalance == "class_weight",
        "enable_optuna": True,
        "optuna_max_trials": 20,
        "enable_early_stopping": num_rows > 10000,
        "design_summary": (design_summary or "").strip(),
        "num_rows": num_rows,
    }
    return config


def validate_script(script: str) -> bool:
    """Validate script is syntactically valid Python."""
    try:
        ast.parse(script)
        return True
    except SyntaxError:
        return False


def validate_script_rich(script: str) -> dict[str, Any]:
    """Validate script and return detailed diagnostics.

    Checks:
        1. Syntax valid (ast.parse)
        2. Has result.json write (orchestrator needs it)
        3. Has TRAINING_COMPLETE print (orchestrator needs it)
        4. Has no unprotected pd.read_csv without encoding
        5. Has no narrow numeric dtype selection

    Returns dict with:
        valid: bool — overall validity
        syntax_ok: bool
        has_result_json: bool
        has_training_complete: bool
        has_encoding: bool
        has_number_dtype: bool
        findings: list[str]
    """
    from agents.forge.static_prevention import validate_script_static

    # Syntax check
    syntax_ok = validate_script(script)

    # Content checks
    has_result_json = "result.json" in script
    has_training_complete = (
        'print("TRAINING_COMPLETE' in script or "print('TRAINING_COMPLETE" in script
    )

    # Run static analysis
    findings_raw = validate_script_static(script) if syntax_ok else []
    findings = [f"[{f['severity'].upper()}] {f['message']}" for f in findings_raw]

    return {
        "valid": syntax_ok and has_result_json and has_training_complete and len(findings) == 0,
        "syntax_ok": syntax_ok,
        "has_result_json": has_result_json,
        "has_training_complete": has_training_complete,
        "findings": findings_raw,
        "diagnostics": findings,
    }


async def _report_error_stats(architecture: str, job_id: str) -> None:
    """Query Redis error stats and log known high-failure categories.

    Uses a sync Redis connection (via redis.Redis) to avoid racing with
    the caller closing forge.redis, and to avoid pending-task-destroyed
    errors when the event loop shuts down before the fire-and-forget
    task completes.
    """
    import os

    import redis as sync_redis

    host = os.getenv("REDIS_HOST", "localhost")
    port = int(os.getenv("REDIS_PORT", 6379))
    password = os.getenv("REDIS_PASSWORD") or None

    try:
        r = sync_redis.Redis(host=host, port=port, password=password, decode_responses=True)
        r.ping()
        from agents.forge.quality_feedback import REDIS_STATS_PREFIX

        pattern = f"{REDIS_STATS_PREFIX}:{architecture}:*"
        keys = r.keys(pattern)
        failures = []
        for key in keys:
            cat = (
                key.split(f"{REDIS_STATS_PREFIX}:{architecture}:")[-1]
                if f"{REDIS_STATS_PREFIX}:{architecture}:" in key
                else ""
            )
            if cat:
                count = int(r.hget(key, "count") or 0)
                failures.append({"category": cat, "count": count})
        failures.sort(key=lambda x: -x["count"])
        top = failures[:5]
        if top:
            stats_str = "; ".join(
                f"{f['category']} ({f['count']}x)" for f in top if f["count"] >= 2
            )
            if stats_str:
                logger.warning(
                    f"[job={job_id}] Known failure patterns for " f"{architecture}: {stats_str}"
                )
        r.close()
    except Exception:
        pass


def select_and_render(
    mission_brief: dict,
    job_id: str,
    data_path: str | None = None,
    architecture: str | None = None,
    design_summary: str | None = None,
    redis_client: Any | None = None,
) -> str | None:
    if not architecture:
        architecture = mission_brief.get("recommended_architecture_family", "lightgbm")

    task_subtype = _classify_task_type(mission_brief.get("task_type", "classification"))
    template_name = _resolve_template_name(architecture, task_subtype)

    if template_name is None:
        logger.info(
            f"No template for ({architecture}, {task_subtype}) — "
            f"falling back to f-string generator"
        )
        return None

    try:
        template = _env.get_template(template_name)
    except TemplateNotFound:
        logger.warning(f"Template file {template_name} not found — falling back")
        return None
    except Exception:
        logger.warning(f"Failed to load template {template_name} — falling back")
        return None

    vars = _build_variables(mission_brief, job_id, data_path, design_summary)

    try:
        script = template.render(**vars)
    except Exception as e:
        logger.warning(f"Template rendering failed for {template_name}: {e}")
        return None

    if not validate_script(script):
        logger.warning(f"Template {template_name} produced invalid Python — falling back")
        return None

    # ── Apply static prevention (Phase 3: deterministic, no Redis needed) ──
    try:
        from agents.forge.static_prevention import apply_static_prevention

        script, findings = apply_static_prevention(script, mission_brief)
        if findings:
            logger.info(
                f"[job={job_id}] Static prevention found {len(findings)} "
                f"pattern(s) in {template_name}"
            )

        # Re-validate after static prevention transforms
        if not validate_script(script):
            logger.error(
                f"Static prevention broke template {template_name} — "
                f"this is a bug in static_prevention.py"
            )
            # Return the original (valid) script
            script = template.render(**vars)
    except Exception as e:
        logger.warning(f"Static prevention skipped: {e}")

    # ── Apply prevention rules from Redis (Gap 2) ───────────────────────
    if redis_client is not None:
        try:
            from agents.forge.prevention import (
                load_all_prevention_rules,
                sync_load_prevention_rules,
                apply_all_prevention_rules,
            )
            from shared.metrics import FORGE_PREVENTIONS_APPLIED

            # Log cross-architecture rules once for observability
            load_all_prevention_rules(redis_client)

            rules = sync_load_prevention_rules(redis_client, architecture)
            if rules:
                patched = apply_all_prevention_rules(script, rules)
                if patched != script:
                    if validate_script(patched):
                        script = patched
                        FORGE_PREVENTIONS_APPLIED.labels(
                            architecture=architecture,
                            job_id=job_id,
                        ).inc(len(rules))
                        logger.info(
                            f"[job={job_id}] Applied {len(rules)} prevention "
                            f"rules for {architecture}"
                        )
                    else:
                        logger.warning(
                            f"Prevention rules produced invalid Python for "
                            f"{architecture} — using original script"
                        )
        except Exception as e:
            logger.debug(f"Prevention rules skipped: {e}")

    # ── Log known high-failure categories from error stats (Gap 3) ──────
    # Fire-and-forget — _report_error_stats creates its own Redis connection
    # so it doesn't race with the caller closing forge.redis.
    try:
        import asyncio

        loop = asyncio.get_event_loop()
        if loop.is_running() and not loop.is_closed():
            asyncio.create_task(_report_error_stats(architecture, job_id))
        elif not loop.is_closed():
            loop.run_until_complete(_report_error_stats(architecture, job_id))
    except (RuntimeError, Exception):
        pass

    logger.info(
        f"[job={job_id}] Rendered template {template_name} "
        f"({len(script)} bytes) for architecture={architecture}"
    )
    return script
