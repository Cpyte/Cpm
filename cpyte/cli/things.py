"""Command handlers for CPM.

Each handler orchestrates the full pipeline for its command:
    manifest read → resolve → lower → optimize → execute → lock
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

from .sat import resolve_get, resolve_remove, deduplicator, _package_path
from .executor import execute, _ensure_cache_dir
from .manifest import (
    Manifest,
    PackageSpec,
    Target,
    find_manifest,
    read_manifest,
    write_manifest,
)
from .lockfile import (
    Lockfile,
    LockEntry,
    find_lockfile,
    read_lockfile,
    write_lockfile,
)
from .gethins import fetch_repo
from .gethins import fetch_repo_multi
from .gethins import fetch_group
from cpyte.cli.commands import (
    InstallCommand,
    RemoveCommand,
    AddCommand,
    UpdateCommand,
    InitCommand,
    BuildCommand,
    RunCommand,
    PublishCommand,
    UnpublishCommand,
    SearchCommand,
    GlobalOptions,
)

DEFAULT_REPO = "https://cypackage.5gnew.io.vn"


def _get_repos(global_opt: GlobalOptions, manifest: Manifest = None) -> list[str]:
    """Build repository URL list in priority order.

    Priority (highest first):
        1. --server CLI flag (repeatable)
        2. [cpm] repos = [...] in manifest
        3. --config CLI flag (legacy single-repo)
        4. DEFAULT_REPO
    """
    repos = []

    # 1. --server CLI flag (highest priority)
    if global_opt.server:
        repos.extend(global_opt.server)

    # 2. Manifest repos
    if manifest and manifest.repos:
        for url in manifest.repos:
            if url not in repos:
                repos.append(url)

    # 3. --config (legacy)
    if global_opt.config and global_opt.config not in repos:
        repos.append(global_opt.config)

    # 4. Default fallback
    if DEFAULT_REPO not in repos:
        repos.append(DEFAULT_REPO)

    return repos


def _get_repo_url(global_opt: GlobalOptions) -> str:
    """Return single repo URL (legacy compat)."""
    if global_opt.server:
        return global_opt.server[0]
    if global_opt.config:
        return global_opt.config
    return DEFAULT_REPO


def _expand_groups(specs: list[PackageSpec], repos: list[str]) -> list[PackageSpec]:
    """Expand group references into individual package specs.

    @std -> [@std/json, @std/math, ...] fetched from registry.
    Non-group specs pass through unchanged.
    """
    expanded = []
    for spec in specs:
        if spec.is_group:
            print(f"Expanding group {spec.name}...")
            try:
                packages = fetch_group(repos, spec.name)
                for pkg_name in packages:
                    expanded.append(PackageSpec(name=pkg_name, version="latest"))
                print(f"  Found {len(packages)} package(s)")
            except Exception as e:
                print(f"  Warning: could not fetch group {spec.name}: {e}")
        else:
            expanded.append(spec)
    return expanded


def _get_target(manifest: Manifest, global_opt: GlobalOptions = None) -> Target:
    """Return the target from manifest, CLI flag, or auto-detect.

    Priority:
        1. --target CLI flag (e.g., --target linux/x86_64)
        2. [cpm.target] section in manifest
        3. Auto-detect from current platform
    """
    # CLI flag takes priority
    if global_opt and global_opt.target:
        target_str = global_opt.target
        parts = target_str.split("/")
        os_name = parts[0] if len(parts) > 0 else None
        arch = parts[1] if len(parts) > 1 else None
        return Target(os=os_name, arch=arch)

    # Manifest target
    if manifest.target.os or manifest.target.arch or manifest.target.features:
        return manifest.target

    # Auto-detect
    return Target.auto()


def _lock_from_instruction(inst: dict, deps: list[str] | None = None) -> LockEntry:
    """Build a LockEntry from an executed GET instruction."""
    return LockEntry(
        name=inst["GET"],
        version=inst.get("version", "latest"),
        resolved=inst.get("url", ""),
        checksum=inst.get("checksum", ""),
        dependencies=deps or [],
        llvm_version=inst.get("llvm_version", ""),
        cpyte_version=inst.get("cpyte_version", ""),
    )


# ---------------------------------------------------------------------------
# cpm init
# ---------------------------------------------------------------------------

def init_project(global_opt: GlobalOptions, command: InitCommand):
    """Initialize a new CPM project.

    Creates cpytoml in the current directory.
    """
    manifest_path = Path.cwd() / "cpytoml"

    if manifest_path.exists() and not global_opt.yes:
        print(f"cpytoml already exists. Use -y to overwrite.")
        return

    project_name = Path.cwd().name
    manifest = Manifest(name=project_name, version="0.1.0", path=manifest_path)
    write_manifest(manifest)
    print(f"Initialized CPM project: {project_name}")
    print(f"Created {manifest_path}")


# ---------------------------------------------------------------------------
# cpm add
# ---------------------------------------------------------------------------

def add_deps(global_opt: GlobalOptions, command: AddCommand):
    """Add packages to the project manifest and install them.

    Pipeline:
        1. Parse package specs
        2. Write to cpytoml
        3. Resolve + execute (install)
        4. Lock resolved versions
    """
    repos = _get_repos(global_opt)
    packages = command.packages

    if not packages:
        print("No packages specified")
        return

    specs = [PackageSpec.parse(p) for p in packages]
    specs = _expand_groups(specs, repos)
    manifest = read_manifest()

    added = []
    skipped = []
    for spec in specs:
        existing = manifest.get(spec.name)
        if existing:
            if existing.version == spec.version:
                skipped.append(spec.name)
            else:
                manifest.add(spec)
                added.append(f"{spec.name} ({existing.version} -> {spec.version})")
        else:
            manifest.add(spec)
            added.append(str(spec))

    path = write_manifest(manifest)
    print(f"Updated {path}")

    if added:
        print(f"Added: {', '.join(added)}")
    if skipped:
        print(f"Already present: {', '.join(skipped)}")

    to_install = [s for s in specs if s.name not in skipped]
    if to_install and not global_opt.offline:
        print(f"\nInstalling {len(to_install)} package(s)...")
        pkg_tuples = [(s.name, s.version) for s in to_install]
        target = _get_target(manifest)
        llvm_version = global_opt.llvm_version or manifest.llvm_version
        tree = resolve_get(pkg_tuples, repos, target=target, prebuilt=manifest.prebuilt, llvm_version=llvm_version)
        instructions = deduplicator(tree)

        if global_opt.verbose:
            print(f"Instruction stream: {instructions}")

        project_root = manifest.path.parent
        execute(instructions, project_root, repos[0], prebuilt=manifest.prebuilt)

        # Lock resolved versions
        lock = read_lockfile()
        for inst in instructions:
            if "GET" in inst:
                lock.add(_lock_from_instruction(inst))
        write_lockfile(lock)


# ---------------------------------------------------------------------------
# cpm remove
# ---------------------------------------------------------------------------

def remove_deps(global_opt: GlobalOptions, command: RemoveCommand):
    """Remove packages from manifest and filesystem."""
    repos = _get_repos(global_opt)
    packages = command.packages

    manifest = read_manifest()
    specs = [PackageSpec.parse(p) for p in packages]
    specs = _expand_groups(specs, repos)
    pkg_tuples = [(s.name, s.version) for s in specs]

    print(f"Resolving {len(packages)} package(s) for removal...")
    target = _get_target(manifest)
    llvm_version = global_opt.llvm_version or manifest.llvm_version
    tree = resolve_remove(pkg_tuples, repos, target=target, prebuilt=manifest.prebuilt, llvm_version=llvm_version)
    instructions = deduplicator(tree)

    if global_opt.verbose:
        print(f"Instruction stream: {instructions}")

    project_root = manifest.path.parent
    execute(instructions, project_root, repos[0], prebuilt=manifest.prebuilt)

    lock = read_lockfile()
    changed = False

    for spec in specs:
        if manifest.remove(spec.name):
            print(f"  removed {spec.name} from {manifest.path.name if manifest.path else 'cpytoml'}")
            changed = True
        if lock.remove(spec.name):
            print(f"  removed {spec.name} from cpm.lock")
            changed = True

    if changed:
        if manifest.path:
            write_manifest(manifest)
        write_lockfile(lock)


# ---------------------------------------------------------------------------
# cpm install
# ---------------------------------------------------------------------------

def install_deps(global_opt: GlobalOptions, command: InstallCommand):
    """Install dependencies.

    If packages are given, install those specific packages.
    If no packages are given, install everything from cpytoml (uses lockfile).
    """
    repos = _get_repos(global_opt)
    packages = command.packages

    if packages:
        # Specific packages
        specs = [PackageSpec.parse(p) for p in packages]
        specs = _expand_groups(specs, repos)
        pkg_tuples = [(s.name, s.version) for s in specs]

        print(f"Resolving {len(packages)} package(s)...")
        manifest = read_manifest()
        target = _get_target(manifest)
        llvm_version = global_opt.llvm_version or manifest.llvm_version
        tree = resolve_get(pkg_tuples, repos, target=target, prebuilt=manifest.prebuilt, llvm_version=llvm_version)
        instructions = deduplicator(tree)

        if global_opt.verbose:
            print(f"Instruction stream: {instructions}")

        project_root = manifest.path.parent
        execute(instructions, project_root, repos[0], prebuilt=manifest.prebuilt)

        lock = read_lockfile()
        for inst in instructions:
            if "GET" in inst:
                lock.add(_lock_from_instruction(inst))
        write_lockfile(lock)
    else:
        # Install from manifest
        manifest = read_manifest()
        if not manifest.path:
            print("No cpytoml found. Run 'cpm init' first.")
            return

        lock = read_lockfile()
        to_install = []

        expanded_specs = _expand_groups(manifest.packages, repos)
        for spec in expanded_specs:
            locked = lock.get(spec.name)
            if locked:
                to_install.append((locked.name, locked.version))
            else:
                to_install.append((spec.name, spec.version))

        if not to_install:
            print("No packages to install")
            return

        print(f"Installing {len(to_install)} package(s) from manifest...")
        target = _get_target(manifest)
        llvm_version = global_opt.llvm_version or manifest.llvm_version
        tree = resolve_get(to_install, repos, target=target, prebuilt=manifest.prebuilt, llvm_version=llvm_version)
        instructions = deduplicator(tree)

        if global_opt.verbose:
            print(f"Instruction stream: {instructions}")

        project_root = manifest.path.parent
        execute(instructions, project_root, repos[0], prebuilt=manifest.prebuilt)

        for inst in instructions:
            if "GET" in inst:
                lock.add(_lock_from_instruction(inst))
        write_lockfile(lock)


# ---------------------------------------------------------------------------
# cpm update
# ---------------------------------------------------------------------------

def update_deps(global_opt: GlobalOptions, command: UpdateCommand):
    """Update packages to their latest resolved versions.

    Pipeline:
        1. Read manifest
        2. Re-resolve each package to get latest version
        3. Diff against lockfile
        4. Update manifest + lockfile + install
    """
    repos = _get_repos(global_opt)
    packages = command.packages

    manifest = read_manifest()
    if not manifest.path:
        print("No cpytoml found. Run 'cpm init' first.")
        return

    if not packages:
        packages = [str(p) for p in manifest.packages]

    if not packages:
        print("No packages to update")
        return

    print(f"Checking {len(packages)} package(s) for updates...\n")

    updated = []
    up_to_date = []
    failed = []
    lock = read_lockfile()

    for pkg_str in packages:
        spec = PackageSpec.parse(pkg_str)
        name = spec.name

        locked = lock.get(name)
        current_ver = locked.version if locked else spec.version

        try:
            path = _package_path(name)
            metadata = fetch_repo_multi(repos, f"metadata/{path}/latest")
            latest_version = metadata.get("version", "latest")
            latest_url = metadata.get("url", "")

            if current_ver == latest_version:
                up_to_date.append(name)
                continue

            manifest.add(PackageSpec(name=name, version=latest_version))
            updated.append({
                "name": name,
                "old": current_ver,
                "new": latest_version,
                "url": latest_url,
                "checksum": metadata.get("checksum", ""),
            })

        except Exception as e:
            failed.append({"name": name, "error": str(e)})

    if updated:
        print("Updates available:")
        for u in updated:
            print(f"  {u['name']}: {u['old']} -> {u['new']}")

    if up_to_date:
        print(f"\nUp to date: {', '.join(up_to_date)}")

    if failed:
        print("\nFailed to resolve:")
        for f in failed:
            print(f"  {f['name']}: {f['error']}")

    if updated:
        write_manifest(manifest)
        print(f"\nUpdated {manifest.path}")

        if not global_opt.offline:
            print(f"\nInstalling updates...")
            for u in updated:
                if u["url"]:
                    instructions = [{
                        "GET": u["name"],
                        "url": u["url"],
                        "checksum": u["checksum"],
                        "version": u["new"],
                    }]
                    project_root = manifest.path.parent
                    execute(instructions, project_root, repos[0], prebuilt=manifest.prebuilt)
                    lock.add(_lock_from_instruction(instructions[0]))
            write_lockfile(lock)


# ---------------------------------------------------------------------------
# cpm build
# ---------------------------------------------------------------------------

def build_project(global_opt: GlobalOptions, command: BuildCommand):
    """Build the project.

    Looks for build configuration in cpytoml [cpm.build] section.
    Falls back to running 'cpy build' if no custom build is defined.
    """
    manifest = read_manifest()
    if not manifest.path:
        print("No cpytoml found. Run 'cpm init' first.")
        return

    project_dir = manifest.path.parent

    # Check for custom build script in manifest
    # For now, look for a build.py or build script in the project
    build_script = project_dir / "build.py"
    if build_script.exists():
        print(f"Running {build_script}...")
        result = subprocess.run(
            [sys.executable, str(build_script)],
            cwd=str(project_dir),
        )
        if result.returncode != 0:
            print(f"Build failed with exit code {result.returncode}")
            sys.exit(result.returncode)
        return

    # Try cpy compiler
    cpy_bin = shutil.which("cpy")
    if cpy_bin:
        print("Running cpy build...")
        result = subprocess.run(
            [cpy_bin, "build"],
            cwd=str(project_dir),
        )
        if result.returncode != 0:
            print(f"Build failed with exit code {result.returncode}")
            sys.exit(result.returncode)
        return

    print("No build system found.")
    print("Add a [cpm.build] section to cpytoml or create a build.py script.")


# ---------------------------------------------------------------------------
# cpm run
# ---------------------------------------------------------------------------

def run_script(global_opt: GlobalOptions, command: RunCommand):
    """Run a script defined in the project.

    Looks for scripts in cpytoml [cpm.scripts] section.
    """
    script_name = command.script
    args = command.args

    manifest = read_manifest()
    if not manifest.path:
        print("No cpytoml found. Run 'cpm init' first.")
        return

    project_dir = manifest.path.parent

    # Look for the script as a file first
    script_file = project_dir / f"{script_name}.py"
    if script_file.exists():
        print(f"Running {script_file.name}...")
        result = subprocess.run(
            [sys.executable, str(script_file)] + args,
            cwd=str(project_dir),
        )
        if result.returncode != 0:
            sys.exit(result.returncode)
        return

    # Look for script in project .cpm/modules paths
    cpm_modules = project_dir / ".cpm" / "modules"
    if cpm_modules.exists():
        for module_dir in cpm_modules.iterdir():
            if module_dir.is_dir():
                for version_dir in module_dir.iterdir():
                    if version_dir.is_dir():
                        candidate = version_dir / f"{script_name}.py"
                        if candidate.exists():
                            print(f"Running {candidate}...")
                            result = subprocess.run(
                                [sys.executable, str(candidate)] + args,
                                cwd=str(project_dir),
                            )
                            if result.returncode != 0:
                                sys.exit(result.returncode)
                            return

    print(f"Script '{script_name}' not found.")
    print(f"Looked for: {script_file}")


# ---------------------------------------------------------------------------
# cpm publish
# ---------------------------------------------------------------------------

DEFAULT_PUBLISH_SERVER = "https://cypackage.5gnew.io.vn"


def publish_package(global_opt: GlobalOptions, command: PublishCommand):
    """Publish a package to the registry.

    Creates a tar.gz from the directory, computes checksum, and uploads
    to the registry server.
    """
    import hashlib
    import json
    import tempfile
    import tarfile
    from pathlib import Path
    import requests as rq

    server = command.server or global_opt.config or DEFAULT_PUBLISH_SERVER
    package_dir = Path(command.directory).resolve()

    if not package_dir.exists():
        print(f"error: directory not found: {package_dir}")
        return

    # Compute the URL path for the package
    if command.name.startswith("@"):
        name_path = "group/" + command.name[1:]
    else:
        name_path = command.name

    url = f"{server.rstrip('/')}/packages/{name_path}/{command.version}.tar.gz"

    # Build metadata
    meta = {
        "name": command.name,
        "version": command.version,
        "url": url,
        "requires": command.requires,
    }
    if command.prebuilt:
        meta["prebuilt"] = True
        meta["llvm_version"] = command.llvm_version
        meta["cpyte_version"] = command.cpyte_version

    if global_opt.verbose:
        print(f"Publishing {command.name}@{command.version} to {server}")
        print(f"Metadata: {json.dumps(meta, indent=2)}")

    # Create tar.gz
    with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
        with tarfile.open(tmp.name, "w:gz") as tar:
            tar.add(str(package_dir), arcname=package_dir.name)
        archive_path = tmp.name

    try:
        # Compute checksum for display
        sha = hashlib.sha256(open(archive_path, "rb").read()).hexdigest()
        meta["checksum"] = f"sha256:{sha}"

        # Upload
        with open(archive_path, "rb") as f:
            headers = {}
            if command.token:
                headers["Authorization"] = f"Bearer {command.token}"
            resp = rq.post(
                f"{server.rstrip('/')}/publish",
                data={"metadata": json.dumps(meta)},
                files={"archive": (f"{command.version}.tar.gz", f, "application/gzip")},
                headers=headers,
            )

        if resp.status_code == 201:
            result = resp.json()
            print(f"Published {command.name}@{command.version}")
            print(f"Checksum: {result.get('checksum', 'unknown')}")
        else:
            print(f"error: publish failed ({resp.status_code}): {resp.text}")

    finally:
        Path(archive_path).unlink(missing_ok=True)


def unpublish_package(global_opt: GlobalOptions, command: UnpublishCommand):
    """Remove a package version from the registry.

    Unpublishing requires browser-based confirmation:
        1. CLI opens the web UI
        2. User solves a proof-of-work
        3. Confirmation email is sent
        4. User clicks the link to confirm

    Use --all to remove all versions. Use --block to prevent re-publish.
    """
    import webbrowser

    server = command.server or global_opt.config or DEFAULT_PUBLISH_SERVER

    if command.all:
        print(f"To unpublish all versions of {command.name}, visit:")
        print(f"  {server.rstrip('/')}/package/{command.name}/unpublish")
        webbrowser.open(f"{server.rstrip('/')}/package/{command.name}/unpublish")
    elif command.version:
        print(f"To unpublish {command.name}@{command.version}, visit:")
        print(f"  {server.rstrip('/')}/package/{command.name}/unpublish")
        webbrowser.open(f"{server.rstrip('/')}/package/{command.name}/unpublish")
    else:
        print("Specify --pkg-version or --all")


def search_packages(global_opt: GlobalOptions, command: SearchCommand):
    """Search for packages locally and on the registry."""
    import requests as rq

    repos = _get_repos(global_opt)
    query = command.query.lower()

    # Search local installed packages
    local_results = []
    project_root = Path.cwd()
    modules_dir = project_root / ".cpm" / "modules"
    if modules_dir.exists():
        for pkg_dir in modules_dir.rglob("package.toml"):
            try:
                import tomllib
                with open(pkg_dir, "rb") as f:
                    data = tomllib.load(f)
                pkg_name = data.get("package", {}).get("name", "")
                pkg_version = data.get("package", {}).get("version", "")
                if query in pkg_name.lower():
                    local_results.append({"name": pkg_name, "version": pkg_version})
            except Exception:
                pass

    # Search registry
    remote_results = []
    for repo_url in repos:
        try:
            resp = rq.get(f"{repo_url.rstrip('/')}/search", params={"q": command.query}, timeout=10)
            if resp.status_code == 200:
                remote_results = resp.json()
                break
        except Exception as e:
            if global_opt.verbose:
                print(f"Registry search failed on {repo_url}: {e}")

    # Print results
    if local_results:
        print("Local:")
        for r in local_results:
            print(f"  {r['name']}@{r['version']}")

    if remote_results:
        print("Community:")
        for r in remote_results:
            marker = " (installed)" if any(l["name"] == r["name"] for l in local_results) else ""
            print(f"  {r['name']}@{r['latest']} by {r['owner']}{marker}")

    if not local_results and not remote_results:
        print(f"No packages found matching '{command.query}'")
