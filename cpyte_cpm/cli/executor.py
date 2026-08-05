"""Execution engine for CPM instruction streams.

Pipeline stage: Execute
Consumes the flat instruction list produced by deduplicator() and
performs actual filesystem operations.

Directory layout:
    ~/.cpm/cache/<name>/<version>/        — downloaded artifacts (shared cache)
    <project>/.cpm/modules/<name>/<version>/ — installed packages (project-local)

Modes:
    prebuilt = false (default): install source (.cpy files)
    prebuilt = true:            install precompiled LLVM IR (.ll)
                                registry serves prebuilt artifacts
"""

import hashlib
import os
import shutil
import tarfile
import tempfile
import zipfile
from pathlib import Path

import requests as rq

from .gethins import fetch_repo
from . import style
from .http_session import get_session


CPM_HOME = Path.home() / ".cpm"
CACHE_DIR = CPM_HOME / "cache"


def _ensure_cache_dir():
    """Create CPM cache directory if it doesn't exist."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _cache_path(name: str, version: str) -> Path:
    """Return the cache directory for a specific package version."""
    return CACHE_DIR / name / version


def _module_path(project_root: Path, name: str, version: str) -> Path:
    """Return the project-local install directory for a specific package version."""
    return project_root / ".cpm" / "modules" / name / version


def calculate_checksum(file_path: str, algorithm: str = "sha256") -> str:
    """Calculate checksum of a file."""
    hash_func = hashlib.new(algorithm)
    with open(file_path, "rb") as fp:
        for chunk in iter(lambda: fp.read(4096), b""):
            hash_func.update(chunk)
    return f"{algorithm}:{hash_func.hexdigest()}"


def _verify_checksum(file_path: str, expected: str) -> None:
    """Verify a file's checksum. Expected format: 'algorithm:hex'."""
    if ":" not in expected:
        raise ValueError(f"Checksum must be 'algorithm:hex', got: {expected}")
    algorithm, expected_hex = expected.split(":", 1)
    actual = calculate_checksum(file_path, algorithm)
    actual_hex = actual.split(":", 1)[1]
    if actual_hex != expected_hex:
        os.remove(file_path)
        raise ValueError(
            f"Checksum mismatch for {file_path}: "
            f"expected {expected}, got {actual}"
        )


def _download(url: str, dest: Path) -> int:
    """Download a file from url to dest. Returns file size in bytes."""
    session = get_session()
    response = session.get(url, stream=True, timeout=30)
    response.raise_for_status()
    size = int(response.headers.get("content-length", 0))
    with open(dest, "wb") as fp:
        for chunk in response.iter_content(chunk_size=8192):
            fp.write(chunk)
    return size


def _extract(archive_path: Path, dest: Path) -> None:
    """Extract a tar.gz or zip archive into dest."""
    dest.mkdir(parents=True, exist_ok=True)
    name = archive_path.name
    if name.endswith(".tar.gz") or name.endswith(".tgz"):
        with tarfile.open(archive_path, "r:gz") as tar:
            # Check if archive contains a single root directory
            members = tar.getmembers()
            if len(members) > 0:
                # Get all top-level paths
                top_level = set()
                for member in members:
                    # Split the path and get the first component
                    parts = member.name.split('/')
                    if len(parts) > 0:
                        top_level.add(parts[0])
                # If there's only one top-level directory, extract its contents
                if len(top_level) == 1:
                    root_dir = top_level.pop()
                    # Extract contents of the single directory
                    for member in members:
                        if member.name.startswith(root_dir + '/'):
                            # Strip the root directory
                            member.name = member.name[len(root_dir)+1:]
                            if member.name:  # Skip empty names
                                tar.extract(member, dest)
                    return
            tar.extractall(dest)
    elif name.endswith(".tar.bz2"):
        with tarfile.open(archive_path, "r:bz2") as tar:
            tar.extractall(dest)
    elif name.endswith(".tar"):
        with tarfile.open(archive_path, "r") as tar:
            tar.extractall(dest)
    elif name.endswith(".zip"):
        with zipfile.ZipFile(archive_path, "r") as zf:
            zf.extractall(dest)
    else:
        # Raw file (e.g. .ll, .bc, .cpy) — copy directly
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy2(archive_path, dest / name)


def _is_cached(name: str, version: str, checksum: str) -> bool:
    """Check if a package is already in cache with matching checksum."""
    cache = _cache_path(name, version)
    if not cache.exists():
        return False
    for f in cache.iterdir():
        if f.is_file():
            try:
                actual = calculate_checksum(str(f))
                if actual == checksum:
                    return True
            except Exception:
                continue
    return False


def _install_from_cache(project_root: Path, name: str, version: str) -> None:
    """Copy a cached archive into the project modules directory and extract."""
    cache = _cache_path(name, version)
    target = _module_path(project_root, name, version)

    if target.exists():
        shutil.rmtree(target)

    for f in cache.iterdir():
        if f.is_file():
            _extract(f, target)
            return


def execute_get(inst: dict, project_root: Path, prebuilt: bool = False,
                force: bool = False, no_cache: bool = False) -> None:
    """Execute a single GET instruction.

    Parameters
    ----------
    inst:
        Instruction dict with GET, url, version, checksum.
    project_root:
        Project root directory (where .cpm/modules/ lives).
    prebuilt:
        If True, fetch prebuilt .ll from registry.
    force:
        If True, reinstall even if already installed.
    no_cache:
        If True, skip cache and re-download.
    """
    name = inst["GET"]
    url = inst.get("url")
    version = inst.get("version", "latest")
    checksum = inst.get("checksum")
    no_download = inst.get("no_download", False)

    if not url:
        raise ValueError(f"No URL provided for package '{name}'")

    target = _module_path(project_root, name, version)

    # Already installed — skip (unless force)
    if target.exists() and not force:
        style.print_already_installed(name, version)
        return

    # If no downloadable file, create a placeholder
    if no_download:
        style.print_verbose(f"  {name}@{version} has no downloadable file (registry metadata only)")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.mkdir(parents=True, exist_ok=True)
        # Create a placeholder file
        (target / ".placeholder").write_text(f"Package {name}@{version} - registry metadata only, no downloadable file")
        style.print_installed(name, version, "placeholder")
        return

    cache = _cache_path(name, version)

    # Check cache (unless no_cache is set)
    if not no_cache and checksum and _is_cached(name, version, checksum):
        style.print_verbose(f"  {name}@{version} found in cache, installing...")
        _install_from_cache(project_root, name, version)
        style.print_installed(name, version, "source", cached=True)
        return

    # Download
    cache.mkdir(parents=True, exist_ok=True)
    filename = url.rsplit("/", 1)[-1] or f"{name}-{version}.tar.gz"
    dest = cache / filename
    style.print_download(name, version)
    size = _download(url, dest)

    # Verify checksum
    if checksum:
        style.print_verbose("  verifying checksum...")
        _verify_checksum(str(dest), checksum)

    # Extract to cache first
    style.print_verbose(f"  extracting {name}@{version}...")
    _extract(dest, cache)

    # Install from cache to project
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(cache, target)

    mode = "prebuilt" if prebuilt else "source"
    style.print_installed(name, version, mode)


def execute_remove(inst: dict, project_root: Path) -> None:
    """Execute a single REMOVE instruction."""
    name = inst["REMOVE"]
    target = project_root / ".cpm" / "modules" / name

    if not target.exists():
        style.print_warning(f"{name} not installed, skipping")
        return

    shutil.rmtree(target)
    style.print_removed(name)


def execute(
    instructions: list[dict],
    project_root: Path,
    repo: str = None,
    ver: str = "latest",
    prebuilt: bool = False,
    force: bool = False,
    no_cache: bool = False,
) -> None:
    """Execute a flat instruction stream.

    Pipeline stage: Execute
    This is the final stage — instructions are consumed and filesystem
    operations are performed.

    Parameters
    ----------
    instructions:
        Flat list of dicts from deduplicator(), e.g.
        [{"GET": "D", "url": "...", ...}, {"GET": "B", ...}]
    project_root:
        Project root directory (where .cpm/modules/ lives).
    repo:
        Repository URL. If provided, missing metadata (url, checksum)
        will be fetched during execution.
    ver:
        Package version to resolve against.
    prebuilt:
        If True, registry serves prebuilt artifacts (.ll).
    force:
        If True, reinstall even if already installed.
    no_cache:
        If True, skip cache and re-download.
    """
    _ensure_cache_dir()

    total = len(instructions)
    mode = "prebuilt" if prebuilt else "source"
    style.print_header(f"Executing {total} instruction(s) [{mode}]")

    for i, inst in enumerate(instructions, 1):
        # If metadata is missing from instruction, fetch it
        if "GET" in inst and "url" not in inst:
            name = inst["GET"]
            if repo is None:
                raise ValueError(
                    f"Instruction for '{name}' has no URL and no repo provided"
                )
            metadata = fetch_repo(repo, f"metadata/{name}/{ver}")
            inst["url"] = metadata["url"]
            inst["checksum"] = metadata.get("checksum", "")
            inst["version"] = metadata.get("version", ver)

        if "GET" in inst:
            style.print_step(i, total, f"GET {inst['GET']}")
            execute_get(inst, project_root, prebuilt=prebuilt, force=force, no_cache=no_cache)
        elif "REMOVE" in inst:
            style.print_step(i, total, f"REMOVE {inst['REMOVE']}")
            execute_remove(inst, project_root)
        else:
            style.print_step(i, total, f"SKIP unknown instruction: {inst}")

    style.print_success(f"\nDone. {total} instruction(s) executed.")
