"""Project manifest management for CPM.

Handles reading and writing cpy.toml, which tracks direct dependencies.
Legacy extensionless `cpytoml` files are still discovered for compatibility.

Manifest format (spec):
    [cpm]
    name = "my-app"
    version = "1.0"
    prebuilt = false
    scorpion = false
    sef = false              # resolve/install SEF (Scorpion) artifacts

    [cpm.target]
    os = "linux"
    arch = "x86_64"
    features = ["gui", "ssl"]

    [cpm.build]
    main = "main.cpy"          # entry override (default: auto-detected)
    pic = true                 # PIC + dynamic SEF v2 for scorpion builds
    exports = ["bigint_add"]   # library symbols to export (dynamic SEF)

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

Platform-scoped dependency tables ([cpm.dependencies.<os>]) apply only when the
resolved target OS matches; the rest are kept aside and rewritten untouched.
Comments (`#`) may follow any value, and inline arrays may span several lines.
"""

from __future__ import annotations

import json
import platform
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cpyte_cpm.cli import minitoml

MANIFEST_NAME = "cpy.toml"
LEGACY_MANIFEST_NAME = "cpytoml"
PACKAGE_JSON_NAME = "package.json"
DEPENDENCIES_SECTION = "cpm.dependencies"


@dataclass
class ExtensionCapabilities:
    """Extension capabilities from package.json."""

    keywords: set[str] = field(default_factory=set)
    operators: set[str] = field(default_factory=set)
    tags: set[str] = field(default_factory=set)
    macros: set[str] = field(default_factory=set)
    custom_types: set[str] = field(default_factory=set)


@dataclass
class ExtensionHooks:
    """Extension hook files from package.json."""

    parser_hooks: list[str] = field(default_factory=list)
    semantic_hooks: list[str] = field(default_factory=list)
    codegen_hooks: list[str] = field(default_factory=list)
    runtime_hooks: list[str] = field(default_factory=list)


@dataclass
class PackageJson:
    """Package manifest from package.json for extension packages."""

    name: str
    version: str
    capabilities: ExtensionCapabilities = field(default_factory=ExtensionCapabilities)
    extensions: ExtensionHooks = field(default_factory=ExtensionHooks)
    dependencies: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    bin: dict[str, str] = field(default_factory=dict)
    path: Path | None = None


@dataclass
class PackageSpec:
    """A parsed package specification: name@version or just name."""

    name: str
    version: str = "latest"

    @classmethod
    def parse(cls, spec: str) -> PackageSpec:
        """Parse a package spec string like 'foo@^1.0' or '@std/json@1.0'."""
        if spec.startswith("@"):
            # Group reference: @std (no slash) vs package: @std/json (has slash)
            match = re.match(r"^(@[^/]+/[^@]+)@(.+)$", spec)
            if match:
                return cls(name=match.group(1), version=match.group(2))
            # @std or @std@latest — could be group or scoped package
            if "/" not in spec:
                # Group reference: @std
                match_ver = re.match(r"^(@[^/]+)@(.+)$", spec)
                if match_ver:
                    return cls(name=match_ver.group(1), version=match_ver.group(2))
                return cls(name=spec, version="latest")
            return cls(name=spec, version="latest")

        if "@" in spec:
            name, version = spec.rsplit("@", 1)
            return cls(name=name, version=version)

        return cls(name=spec, version="latest")

    @property
    def is_group(self) -> bool:
        """True if this is a group reference like @std (no slash)."""
        return self.name.startswith("@") and "/" not in self.name

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

    os: str | None = None
    arch: str | None = None
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
class BuildConfig:
    """Build configuration from the [cpm.build] section."""

    main: str = ""
    pic: bool = True
    exports: list[str] = field(default_factory=list)

    @property
    def is_set(self) -> bool:
        return bool(self.main or not self.pic or self.exports)


@dataclass
class Manifest:
    """Represents a cpy.toml project manifest."""

    name: str = ""
    version: str = "0.1.0"
    prebuilt: bool = False
    scorpion: bool = False
    sef: bool = False
    llvm_version: str = ""
    repos: list[str] = field(default_factory=list)
    packages: list[PackageSpec] = field(default_factory=list)
    platform_packages: dict[str, list[PackageSpec]] = field(default_factory=dict)
    bin: dict[str, str] = field(default_factory=dict)
    target: Target = field(default_factory=Target)
    build: BuildConfig = field(default_factory=BuildConfig)
    path: Path | None = None

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
        removed = False
        for specs in [self.packages, *self.platform_packages.values()]:
            for i, existing in enumerate(specs):
                if existing.name == name:
                    specs.pop(i)
                    removed = True
                    break
        return removed

    def add_scoped(self, scope: str, spec: PackageSpec) -> None:
        """Add a package to a platform-scoped dependency table (e.g. 'linux')."""
        specs = self.platform_packages.setdefault(scope, [])
        for existing in specs:
            if existing.name == spec.name:
                existing.version = spec.version
                return
        specs.append(spec)

    def get(self, name: str) -> PackageSpec | None:
        """Get a package spec by name."""
        for existing in self.packages:
            if existing.name == name:
                return existing
        return None

    def scoped_names(self) -> set[str]:
        """Names declared inside a platform-scoped dependency table."""
        return {
            spec.name for specs in self.platform_packages.values() for spec in specs
        }

    def toml_str(self) -> str:
        """Serialize manifest to TOML string."""
        lines = ["[cpm]"]
        if self.name:
            lines.append(f"name = {minitoml.toml_string(self.name)}")
        lines.append(f"version = {minitoml.toml_string(self.version)}")
        lines.append(f"prebuilt = {str(self.prebuilt).lower()}")
        lines.append(f"scorpion = {str(self.scorpion).lower()}")
        lines.append(f"sef = {str(self.sef).lower()}")
        if self.llvm_version:
            lines.append(f'llvm_version = {minitoml.toml_string(self.llvm_version)}')
        if self.repos:
            lines.append(f"repos = {minitoml.toml_array(self.repos)}")
        lines.append("")

        # Build section
        if self.build.is_set:
            lines.append("[cpm.build]")
            if self.build.main:
                lines.append(f"main = {minitoml.toml_string(self.build.main)}")
            if not self.build.pic:
                lines.append("pic = false")
            if self.build.exports:
                lines.append(f"exports = {minitoml.toml_array(self.build.exports)}")
            lines.append("")

        # Bin section (CLI tools registered by this project)
        if self.bin:
            lines.append("[cpm.bin]")
            for tool, target_path in self.bin.items():
                lines.append(
                    f"{minitoml.toml_string(tool)} = "
                    f"{minitoml.toml_string(target_path)}"
                )
            lines.append("")

        # Target section
        has_target = self.target.os or self.target.arch or self.target.features
        if has_target:
            lines.append("[cpm.target]")
            if self.target.os:
                lines.append(f"os = {minitoml.toml_string(self.target.os)}")
            if self.target.arch:
                lines.append(f"arch = {minitoml.toml_string(self.target.arch)}")
            if self.target.features:
                lines.append(f"features = {minitoml.toml_array(self.target.features)}")
            lines.append("")

        # Platform-scoped names stay in their own table so a rewrite never
        # widens them to every platform.
        scoped_names = self.scoped_names()
        common = [p for p in self.packages if p.name not in scoped_names]

        lines.append(f"[{DEPENDENCIES_SECTION}]")
        if common:
            for p in common:
                lines.append(
                    f"{minitoml.toml_string(p.name)} = "
                    f"{minitoml.toml_string(p.version)}"
                )
        else:
            lines.append("# no dependencies")

        for scope, specs in self.platform_packages.items():
            if not specs:
                continue
            lines.append("")
            lines.append(f"[{DEPENDENCIES_SECTION}.{scope}]")
            for p in specs:
                current = self.get(p.name)
                version = current.version if current else p.version
                lines.append(
                    f"{minitoml.toml_string(p.name)} = "
                    f"{minitoml.toml_string(version)}"
                )

        return "\n".join(lines) + "\n"


def find_manifest(start: Path | None = None) -> Path | None:
    """Walk up from start directory to find cpy.toml (or legacy cpytoml)."""
    if start is None:
        start = Path.cwd()

    current = start.resolve()
    while True:
        candidate = current / MANIFEST_NAME
        if candidate.exists():
            return candidate
        legacy = current / LEGACY_MANIFEST_NAME
        if legacy.exists():
            return legacy
        parent = current.parent
        if parent == current:
            return None
        current = parent


def read_manifest(path: Path | None = None, target_os: str | None = None) -> Manifest:
    """Read a cpy.toml manifest file.

    If path is None, searches upward from cwd.
    ``target_os`` selects which platform-scoped dependency tables apply.
    Returns an empty manifest if not found.
    """
    if path is None:
        path = find_manifest()

    manifest = Manifest(path=path)

    if path is None or not path.exists():
        return manifest

    content = path.read_text()
    _parse_toml(content, manifest, target_os=target_os)
    return manifest


def write_manifest(manifest: Manifest) -> Path:
    """Write manifest to its path. Creates cpy.toml in cwd if no path set."""
    if manifest.path is None:
        manifest.path = Path.cwd() / MANIFEST_NAME

    manifest.path.write_text(manifest.toml_str())
    return manifest.path


def _parse_toml(content: str, manifest: Manifest, target_os: str | None = None) -> None:
    """Minimal TOML parser for cpy.toml manifests.

    ``target_os`` overrides the OS used to resolve platform-scoped dependency
    tables such as ``[cpm.dependencies.linux]``; without it the manifest's
    ``[cpm.target] os`` is used, falling back to the current platform.
    """
    section = ""

    for table, _is_array, statement in minitoml.iter_statements(content):
        if not statement:
            section = table
            continue

        if "=" not in statement or not section:
            continue

        key, _, value = statement.partition("=")
        key = key.strip()
        value = value.strip()

        if section == "cpm":
            if key == "name":
                manifest.name = minitoml.unquote(value)
            elif key == "version":
                manifest.version = minitoml.unquote(value)
            elif key == "prebuilt":
                manifest.prebuilt = value.strip().lower() == "true"
            elif key == "scorpion":
                manifest.scorpion = value.strip().lower() == "true"
            elif key == "sef":
                manifest.sef = value.strip().lower() == "true"
            elif key == "llvm_version":
                manifest.llvm_version = minitoml.unquote(value)
            elif key == "repos":
                manifest.repos = minitoml.parse_array(value)
            elif key == "packages":
                # Legacy format: packages = ["foo", "bar"]
                _parse_inline_packages(value, manifest)

        elif section == "cpm.target":
            if key == "os":
                manifest.target.os = minitoml.unquote(value)
            elif key == "arch":
                manifest.target.arch = minitoml.unquote(value)
            elif key == "features":
                manifest.target.features = minitoml.parse_array(value)

        elif section == "cpm.build":
            if key == "main":
                manifest.build.main = minitoml.unquote(value)
            elif key == "pic":
                manifest.build.pic = value.strip().lower() == "true"
            elif key == "exports":
                manifest.build.exports = minitoml.parse_array(value)

        elif section == "cpm.bin":
            manifest.bin[minitoml.unquote(key)] = minitoml.unquote(value)

        elif section == DEPENDENCIES_SECTION or section.startswith(
            DEPENDENCIES_SECTION + "."
        ):
            # New format: "@std/json" = "^2.0"
            spec = PackageSpec(
                name=minitoml.unquote(key), version=minitoml.unquote(value)
            )
            scope = section[len(DEPENDENCIES_SECTION) + 1 :].strip().lower()
            if scope:
                # Platform-scoped table: remembered so writes keep the scope.
                manifest.add_scoped(scope, spec)
            else:
                manifest.add(spec)

    # Merge the platform-scoped tables that apply to the effective target.
    effective_os = (target_os or manifest.target.os or Target.auto().os or "").lower()
    for spec in manifest.platform_packages.get(effective_os, []):
        manifest.add(spec)


def _parse_inline_packages(value: str, manifest: Manifest) -> None:
    """Parse legacy inline package list: ["foo@1.0", "bar"]"""
    for item in minitoml.parse_array(value):
        manifest.add(PackageSpec.parse(item))


def find_package_json(package_dir: Path) -> Path | None:
    """Find package.json in a package directory."""
    package_json = package_dir / PACKAGE_JSON_NAME
    if package_json.exists():
        return package_json
    return None


def read_package_json(package_dir: Path) -> PackageJson | None:
    """Read package.json from a package directory."""
    package_json_path = find_package_json(package_dir)
    if not package_json_path:
        return None

    try:
        with open(package_json_path, "r") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"Warning: Failed to read package.json: {e}")
        return None

    # Parse capabilities
    capabilities_data = data.get("capabilities", {})
    capabilities = ExtensionCapabilities(
        keywords=set(capabilities_data.get("keywords", [])),
        operators=set(capabilities_data.get("operators", [])),
        tags=set(capabilities_data.get("tags", [])),
        macros=set(capabilities_data.get("macros", [])),
        custom_types=set(capabilities_data.get("custom_types", [])),
    )

    # Parse extensions
    extensions_data = data.get("extensions", {})
    extensions = ExtensionHooks(
        parser_hooks=extensions_data.get("parser_hooks", []),
        semantic_hooks=extensions_data.get("semantic_hooks", []),
        codegen_hooks=extensions_data.get("codegen_hooks", []),
        runtime_hooks=extensions_data.get("runtime_hooks", []),
    )

    return PackageJson(
        name=data.get("name", ""),
        version=data.get("version", ""),
        capabilities=capabilities,
        extensions=extensions,
        dependencies=data.get("dependencies", []),
        metadata=data.get("metadata", {}),
        bin=dict(data.get("bin", {})),
        path=package_json_path,
    )
