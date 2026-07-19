"""CLI error types for clear, user-facing error messages."""

from __future__ import annotations


class CLIError(Exception):
    """Base error for CLI parsing issues."""


class UnknownCommandError(CLIError):
    """Raised when an unrecognized subcommand is given."""

    def __init__(self, command: str, suggestions: list[str] | None = None) -> None:
        self.command = command
        self.suggestions = suggestions or []
        msg = f"unknown command '{command}'"
        if self.suggestions:
            msg += f". Did you mean: {', '.join(self.suggestions)}?"
        super().__init__(msg)


class MissingArgumentError(CLIError):
    """Raised when a required argument is missing."""

    def __init__(self, argument: str, command: str) -> None:
        self.argument = argument
        self.command = command
        super().__init__(
            f"command '{command}' requires {argument}"
        )


class InvalidPackageSpecError(CLIError):
    """Raised when a package specification is invalid."""

    def __init__(self, spec: str) -> None:
        self.spec = spec
        super().__init__(f"invalid package specification: '{spec}'")


class InvalidOptionError(CLIError):
    """Raised when an invalid option is provided."""

    def __init__(self, option: str, message: str = "") -> None:
        self.option = option
        msg = f"invalid option '{option}'"
        if message:
            msg += f": {message}"
        super().__init__(msg)
