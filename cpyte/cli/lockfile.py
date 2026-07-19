"""Lockfile management for CPM.

Handles reading and writing cpm.lock, which stores exact resolved
versions for reproducible builds.

Lockfile format:
    [[package]]
    name = "@std/json"
    version = "2.0.3"
    resolved = "https://repo.example.com/group/std/json/2.0.3.tar.gz"
    checksum = "sha256:abc123..."
    dependencies = ["@std/encoding@1.2.0"]
    llvm_version = "18.1.0"
    cpyte_version = "0.5.0"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


LOCKFILE_NAME = "cpm.lock"


@dataclass
class LockEntry:
    """A single locked package."""
    name: str
    version: str
    resolved: str = ""
    checksum: str = ""
    dependencies: list[str] = field(default_factory=list)
    llvm_version: str = ""
    cpyte_version: str = ""


@dataclass
class Lockfile:
    """Represents a cpm.lock file."""
    entries: list[LockEntry] = field(default_factory=list)
    path: Optional[Path] = None

    def get(self, name: str) -> Optional[LockEntry]:
        """Get a locked entry by package name."""
        for entry in self.entries:
            if entry.name == name:
                return entry
        return None

    def add(self, entry: LockEntry) -> None:
        """Add or update a locked entry."""
        for i, existing in enumerate(self.entries):
            if existing.name == entry.name:
                self.entries[i] = entry
                return
        self.entries.append(entry)

    def remove(self, name: str) -> bool:
        """Remove a locked entry by name. Returns True if removed."""
        for i, entry in enumerate(self.entries):
            if entry.name == name:
                self.entries.pop(i)
                return True
        return False

    def toml_str(self) -> str:
        """Serialize lockfile to TOML string."""
        if not self.entries:
            return "# cpm.lock — auto-generated, do not edit manually\n"

        lines = ["# cpm.lock — auto-generated, do not edit manually", ""]
        for entry in self.entries:
            lines.append("[[package]]")
            lines.append(f'name = "{entry.name}"')
            lines.append(f'version = "{entry.version}"')
            if entry.resolved:
                lines.append(f'resolved = "{entry.resolved}"')
            if entry.checksum:
                lines.append(f'checksum = "{entry.checksum}"')
            if entry.dependencies:
                deps_str = ", ".join(f'"{d}"' for d in entry.dependencies)
                lines.append(f"dependencies = [{deps_str}]")
            if entry.llvm_version:
                lines.append(f'llvm_version = "{entry.llvm_version}"')
            if entry.cpyte_version:
                lines.append(f'cpyte_version = "{entry.cpyte_version}"')
            lines.append("")
        return "\n".join(lines)


def find_lockfile(start: Optional[Path] = None) -> Optional[Path]:
    """Walk up from start directory to find cpm.lock."""
    if start is None:
        start = Path.cwd()

    current = start.resolve()
    while True:
        candidate = current / LOCKFILE_NAME
        if candidate.exists():
            return candidate
        parent = current.parent
        if parent == current:
            return None
        current = parent


def read_lockfile(path: Optional[Path] = None) -> Lockfile:
    """Read a cpm.lock file.

    If path is None, searches upward from cwd.
    Returns an empty lockfile if not found.
    """
    if path is None:
        path = find_lockfile()

    lockfile = Lockfile(path=path)

    if path is None or not path.exists():
        return lockfile

    content = path.read_text()
    _parse_lockfile(content, lockfile)
    return lockfile


def write_lockfile(lockfile: Lockfile) -> Path:
    """Write lockfile to its path. Creates cpm.lock in cwd if no path set."""
    if lockfile.path is None:
        lockfile.path = Path.cwd() / LOCKFILE_NAME

    lockfile.path.write_text(lockfile.toml_str())
    return lockfile.path


def _parse_lockfile(content: str, lockfile: Lockfile) -> None:
    """Minimal TOML parser for [[package]] sections."""
    current_entry: Optional[LockEntry] = None

    for line in content.splitlines():
        stripped = line.strip()

        # Skip empty lines and comments
        if not stripped or stripped.startswith("#"):
            continue

        # Section header
        if stripped == "[[package]]":
            current_entry = LockEntry(name="", version="")
            lockfile.entries.append(current_entry)
            continue

        if current_entry is None:
            continue

        # key = value
        if "=" in stripped:
            key, _, value = stripped.partition("=")
            key = key.strip()
            value = value.strip()

            if key == "name":
                current_entry.name = value.strip('"')
            elif key == "version":
                current_entry.version = value.strip('"')
            elif key == "resolved":
                current_entry.resolved = value.strip('"')
            elif key == "checksum":
                current_entry.checksum = value.strip('"')
            elif key == "llvm_version":
                current_entry.llvm_version = value.strip('"')
            elif key == "cpyte_version":
                current_entry.cpyte_version = value.strip('"')
            elif key == "dependencies":
                # Parse array: ["dep1", "dep2"]
                inner = value.strip("[]")
                if inner:
                    current_entry.dependencies = [
                        d.strip().strip('"')
                        for d in inner.split(",")
                        if d.strip()
                    ]
