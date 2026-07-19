"""Project manifest management for CPM.

Handles reading and writing cpytoml, which tracks direct dependencies.

Manifest format (spec):
    [cpm]
    name = "my-app"
    version = "1.0"
    prebuilt = false

    [cpm.target]
    os = "linux"
    arch = "x86_64"
    features = ["gui", "ssl"]

    [cpm.dependencies]
    "@std/json" = "^2.0"
    "@std/http" = "1.0"
    "package_a" = "latest"

    [cpm.dependencies.windows]
    "win32-api" = "1.0"

    [cpm.dependencies.linux]
    "posix-api" = "1.0"

Legacy format (also supported):
    [cpm]
    packages = ["foo@^1.0", "bar@latest"]
"""

from __future__ import annotations

import platform
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

MANIFEST_NAME = "cpytoml"


@dataclass
class PackageSpec:
    """A parsed package specification: name@version or just name."""
    name: str
    version: str = "latest"

    @classmethod
    def parse(cls, spec: str) -> PackageSpec:
        """Parse a package spec string like 'foo@^1.0' or '@std/json@1.0'."""
        if spec.startswith("@"):
            match = re.match(r"^(@[^/]+/[^@]+)@(.+)$", spec)
            if match:
                return cls(name=match.group(1), version=match.group(2))
            return cls(name=spec, version="latest")

        if "@" in spec:
            name, version = spec.rsplit("@", 1)
            return cls(name=name, version=version)

        return cls(name=spec, version="latest")

    def __str__(self) -> str:
        if self.version == "latest":
            return self.name
        return f"{self.name}@{self.version}"


@dataclass
class Target:
    """Target platform claims for dependency resolution.

    Attributes
    ----------
    os:
        Target operating system (linux, darwin, windows).
        None means auto-detect from current platform.
    arch:
        Target architecture (x86_64, aarch64, arm).
        None means auto-detect from current platform.
    features:
        List of feature flags to enable.
        Empty list means no features.
    """
    os: Optional[str] = None
    arch: Optional[str] = None
    features: list[str] = field(default_factory=list)

    @classmethod
    def auto(cls) -> Target:
        """Auto-detect target from current platform."""
        os_map = {
            "Linux": "linux",
            "Darwin": "darwin",
            "Windows": "windows",
        }
        arch_map = {
            "x86_64": "x86_64",
            "AMD64": "x86_64",
            "arm64": "aarch64",
            "aarch64": "aarch64",
        }
        return cls(
            os=os_map.get(platform.system(), platform.system().lower()),
            arch=arch_map.get(platform.machine(), platform.machine().lower()),
        )

    def matches(self, claims: dict) -> bool:
        """Check if this target matches the given package claims.

        Parameters
        ----------
        claims:
            Package claims dict with optional keys: os, arch, features.

        Returns
        -------
        True if the target is compatible with the claims.
        """
        if not claims:
            return True

        # Check OS
        claim_os = claims.get("os")
        if claim_os:
            if isinstance(claim_os, str):
                claim_os = [claim_os]
            if self.os and self.os not in claim_os:
                return False

        # Check architecture
        claim_arch = claims.get("arch")
        if claim_arch:
            if isinstance(claim_arch, str):
                claim_arch = [claim_arch]
            if self.arch and self.arch not in claim_arch:
                return False

        # Check features (all required features must be enabled)
        claim_features = claims.get("features", [])
        if claim_features:
            if isinstance(claim_features, str):
                claim_features = [claim_features]
            for feat in claim_features:
                if feat not in self.features:
                    return False

        return True


@dataclass
class Manifest:
    """Represents a cpytoml project manifest."""
    name: str = ""
    version: str = "0.1.0"
    prebuilt: bool = False
    llvm_version: str = ""
    packages: list[PackageSpec] = field(default_factory=list)
    target: Target = field(default_factory=Target)
    path: Optional[Path] = None

    def add(self, spec: PackageSpec) -> bool:
        """Add a package. Returns True if added/updated, False if unchanged."""
        for existing in self.packages:
            if existing.name == spec.name:
                if existing.version != spec.version:
                    existing.version = spec.version
                    return True
                return False
        self.packages.append(spec)
        return True

    def remove(self, name: str) -> bool:
        """Remove a package by name. Returns True if removed."""
        for i, existing in enumerate(self.packages):
            if existing.name == name:
                self.packages.pop(i)
                return True
        return False

    def get(self, name: str) -> Optional[PackageSpec]:
        """Get a package spec by name."""
        for existing in self.packages:
            if existing.name == name:
                return existing
        return None

    def toml_str(self) -> str:
        """Serialize manifest to TOML string."""
        lines = ["[cpm]"]
        if self.name:
            lines.append(f'name = "{self.name}"')
        lines.append(f'version = "{self.version}"')
        lines.append(f"prebuilt = {str(self.prebuilt).lower()}")
        if self.llvm_version:
            lines.append(f'llvm_version = "{self.llvm_version}"')
        lines.append("")

        # Target section
        has_target = self.target.os or self.target.arch or self.target.features
        if has_target:
            lines.append("[cpm.target]")
            if self.target.os:
                lines.append(f'os = "{self.target.os}"')
            if self.target.arch:
                lines.append(f'arch = "{self.target.arch}"')
            if self.target.features:
                lines.append(f"features = {self.target.features}")
            lines.append("")

        lines.append("[cpm.dependencies]")
        if self.packages:
            for p in self.packages:
                lines.append(f'"{p.name}" = "{p.version}"')
        else:
            lines.append("# no dependencies")

        return "\n".join(lines) + "\n"


def find_manifest(start: Optional[Path] = None) -> Optional[Path]:
    """Walk up from start directory to find cpytoml."""
    if start is None:
        start = Path.cwd()

    current = start.resolve()
    while True:
        candidate = current / MANIFEST_NAME
        if candidate.exists():
            return candidate
        parent = current.parent
        if parent == current:
            return None
        current = parent


def read_manifest(path: Optional[Path] = None) -> Manifest:
    """Read a cpytoml manifest file.

    If path is None, searches upward from cwd.
    Returns an empty manifest if not found.
    """
    if path is None:
        path = find_manifest()

    manifest = Manifest(path=path)

    if path is None or not path.exists():
        return manifest

    content = path.read_text()
    _parse_toml(content, manifest)
    return manifest


def write_manifest(manifest: Manifest) -> Path:
    """Write manifest to its path. Creates cpytoml in cwd if no path set."""
    if manifest.path is None:
        manifest.path = Path.cwd() / MANIFEST_NAME

    manifest.path.write_text(manifest.toml_str())
    return manifest.path


def _parse_toml(content: str, manifest: Manifest) -> None:
    """Minimal TOML parser for cpytoml manifests."""
    section = ""

    for line in content.splitlines():
        stripped = line.strip()

        if not stripped or stripped.startswith("#"):
            continue

        # Section header
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1].strip()
            continue

        # key = value
        if "=" in stripped and section:
            key, _, value = stripped.partition("=")
            key = key.strip()
            value = value.strip()

            if section == "cpm":
                if key == "name":
                    manifest.name = value.strip('"')
                elif key == "version":
                    manifest.version = value.strip('"')
                elif key == "prebuilt":
                    manifest.prebuilt = value.strip().lower() == "true"
                elif key == "llvm_version":
                    manifest.llvm_version = value.strip('"')
                elif key == "packages":
                    # Legacy format: packages = ["foo", "bar"]
                    _parse_inline_packages(value, manifest)

            elif section == "cpm.target":
                if key == "os":
                    manifest.target.os = value.strip('"')
                elif key == "arch":
                    manifest.target.arch = value.strip('"')
                elif key == "features":
                    manifest.target.features = _parse_list(value)

            elif section == "cpm.dependencies":
                # New format: "@std/json" = "^2.0"
                name = key.strip('"')
                version = value.strip('"')
                manifest.add(PackageSpec(name=name, version=version))


def _parse_inline_packages(value: str, manifest: Manifest) -> None:
    """Parse legacy inline package list: ["foo@1.0", "bar"]"""
    value = value.strip()
    if not value.startswith("["):
        return

    inner = value[1:]
    if inner.endswith("]"):
        inner = inner[:-1]

    for item in inner.split(","):
        item = item.strip().strip('"').strip("'")
        if item:
            manifest.add(PackageSpec.parse(item))


def _parse_list(value: str) -> list[str]:
    """Parse a TOML inline list like ['a', 'b', 'c']."""
    value = value.strip()
    if not value.startswith("["):
        return []

    inner = value[1:]
    if inner.endswith("]"):
        inner = inner[:-1]

    return [
        item.strip().strip('"').strip("'")
        for item in inner.split(",")
        if item.strip()
    ]
