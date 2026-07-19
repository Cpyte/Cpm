import hashlib
import os
import tempfile
from packaging.version import Version
from .gethins import fetch_repo as f
import requests as rq

from .manifest import Target


class PackageKey:
    """Unique identity for a package: name@version."""
    __slots__ = ("name", "version")

    def __init__(self, name: str, version: str):
        self.name = name
        self.version = version

    def __eq__(self, other):
        if not isinstance(other, PackageKey):
            return NotImplemented
        return self.name == other.name and self.version == other.version

    def __hash__(self):
        return hash((self.name, self.version))

    def __repr__(self):
        return f"{self.name}@{self.version}"


def calculate_checksum(file_path: str, algorithm: str = "sha256") -> str:
    """Calculate checksum of a file."""
    hash_func = hashlib.new(algorithm)
    with open(file_path, "rb") as fp:
        for chunk in iter(lambda: fp.read(4096), b""):
            hash_func.update(chunk)
    return f"{algorithm}:{hash_func.hexdigest()}"


def download_and_verify(url: str, expected_checksum: str, version: float | int, algorithm: str = "sha256") -> str:
    """Download a file and verify its checksum."""
    response = rq.get(url, stream=True)
    response.raise_for_status()

    suffix = os.path.basename(url)
    with tempfile.NamedTemporaryFile(
        prefix=f"{version}_",
        suffix=f"_{suffix}",
        delete=False,
    ) as tmp:
        for chunk in response.iter_content(chunk_size=8192):
            tmp.write(chunk)
        temp_path = tmp.name

    actual_checksum = calculate_checksum(temp_path, algorithm)

    if actual_checksum != expected_checksum:
        os.remove(temp_path)
        raise ValueError(f"Checksum mismatch: expected {expected_checksum}, got {actual_checksum}")

    print(f"Checksum verified: {actual_checksum}")
    return temp_path


def _build_instruction(metadata: dict, prebuilt: bool = False) -> dict:
    """Build a rich instruction dict from package metadata.

    The instruction carries everything the executor needs:
        {"GET": "name", "url": "...", "checksum": "sha256:...", "version": "1.0"}
    """
    inst = {
        "GET": metadata["name"],
        "url": metadata["url"],
        "checksum": metadata.get("checksum", ""),
        "version": metadata.get("version", "latest"),
    }
    if prebuilt:
        inst["prebuilt"] = True
        inst["llvm_version"] = metadata.get("llvm_version", "")
        inst["cpyte_version"] = metadata.get("cpyte_version", "")
    return inst


def _parse_package(pkg) -> tuple[str, str]:
    """Parse a package argument into (name, version).

    Accepts:
        - "foo"              → ("foo", "latest")
        - "foo@1.0"          → ("foo", "1.0")
        - "@scope/name@1.0"  → ("@scope/name", "1.0")
        - ("foo", "1.0")     → ("foo", "1.0")
    """
    if isinstance(pkg, tuple):
        return pkg[0], pkg[1]

    pkg = str(pkg)

    # Scoped: @scope/name@version
    if pkg.startswith("@"):
        if "@" in pkg[1:]:
            idx = pkg.index("@", 1)
            return pkg[:idx], pkg[idx + 1:]
        return pkg, "latest"

    # Regular: name@version
    if "@" in pkg:
        name, version = pkg.rsplit("@", 1)
        return name, version

    return pkg, "latest"


def _package_path(name: str) -> str:
    """Convert a package name to a URL path segment.

    "@std/json"  → "group/std/json"
    "@a/b/c"     → "group/a/b/c"
    "foo"        → "foo"
    """
    if name.startswith("@"):
        # @scope/name → group/scope/name
        return "group/" + name[1:].replace("/", "/")
    return name


def _check_version_compat(package_version: str, project_version: str, label: str) -> bool:
    """Check if a package's version is compatible with the project's version.

    Compatible means: major version matches (semver).
    Returns True if compatible, False otherwise.
    """
    if not package_version or not project_version:
        return True

    try:
        pkg_ver = Version(package_version)
        proj_ver = Version(project_version)
        # Major version must match for prebuilt IR compatibility
        return pkg_ver.major == proj_ver.major
    except Exception:
        # If we can't parse, assume compatible
        return True


def resolve_get(packages: list, repo: str, resolving=None, resolved=None, target: Target = None, prebuilt: bool = False, llvm_version: str = None):
    """Resolve dependency tree into a flat instruction stream (GET only).

    Pipeline stage: Resolve -> Lower -> Optimize -> Execute
    This is the Resolve + Lower stage combined.
    Each instruction carries url/checksum/version from metadata.

    Parameters
    ----------
    packages:
        List of package specs. Each can be:
            - "foo" or "foo@1.0" (string)
            - ("foo", "1.0") (tuple)
    repo:
        Repository URL base.
    target:
        Target platform claims for filtering. Packages whose claims
        don't match the target are skipped.
    prebuilt:
        If True, fetch prebuilt metadata from registry.
    llvm_version:
        Required LLVM version for prebuilt packages.
    """
    if resolving is None:
        resolving = set()
    if resolved is None:
        resolved = set()
    if target is None:
        target = Target.auto()

    instructions = []

    for pkg in packages:
        name, version = _parse_package(pkg)

        if name in resolving:
            raise ValueError(f"Dependency cycle detected involving {name}")

        if name in resolved:
            continue

        resolving.add(name)

        path = _package_path(name)

        # Fetch metadata — prebuilt uses different path
        if prebuilt:
            metadata = f(repo, f"metadata/prebuilt/{path}/{version}")
        else:
            metadata = f(repo, f"metadata/{path}/{version}")

        # Check claims — skip packages that don't match target
        claims = metadata.get("claims", {})
        if not target.matches(claims):
            print(f"  skipping {name}@{version} (claims don't match target)")
            resolving.remove(name)
            resolved.add(name)
            continue

        # Check LLVM version compatibility for prebuilt packages
        if prebuilt and llvm_version:
            pkg_llvm = metadata.get("llvm_version", "")
            if pkg_llvm and not _check_version_compat(pkg_llvm, llvm_version, "LLVM"):
                print(f"  skipping {name}@{version} (LLVM {pkg_llvm} != {llvm_version})")
                resolving.remove(name)
                resolved.add(name)
                continue

        requirements = metadata.get("requires", [])

        if requirements:
            instructions.append(
                resolve_get(requirements, repo, resolving, resolved, target, prebuilt, llvm_version)
            )

        instructions.append(_build_instruction(metadata, prebuilt))

        resolving.remove(name)
        resolved.add(name)

    return instructions


def resolve_remove(packages: list, repo: str, resolving=None, resolved=None, target: Target = None, prebuilt: bool = False, llvm_version: str = None):
    """Resolve dependency tree into a flat instruction stream (REMOVE only).

    Same pipeline as resolve_get but for removal operations.
    """
    if resolving is None:
        resolving = set()
    if resolved is None:
        resolved = set()
    if target is None:
        target = Target.auto()

    instructions = []

    for pkg in packages:
        name, version = _parse_package(pkg)

        if name in resolving:
            raise ValueError(f"Dependency cycle detected involving {name}")

        if name in resolved:
            continue

        resolving.add(name)

        path = _package_path(name)

        # Fetch metadata — prebuilt uses different path
        if prebuilt:
            metadata = f(repo, f"metadata/prebuilt/{path}/{version}")
        else:
            metadata = f(repo, f"metadata/{path}/{version}")

        # Check claims — skip packages that don't match target
        claims = metadata.get("claims", {})
        if not target.matches(claims):
            resolving.remove(name)
            resolved.add(name)
            continue

        # Check LLVM version compatibility for prebuilt packages
        if prebuilt and llvm_version:
            pkg_llvm = metadata.get("llvm_version", "")
            if pkg_llvm and not _check_version_compat(pkg_llvm, llvm_version, "LLVM"):
                resolving.remove(name)
                resolved.add(name)
                continue

        requirements = metadata.get("requires", [])

        if requirements:
            instructions.append(
                resolve_remove(requirements, repo, resolving, resolved, target, prebuilt, llvm_version)
            )

        instructions.append({"REMOVE": metadata["name"]})

        resolving.remove(name)
        resolved.add(name)

    return instructions


def deduplicator(tree: list[dict]) -> list[dict]:
    """Flatten and deduplicate a dependency tree into an instruction stream.

    Pipeline stage: Optimize
    Traverses nested tree, deduplicates by package name, returns flat list.
    """
    seen: set[str] = set()
    result: list[dict] = []

    def traverse(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "GET" and value not in seen:
                    seen.add(value)
                    result.append(node)
                elif key == "REMOVE" and value not in seen:
                    seen.add(value)
                    result.append(node)
        elif isinstance(node, list):
            for item in node:
                traverse(item)

    traverse(tree)
    return result
