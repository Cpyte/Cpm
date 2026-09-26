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
from collections.abc import Sequence

try:
    from importlib.metadata import version

    CPM_VERSION = version("cpyte-cpm")
except Exception:
    CPM_VERSION = "1.6.0"

from cpyte_cpm.cli.commands import (
    AddCommand,
    BuildCommand,
    Command,
    DoctorCommand,
    ExecCommand,
    GlobalOptions,
    InfoCommand,
    InitCommand,
    InstallCommand,
    ListCommand,
    LocalInstallCommand,
    LoginCommand,
    LogoutCommand,
    ParsedCLI,
    PublishCommand,
    RemoveCommand,
    ReportCommand,
    RunCommand,
    SearchCommand,
    SefCommand,
    UnpublishCommand,
    UpdateCommand,
    ValidateCommand,
)
from cpyte_cpm.cli.errors import CLIError, UnknownCommandError

COMMANDS = [
    "init",
    "add",
    "remove",
    "install",
    "install-local",
    "update",
    "build",
    "run",
    "exec",
    "doctor",
    "login",
    "logout",
    "report",
    "publish",
    "unpublish",
    "search",
    "info",
    "list",
    "validate",
    "sef",
]

SEF_SUBCOMMANDS = ("pack", "dump", "check", "size")


def _suggest_command(name: str) -> list[str]:
    """Return close matches for an unknown command name."""
    return [m for m in difflib.get_close_matches(name, COMMANDS, n=3, cutoff=0.4)]


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
    parser.add_argument(
        "--json", action="store_true", default=False, dest="json_output"
    )
    parser.add_argument("-y", "--yes", action="store_true", default=False)
    parser.add_argument("--offline", action="store_true", default=False)
    parser.add_argument("--no-cache", action="store_true", default=False)
    parser.add_argument("--config", default=None, metavar="PATH")
    parser.add_argument(
        "--target",
        default=None,
        metavar="TARGET",
        help="target platform (e.g., linux/x86_64, darwin/aarch64)",
    )
    parser.add_argument(
        "--llvm-version",
        default=None,
        metavar="VERSION",
        help="LLVM version for prebuilt packages (e.g., 18.1.0)",
    )
    parser.add_argument(
        "--server",
        action="append",
        default=[],
        metavar="URL",
        help="registry server URL (repeatable, highest priority first)",
    )
    parser.add_argument("--version", action="store_true", default=False)
    parser.add_argument("-h", "--help", action="store_true", default=False)
    return parser


def _global_options_from_namespace(ns: argparse.Namespace) -> GlobalOptions:
    return GlobalOptions(
        verbose=ns.verbose,
        quiet=ns.quiet,
        json=ns.json_output,
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
    parsers["add"].add_argument(
        "--force", action="store_true", help="force reinstall even if installed"
    )

    parsers["remove"] = _cmd_parser("remove", "remove packages")
    parsers["remove"].add_argument("packages", nargs="+", metavar="PACKAGE")

    parsers["install"] = _cmd_parser("install", "install dependencies")
    parsers["install"].add_argument("packages", nargs="*", metavar="PACKAGE")
    parsers["install"].add_argument(
        "--force", action="store_true", help="force reinstall even if installed"
    )

    parsers["install-local"] = _cmd_parser(
        "install-local", "install package from local directory"
    )
    parsers["install-local"].add_argument(
        "path", help="path to local package directory"
    )
    parsers["install-local"].add_argument(
        "--force", action="store_true", help="force reinstall even if installed"
    )

    parsers["update"] = _cmd_parser("update", "update packages")
    parsers["update"].add_argument("packages", nargs="*", metavar="PACKAGE")

    parsers["build"] = _cmd_parser("build", "build the project")
    parsers["build"].add_argument(
        "--opt", action="store_true", help="optimize for speed (-O2)"
    )
    parsers["build"].add_argument(
        "--osize", action="store_true", help="optimize for size (-Os)"
    )
    parsers["build"].add_argument(
        "--debug", action="store_true", help="include debug info (-g)"
    )
    parsers["build"].add_argument(
        "--lto", action="store_true", help="link-time optimization"
    )
    parsers["build"].add_argument(
        "--scorpion",
        action="store_true",
        help="also produce a .sef (Scorpion RISC-V) artifact",
    )

    parsers["run"] = _cmd_parser("run", "run a script")
    parsers["run"].add_argument("script", help="script name to run")
    parsers["run"].add_argument(
        "passthrough",
        nargs="*",
        metavar="ARG",
    )

    parsers["exec"] = _cmd_parser("exec", "execute a .cpy file with the Cpyte compiler")
    parsers["exec"].add_argument("file", help="path to a .cpy file")
    parsers["exec"].add_argument(
        "passthrough",
        nargs="*",
        metavar="ARG",
    )

    parsers["doctor"] = _cmd_parser(
        "doctor", "diagnose the Cpyte toolchain and project"
    )

    parsers["login"] = _cmd_parser("login", "log in to a registry (device code flow)")
    parsers["login"].add_argument("--server", default="", help="registry server URL")

    parsers["logout"] = _cmd_parser("logout", "remove stored registry credentials")
    parsers["logout"].add_argument("--server", default="", help="registry server URL")

    parsers["report"] = _cmd_parser("report", "report a package for malware or abuse")
    parsers["report"].add_argument("package", help="package name (e.g. @std/json)")
    parsers["report"].add_argument(
        "--reason",
        default="malware",
        choices=["malware", "typosquatting", "spam", "license", "other"],
        help="report reason (default: malware)",
    )
    parsers["report"].add_argument(
        "--details", default="", help="extra context for reviewers"
    )
    parsers["report"].add_argument(
        "--pkg-version", default="", dest="pkg_version", help="affected version"
    )
    parsers["report"].add_argument("--server", default="", help="registry server URL")
    parsers["report"].add_argument(
        "--token", default="", help="auth token (else stored credentials)"
    )

    parsers["publish"] = _cmd_parser("publish", "publish a package to the registry")
    parsers["publish"].add_argument("directory", help="package directory to publish")
    parsers["publish"].add_argument(
        "--name", required=True, help="package name (e.g. @std/json)"
    )
    parsers["publish"].add_argument(
        "--pkg-version", required=True, dest="pkg_version", help="package version"
    )
    parsers["publish"].add_argument(
        "--requires", nargs="*", default=[], metavar="DEP", help="dependencies"
    )
    parsers["publish"].add_argument(
        "--prebuilt", action="store_true", help="mark as prebuilt"
    )
    parsers["publish"].add_argument(
        "--llvm-version", default="", help="LLVM version for prebuilt"
    )
    parsers["publish"].add_argument(
        "--cpyte-version", default="", help="Cpyte version for prebuilt"
    )
    parsers["publish"].add_argument("--server", default="", help="registry server URL")
    parsers["publish"].add_argument(
        "--token", default="", help="auth token (email hash from web UI)"
    )

    parsers["unpublish"] = _cmd_parser(
        "unpublish", "remove a package from the registry"
    )
    parsers["unpublish"].add_argument("name", help="package name (e.g. @std/json)")
    parsers["unpublish"].add_argument(
        "--pkg-version",
        default="",
        dest="pkg_version",
        help="package version to remove",
    )
    parsers["unpublish"].add_argument(
        "--all", action="store_true", dest="all_versions", help="remove all versions"
    )
    parsers["unpublish"].add_argument(
        "--block", action="store_true", help="block package from re-publish"
    )
    parsers["unpublish"].add_argument(
        "--server", default="", help="registry server URL"
    )

    parsers["search"] = _cmd_parser("search", "search for packages")
    parsers["search"].add_argument("query", help="search query")

    parsers["info"] = _cmd_parser("info", "show package information")
    parsers["info"].add_argument("package", help="package name (e.g. @std/json)")

    parsers["list"] = _cmd_parser("list", "list installed packages")

    parsers["validate"] = _cmd_parser(
        "validate",
        "deep-validate manifest, lockfile and security config",
    )
    parsers["validate"].add_argument(
        "--fix",
        action="store_true",
        help="auto-fix what is safely fixable (missing name/version, bad target, file perms)",
    )
    parsers["validate"].add_argument(
        "--strict",
        action="store_true",
        help="treat warnings as errors (exit 1)",
    )

    parsers["sef"] = _cmd_parser(
        "sef", "Scorpion SEF binary tools (pack/dump/check/size)"
    )
    parsers["sef"].add_argument(
        "args",
        nargs=argparse.REMAINDER,
        metavar="ARG",
        help="subcommand + args, e.g. 'check file.sef'",
    )

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
        return AddCommand(packages=list(ns.packages), force=getattr(ns, "force", False))
    if name == "remove":
        return RemoveCommand(packages=list(ns.packages))
    if name == "install":
        return InstallCommand(
            packages=list(ns.packages), force=getattr(ns, "force", False)
        )
    if name == "install-local":
        return LocalInstallCommand(path=ns.path, force=getattr(ns, "force", False))
    if name == "update":
        return UpdateCommand(packages=list(ns.packages))
    if name == "build":
        return BuildCommand(
            opt=ns.opt,
            osize=ns.osize,
            debug=ns.debug,
            lto=ns.lto,
            scorpion=ns.scorpion,
        )
    if name == "run":
        return RunCommand(script=ns.script, args=list(ns.passthrough))
    if name == "exec":
        return ExecCommand(file=ns.file, args=list(ns.passthrough))
    if name == "doctor":
        return DoctorCommand()
    if name == "login":
        return LoginCommand(server=ns.server)
    if name == "logout":
        return LogoutCommand(server=ns.server)
    if name == "report":
        return ReportCommand(
            package=ns.package,
            reason=ns.reason,
            details=ns.details,
            version=ns.pkg_version,
            server=ns.server,
            token=ns.token,
        )
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
    if name == "info":
        return InfoCommand(package=ns.package)
    if name == "list":
        return ListCommand()
    if name == "validate":
        return ValidateCommand(fix=ns.fix, strict=ns.strict)
    if name == "sef":
        args = list(ns.args)
        subcommand = args[0] if args else ""
        if subcommand and subcommand not in SEF_SUBCOMMANDS:
            raise UnknownCommandError(
                f"sef {subcommand}",
                [
                    m
                    for m in difflib.get_close_matches(
                        subcommand, SEF_SUBCOMMANDS, n=3, cutoff=0.4
                    )
                ],
            )
        return SefCommand(subcommand=subcommand, args=args[1:])
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
        "  init           initialize a new project",
        "  add            add packages to the project",
        "  remove         remove packages from the project",
        "  install        install dependencies from manifest",
        "  install-local  install package from local directory",
        "  update         update packages to latest versions",
        "  build          build the project",
        "  run            run a script",
        "  exec           execute a .cpy file with the Cpyte compiler",
        "  doctor         diagnose the Cpyte toolchain and project",
        "  publish        publish a package to the registry",
        "  unpublish      remove a package from the registry",
        "  search         search for packages",
        "  info           show package information",
        "  list           list installed packages",
        "  validate       deep-validate manifest, lockfile and security (--fix, --strict)",
        "  sef            Scorpion SEF binary tools (pack/dump/check/size)",
        "  login          log in to a registry (device code flow)",
        "  logout         remove stored registry credentials",
        "  report         report a package for malware or abuse",
        "",
        "Global options:",
        "  -v, --verbose    enable verbose output",
        "  -q, --quiet      suppress output (errors still shown)",
        "  --json           output in JSON format (for scripts)",
        "  -y, --yes        automatically confirm prompts",
        "  --offline        run in offline mode",
        "  --no-cache       disable cache (re-download all)",
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


def parse_args(argv: Sequence[str] | None = None) -> ParsedCLI:
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
        from cpyte_cpm.compiler import get_cpyte_version

        cpyte_ver = get_cpyte_version()
        print(f"cpm {CPM_VERSION}  (cpyte {cpyte_ver})")
        raise SystemExit(0)

    # Handle top-level --help (only if no command follows)
    if known.help and not remaining:
        _print_top_level_help()
        raise SystemExit(0)

    # No command provided (only global flags were given)
    if not remaining:
        return ParsedCLI(global_options=global_options, command=None)

    # Pass 2: first remaining token is the command
    command_name = remaining[0]
    command_args = remaining[1:]

    # Validate command name
    if command_name not in COMMAND_PARSERS:
        raise UnknownCommandError(command_name, _suggest_command(command_name))

    # Handle --help consumed by global parser (e.g. `cpm install --help`)
    if known.help:
        _print_command_help(command_name)
        raise SystemExit(0)

    # Handle --help after the command (e.g. `cpm install --help` with nargs="*")
    if "-h" in command_args or "--help" in command_args:
        _print_command_help(command_name)
        raise SystemExit(0)

    # Parse command-specific arguments
    parser = COMMAND_PARSERS[command_name]
    try:
        ns = parser.parse_args(command_args)
    except SystemExit as exc:
        raise CLIError(f"invalid arguments for command '{command_name}'") from exc

    command = _build_command(command_name, ns)
    return ParsedCLI(global_options=global_options, command=command)
