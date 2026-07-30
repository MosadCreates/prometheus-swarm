"""Exit tests for the init wizard — CliRunner with isolated filesystem."""

import os
from pathlib import Path

from click.testing import CliRunner
from prometheus.main import cli


def _write_env(
    td_path: str,
    content: str = "ANTHROPIC_API_KEY=sk-real-for-testing\nANTHROPIC_MODEL=claude-sonnet-4-6\n",
):
    env_path = Path(td_path) / ".env"
    env_path.write_text(content)
    (Path(td_path) / "outputs").mkdir(exist_ok=True)


# ===================================================================
# --non-interactive mode
# ===================================================================


class TestInitNonInteractive:
    def test_init_non_interactive_missing_key_fails(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=str(tmp_path)):
            result = runner.invoke(
                cli,
                [
                    "init",
                    "--non-interactive",
                    "--provider",
                    "anthropic",
                    "--api-key-env",
                    "MISSING_ENV_VAR",
                ],
            )
        assert result.exit_code != 0
        assert "failed" in result.output.lower() or "verification" in result.output.lower()

    def test_init_non_interactive_checks_env(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=str(tmp_path)):
            result = runner.invoke(
                cli,
                [
                    "init",
                    "--non-interactive",
                    "--provider",
                    "anthropic",
                    "--api-key-env",
                    "ANTHROPIC_API_KEY",
                ],
                env={"ANTHROPIC_API_KEY": "sk-test-real-key"},
            )
        assert result.exit_code != 0 or "Configuration complete" in result.output


# ===================================================================
# Interactive mode — CliRunner with input= feeding stdin
# ===================================================================


class TestInitInteractive:
    def test_wizard_welcome_screen(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=str(tmp_path)):
            result = runner.invoke(cli, ["init"], input="\n\n\n\n\n")
        assert "PROMETHEUS" in result.output
        assert "first time" in result.output.lower() or "set up" in result.output.lower()

    def test_wizard_provider_selection(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=str(tmp_path)):
            result = runner.invoke(cli, ["init"], input="\n\n\n\n\n")
        assert "model provider" in result.output.lower()
        assert "Anthropic" in result.output

    def test_wizard_checks_prerequisites(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=str(tmp_path)):
            result = runner.invoke(cli, ["init"], input="\n\n\n\n\n")
        assert "Checking your environment" in result.output or "Python" in result.output


# ===================================================================
# First-run auto-trigger (no config → wizard, not splash)
# ===================================================================


class TestInitFirstRun:
    def test_no_config_triggers_wizard(self, tmp_path):
        """No .env file → running with --shell triggers wizard, not splash."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=str(tmp_path)):
            result = runner.invoke(cli, ["--shell"], input="\n\n\n\n\n")
        assert "PROMETHEUS" in result.output or "first time" in result.output.lower()

    def test_config_present_skips_wizard(self, tmp_path):
        """Having .env with key → wizard is NOT shown on --shell startup."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=str(tmp_path)) as td:
            _write_env(td)
            result = runner.invoke(cli, ["--shell"], input="exit\n")
        assert "PROMETHEUS" not in result.output
        assert "prometheus" in result.output.lower() or "mission" in result.output.lower()
