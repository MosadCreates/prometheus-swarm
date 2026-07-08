"""Forge Quality Feedback — Redis-backed error prevention database (Gap 3).

Tracks error statistics per architecture and auto-generates PreventionRules
when error rates exceed thresholds. The template renderer queries this data
to proactively harden generated scripts.

Three-tier storage:
  1. Redis hashes (primary — fast concurrent reads during template rendering)
  2. JSON file (fallback — no Redis dependency for basic operation)
  3. Prevention rules in Redis (auto-generated when thresholds exceeded)

Feed the stats by calling record_repair() from Dissect after every repair attempt.
Forge queries get_error_rate() / get_top_failures() during script generation.
"""

import json
import logging
import os
import time
from collections import Counter
from typing import Any

logger = logging.getLogger(__name__)

FEEDBACK_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "research", "forge_feedback.json"
)

# ── Auto-prevention thresholds ─────────────────────────────────────
MIN_ERRORS_FOR_AUTO_PREVENTION = 3
MIN_ERROR_RATE_FOR_AUTO_PREVENTION = 0.30
AUTO_PREVENTION_CONFIDENCE = 0.70

# Redis key prefixes
REDIS_STATS_PREFIX = "forge:error_stats"
REDIS_TOTALS_KEY = "forge:error_stats:totals"

# Architecture keywords for script inference
_ARCHITECTURE_KEYWORDS = {
    "lightgbm": ["lightgbm", "lgb.LGBM", "LGBMClassifier", "LGBMRegressor"],
    "xgboost": ["xgboost", "xgb.XGB", "XGBClassifier", "XGBRegressor"],
    "tabnet": ["tabnet", "TabNetClassifier", "TabNetRegressor", "pytorch_tabnet"],
    "distilbert": ["distilbert", "DistilBert", "distilbert-base"],
    "efficientnet": ["efficientnet", "efficientnet_b", "EfficientNet"],
}


def infer_architecture(script_content: str) -> str:
    """Infer the ML architecture from script content by keyword matching."""
    script_lower = script_content.lower() if script_content else ""
    for arch, keywords in _ARCHITECTURE_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in script_lower:
                return arch
    return "unknown"


# ── File-based fallback (original implementation) ──────────────────


def _load_feedback() -> dict[str, Any]:
    try:
        with open(FEEDBACK_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}

    defaults = {
        "recurring_categories": {},
        "category_by_architecture": {},
        "top_failures": [],
        "total_jobs_tracked": 0,
        "total_repairs_needed": 0,
    }
    for key, default in defaults.items():
        if key not in data:
            data[key] = default
    return data


def _save_feedback(data: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(FEEDBACK_FILE), exist_ok=True)
    with open(FEEDBACK_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _get_recommendation(category: str, architecture: str) -> str:
    recommendations = {
        "dtype_mismatch": "Add LabelEncoder/OrdinalEncoder for categorical columns during preprocessing; "
        "use pd.to_numeric with errors='coerce' for mixed-type columns",
        "missing_column": "Verify all column names used in script match actual dataset columns; "
        "use df.columns to list available columns before referencing them",
        "syntax_error": "Run ast.parse() on generated script before writing to file; "
        "use black or autopep8 formatter",
        "import_error": f"Add missing {architecture} dependencies to requirements in training container; "
        "verify pip install in Dockerfile",
        "name_error": "Never generate JS-style literals (false, true, null); use Python literals",
        "nan_propagation": "Add SimpleImputer step before model training in generated script",
        "empty_dataset": "Check train_test_split produces non-empty sets; add fallback split logic",
        "shape_mismatch": "Align feature count between training and inference; cache feature list at training time",
        "sparse_matrix": "Convert sparse matrix to dense before SMOTE; or replace SMOTE with class_weight",
        "convergence_failure": "Increase max_iter; switch solver; reduce regularization",
        "checkpoint_corruption": "Delete corrupt checkpoint; increase save frequency",
        "oom": "Reduce batch size; switch to chunked data loading",
    }
    return recommendations.get(
        category,
        f"Avoid errors of type {category} in {architecture} scripts",
    )


# ── Redis-backed primary storage (for fast reads during rendering) ──


async def record_repair_redis(
    redis_client: Any,
    job_id: str,
    category: str,
    architecture: str,
    sandbox_passed: bool,
    script_content: str | None = None,
) -> None:
    """Record a repair attempt in Redis and auto-generate prevention rules.

    This is the Redis-backed version of record_repair(). It:
      1. Increments the error counter for (architecture, category)
      2. Tracks total scripts and error rates
      3. Auto-creates a PreventionRule if thresholds are exceeded
      4. Also syncs to the JSON file for research persistence
    """
    if architecture == "unknown" and script_content:
        architecture = infer_architecture(script_content)

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    try:
        # Increment per-architecture error stats
        stats_key = f"{REDIS_STATS_PREFIX}:{architecture}:{category}"
        await redis_client.hincrby(stats_key, "count", 1)
        await redis_client.hset(stats_key, "last_seen", now)
        await redis_client.expire(stats_key, 86400 * 90)  # 90-day TTL

        # Track total scripts per architecture
        totals_key = REDIS_TOTALS_KEY
        script_count_key = f"{architecture}:total_scripts"
        error_count_key = f"{architecture}:total_errors"

        await redis_client.hincrby(totals_key, f"{architecture}:total_errors", 1)

        if sandbox_passed:
            # Successful repair — no auto-prevention needed
            logger.debug(f"Repair recorded | arch={architecture} cat={category} outcome=success")
            _sync_to_file(job_id, category, architecture, sandbox_passed)
            return

        # ── Check auto-prevention thresholds ──────────────────────────
        count = await redis_client.hget(stats_key, "count")
        count = int(count) if count else 1
        total_scripts = await redis_client.hget(totals_key, script_count_key)
        total_scripts = (
            int(total_scripts)
            if total_scripts
            else await _get_approx_total(redis_client, architecture)
        )
        error_rate = count / max(total_scripts, 1)

        if (
            count >= MIN_ERRORS_FOR_AUTO_PREVENTION
            and error_rate >= MIN_ERROR_RATE_FOR_AUTO_PREVENTION
        ):
            await _auto_create_prevention_rule(
                redis_client,
                architecture,
                category,
                count,
                error_rate,
            )

        logger.info(
            f"Repair recorded | arch={architecture} cat={category} "
            f"count={count} rate={error_rate:.2%} auto_prevention={count >= MIN_ERRORS_FOR_AUTO_PREVENTION and error_rate >= MIN_ERROR_RATE_FOR_AUTO_PREVENTION}"
        )

    except Exception as e:
        logger.warning(f"Redis quality feedback failed: {e}")

    _sync_to_file(job_id, category, architecture, sandbox_passed)


async def _get_approx_total(redis_client: Any, architecture: str) -> int:
    """Get approximate total scripts generated for an architecture."""
    totals_key = REDIS_TOTALS_KEY
    try:
        val = await redis_client.hget(totals_key, f"{architecture}:total_scripts")
        return int(val) if val else 1
    except Exception:
        return 1


async def increment_script_count(redis_client: Any, architecture: str) -> None:
    """Increment the total script counter for an architecture.

    Called by Forge after generating a script (before training starts).
    """
    try:
        totals_key = REDIS_TOTALS_KEY
        await redis_client.hincrby(totals_key, f"{architecture}:total_scripts", 1)
        await redis_client.hincrby(totals_key, "global:total_scripts", 1)
        await redis_client.expire(totals_key, 86400 * 90)
    except Exception as e:
        logger.debug(f"Failed to increment script count: {e}")


async def _auto_create_prevention_rule(
    redis_client: Any,
    architecture: str,
    category: str,
    count: int,
    error_rate: float,
) -> None:
    """Auto-generate a PreventionRule when error thresholds are exceeded.

    The rule is created from the statistical data: the recommendation text
    becomes the code snippet, and the modification type is determined by
    the error category.
    """
    try:
        from agents.forge.prevention import PreventionRule, push_prevention_rule
        from shared.metrics import FORGE_ERROR_PREVENTIONS_AUTO

        rec = _get_recommendation(category, architecture)
        mod_type = _category_to_modification_type(category)

        rule = PreventionRule(
            architecture=architecture,
            error_category=category,
            modification_type=mod_type,
            code_snippet=_recommendation_to_code_snippet(rec, category),
            summary=f"[auto] {category} in {architecture}: "
            f"{count} occurrences @ {error_rate:.0%} rate",
            source_patch_id=f"auto-{architecture}-{category}",
            confidence=AUTO_PREVENTION_CONFIDENCE,
            occurrences=count,
        )
        await push_prevention_rule(redis_client, rule)
        FORGE_ERROR_PREVENTIONS_AUTO.labels(
            architecture=architecture,
            category=category,
        ).inc()

        logger.info(
            f"Auto-prevention rule created | arch={architecture} "
            f"cat={category} count={count} rate={error_rate:.0%}"
        )
    except Exception as e:
        logger.warning(f"Auto-prevention failed: {e}")


def _category_to_modification_type(category: str) -> str:
    """Map error category to the best prevention modification type."""
    mapping = {
        "dtype_mismatch": "insert_after_imports",
        "missing_column": "insert_after_data_loading",
        "nan_propagation": "insert_after_data_loading",
        "shape_mismatch": "insert_after_data_loading",
        "sparse_matrix": "insert_after_imports",
        "empty_dataset": "insert_after_data_loading",
        "convergence_failure": "insert_before_checkpoint",
        "checkpoint_corruption": "insert_before_checkpoint",
        "oom": "insert_after_imports",
    }
    return mapping.get(category, "insert_after_imports")


def _recommendation_to_code_snippet(recommendation: str, category: str) -> str:
    """Convert a textual recommendation into an executable Python code snippet."""
    snippets = {
        "dtype_mismatch": (
            "# Auto-fix: ensure numeric columns are numeric\n"
            "for _col in df.select_dtypes(include=['object']).columns:\n"
            "    try:\n"
            "        df[_col] = pd.to_numeric(df[_col], errors='coerce')\n"
            "    except (ValueError, TypeError):\n"
            "        pass"
        ),
        "missing_column": (
            "# Auto-fix: verify expected columns exist\n"
            "_expected_cols = [{{ column_names }}]\n"
            "_actual_cols = set(df.columns)\n"
            "for _col in _expected_cols:\n"
            "    if _col not in _actual_cols:\n"
            '        logger.warning(f"Column {_col} not found, using default value")\n'
            "        df[_col] = 0"
        ),
        "nan_propagation": (
            "# Auto-fix: drop rows with NaN in target then fill NaN in features\n"
            "df = df.dropna(subset=[target.name if hasattr(target, 'name') else '{{target_column}}'])\n"
            "for _c in df.select_dtypes(include=['int64', 'float64']).columns:\n"
            "    df[_c] = df[_c].fillna(df[_c].median())"
        ),
        "empty_dataset": (
            "# Auto-fix: ensure non-empty split\n"
            "if len(df) < 10:\n"
            '    raise ValueError(f"Dataset too small: {len(df)} rows")\n'
            "if len(y_train.unique()) < 2:\n"
            "    X_train, X_test, y_train, y_test = train_test_split(\n"
            "        df, target, test_size=0.3, random_state=42\n"
            "    )"
        ),
    }
    return snippets.get(category, f"# Recommendation: {recommendation}")


def _sync_to_file(job_id: str, category: str, architecture: str, sandbox_passed: bool) -> None:
    """Sync a repair record to the JSON file for research persistence."""
    try:
        feedback = _load_feedback()
        feedback["total_jobs_tracked"] += 1
        if not sandbox_passed:
            feedback["total_repairs_needed"] += 1

        cat_key = f"{architecture}::{category}"
        if cat_key not in feedback["recurring_categories"]:
            feedback["recurring_categories"][cat_key] = {
                "architecture": architecture,
                "category": category,
                "count": 0,
                "last_seen": "",
                "recommendation": _get_recommendation(category, architecture),
            }
        feedback["recurring_categories"][cat_key]["count"] += 1
        feedback["recurring_categories"][cat_key]["last_seen"] = (
            __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
        )

        if architecture not in feedback["category_by_architecture"]:
            feedback["category_by_architecture"][architecture] = {}
        arch_cats = feedback["category_by_architecture"][architecture]
        arch_cats[category] = arch_cats.get(category, 0) + 1

        all_counts: Counter = Counter()
        for key, val in feedback["recurring_categories"].items():
            all_counts[key] = val["count"]
        feedback["top_failures"] = [
            {
                "key": k,
                "count": c,
                "recommendation": feedback["recurring_categories"][k]["recommendation"],
            }
            for k, c in all_counts.most_common(10)
        ]

        _save_feedback(feedback)
    except Exception as e:
        logger.warning(f"Failed to sync to feedback file: {e}")


# ── Legacy function (backward compat) ────────────────────────────────


def record_repair(
    job_id: str,
    category: str,
    architecture: str,
    sandbox_passed: bool,
    redis_client: Any | None = None,
    script_content: str | None = None,
) -> None:
    """Record a repair attempt.

    Args:
        job_id: The job ID.
        category: Error taxonomy category.
        architecture: ML architecture (e.g., "lightgbm"). If "unknown",
            inferred from script_content.
        sandbox_passed: Whether the sandbox test passed.
        redis_client: Optional Redis client for stats recording.
        script_content: Original script content (used for architecture inference).
    """
    if redis_client is not None:
        import asyncio

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(
                    record_repair_redis(
                        redis_client,
                        job_id,
                        category,
                        architecture,
                        sandbox_passed,
                        script_content,
                    )
                )
            else:
                loop.run_until_complete(
                    record_repair_redis(
                        redis_client,
                        job_id,
                        category,
                        architecture,
                        sandbox_passed,
                        script_content,
                    )
                )
            return
        except RuntimeError:
            pass

    # Fallback: file-based recording
    if architecture == "unknown" and script_content:
        architecture = infer_architecture(script_content)
    _sync_to_file(job_id, category, architecture, sandbox_passed)


# ── Redis query functions (for Forge template renderer) ──────────────


async def get_error_rate_redis(
    redis_client: Any,
    architecture: str,
    category: str | None = None,
) -> float | dict[str, float]:
    """Get the error rate for a specific (architecture, category) pair
    or all categories for an architecture.

    Returns a single float if category is specified, or a dict of
    {category: rate} if category is None.
    """
    try:
        totals_key = REDIS_TOTALS_KEY
        total_scripts_raw = await redis_client.hget(totals_key, f"{architecture}:total_scripts")
        total_scripts = int(total_scripts_raw) if total_scripts_raw else 1

        if category:
            stats_key = f"{REDIS_STATS_PREFIX}:{architecture}:{category}"
            count_raw = await redis_client.hget(stats_key, "count")
            count = int(count_raw) if count_raw else 0
            return count / max(total_scripts, 1)

        # Return all categories
        pattern = f"{REDIS_STATS_PREFIX}:{architecture}:*"
        keys = await redis_client.keys(pattern)
        rates = {}
        for key in keys:
            cat = (
                key.split(f"{REDIS_STATS_PREFIX}:{architecture}:")[-1]
                if f"{REDIS_STATS_PREFIX}:{architecture}:" in key
                else ""
            )
            if cat:
                count_raw = await redis_client.hget(key, "count")
                count = int(count_raw) if count_raw else 0
                rates[cat] = count / max(total_scripts, 1)
        return rates

    except Exception as e:
        logger.warning(f"Failed to query error rate: {e}")
        return 0.0 if category else {}


async def get_top_failures_redis(
    redis_client: Any,
    architecture: str,
    n: int = 5,
) -> list[dict]:
    """Return top-N failure patterns for a given architecture from Redis."""
    try:
        pattern = f"{REDIS_STATS_PREFIX}:{architecture}:*"
        keys = await redis_client.keys(pattern)
        failures = []
        for key in keys:
            cat = (
                key.split(f"{REDIS_STATS_PREFIX}:{architecture}:")[-1]
                if f"{REDIS_STATS_PREFIX}:{architecture}:" in key
                else ""
            )
            if cat:
                count_raw = await redis_client.hget(key, "count")
                count = int(count_raw) if count_raw else 0
                last_seen = await redis_client.hget(key, "last_seen") or ""
                failures.append(
                    {
                        "category": cat,
                        "count": count,
                        "last_seen": last_seen,
                        "recommendation": _get_recommendation(cat, architecture),
                    }
                )
        failures.sort(key=lambda x: -x["count"])
        return failures[:n]

    except Exception as e:
        logger.warning(f"Failed to query top failures: {e}")
        return []


async def get_recommendations_from_redis(
    redis_client: Any,
    architecture: str,
) -> list[dict]:
    """Return sorted recommendations for an architecture based on Redis error stats."""
    try:
        failures = await get_top_failures_redis(redis_client, architecture, n=10)
        return [
            {
                "category": f["category"],
                "count": f["count"],
                "recommendation": f["recommendation"],
                "error_rate": f["count"]
                / max(
                    int(
                        await redis_client.hget(REDIS_TOTALS_KEY, f"{architecture}:total_scripts")
                        or 1
                    ),
                    1,
                ),
            }
            for f in failures
        ]
    except Exception as e:
        logger.warning(f"Failed to query recommendations: {e}")
        return []
