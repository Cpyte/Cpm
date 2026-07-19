from __future__ import annotations

import sys
from typing import Callable, Dict, List, Optional

from cpyte.cli.commands import (
    Command,
    GlobalOptions,
    ParsedCLI,
)
from cpyte.cli.errors import CLIError
from cpyte.cli.parser import parse_args

Handler = Callable[[GlobalOptions, Command], None]

_HANDLERS: Dict[type, Handler] = {}


def register_handler(command_type: type, handler: Handler) -> None:
    _HANDLERS[command_type] = handler


def dispatch(parsed: ParsedCLI) -> None:
    if parsed.command is None:
        return

    # Lazy register handlers on first dispatch
    if not _HANDLERS:
        from .things import (
            init_project,
            add_deps,
            remove_deps,
            install_deps,
            update_deps,
            build_project,
            run_script,
        )
        from cpyte.cli.commands import (
            InitCommand,
            AddCommand,
            RemoveCommand,
            InstallCommand,
            UpdateCommand,
            BuildCommand,
            RunCommand,
        )
        register_handler(InitCommand, init_project)
        register_handler(AddCommand, add_deps)
        register_handler(RemoveCommand, remove_deps)
        register_handler(InstallCommand, install_deps)
        register_handler(UpdateCommand, update_deps)
        register_handler(BuildCommand, build_project)
        register_handler(RunCommand, run_script)

    handler = _HANDLERS.get(type(parsed.command))
    if handler is None:
        raise CLIError(f"no handler registered for {type(parsed.command).__name__}")
    handler(parsed.global_options, parsed.command)


def main(argv: Optional[List[str]] = None) -> None:
    try:
        parsed = parse_args(argv)
    except CLIError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        dispatch(parsed)
    except CLIError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"unexpected error: {exc}", file=sys.stderr)
        sys.exit(1)
