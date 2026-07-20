"""CLI argument parser for CPM.

Parses CLI arguments into a structured ParsedCLI object.
Does not perform any side effects — only parses and validates syntax.

Architecture:
  Pass 1: Extract global options via parse_known_args
  Pass 2: Identify the command, parse its arguments with a dedicated parser
"""

from __future__ import annotations

import argparse
import difflib
import sys
from typing import List, Optional, Sequence

try:
    from importlib.metadata import version
    CPM_VERSION = version("cpyte-cpm")
except Exception:
    CPM_VERSION = "1.1.8"

from cpyte.cli.commands import (
    AddCommand,
    BuildCommand,
    Command,
    GlobalOptions,
    InitCommand,
    InstallCommand,
    ParsedCLI,
    PublishCommand,
    RemoveCommand,
    RunCommand,
    SearchCommand,
    UnpublishCommand,
    UpdateCommand,
    VersionCommand,
)
from cpyte.cli.errors import CLIError, UnknownCommandError

COMMANDS = [
    "init",
    "add",
    "remove",
    "install",
    "update",
    "build",
    "run",
    "publish",
    "unpublish",
    "search",
]


def _suggest_command(name: str) -> list[str]:
    """Return close matches for an unknown command name."""
    return [
        m for m in difflib.get_close_matches(name, COMMANDS, n=3, cutoff=0.4)
    ]


# ---------------------------------------------------------------------------
# Global option parser (Pass 1)
# ---------------------------------------------------------------------------

def _build_global_parser() -> argparse.ArgumentParser:
    """Build a parser that only handles global options.

    Uses parse_known_args so that command tokens pass through as
    'remaining' args without causing errors.
    """
    parser = argparse.ArgumentParser(
        prog="cpm",
        description="CPM - A package manager for Cpyte",
        add_help=False,
    )
    parser.add_argument("-v", "--verbose", action="store_true", default=False)
    parser.add_argument("-q", "--quiet", action="store_true", default=False)
    parser.add_argument("-y", "--yes", action="store_true", default=False)
    parser.add_argument("--offline", action="store_true", default=False)
    parser.add_argument("--no-cache", action="store_true", default=False)
    parser.add_argument("--config", default=None, metavar="PATH")
    parser.add_argument("--target", default=None, metavar="TARGET",
                        help="target platform (e.g., linux/x86_64, darwin/aarch64)")
    parser.add_argument("--llvm-version", default=None, metavar="VERSION",
                        help="LLVM version for prebuilt packages (e.g., 18.1.0)")
    parser.add_argument("--server", action="append", default=[], metavar="URL",
                        help="registry server URL (repeatable, highest priority first)")
    parser.add_argument("--version", action="store_true", default=False)
    parser.add_argument("-h", "--help", action="store_true", default=False)
    return parser


def _global_options_from_namespace(ns: argparse.Namespace) -> GlobalOptions:
    return GlobalOptions(
        verbose=ns.verbose,
        quiet=ns.quiet,
        yes=ns.yes,
        offline=ns.offline,
        no_cache=ns.no_cache,
        config=ns.config,
        server=ns.server,
        target=ns.target,
        llvm_version=ns.llvm_version,
    )


# ---------------------------------------------------------------------------
# Per-command parsers (Pass 2)
# ---------------------------------------------------------------------------

def _build_command_parsers() -> dict[str, argparse.ArgumentParser]:
    """Build a map of command name -> dedicated argparse parser."""
    parsers: dict[str, argparse.ArgumentParser] = {}

    parsers["init"] = _cmd_parser("init", "initialize a new project")
    parsers["add"] = _cmd_parser("add", "add packages")
    parsers["add"].add_argument("packages", nargs="+", metavar="PACKAGE")

    parsers["remove"] = _cmd_parser("remove", "remove packages")
    parsers["remove"].add_argument("packages", nargs="+", metavar="PACKAGE")

    parsers["install"] = _cmd_parser("install", "install dependencies")
    parsers["install"].add_argument("packages", nargs="*", metavar="PACKAGE")

    parsers["update"] = _cmd_parser("update", "update packages")
    parsers["update"].add_argument("packages", nargs="*", metavar="PACKAGE")

    parsers["build"] = _cmd_parser("build", "build the project")

    parsers["run"] = _cmd_parser("run", "run a script")
    parsers["run"].add_argument("script", help="script name to run")
    parsers["run"].add_argument(
        "passthrough", nargs="*", metavar="ARG",
    )

    parsers["publish"] = _cmd_parser("publish", "publish a package to the registry")
    parsers["publish"].add_argument("directory", help="package directory to publish")
    parsers["publish"].add_argument("--name", required=True, help="package name (e.g. @std/json)")
    parsers["publish"].add_argument("--pkg-version", required=True, dest="pkg_version", help="package version")
    parsers["publish"].add_argument("--requires", nargs="*", default=[], metavar="DEP", help="dependencies")
    parsers["publish"].add_argument("--prebuilt", action="store_true", help="mark as prebuilt")
    parsers["publish"].add_argument("--llvm-version", default="", help="LLVM version for prebuilt")
    parsers["publish"].add_argument("--cpyte-version", default="", help="Cpyte version for prebuilt")
    parsers["publish"].add_argument("--server", default="", help="registry server URL")
    parsers["publish"].add_argument("--token", default="", help="auth token (email hash from web UI)")

    parsers["unpublish"] = _cmd_parser("unpublish", "remove a package from the registry")
    parsers["unpublish"].add_argument("name", help="package name (e.g. @std/json)")
    parsers["unpublish"].add_argument("--pkg-version", default="", dest="pkg_version", help="package version to remove")
    parsers["unpublish"].add_argument("--all", action="store_true", dest="all_versions", help="remove all versions")
    parsers["unpublish"].add_argument("--block", action="store_true", help="block package from re-publish")
    parsers["unpublish"].add_argument("--server", default="", help="registry server URL")

    parsers["search"] = _cmd_parser("search", "search for packages")
    parsers["search"].add_argument("query", help="search query")

    return parsers


def _cmd_parser(name: str, help_text: str) -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        prog=f"cpm {name}",
        description=help_text,
        add_help=False,
    )


COMMAND_PARSERS = _build_command_parsers()


# ---------------------------------------------------------------------------
# Command builders
# ---------------------------------------------------------------------------

def _build_command(name: str, ns: argparse.Namespace) -> Command:
    """Construct a Command dataclass from the parsed namespace."""
    if name == "init":
        return InitCommand()
    if name == "add":
        return AddCommand(packages=list(ns.packages))
    if name == "remove":
        return RemoveCommand(packages=list(ns.packages))
    if name == "install":
        return InstallCommand(packages=list(ns.packages))
    if name == "update":
        return UpdateCommand(packages=list(ns.packages))
    if name == "build":
        return BuildCommand()
    if name == "run":
        return RunCommand(script=ns.script, args=list(ns.passthrough))
    if name == "publish":
        return PublishCommand(
            directory=ns.directory,
            name=ns.name,
            version=ns.pkg_version,
            requires=list(ns.requires),
            prebuilt=ns.prebuilt,
            llvm_version=ns.llvm_version,
            cpyte_version=ns.cpyte_version,
            server=ns.server,
            token=ns.token,
        )
    if name == "unpublish":
        return UnpublishCommand(
            name=ns.name,
            version=ns.pkg_version,
            all=ns.all_versions,
            block=ns.block,
            server=ns.server,
        )
    if name == "search":
        return SearchCommand(query=ns.query)
    raise UnknownCommandError(name, _suggest_command(name))


# ---------------------------------------------------------------------------
# Help text for --help on a specific command
# ---------------------------------------------------------------------------

def _print_command_help(name: str) -> None:
    parser = COMMAND_PARSERS.get(name)
    if parser is not None:
        parser.print_help()
    else:
        print(f"unknown command: {name}")


def _print_top_level_help() -> None:
    lines = [
        "CPM - A package manager for Cpyte",
        "",
        "Usage: cpm [global options] <command> [command options]",
        "",
        "Commands:",
        "  init       initialize a new project",
        "  add        add packages",
        "  remove     remove packages",
        "  install    install dependencies",
        "  update     update packages",
        "  build      build the project",
        "  run        run a script",
        "  publish    publish a package to the registry",
        "  unpublish  remove a package from the registry",
        "  search     search for packages",
        "",
        "Global options:",
        "  -v, --verbose    enable verbose output",
        "  -q, --quiet      suppress output",
        "  -y, --yes        automatically confirm prompts",
        "  --offline        run in offline mode",
        "  --no-cache       disable cache",
        "  --config PATH    path to configuration file",
        "  --target TARGET  target platform (e.g., linux/x86_64)",
        "  --llvm-version V LLVM version for prebuilt (e.g., 18.1.0)",
        "  --server URL     registry server (repeatable, highest priority first)",
        "  --version        show version information",
        "  -h, --help       show this help message",
        "",
        "Use 'cpm <command> --help' for help on a specific command.",
    ]
    print("\n".join(lines))


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def parse_args(argv: Optional[Sequence[str]] = None) -> ParsedCLI:
    """Parse CLI arguments into a structured ParsedCLI.

    Parameters
    ----------
    argv:
        Command-line arguments (excluding program name).
        Defaults to sys.argv[1:] when None.

    Returns
    -------
    ParsedCLI with global_options and command populated.

    Raises
    ------
    CLIError
        On unknown commands or invalid arguments.
    SystemExit
        On --help or --version.
    """
    if argv is None:
        argv = sys.argv[1:]
    argv = list(argv)

    if len(argv) == 0:
        return ParsedCLI(global_options=GlobalOptions(), command=None)

    # Pass 1: extract global options, leaving everything else as 'remaining'
    global_parser = _build_global_parser()
    known, remaining = global_parser.parse_known_args(argv)
    global_options = _global_options_from_namespace(known)

    # Handle top-level --version
    if known.version:
        print(f"cpm {CPM_VERSION}")
        raise SystemExit(0)

    # Handle top-level --help (only if no command follows)
    if known.help and not remaining:
        _print_top_level_help()
        raise SystemExit(0)

    # No command provided (only global flags were given)
    if not remaining:
        if known.help:
            _print_top_level_help()
            raise SystemExit(0)
        return ParsedCLI(global_options=global_options, command=None)

    # Pass 2: first remaining token is the command
    command_name = remaining[0]
    command_args = remaining[1:]

    # Validate command name
    if command_name not in COMMAND_PARSERS:
        raise UnknownCommandError(command_name, _suggest_command(command_name))

    # Handle --help for a specific command
    if "-h" in command_args or "--help" in command_args:
        _print_command_help(command_name)
        raise SystemExit(0)

    # Parse command-specific arguments
    parser = COMMAND_PARSERS[command_name]
    try:
        ns = parser.parse_args(command_args)
    except SystemExit as exc:
        raise CLIError(
            f"invalid arguments for command '{command_name}'"
        ) from exc

    command = _build_command(command_name, ns)
    return ParsedCLI(global_options=global_options, command=command)
