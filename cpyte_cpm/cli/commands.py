"""Structured types for parsed CLI commands."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Union


@dataclass(frozen=True)
class GlobalOptions:
    verbose: bool = False
    quiet: bool = False
    json: bool = False
    yes: bool = False
    offline: bool = False
    no_cache: bool = False
    config: str | None = None
    server: list[str] = field(default_factory=list)
    target: str | None = None
    llvm_version: str | None = None


@dataclass(frozen=True)
class InitCommand:
    pass


@dataclass(frozen=True)
class AddCommand:
    packages: list[str] = field(default_factory=list)
    force: bool = False


@dataclass(frozen=True)
class RemoveCommand:
    packages: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class InstallCommand:
    packages: list[str] = field(default_factory=list)
    force: bool = False


@dataclass(frozen=True)
class LocalInstallCommand:
    path: str = ""
    force: bool = False


@dataclass(frozen=True)
class UpdateCommand:
    packages: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class BuildCommand:
    opt: bool = False  # -O2 optimization (default)
    osize: bool = False  # optimize for size (-Os)
    debug: bool = False  # include debug info (-g)
    lto: bool = False  # link-time optimization
    scorpion: bool = False  # also produce a .sef (Scorpion RISC-V) artifact


@dataclass(frozen=True)
class RunCommand:
    script: str = ""
    args: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ExecCommand:
    file: str = ""
    args: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DoctorCommand:
    pass


@dataclass(frozen=True)
class VersionCommand:
    pass


@dataclass(frozen=True)
class PublishCommand:
    directory: str = ""
    name: str = ""
    version: str = ""
    requires: list[str] = field(default_factory=list)
    prebuilt: bool = False
    llvm_version: str = ""
    cpyte_version: str = ""
    server: str = ""
    token: str = ""


@dataclass(frozen=True)
class UnpublishCommand:
    name: str = ""
    version: str = ""
    all: bool = False
    block: bool = False
    server: str = ""


@dataclass(frozen=True)
class SearchCommand:
    query: str = ""


@dataclass(frozen=True)
class InfoCommand:
    package: str = ""


@dataclass(frozen=True)
class ListCommand:
    pass


@dataclass(frozen=True)
class ValidateCommand:
    fix: bool = False
    strict: bool = False


@dataclass(frozen=True)
class SefCommand:
    subcommand: str = ""
    args: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class LoginCommand:
    server: str = ""


@dataclass(frozen=True)
class LogoutCommand:
    server: str = ""


@dataclass(frozen=True)
class ReportCommand:
    package: str
    reason: str = "malware"
    details: str = ""
    version: str = ""
    server: str = ""
    token: str = ""


Command = Union[
    InitCommand,
    AddCommand,
    RemoveCommand,
    InstallCommand,
    LocalInstallCommand,
    UpdateCommand,
    BuildCommand,
    RunCommand,
    ExecCommand,
    DoctorCommand,
    VersionCommand,
    PublishCommand,
    UnpublishCommand,
    SearchCommand,
    InfoCommand,
    ListCommand,
    ValidateCommand,
    SefCommand,
    LoginCommand,
    LogoutCommand,
]


@dataclass(frozen=True)
class ParsedCLI:
    global_options: GlobalOptions = field(default_factory=GlobalOptions)
    command: Command | None = None
