from __future__ import annotations

import sys
from collections.abc import Callable

from cpyte_cpm.cli import style
from cpyte_cpm.cli.commands import (
    Command,
    GlobalOptions,
    ParsedCLI,
)
from cpyte_cpm.cli.errors import CLIError
from cpyte_cpm.cli.parser import parse_args

Handler = Callable[[GlobalOptions, Command], None]

_HANDLERS: dict[type, Handler] = {}


def register_handler(command_type: type, handler: Handler) -> None:
    _HANDLERS[command_type] = handler


def dispatch(parsed: ParsedCLI) -> None:
    if parsed.command is None:
        return

    # Lazy register handlers on first dispatch
    if not _HANDLERS:
        from cpyte_cpm.cli.commands import (
            AddCommand,
            BuildCommand,
            DoctorCommand,
            ExecCommand,
            InfoCommand,
            InitCommand,
            InstallCommand,
            ListCommand,
            LocalInstallCommand,
            LoginCommand,
            LogoutCommand,
            ReportCommand,
            PublishCommand,
            RemoveCommand,
            RunCommand,
            SearchCommand,
            SefCommand,
            UnpublishCommand,
            UpdateCommand,
            ValidateCommand,
        )

        from .things import (
            add_deps,
            build_project,
            doctor_project,
            exec_cpy,
            init_project,
            install_deps,
            install_local_deps,
            list_installed_packages,
            login_device,
            logout_device,
            publish_package,
            remove_deps,
            report_package,
            run_script,
            search_packages,
            sef_tool,
            show_package_info,
            unpublish_package,
            update_deps,
            validate_manifest,
        )
        register_handler(InitCommand, init_project)
        register_handler(AddCommand, add_deps)
        register_handler(RemoveCommand, remove_deps)
        register_handler(InstallCommand, install_deps)
        register_handler(LocalInstallCommand, install_local_deps)
        register_handler(UpdateCommand, update_deps)
        register_handler(BuildCommand, build_project)
        register_handler(RunCommand, run_script)
        register_handler(ExecCommand, exec_cpy)
        register_handler(DoctorCommand, doctor_project)
        register_handler(LoginCommand, login_device)
        register_handler(LogoutCommand, logout_device)
        register_handler(ReportCommand, report_package)
        register_handler(PublishCommand, publish_package)
        register_handler(UnpublishCommand, unpublish_package)
        register_handler(SearchCommand, search_packages)
        register_handler(InfoCommand, show_package_info)
        register_handler(ListCommand, list_installed_packages)
        register_handler(ValidateCommand, validate_manifest)
        register_handler(SefCommand, sef_tool)

    handler = _HANDLERS.get(type(parsed.command))
    if handler is None:
        raise CLIError(f"no handler registered for {type(parsed.command).__name__}")
    handler(parsed.global_options, parsed.command)


def main(argv: list[str] | None = None) -> None:
    from .http_session import close_session
    try:
        parsed = parse_args(argv)
    except CLIError as exc:
        style.print_error(str(exc))
        sys.exit(1)
    except SystemExit:
        raise
    except Exception as exc:
        style.print_error(f"unexpected error: {exc}")
        sys.exit(1)

    # Initialize style module based on global options
    style.set_quiet(parsed.global_options.quiet)
    style.set_json_mode(parsed.global_options.json)

    if parsed.command is None and not parsed.global_options.quiet:
        style.banner(title="Cpyte Package Manager")
        style.pipeline()
        print()

    try:
        dispatch(parsed)
    except CLIError as exc:
        style.print_error(str(exc))
        sys.exit(1)
    except SystemExit:
        raise
    except Exception as exc:
        if parsed.global_options.verbose:
            import traceback
            traceback.print_exc()
        else:
            style.print_error(f"unexpected error: {exc}")
        sys.exit(1)
    finally:
        close_session()
