"""Command handlers for CPM.

Each handler orchestrates the full pipeline for its command:
    manifest read → resolve → lower → optimize → execute → lock
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import style
from .sat import resolve_get, resolve_remove, deduplicator, _package_path
from .executor import execute, _ensure_cache_dir, _module_path
from .manifest import (
    Manifest,
    PackageSpec,
    Target,
    find_manifest,
    read_manifest,
    write_manifest,
    read_package_json,
    PackageJson,
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
from .gethins import find_package_metadata
from cpyte.cli.commands import (
    InstallCommand,
    LocalInstallCommand,
    RemoveCommand,
    AddCommand,
    UpdateCommand,
    InitCommand,
    BuildCommand,
    RunCommand,
    PublishCommand,
    UnpublishCommand,
    SearchCommand,
    InfoCommand,
    ListCommand,
    ValidateCommand,
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
            style.print_info(f"Expanding group {style.print_package(spec.name)}...")
            try:
                packages = fetch_group(repos, spec.name)
                for pkg_name in packages:
                    # Try to get the actual version from the packages list
                    try:
                        pkg_metadata = find_package_metadata(repos, pkg_name)
                        if pkg_metadata:
                            actual_version = pkg_metadata.get("version", "latest")
                            expanded.append(PackageSpec(name=pkg_name, version=actual_version))
                        else:
                            # Fallback to "latest" if we can't find the package
                            expanded.append(PackageSpec(name=pkg_name, version="latest"))
                    except Exception:
                        # Fallback to "latest" if we can't determine version
                        expanded.append(PackageSpec(name=pkg_name, version="latest"))
                style.print_status(f"  Found {len(packages)} package(s)")
            except Exception as e:
                style.print_warning(f"could not fetch group {spec.name}: {e}")
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
        style.print_warning("cpytoml already exists. Use -y to overwrite.")
        return

    project_name = Path.cwd().name
    manifest = Manifest(name=project_name, version="0.1.0", path=manifest_path)
    write_manifest(manifest)
    style.print_success(f"Initialized CPM project: {project_name}")
    style.print_info(f"Created {manifest_path}")


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
        style.print_error("No packages specified")
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
    style.print_info(f"Updated {path}")

    if added:
        style.print_info(f"Added: {', '.join(added)}")
    if skipped:
        style.print_warning(f"Already present: {', '.join(skipped)}")

    to_install = [s for s in specs if s.name not in skipped]
    if to_install and not global_opt.offline:
        style.print_header(f"Installing {len(to_install)} package(s)")
        pkg_tuples = [(s.name, s.version) for s in to_install]
        target = _get_target(manifest)
        llvm_version = global_opt.llvm_version or manifest.llvm_version
        tree = resolve_get(pkg_tuples, repos, target=target, prebuilt=manifest.prebuilt, llvm_version=llvm_version)
        instructions = deduplicator(tree)

        if global_opt.verbose:
            style.print_verbose(f"Instruction stream: {instructions}")

        project_root = manifest.path.parent
        execute(instructions, project_root, repos[0], prebuilt=manifest.prebuilt,
                force=command.force, no_cache=global_opt.no_cache)

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

    style.print_header(f"Resolving {len(packages)} package(s) for removal")
    target = _get_target(manifest)
    llvm_version = global_opt.llvm_version or manifest.llvm_version
    tree = resolve_remove(pkg_tuples, repos, target=target, prebuilt=manifest.prebuilt, llvm_version=llvm_version)
    instructions = deduplicator(tree)

    if global_opt.verbose:
        style.print_verbose(f"Instruction stream: {instructions}")

    project_root = manifest.path.parent
    execute(instructions, project_root, repos[0], prebuilt=manifest.prebuilt)

    lock = read_lockfile()
    changed = False

    for spec in specs:
        if manifest.remove(spec.name):
            style.print_info(f"  removed {spec.name} from {manifest.path.name if manifest.path else 'cpytoml'}")
            changed = True
        if lock.remove(spec.name):
            style.print_info(f"  removed {spec.name} from cpm.lock")
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

        style.print_header(f"Resolving {len(packages)} package(s)")
        manifest = read_manifest()
        target = _get_target(manifest)
        llvm_version = global_opt.llvm_version or manifest.llvm_version
        tree = resolve_get(pkg_tuples, repos, target=target, prebuilt=manifest.prebuilt, llvm_version=llvm_version)
        instructions = deduplicator(tree)

        if global_opt.verbose:
            style.print_verbose(f"Instruction stream: {instructions}")

        project_root = manifest.path.parent
        execute(instructions, project_root, repos[0], prebuilt=manifest.prebuilt,
                force=command.force, no_cache=global_opt.no_cache)

        lock = read_lockfile()
        for inst in instructions:
            if "GET" in inst:
                lock.add(_lock_from_instruction(inst))
        write_lockfile(lock)
    else:
        # Install from manifest
        manifest = read_manifest()
        if not manifest.path:
            style.print_error("No cpytoml found. Run 'cpm init' first.")
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
            style.print_info("No packages to install")
            return

        style.print_header(f"Installing {len(to_install)} package(s) from manifest")
        target = _get_target(manifest)
        llvm_version = global_opt.llvm_version or manifest.llvm_version
        tree = resolve_get(to_install, repos, target=target, prebuilt=manifest.prebuilt, llvm_version=llvm_version)
        instructions = deduplicator(tree)

        if global_opt.verbose:
            style.print_verbose(f"Instruction stream: {instructions}")

        project_root = manifest.path.parent
        execute(instructions, project_root, repos[0], prebuilt=manifest.prebuilt,
                force=command.force, no_cache=global_opt.no_cache)

        for inst in instructions:
            if "GET" in inst:
                lock.add(_lock_from_instruction(inst))
        write_lockfile(lock)


# ---------------------------------------------------------------------------
# cpm install-local
# ---------------------------------------------------------------------------

def install_local_deps(global_opt: GlobalOptions, command: LocalInstallCommand):
    """Install a package from a local directory.

    Pipeline:
        1. Validate local path exists and has package.json
        2. Read package metadata from package.json
        3. Copy directory to .cpm/modules/<name>/<version>/
        4. Update lockfile
    """
    local_path = Path(command.path).resolve()

    if not local_path.exists():
        style.print_error(f"Path does not exist: {local_path}")
        return

    if not local_path.is_dir():
        style.print_error(f"Path is not a directory: {local_path}")
        return

    # Read package.json from the local directory
    package_json_path = local_path / "package.json"
    if not package_json_path.exists():
        style.print_error(f"No package.json found in {local_path}")
        return

    try:
        import json
        with open(package_json_path, "r") as f:
            pkg_data = json.load(f)
    except Exception as e:
        style.print_error(f"Failed to read package.json: {e}")
        return

    name = pkg_data.get("name", "")
    version = pkg_data.get("version", "")

    if not name:
        style.print_error("package.json is missing 'name' field")
        return

    if not version:
        style.print_error("package.json is missing 'version' field")
        return

    # Find or create manifest
    manifest_path = find_manifest()
    if manifest_path:
        manifest = read_manifest(manifest_path)
        project_root = manifest_path.parent
    else:
        # Create a minimal manifest
        project_root = Path.cwd()
        manifest = Manifest(name=project_root.name, version="0.1.0", path=project_root / "cpytoml")

    # Target directory
    target = _module_path(project_root, name, version)

    if target.exists() and not command.force:
        style.print_already_installed(name, version)
        return

    # Copy the local directory
    style.print_header(f"Installing {style.print_package(name, version)} from local directory")

    if target.exists():
        shutil.rmtree(target)

    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(local_path, target)

    style.print_installed(name, version, "local")

    # Update lockfile
    lock = read_lockfile()
    lock_entry = LockEntry(
        name=name,
        version=version,
        resolved=f"file://{local_path}",
        checksum="",
        dependencies=[],
    )
    lock.add(lock_entry)
    write_lockfile(lock)

    # Optionally add to manifest
    if manifest_path:
        manifest.add(PackageSpec(name=name, version=version))
        write_manifest(manifest)
        style.print_info(f"Added {name}@{version} to {manifest_path.name}")


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
        style.print_error("No cpytoml found. Run 'cpm init' first.")
        return

    if not packages:
        packages = [str(p) for p in manifest.packages]

    if not packages:
        style.print_info("No packages to update")
        return

    style.print_header(f"Checking {len(packages)} package(s) for updates")

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
        style.print_header("Updates available")
        for u in updated:
            style.print_info(f"  {style.print_package(u['name'])}: {u['old']} -> {style.print_package(u['name'], u['new'])}")

    if up_to_date:
        style.print_info(f"\nUp to date: {', '.join(up_to_date)}")

    if failed:
        style.print_header("Failed to resolve")
        for f in failed:
            style.print_error(f"  {f['name']}: {f['error']}")

    if updated:
        write_manifest(manifest)
        style.print_info(f"\nUpdated {manifest.path}")

        if not global_opt.offline:
            style.print_header("Installing updates")
            all_instructions = []
            for u in updated:
                if u["url"]:
                    instructions = [{
                        "GET": u["name"],
                        "url": u["url"],
                        "checksum": u["checksum"],
                        "version": u["new"],
                    }]
                    all_instructions.extend(instructions)
                    lock.add(_lock_from_instruction(instructions[0]))
            if all_instructions:
                project_root = manifest.path.parent
                execute(all_instructions, project_root, repos[0], prebuilt=manifest.prebuilt,
                        force=False, no_cache=global_opt.no_cache)
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
        style.print_error("No cpytoml found. Run 'cpm init' first.")
        return

    project_dir = manifest.path.parent

    # Check for custom build script in manifest
    # For now, look for a build.py or build script in the project
    build_script = project_dir / "build.py"
    if build_script.exists():
        style.print_info(f"Running {build_script}...")
        result = subprocess.run(
            [sys.executable, str(build_script)],
            cwd=str(project_dir),
        )
        if result.returncode != 0:
            style.print_error(f"Build failed with exit code {result.returncode}")
            sys.exit(result.returncode)
        return

    # Try cpy compiler
    cpy_bin = shutil.which("cpy")
    if cpy_bin:
        style.print_info("Running cpy build...")
        result = subprocess.run(
            [cpy_bin, "build"],
            cwd=str(project_dir),
        )
        if result.returncode != 0:
            style.print_error(f"Build failed with exit code {result.returncode}")
            sys.exit(result.returncode)
        return

    style.print_warning("No build system found.")
    style.print_info("Add a [cpm.build] section to cpytoml or create a build.py script.")


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
        style.print_error("No cpytoml found. Run 'cpm init' first.")
        return

    project_dir = manifest.path.parent

    # Look for the script as a file first
    script_file = project_dir / f"{script_name}.py"
    if script_file.exists():
        style.print_info(f"Running {script_file.name}...")
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
                            style.print_info(f"Running {candidate}...")
                            result = subprocess.run(
                                [sys.executable, str(candidate)] + args,
                                cwd=str(project_dir),
                            )
                            if result.returncode != 0:
                                sys.exit(result.returncode)
                            return

    style.print_error(f"Script '{script_name}' not found.")
    style.print_info(f"Looked for: {script_file}")


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
        style.print_error(f"directory not found: {package_dir}")
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
        style.print_verbose(f"Publishing {command.name}@{command.version} to {server}")
        style.print_verbose(f"Metadata: {json.dumps(meta, indent=2)}")

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
            style.print_success(f"Published {command.name}@{command.version}")
            style.print_info(f"Checksum: {result.get('checksum', 'unknown')}")
        else:
            style.print_error(f"publish failed ({resp.status_code}): {resp.text}")

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
        style.print_info(f"To unpublish all versions of {command.name}, visit:")
        style.print_info(f"  {server.rstrip('/')}/package/{command.name}/unpublish")
        webbrowser.open(f"{server.rstrip('/')}/package/{command.name}/unpublish")
    elif command.version:
        style.print_info(f"To unpublish {command.name}@{command.version}, visit:")
        style.print_info(f"  {server.rstrip('/')}/package/{command.name}/unpublish")
        webbrowser.open(f"{server.rstrip('/')}/package/{command.name}/unpublish")
    else:
        style.print_error("Specify --pkg-version or --all")


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
                style.print_warning(f"Registry search failed on {repo_url}: {e}")

    # Print results
    if local_results:
        style.print_header("Local")
        for r in local_results:
            style.print_info(f"  {style.print_package(r['name'], r['version'])}")

    if remote_results:
        style.print_header("Community")
        for r in remote_results:
            marker = " (installed)" if any(l["name"] == r["name"] for l in local_results) else ""
            style.print_info(f"  {style.print_package(r['name'], r['latest'])} by {r['owner']}{marker}")

    if not local_results and not remote_results:
        style.print_warning(f"No packages found matching '{command.query}'")


# ---------------------------------------------------------------------------
# cpm info
# ---------------------------------------------------------------------------

def show_package_info(global_opt: GlobalOptions, command: InfoCommand):
    """Show detailed information about a package."""
    if not command.package:
        style.print_error("package name required")
        style.print_info("Usage: cpm info <package>")
        return

    repos = _get_repos(global_opt)
    spec = PackageSpec.parse(command.package)
    
    style.print_header(f"Package: {style.print_package(spec.name)}")
    style.print_info(f"Version: {spec.version}")
    
    try:
        metadata = find_package_metadata(repos, spec.name)
        if metadata:
            style.print_header("Registry Metadata")
            style.print_info(f"  Latest version: {metadata.get('version', 'unknown')}")
            style.print_info(f"  URL: {metadata.get('url', 'unknown')}")
            
            claims = metadata.get('claims', {})
            if claims:
                style.print_info("  Platform claims:")
                if 'os' in claims:
                    style.print_info(f"    OS: {claims['os']}")
                if 'arch' in claims:
                    style.print_info(f"    Arch: {claims['arch']}")
                if 'features' in claims:
                    style.print_info(f"    Features: {claims['features']}")
            
            requires = metadata.get('requires', [])
            if requires:
                style.print_info("  Dependencies:")
                for dep in requires:
                    style.print_info(f"    - {dep}")
            
            if metadata.get('no_download'):
                style.print_info("  Note: Metadata-only package (no downloadable content)")
        else:
            style.print_warning("Package not found in registry")
    except Exception as e:
        style.print_error(f"fetching package info: {e}")
        if global_opt.verbose:
            import traceback
            traceback.print_exc()
    
    # Check for package.json in installed packages
    manifest_path = find_manifest()
    if manifest_path:
        project_root = manifest_path.parent
        modules_dir = project_root / ".cpm" / "modules"
        
        # Try to find the package in installed modules
        package_dir = modules_dir / spec.name
        if package_dir.exists():
            # Find the latest version
            versions = [d for d in package_dir.iterdir() if d.is_dir()]
            if versions:
                latest_version_dir = sorted(versions, reverse=True)[0]
                package_json = read_package_json(latest_version_dir)
                
                if package_json:
                    style.print_header("Extension Capabilities")
                    if package_json.capabilities.keywords:
                        style.print_info(f"  Keywords: {', '.join(sorted(package_json.capabilities.keywords))}")
                    if package_json.capabilities.operators:
                        style.print_info(f"  Operators: {', '.join(sorted(package_json.capabilities.operators))}")
                    if package_json.capabilities.tags:
                        style.print_info(f"  Tags: {', '.join(sorted(package_json.capabilities.tags))}")
                    if package_json.capabilities.macros:
                        style.print_info(f"  Macros: {', '.join(sorted(package_json.capabilities.macros))}")
                    if package_json.capabilities.custom_types:
                        style.print_info(f"  Custom Types: {', '.join(sorted(package_json.capabilities.custom_types))}")
                    
                    if package_json.extensions.parser_hooks or package_json.extensions.semantic_hooks or \
                       package_json.extensions.codegen_hooks or package_json.extensions.runtime_hooks:
                        style.print_info("  Extension Hooks:")
                        if package_json.extensions.parser_hooks:
                            style.print_info(f"    Parser: {', '.join(package_json.extensions.parser_hooks)}")
                        if package_json.extensions.semantic_hooks:
                            style.print_info(f"    Semantic: {', '.join(package_json.extensions.semantic_hooks)}")
                        if package_json.extensions.codegen_hooks:
                            style.print_info(f"    Codegen: {', '.join(package_json.extensions.codegen_hooks)}")
                        if package_json.extensions.runtime_hooks:
                            style.print_info(f"    Runtime: {', '.join(package_json.extensions.runtime_hooks)}")
                    
                    if package_json.metadata:
                        style.print_info("  Metadata:")
                        for key, value in package_json.metadata.items():
                            style.print_info(f"    {key}: {value}")


# ---------------------------------------------------------------------------
# cpm list
# ---------------------------------------------------------------------------

def list_installed_packages(global_opt: GlobalOptions, command: ListCommand):
    """List all installed packages in the current project."""
    manifest_path = find_manifest()
    if not manifest_path:
        style.print_error("No cpytoml found. Are you in a CPM project?")
        return
    
    project_root = manifest_path.parent
    modules_dir = project_root / ".cpm" / "modules"
    
    lock = read_lockfile()
    if lock and lock.entries:
        style.print_header("Installed packages (from lockfile)")
        for entry in lock.entries:
            installed_path = modules_dir / entry.name / entry.version
            status = f"{style.Color.GREEN}ok{style.Color.RESET}" if installed_path.exists() else f"{style.Color.RED}missing{style.Color.RESET}"
            style.print_info(f"  [{status}] {style.print_package(entry.name, entry.version)}")
            if entry.dependencies:
                for dep in entry.dependencies:
                    style.print_info(f"      - {dep}")
    else:
        style.print_warning("No lockfile found or lockfile is empty")
        if modules_dir.exists():
            style.print_header("Installed packages (from filesystem)")
            for pkg_dir in sorted(modules_dir.iterdir()):
                if pkg_dir.is_dir():
                    for version_dir in sorted(pkg_dir.iterdir()):
                        if version_dir.is_dir():
                            style.print_info(f"  {style.print_package(pkg_dir.name, version_dir.name)}")
        else:
            style.print_info("No packages installed")


# ---------------------------------------------------------------------------
# cpm validate
# ---------------------------------------------------------------------------

def validate_manifest(global_opt: GlobalOptions, command: ValidateCommand):
    """Validate the project manifest and lockfile."""
    manifest_path = find_manifest()
    if not manifest_path:
        style.print_error("No cpytoml found. Are you in a CPM project?")
        return
    
    style.print_header(f"Validating {manifest_path}")
    
    try:
        manifest = read_manifest(manifest_path)
        style.print_success("Manifest is valid TOML")
        
        # Check manifest fields
        if not manifest.name:
            style.print_warning("Project name is empty")
        if not manifest.version:
            style.print_warning("Project version is empty")
        
        # Check dependencies
        if manifest.packages:
            style.print_success(f"Found {len(manifest.packages)} dependencies")
            for pkg in manifest.packages:
                style.print_info(f"  - {style.print_package(pkg.name, pkg.version)}")
                
                # Check for package.json in installed packages
                project_root = manifest_path.parent
                modules_dir = project_root / ".cpm" / "modules"
                package_dir = modules_dir / pkg.name
                
                if package_dir.exists():
                    versions = [d for d in package_dir.iterdir() if d.is_dir()]
                    if versions:
                        latest_version_dir = sorted(versions, reverse=True)[0]
                        package_json = read_package_json(latest_version_dir)
                        
                        if package_json:
                            style.print_success(f"    Extension package with capabilities")
                            if package_json.capabilities.keywords:
                                style.print_info(f"      Keywords: {', '.join(sorted(package_json.capabilities.keywords))}")
        else:
            style.print_info("  No dependencies declared")
        
        # Check lockfile
        lockfile_path = find_lockfile()
        if lockfile_path:
            style.print_success(f"Lockfile found: {lockfile_path}")
            lock = read_lockfile(lockfile_path)
            if lock.entries:
                style.print_success(f"Lockfile contains {len(lock.entries)} entries")
            else:
                style.print_warning("Lockfile is empty")
        else:
            style.print_warning("No lockfile found. Run 'cpm install' to create one.")
        
        # Check target platform
        if manifest.target.os or manifest.target.arch:
            style.print_success(f"Target platform: {manifest.target.os or 'auto'}/{manifest.target.arch or 'auto'}")
        
        style.print_success("\nValidation complete")
        
    except Exception as e:
        style.print_error(f"validation failed: {e}")
        if global_opt.verbose:
            import traceback
            traceback.print_exc()
