"""Tests for the CPM CLI argument parser."""

from __future__ import annotations

import pytest
from cpyte_cpm.cli.commands import (
    AddCommand,
    BuildCommand,
    DoctorCommand,
    ExecCommand,
    GlobalOptions,
    InitCommand,
    InstallCommand,
    ParsedCLI,
    RemoveCommand,
    RunCommand,
    SefCommand,
    UpdateCommand,
)
from cpyte_cpm.cli.errors import CLIError, UnknownCommandError
from cpyte_cpm.cli.parser import parse_args

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

    def test_build_opt(self) -> None:
        result = parse(["build", "--opt"])
        assert isinstance(result.command, BuildCommand)
        assert result.command.opt is True

    def test_build_osize(self) -> None:
        result = parse(["build", "--osize"])
        assert isinstance(result.command, BuildCommand)
        assert result.command.osize is True

    def test_build_debug(self) -> None:
        result = parse(["build", "--debug"])
        assert isinstance(result.command, BuildCommand)
        assert result.command.debug is True

    def test_build_lto(self) -> None:
        result = parse(["build", "--lto"])
        assert isinstance(result.command, BuildCommand)
        assert result.command.lto is True

    def test_build_scorpion(self) -> None:
        result = parse(["build", "--scorpion"])
        assert isinstance(result.command, BuildCommand)
        assert result.command.scorpion is True

    def test_build_flags_default(self) -> None:
        result = parse(["build"])
        assert result.command.opt is False
        assert result.command.osize is False
        assert result.command.debug is False
        assert result.command.lto is False
        assert result.command.scorpion is False


# ---------------------------------------------------------------------------
# sef
# ---------------------------------------------------------------------------

class TestSefCommand:
    def test_sef_no_subcommand(self) -> None:
        result = parse(["sef"])
        assert isinstance(result.command, SefCommand)
        assert result.command.subcommand == ""
        assert result.command.args == []

    def test_sef_pack(self) -> None:
        result = parse(["sef", "pack", "main.cpy", "-o", "main.sef"])
        assert isinstance(result.command, SefCommand)
        assert result.command.subcommand == "pack"
        assert result.command.args == ["main.cpy", "-o", "main.sef"]

    def test_sef_dump(self) -> None:
        result = parse(["sef", "dump", "main.sef"])
        assert isinstance(result.command, SefCommand)
        assert result.command.subcommand == "dump"
        assert result.command.args == ["main.sef"]

    def test_sef_check(self) -> None:
        result = parse(["sef", "check", "main.sef"])
        assert isinstance(result.command, SefCommand)
        assert result.command.subcommand == "check"

    def test_sef_size(self) -> None:
        result = parse(["sef", "size", "main.sef"])
        assert isinstance(result.command, SefCommand)
        assert result.command.subcommand == "size"

    def test_sef_unknown_subcommand_raises(self) -> None:
        with pytest.raises(UnknownCommandError) as exc_info:
            parse(["sef", "explode"])
        assert "sef explode" in str(exc_info.value)


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
# exec
# ---------------------------------------------------------------------------

class TestExecCommand:
    def test_exec(self) -> None:
        result = parse(["exec", "scripts/run.cpy"])
        assert isinstance(result.command, ExecCommand)
        assert result.command.file == "scripts/run.cpy"
        assert result.command.args == []

    def test_exec_with_passthrough_args(self) -> None:
        result = parse(["exec", "main.cpy", "--", "-x", "42"])
        assert isinstance(result.command, ExecCommand)
        assert result.command.file == "main.cpy"
        assert result.command.args == ["-x", "42"]

    def test_exec_missing_file_raises_error(self) -> None:
        with pytest.raises(CLIError, match="exec"):
            parse(["exec"])


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------

class TestDoctorCommand:
    def test_doctor(self) -> None:
        result = parse(["doctor"])
        assert isinstance(result.command, DoctorCommand)

    def test_doctor_with_global_flags(self) -> None:
        result = parse(["-v", "doctor"])
        assert isinstance(result.command, DoctorCommand)
        assert result.global_options.verbose is True


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
