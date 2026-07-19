"""Tests for the CPM CLI argument parser."""

from __future__ import annotations

import pytest

from cpyte.cli.commands import (
    AddCommand,
    BuildCommand,
    Command,
    GlobalOptions,
    InitCommand,
    InstallCommand,
    ParsedCLI,
    RemoveCommand,
    RunCommand,
    UpdateCommand,
    VersionCommand,
)
from cpyte.cli.errors import CLIError, UnknownCommandError
from cpyte.cli.parser import parse_args


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def parse(argv: list[str]) -> ParsedCLI:
    """Shorthand to parse a list of string arguments."""
    return parse_args(argv)


# ---------------------------------------------------------------------------
# No arguments
# ---------------------------------------------------------------------------

class TestNoArgs:
    def test_empty_args_returns_no_command(self) -> None:
        result = parse([])
        assert result.command is None
        assert result.global_options == GlobalOptions()

    def test_no_args_has_default_options(self) -> None:
        result = parse([])
        assert result.global_options.verbose is False
        assert result.global_options.quiet is False
        assert result.global_options.yes is False
        assert result.global_options.offline is False
        assert result.global_options.no_cache is False
        assert result.global_options.config is None


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------

class TestInitCommand:
    def test_init(self) -> None:
        result = parse(["init"])
        assert isinstance(result.command, InitCommand)

    def test_init_has_no_fields(self) -> None:
        result = parse(["init"])
        assert result.command == InitCommand()


# ---------------------------------------------------------------------------
# add
# ---------------------------------------------------------------------------

class TestAddCommand:
    def test_add_single_package(self) -> None:
        result = parse(["add", "foo"])
        assert isinstance(result.command, AddCommand)
        assert result.command.packages == ["foo"]

    def test_add_multiple_packages(self) -> None:
        result = parse(["add", "foo", "bar", "baz"])
        assert isinstance(result.command, AddCommand)
        assert result.command.packages == ["foo", "bar", "baz"]

    def test_add_versioned_package(self) -> None:
        result = parse(["add", "foo@1.2.3"])
        assert isinstance(result.command, AddCommand)
        assert result.command.packages == ["foo@1.2.3"]

    def test_add_namespaced_package(self) -> None:
        result = parse(["add", "@std/json"])
        assert isinstance(result.command, AddCommand)
        assert result.command.packages == ["@std/json"]

    def test_add_namespaced_versioned(self) -> None:
        result = parse(["add", "@std/json@^1.0"])
        assert isinstance(result.command, AddCommand)
        assert result.command.packages == ["@std/json@^1.0"]

    def test_add_local_package(self) -> None:
        result = parse(["add", "./local-package"])
        assert isinstance(result.command, AddCommand)
        assert result.command.packages == ["./local-package"]

    def test_add_url_package(self) -> None:
        result = parse(["add", "https://example.com/package"])
        assert isinstance(result.command, AddCommand)
        assert result.command.packages == ["https://example.com/package"]

    def test_add_missing_packages_raises_error(self) -> None:
        with pytest.raises(CLIError, match="add"):
            parse(["add"])


# ---------------------------------------------------------------------------
# remove
# ---------------------------------------------------------------------------

class TestRemoveCommand:
    def test_remove_single_package(self) -> None:
        result = parse(["remove", "foo"])
        assert isinstance(result.command, RemoveCommand)
        assert result.command.packages == ["foo"]

    def test_remove_multiple_packages(self) -> None:
        result = parse(["remove", "foo", "bar"])
        assert isinstance(result.command, RemoveCommand)
        assert result.command.packages == ["foo", "bar"]

    def test_remove_missing_packages_raises_error(self) -> None:
        with pytest.raises(CLIError, match="remove"):
            parse(["remove"])


# ---------------------------------------------------------------------------
# install
# ---------------------------------------------------------------------------

class TestInstallCommand:
    def test_install(self) -> None:
        result = parse(["install"])
        assert isinstance(result.command, InstallCommand)


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------

class TestUpdateCommand:
    def test_update_no_packages(self) -> None:
        result = parse(["update"])
        assert isinstance(result.command, UpdateCommand)
        assert result.command.packages == []

    def test_update_single_package(self) -> None:
        result = parse(["update", "foo"])
        assert isinstance(result.command, UpdateCommand)
        assert result.command.packages == ["foo"]

    def test_update_multiple_packages(self) -> None:
        result = parse(["update", "foo", "bar"])
        assert isinstance(result.command, UpdateCommand)
        assert result.command.packages == ["foo", "bar"]


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------

class TestBuildCommand:
    def test_build(self) -> None:
        result = parse(["build"])
        assert isinstance(result.command, BuildCommand)


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------

class TestRunCommand:
    def test_run_script_only(self) -> None:
        result = parse(["run", "test"])
        assert isinstance(result.command, RunCommand)
        assert result.command.script == "test"
        assert result.command.args == []

    def test_run_with_passthrough_args(self) -> None:
        result = parse(["run", "test", "--", "--foo", "bar"])
        assert isinstance(result.command, RunCommand)
        assert result.command.script == "test"
        assert result.command.args == ["--foo", "bar"]

    def test_run_with_multiple_passthrough_args(self) -> None:
        result = parse(["run", "test", "--", "--verbose", "--count", "3"])
        assert isinstance(result.command, RunCommand)
        assert result.command.script == "test"
        assert result.command.args == ["--verbose", "--count", "3"]

    def test_run_missing_script_raises_error(self) -> None:
        with pytest.raises(CLIError, match="run"):
            parse(["run"])


# ---------------------------------------------------------------------------
# --version
# ---------------------------------------------------------------------------

class TestVersionFlag:
    def test_version_flag_exits(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            parse(["--version"])
        assert exc_info.value.code == 0


# ---------------------------------------------------------------------------
# --help
# ---------------------------------------------------------------------------

class TestHelpFlag:
    def test_help_flag_exits(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            parse(["--help"])
        assert exc_info.value.code == 0


# ---------------------------------------------------------------------------
# Global options
# ---------------------------------------------------------------------------

class TestGlobalOptions:
    def test_verbose_short(self) -> None:
        result = parse(["-v", "init"])
        assert result.global_options.verbose is True
        assert isinstance(result.command, InitCommand)

    def test_verbose_long(self) -> None:
        result = parse(["--verbose", "init"])
        assert result.global_options.verbose is True

    def test_quiet(self) -> None:
        result = parse(["-q", "init"])
        assert result.global_options.quiet is True

    def test_yes(self) -> None:
        result = parse(["-y", "init"])
        assert result.global_options.yes is True

    def test_offline(self) -> None:
        result = parse(["--offline", "init"])
        assert result.global_options.offline is True

    def test_no_cache(self) -> None:
        result = parse(["--no-cache", "init"])
        assert result.global_options.no_cache is True

    def test_config(self) -> None:
        result = parse(["--config", "/path/to/config.toml", "init"])
        assert result.global_options.config == "/path/to/config.toml"

    def test_combined_options(self) -> None:
        result = parse(["-v", "-q", "--offline", "--no-cache", "init"])
        assert result.global_options.verbose is True
        assert result.global_options.quiet is True
        assert result.global_options.offline is True
        assert result.global_options.no_cache is True

    def test_options_after_command(self) -> None:
        result = parse(["add", "-v", "foo"])
        assert result.global_options.verbose is True
        assert isinstance(result.command, AddCommand)
        assert result.command.packages == ["foo"]


# ---------------------------------------------------------------------------
# Unknown commands
# ---------------------------------------------------------------------------

class TestUnknownCommand:
    def test_unknown_command_raises_error(self) -> None:
        with pytest.raises(UnknownCommandError) as exc_info:
            parse(["unknown-command"])
        assert "unknown-command" in str(exc_info.value)

    def test_unknown_command_suggests_close_match(self) -> None:
        with pytest.raises(UnknownCommandError) as exc_info:
            parse(["ad"])
        assert exc_info.value.suggestions

    def test_unknown_command_has_no_suggestions_for_distant_match(self) -> None:
        with pytest.raises(UnknownCommandError) as exc_info:
            parse(["xyzzy"])
        assert exc_info.value.suggestions == []


# ---------------------------------------------------------------------------
# Structured result type
# ---------------------------------------------------------------------------

class TestParsedCLI:
    def test_parsed_cli_is_frozen(self) -> None:
        result = parse(["init"])
        with pytest.raises(AttributeError):
            result.command = AddCommand()  # type: ignore[misc]

    def test_global_options_is_frozen(self) -> None:
        result = parse(["init"])
        with pytest.raises(AttributeError):
            result.global_options.verbose = True  # type: ignore[misc]

    def test_command_is_frozen(self) -> None:
        result = parse(["add", "foo"])
        with pytest.raises(AttributeError):
            result.command.packages = []  # type: ignore[union-attr]
