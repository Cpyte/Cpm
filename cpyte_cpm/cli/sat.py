import hashlib

from packaging.specifiers import SpecifierSet
from packaging.version import Version

from ..compiler import has_codegen_feature
from . import style
from .gethins import fetch_repo_multi, find_package_metadata
from .manifest import Target


def calculate_checksum(file_path: str, algorithm: str = "sha256") -> str:
    """Calculate checksum of a file."""
    hash_func = hashlib.new(algorithm)
    with open(file_path, "rb") as fp:
        for chunk in iter(lambda: fp.read(4096), b""):
            hash_func.update(chunk)
    return f"{algorithm}:{hash_func.hexdigest()}"


def _build_instruction(metadata: dict, prebuilt: bool = False, sef: bool = False) -> dict:
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
    if sef:
        inst["sef"] = True
    if metadata.get("no_download"):
        inst["no_download"] = True
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
    # Convert scoped packages to registry format: @scope/name -> group/scope/name
    if name.startswith("@"):
        return "group/" + name[1:]
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


def _version_satisfies(required: str, actual: str) -> bool:
    """Check whether ``actual`` satisfies the ``required`` version constraint.

    Supports PEP 440 specifiers (``>=22``, ``<19.1.0``, ``==3.14``, unions
    and comma lists). A bare version means major-version compatibility — the
    prebuilt IR contract between package and toolchain.
    """
    if not required or not actual:
        return True
    required = str(required).strip()
    operators = ("==", "!=", "<=", ">=", "<", ">", "~=")
    if required.startswith(operators) or "," in required or "||" in required:
        try:
            return actual in SpecifierSet(required)
        except Exception:
            return True
    return _check_version_compat(required, actual, "version")


def _matches_toolchain(required: dict, detected: dict) -> tuple[bool, str]:
    """Check a package's ``toolchain`` requirements against detected capabilities.

    ``required`` shape (recorded at publish from package.json ``metadata``):
        {"compiler": ">=2.7.0", "llvm": ">=22", "codegen": ["setjmp"]}

    Returns ``(ok, reason)``. Empty or missing requirements always pass.
    """
    for key, constraint in (required or {}).items():
        if not constraint:
            continue
        if key in ("compiler", "llvm"):
            actual = detected.get(key, "")
            if not actual:
                return False, f"requires {key} {constraint} (toolchain not detected)"
            if not _version_satisfies(constraint, actual):
                return False, f"requires {key} {constraint}, installed {key} is {actual}"
        elif key == "codegen":
            features = constraint if isinstance(constraint, list) else [constraint]
            for feature in features:
                if not has_codegen_feature(str(feature)):
                    return False, f"requires codegen feature '{feature}' (not supported by installed compiler)"
    return True, ""


def resolve_get(packages: list, repos: list[str], resolving=None, resolved=None, target: Target = None, prebuilt: bool = False, sef: bool = False, llvm_version: str = None, cpyte_version: str = None, capabilities: dict = None):
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
    repos:
        Repository URLs in priority order (highest first).
    target:
        Target platform claims for filtering. Packages whose claims
        don't match the target are skipped.
    prebuilt:
        If True, fetch prebuilt metadata from registry.
    sef:
        If True, fetch SEF artifacts from the registry
        (``metadata/sef/...``). Packages that don't declare SEF support
        (``sef`` or ``scorpion`` in metadata) are skipped.
    llvm_version:
        Required LLVM version for prebuilt packages.
    cpyte_version:
        Required Cpyte compiler version for prebuilt packages.
    capabilities:
        Detected toolchain capabilities (``{"compiler": ..., "llvm": ...}``)
        used to satisfy packages that declare a ``toolchain`` requirement.
        Codegen features are probed lazily. When None, toolchain
        requirements are skipped (best-effort).
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

        # Fetch metadata — try different path formats for compatibility
        if prebuilt:
            paths_to_try = [
                f"metadata/prebuilt/{path}/{version}",
                f"metadata/{path}/{version}",  # fallback
            ]
        elif sef:
            paths_to_try = [
                f"metadata/sef/{path}/{version}",
                f"metadata/{path}/{version}",  # fallback to regular metadata
                f"metadata/sef/{path}/latest",
            ]
        else:
            paths_to_try = [
                f"metadata/{path}/{version}",
                f"metadata/{path}/latest",  # fallback to latest if version not found
            ]
        
        metadata = None
        last_error = None
        for metadata_path in paths_to_try:
            try:
                metadata = fetch_repo_multi(repos, metadata_path)
                break
            except Exception as e:
                last_error = e
                continue
        
        # If regular metadata fetch fails, try to get metadata from packages list
        if metadata is None:
            try:
                metadata = find_package_metadata(repos, name)
                if metadata:
                    style.print_verbose(f"  Using metadata from packages list for {name}")
            except Exception as e:
                last_error = e
        
        if metadata is None:
            raise last_error or RuntimeError(f"Could not fetch metadata for {name}@{version}")

        # Check claims — skip packages that don't match target
        claims = metadata.get("claims", {})
        if not target.matches(claims):
            style.print_skipped(name, version, "claims don't match target")
            resolving.remove(name)
            resolved.add(name)
            continue

        # SEF mode: the package must actually ship a SEF artifact
        if sef and not (metadata.get("sef") or metadata.get("scorpion")):
            style.print_skipped(name, version, "package is not a SEF artifact (no 'sef'/'scorpion' in metadata)")
            resolving.remove(name)
            resolved.add(name)
            continue

        # Check declared toolchain requirements against the installed compiler
        required_tc = metadata.get("toolchain", {}) or {}
        if required_tc:
            if capabilities:
                tc_ok, tc_reason = _matches_toolchain(required_tc, capabilities)
                if not tc_ok:
                    style.print_skipped(name, version, tc_reason)
                    resolving.remove(name)
                    resolved.add(name)
                    continue
            else:
                style.print_verbose(f"  {name}: declares toolchain requirements but no compiler detected; skipping check")

        # Check LLVM version compatibility for prebuilt packages
        if prebuilt and llvm_version:
            pkg_llvm = metadata.get("llvm_version", "")
            if pkg_llvm and not _check_version_compat(pkg_llvm, llvm_version, "LLVM"):
                style.print_skipped(name, version, f"LLVM {pkg_llvm} != {llvm_version}")
                resolving.remove(name)
                resolved.add(name)
                continue

        # Check Cpyte compiler version compatibility for prebuilt packages
        if prebuilt and cpyte_version:
            pkg_cpyte = metadata.get("cpyte_version", "")
            if pkg_cpyte and not _check_version_compat(pkg_cpyte, cpyte_version, "cpyte"):
                style.print_skipped(name, version, f"cpyte {pkg_cpyte} != {cpyte_version}")
                resolving.remove(name)
                resolved.add(name)
                continue

        requirements = metadata.get("requires", [])

        if requirements:
            instructions.append(
                resolve_get(requirements, repos, resolving, resolved, target, prebuilt, sef, llvm_version, cpyte_version, capabilities)
            )

        instructions.append(_build_instruction(metadata, prebuilt, sef))

        resolving.remove(name)
        resolved.add(name)

    return instructions


def resolve_remove(packages: list, repos: list[str], resolving=None, resolved=None, target: Target = None, prebuilt: bool = False, llvm_version: str = None):
    """Resolve dependency tree into a flat instruction stream (REMOVE only).

    For removal, we don't need metadata - just remove the packages by name.
    Dependencies are handled by the lockfile, not by resolving from registry.
    """
    if resolving is None:
        resolving = set()
    if resolved is None:
        resolved = set()

    instructions = []

    for pkg in packages:
        name, version = _parse_package(pkg)

        if name in resolving:
            raise ValueError(f"Dependency cycle detected involving {name}")

        if name in resolved:
            continue

        resolving.add(name)

        # For removal, we don't need to fetch metadata
        # Just create a REMOVE instruction for the package name
        instructions.append({"REMOVE": name})

        resolving.remove(name)
        resolved.add(name)

    return instructions


def deduplicator(tree: list[dict]) -> list[dict]:
    """Flatten and deduplicate a dependency tree into an instruction stream.

    Pipeline stage: Optimize
    Traverses nested tree, deduplicates by name@version (not just name),
    returns flat list. Different versions of the same package are NOT
    duplicates and will both be kept.
    """
    seen: set[str] = set()
    result: list[dict] = []

    def traverse(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "GET":
                    version = node.get("version", "latest")
                    identity = f"{value}@{version}"
                    if identity not in seen:
                        seen.add(identity)
                        result.append(node)
                elif key == "REMOVE" and value not in seen:
                    seen.add(value)
                    result.append(node)
        elif isinstance(node, list):
            for item in node:
                traverse(item)

    traverse(tree)
    return result
