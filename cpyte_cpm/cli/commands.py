"""Structured types for parsed CLI commands."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Union


@dataclass(frozen=True)
class GlobalOptions:
    verbose: bool = False
    quiet: bool = False
    json: bool = False
    yes: bool = False
    offline: bool = False
    no_cache: bool = False
    config: Optional[str] = None
    server: List[str] = field(default_factory=list)
    target: Optional[str] = None
    llvm_version: Optional[str] = None


@dataclass(frozen=True)
class InitCommand:
    pass


@dataclass(frozen=True)
class AddCommand:
    packages: List[str] = field(default_factory=list)
    force: bool = False


@dataclass(frozen=True)
class RemoveCommand:
    packages: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class InstallCommand:
    packages: List[str] = field(default_factory=list)
    force: bool = False


@dataclass(frozen=True)
class LocalInstallCommand:
    path: str = ""
    force: bool = False


@dataclass(frozen=True)
class UpdateCommand:
    packages: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class BuildCommand:
    pass


@dataclass(frozen=True)
class RunCommand:
    script: str = ""
    args: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class ExecCommand:
    file: str = ""
    args: List[str] = field(default_factory=list)


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
    requires: List[str] = field(default_factory=list)
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
    pass


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
]


@dataclass(frozen=True)
class ParsedCLI:
    global_options: GlobalOptions = field(default_factory=GlobalOptions)
    command: Optional[Command] = None
