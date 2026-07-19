"""Structured types for parsed CLI commands."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Union


@dataclass(frozen=True)
class GlobalOptions:
    verbose: bool = False
    quiet: bool = False
    yes: bool = False
    offline: bool = False
    no_cache: bool = False
    config: Optional[str] = None
    target: Optional[str] = None
    llvm_version: Optional[str] = None


@dataclass(frozen=True)
class InitCommand:
    pass


@dataclass(frozen=True)
class AddCommand:
    packages: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class RemoveCommand:
    packages: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class InstallCommand:
    packages: List[str] = field(default_factory=list)


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
class VersionCommand:
    pass


Command = Union[
    InitCommand,
    AddCommand,
    RemoveCommand,
    InstallCommand,
    UpdateCommand,
    BuildCommand,
    RunCommand,
    VersionCommand,
]


@dataclass(frozen=True)
class ParsedCLI:
    global_options: GlobalOptions = field(default_factory=GlobalOptions)
    command: Optional[Command] = None
