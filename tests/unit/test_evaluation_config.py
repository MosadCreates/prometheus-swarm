"""Tests for evaluation/config.py — experimental feature toggles."""

import os
from unittest.mock import patch

from evaluation import config as eval_config


def test_defaults_all_false():
    """All toggles default to False when no env vars are set."""
    with patch.dict(os.environ, {}, clear=True):
        cfg = eval_config.load_config()
        assert cfg["DISABLE_PLANNER"] is False
        assert cfg["DISABLE_PATCH_MEMORY"] is False
        assert cfg["DISABLE_DISSECT"] is False
        assert cfg["STRESS_MODE"] is False
        assert cfg["PROFILE_MODE"] is False

        # Module-level attribute access should also be False
        assert eval_config.DISABLE_PLANNER is False
        assert eval_config.DISABLE_PATCH_MEMORY is False
        assert eval_config.DISABLE_DISSECT is False
        assert eval_config.PROFILE_MODE is False


def test_env_vars_enable_toggles():
    with patch.dict(
        os.environ,
        {
            "DISABLE_PLANNER": "1",
            "DISABLE_PATCH_MEMORY": "true",
            "DISABLE_DISSECT": "yes",
            "STRESS_MODE": "TRUE",
            "PROFILE_MODE": "1",
        },
        clear=True,
    ):
        cfg = eval_config.load_config()
        assert cfg["DISABLE_PLANNER"] is True
        assert cfg["DISABLE_PATCH_MEMORY"] is True
        assert cfg["DISABLE_DISSECT"] is True
        assert cfg["STRESS_MODE"] is True
        assert cfg["PROFILE_MODE"] is True

        # Dynamic attribute access
        assert eval_config.DISABLE_PLANNER is True
        assert eval_config.DISABLE_PATCH_MEMORY is True
        assert eval_config.DISABLE_DISSECT is True


def test_env_vars_false_values():
    with patch.dict(
        os.environ,
        {
            "DISABLE_PLANNER": "0",
            "DISABLE_PATCH_MEMORY": "false",
            "DISABLE_DISSECT": "no",
        },
        clear=True,
    ):
        cfg = eval_config.load_config()
        assert cfg["DISABLE_PLANNER"] is False
        assert cfg["DISABLE_PATCH_MEMORY"] is False
        assert cfg["DISABLE_DISSECT"] is False


def test_env_vars_partial():
    with patch.dict(
        os.environ,
        {
            "DISABLE_PLANNER": "1",
        },
        clear=True,
    ):
        cfg = eval_config.load_config()
        assert cfg["DISABLE_PLANNER"] is True
        assert cfg["DISABLE_PATCH_MEMORY"] is False
        assert cfg["DISABLE_DISSECT"] is False
        assert cfg["STRESS_MODE"] is False
        assert cfg["PROFILE_MODE"] is False


def test_attribute_error_for_unknown_name():
    import pytest

    with pytest.raises(AttributeError):
        _ = eval_config.NONEXISTENT_VAR


def test_dynamic_reflects_env_change():
    """Attribute access reads fresh env vars every time."""
    with patch.dict(os.environ, {"DISABLE_PLANNER": "1"}, clear=True):
        assert eval_config.DISABLE_PLANNER is True
    # After exiting the patch, the env var is gone
    assert eval_config.DISABLE_PLANNER is False
