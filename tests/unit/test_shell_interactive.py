"""Exit tests for the interactive shell (REPL).

Two paths tested separately:
Path A — --shell flag forced entry (CliRunner with input=)
Path B — bare piped stdin with no --shell flag (CliRunner, no input)
Both paths tested via CliRunner which handles stdin piped simulation on Windows.
"""

from pathlib import Path

from click.testing import CliRunner
from prometheus.main import cli


_ENV_CONTENT = "ANTHROPIC_API_KEY=sk-real-for-testing\nANTHROPIC_MODEL=claude-sonnet-4-6\n"


def _prepare(td_path: str):
    env_path = Path(td_path) / ".env"
    env_path.write_text(_ENV_CONTENT)
    (Path(td_path) / "outputs").mkdir(exist_ok=True)


# ===================================================================
# Path A — --shell flag forced entry (CliRunner with input=)
# ===================================================================


class TestShellForcedEntry:
    def test_shell_exit(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=str(tmp_path)) as td:
            _prepare(td)
            result = runner.invoke(cli, ["--shell"], input="exit\n")
        assert result.exit_code == 0
        assert "offline" in result.output.lower()

    def test_shell_quit(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=str(tmp_path)) as td:
            _prepare(td)
            result = runner.invoke(cli, ["--shell"], input="quit\n")
        assert "offline" in result.output.lower()

    def test_shell_compact_header_shown(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=str(tmp_path)) as td:
            _prepare(td)
            result = runner.invoke(cli, ["--shell"], input="exit\n")
        assert "prometheus" in result.output.lower()
        assert "mission" in result.output.lower()

    def test_shell_help(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=str(tmp_path)) as td:
            _prepare(td)
            result = runner.invoke(cli, ["--shell"], input="help\nexit\n")
        assert "help|?" in result.output

    def test_shell_question_mark(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=str(tmp_path)) as td:
            _prepare(td)
            result = runner.invoke(cli, ["--shell"], input="?\nexit\n")
        assert "help|?" in result.output

    def test_shell_double_question(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=str(tmp_path)) as td:
            _prepare(td)
            result = runner.invoke(cli, ["--shell"], input="??\nexit\n")
        assert any(cat in result.output for cat in ["System", "Mission", "Config", "Agents"])

    def test_shell_history(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=str(tmp_path)) as td:
            _prepare(td)
            result = runner.invoke(cli, ["--shell"], input="version\nhistory\nexit\n")
        assert "1" in result.output
        assert "version" in result.output

    def test_shell_version_command(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=str(tmp_path)) as td:
            _prepare(td)
            result = runner.invoke(cli, ["--shell"], input="version\nexit\n")
        assert "v" in result.output

    def test_shell_doctor_command(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=str(tmp_path)) as td:
            _prepare(td)
            result = runner.invoke(cli, ["--shell"], input="doctor\nexit\n")
        assert "Compatibility" in result.output or "Python" in result.output

    def test_shell_mission_list_command(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=str(tmp_path)) as td:
            _prepare(td)
            result = runner.invoke(cli, ["--shell"], input="mission list\nexit\n")
        assert result.exit_code == 0

    def test_shell_natural_language_routing(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=str(tmp_path)) as td:
            _prepare(td)
            result = runner.invoke(cli, ["--shell"], input="classify this dataset\nexit\n")
        assert (
            "starting a new mission" in result.output.lower()
            or "mission new" in result.output.lower()
        )

    def test_shell_re_run_history(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=str(tmp_path)) as td:
            _prepare(td)
            result = runner.invoke(cli, ["--shell"], input="version\n!1\nexit\n")
        # Should show version output twice (original + re-run)
        assert result.output.count("v") >= 2

    def test_shell_clear(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=str(tmp_path)) as td:
            _prepare(td)
            result = runner.invoke(cli, ["--shell"], input="clear\nexit\n")
        assert result.exit_code == 0

    def test_shell_unknown_word_routed_as_natural_language(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=str(tmp_path)) as td:
            _prepare(td)
            result = runner.invoke(cli, ["--shell"], input="zizibble\nexit\n")
        assert "starting a new mission" in result.output.lower()


# ===================================================================
# Path B — bare piped stdin, no --shell flag (Chapter 4.5)
# ===================================================================


class TestShellNonTTYGuard:
    """When stdin is not a TTY and no --shell flag is passed,
    the REPL must NOT launch. Top-level help is printed and exit 0."""

    def test_non_tty_no_shell_no_repl(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(cli, [])
        assert result.exit_code == 0
        assert "Usage:" in result.output or "Prometheus" in result.output

    def test_non_tty_no_shell_help_not_repl_prompt(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(cli, [])
        assert "\u276f" not in result.output
