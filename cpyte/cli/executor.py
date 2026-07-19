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


def _download(url: str, dest: Path) -> None:
    """Download a file from url to dest."""
    response = rq.get(url, stream=True, timeout=30)
    response.raise_for_status()
    with open(dest, "wb") as fp:
        for chunk in response.iter_content(chunk_size=8192):
            fp.write(chunk)


def _extract(archive_path: Path, dest: Path) -> None:
    """Extract a tar.gz or zip archive into dest."""
    dest.mkdir(parents=True, exist_ok=True)
    name = archive_path.name
    if name.endswith(".tar.gz") or name.endswith(".tgz"):
        with tarfile.open(archive_path, "r:gz") as tar:
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


def execute_get(inst: dict, project_root: Path, prebuilt: bool = False) -> None:
    """Execute a single GET instruction.

    Parameters
    ----------
    inst:
        Instruction dict with GET, url, version, checksum.
    project_root:
        Project root directory (where .cpm/modules/ lives).
    prebuilt:
        If True, fetch prebuilt .ll from registry.
    """
    name = inst["GET"]
    url = inst.get("url")
    version = inst.get("version", "latest")
    checksum = inst.get("checksum")

    if not url:
        raise ValueError(f"No URL provided for package '{name}'")

    target = _module_path(project_root, name, version)

    # Already installed — skip
    if target.exists():
        print(f"  {name}@{version} already installed")
        return

    cache = _cache_path(name, version)

    # Check cache
    if checksum and _is_cached(name, version, checksum):
        print(f"  {name}@{version} found in cache, installing...")
        _install_from_cache(project_root, name, version)
        print(f"  {name}@{version} installed")
        return

    # Download
    print(f"  downloading {name}@{version}...")
    cache.mkdir(parents=True, exist_ok=True)
    filename = url.rsplit("/", 1)[-1] or f"{name}-{version}.tar.gz"
    dest = cache / filename
    _download(url, dest)

    # Verify checksum
    if checksum:
        print(f"  verifying checksum...")
        _verify_checksum(str(dest), checksum)

    # Extract to cache first
    print(f"  installing {name}@{version}...")
    _extract(dest, cache)

    # Install from cache to project
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(cache, target)

    mode = "prebuilt" if prebuilt else "source"
    print(f"  {name}@{version} installed [{mode}]")


def execute_remove(inst: dict, project_root: Path) -> None:
    """Execute a single REMOVE instruction."""
    name = inst["REMOVE"]
    target = project_root / ".cpm" / "modules" / name

    if not target.exists():
        print(f"  {name} not installed, skipping")
        return

    shutil.rmtree(target)
    print(f"  {name} removed")


def execute(
    instructions: list[dict],
    project_root: Path,
    repo: str = None,
    ver: str = "latest",
    prebuilt: bool = False,
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
    """
    _ensure_cache_dir()

    total = len(instructions)
    mode = "prebuilt" if prebuilt else "source"
    print(f"\nExecuting {total} instruction(s) [{mode}]...\n")

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
            print(f"[{i}/{total}] GET {inst['GET']}")
            execute_get(inst, project_root, prebuilt=prebuilt)
        elif "REMOVE" in inst:
            print(f"[{i}/{total}] REMOVE {inst['REMOVE']}")
            execute_remove(inst, project_root)
        else:
            print(f"[{i}/{total}] SKIP unknown instruction: {inst}")

    print(f"\nDone. {total} instruction(s) executed.")
