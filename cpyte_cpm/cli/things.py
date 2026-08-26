"""Command handlers for CPM.

Each handler orchestrates the full pipeline for its command:
    manifest read → resolve → lower → optimize → execute → lock
"""

import json
import re
import shutil
import stat as stat_mod
import subprocess
import sys
from pathlib import Path

from .errors import CLIError
from cpyte_cpm.cli.commands import (
    AddCommand,
    BuildCommand,
    DoctorCommand,
    ExecCommand,
    GlobalOptions,
    InfoCommand,
    InitCommand,
    InstallCommand,
    ListCommand,
    LocalInstallCommand,
    LoginCommand,
    LogoutCommand,
    PublishCommand,
    RemoveCommand,
    RunCommand,
    SearchCommand,
    SefCommand,
    UnpublishCommand,
    UpdateCommand,
    ValidateCommand,
)

from .. import compiler as cpyte_toolchain
from . import auth as auth_store
from . import style
from .executor import _bin_dir, _module_path, _shim_body, execute, register_bins
from .gethins import fetch_group, fetch_repo_multi, find_package_metadata
from .lockfile import (
    LockEntry,
    find_lockfile,
    read_lockfile,
    write_lockfile,
)
from .manifest import (
    MANIFEST_NAME,
    Manifest,
    PackageSpec,
    Target,
    find_manifest,
    read_manifest,
    read_package_json,
    write_manifest,
)
from .sat import (
    _package_path,
    _version_satisfies,
    deduplicator,
    resolve_get,
    resolve_remove,
)

DEFAULT_REPO = "https://cypackage.5gnew.io.vn"
DEVICE_POLL_INTERVAL = 3          # seconds between polls
DEVICE_TIMEOUT = 15 * 60          # give up after 15 minutes


def _is_local_path(spec: str) -> bool:
    """Check if a package spec is a local filesystem path."""
    if not spec:
        return False
    # Absolute paths
    if spec.startswith("/"):
        return True
    # Home directory
    if spec.startswith("~"):
        return True
    # Relative paths (./ or ../)
    if spec.startswith("./") or spec.startswith("../"):
        return True
    # Check if it's an existing directory
    p = Path(spec)
    if p.exists() and p.is_dir():
        return True
    return False


def _route_local_packages(packages: list[str]) -> tuple[list[str], list[str]]:
    """Split packages into registry packages and local paths.
    
    Returns (registry_specs, local_paths).
    """
    registry = []
    local = []
    for pkg in packages:
        if _is_local_path(pkg):
            local.append(pkg)
        else:
            registry.append(pkg)
    return registry, local


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
        # Scorpion (RISC-V) shorthand targets
        if target_str in ("scorpion", "riscv32", "riscv32-unknown-elf"):
            return Target(os="scorpion", arch="riscv32")
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
        sef=bool(inst.get("sef")),
    )


def _compiler_pin(prebuilt: bool) -> str:
    """Return the detected Cpyte compiler version for prebuilt installs."""
    if not prebuilt:
        return ""
    return cpyte_toolchain.get_cpyte_version()


# ---------------------------------------------------------------------------
# cpm sef
# ---------------------------------------------------------------------------

def sef_tool(global_opt: GlobalOptions, command: SefCommand):
    """Scorpion SEF binary tools (pack/dump/check/size).

    Delegates to the Cpyte compiler's `cpy sef` subcommands so CPM and the
    compiler always agree on the SEF binary format.
    """
    if not command.subcommand:
        style.print_error("Usage: cpm sef <pack|dump|check|size> [args...]")
        style.print_info("e.g.  cpm sef check out/main.sef")
        return

    toolchain = cpyte_toolchain.detect_compiler()
    if not toolchain.available:
        style.print_error("Cpyte compiler not detected. Run 'cpm doctor' for details.")
        return

    result = cpyte_toolchain.run_compiler(["sef", command.subcommand] + command.args)
    sys.exit(result.returncode)


# ---------------------------------------------------------------------------
# cpm init
# ---------------------------------------------------------------------------

def init_project(global_opt: GlobalOptions, command: InitCommand):
    """Initialize a new CPM project.

    Creates cpy.toml in the current directory with a full template.
    """
    manifest_path = Path.cwd() / MANIFEST_NAME

    if manifest_path.exists() and not global_opt.yes:
        style.print_warning("cpy.toml already exists. Use -y to overwrite.")
        return

    project_name = Path.cwd().name
    manifest = Manifest(
        name=project_name,
        version="0.1.0",
        path=manifest_path,
    )
    write_manifest(manifest)

    # Append informative comments to the generated file
    with open(manifest_path, "a") as f:
        f.write("""
# [cpm.dependencies]
# "@std/json" = "^1.0"
# "@std/http" = "1.0"

# [cpm.target]
# os = "linux"
# arch = "x86_64"
# features = ["gui", "ssl"]

# [cpm.dependencies.windows]
# "win32-api" = "1.0"

# [cpm.dependencies.linux]
# "posix-api" = "1.0"

# Set scorpion = true to also pre-compile a .sef (Scorpion RISC-V) artifact
# on every build:  scorpion = true
#
# Set sef = true to install SEF artifacts from the registry instead of source:
#   sef = true
#
# [cpm.build]
# pic = true               # dynamic SEF v2 (PIC + relocations); default true
# exports = ["bigint_add"] # library symbols to mark as exported
""")

    style.print_success(f"Initialized CPM project: {project_name}")
    style.print_info(f"Created {manifest_path}")


# ---------------------------------------------------------------------------
# cpm add
# ---------------------------------------------------------------------------

def add_deps(global_opt: GlobalOptions, command: AddCommand):
    """Add packages to the project manifest and install them.

    Pipeline:
        1. Parse package specs
        2. Write to cpy.toml
        3. Resolve + execute (install)
        4. Lock resolved versions
    """
    repos = _get_repos(global_opt)
    packages = command.packages

    if not packages:
        style.print_error("No packages specified")
        return

    # Route local paths
    registry_pkgs, local_paths = _route_local_packages(packages)
    
    # Handle local packages first
    for path in local_paths:
        install_local_deps(global_opt, LocalInstallCommand(path=path, force=command.force))

    # Handle registry packages
    if not registry_pkgs:
        return

    specs = [PackageSpec.parse(p) for p in registry_pkgs]
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
        tree = resolve_get(pkg_tuples, repos, target=target, prebuilt=manifest.prebuilt, llvm_version=llvm_version, cpyte_version=_compiler_pin(manifest.prebuilt), capabilities=cpyte_toolchain.toolchain_capabilities())
        instructions = deduplicator(tree)

        if global_opt.verbose:
            style.print_verbose(f"Instruction stream: {instructions}")

        project_root = manifest.path.parent
        execute(instructions, project_root, repos[0], prebuilt=manifest.prebuilt,
                force=command.force, no_cache=global_opt.no_cache, sef=manifest.sef)

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
            style.print_info(f"  removed {spec.name} from {manifest.path.name if manifest.path else MANIFEST_NAME}")
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
    If no packages are given, install everything from cpy.toml (uses lockfile).
    """
    repos = _get_repos(global_opt)
    packages = command.packages

    if packages:
        # Route local paths
        registry_pkgs, local_paths = _route_local_packages(packages)

        # Handle local packages first
        for path in local_paths:
            install_local_deps(global_opt, LocalInstallCommand(path=path, force=command.force))

        if not registry_pkgs:
            return

        # Specific packages from registry
        specs = [PackageSpec.parse(p) for p in registry_pkgs]
        specs = _expand_groups(specs, repos)
        pkg_tuples = [(s.name, s.version) for s in specs]

        style.print_header(f"Resolving {len(packages)} package(s)")
        manifest = read_manifest()
        target = _get_target(manifest)
        llvm_version = global_opt.llvm_version or manifest.llvm_version
        tree = resolve_get(pkg_tuples, repos, target=target, prebuilt=manifest.prebuilt, llvm_version=llvm_version, cpyte_version=_compiler_pin(manifest.prebuilt), capabilities=cpyte_toolchain.toolchain_capabilities())
        instructions = deduplicator(tree)

        if global_opt.verbose:
            style.print_verbose(f"Instruction stream: {instructions}")

        project_root = manifest.path.parent
        execute(instructions, project_root, repos[0], prebuilt=manifest.prebuilt,
                force=command.force, no_cache=global_opt.no_cache, sef=manifest.sef)

        lock = read_lockfile()
        for inst in instructions:
            if "GET" in inst:
                lock.add(_lock_from_instruction(inst))
        write_lockfile(lock)
    else:
        # Install from manifest
        manifest = read_manifest()
        if not manifest.path:
            style.print_error("No cpy.toml found. Run 'cpm init' first.")
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
        tree = resolve_get(to_install, repos, target=target, prebuilt=manifest.prebuilt, llvm_version=llvm_version, cpyte_version=_compiler_pin(manifest.prebuilt), capabilities=cpyte_toolchain.toolchain_capabilities())
        instructions = deduplicator(tree)

        if global_opt.verbose:
            style.print_verbose(f"Instruction stream: {instructions}")

        project_root = manifest.path.parent
        execute(instructions, project_root, repos[0], prebuilt=manifest.prebuilt,
                force=command.force, no_cache=global_opt.no_cache, sef=manifest.sef)

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
        manifest = Manifest(name=project_root.name, version="0.1.0", path=project_root / MANIFEST_NAME)

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

    # Register CLI launchers declared in package.json
    registered = register_bins(project_root, name, version, module_dir=target)
    if registered:
        bin_dir = _bin_dir(project_root)
        style.print_info(
            f"Registered CLI tools: {', '.join(registered)}\n"
            f'  Add to PATH: export PATH="$PATH:{bin_dir}"')

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
        style.print_error("No cpy.toml found. Run 'cpm init' first.")
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
                        "sef": True if manifest.sef else False,
                    }]
                    all_instructions.extend(instructions)
                    lock.add(_lock_from_instruction(instructions[0]))
            if all_instructions:
                project_root = manifest.path.parent
                execute(all_instructions, project_root, repos[0], prebuilt=manifest.prebuilt,
                        force=False, no_cache=global_opt.no_cache, sef=manifest.sef)
            write_lockfile(lock)


# ---------------------------------------------------------------------------
# cpm build
# ---------------------------------------------------------------------------

def build_project(global_opt: GlobalOptions, command: BuildCommand):
    """Build the project.

    Prefers the Cpyte compiler. Falls back to build.py for custom builds.
    """
    manifest = read_manifest()
    if not manifest.path:
        style.print_error("No cpy.toml found. Run 'cpm init' first.")
        return

    project_dir = manifest.path.parent

    # Toolchain check first — building is meaningless without the compiler
    toolchain = cpyte_toolchain.detect_compiler()
    if not toolchain.available:
        style.print_error("Cpyte compiler not detected.")
        if toolchain.binary_error:
            style.print_warning(f"  {toolchain.binary_error}")
        style.print_info("  Install the compiler: pip install cpyte  (or run 'cpm doctor')")
        return

    style.print_info(
        f"  Using {style.Color.BOLD_CYAN}cpyte {toolchain.version}{style.Color.RESET}"
        f"{f' (LLVM {toolchain.llvm_version})' if toolchain.llvm_version else ''}"
    )

    # Custom build script wins
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
        style.print_success("Build complete")
        return

    # Find the project entry point
    entry = _find_project_entry(project_dir, manifest.name)
    if manifest.build.main:
        entry = project_dir / manifest.build.main
    if entry is None:
        style.print_warning("No entry point found (looked for main.cpy, <project>.cpy, src/main.cpy).")
        style.print_info("Add a [cpm.build] section to cpy.toml or create a build.py script.")
        _register_project_bins(project_dir, manifest)
        return

    style.print_header(f"Building {entry.name}")
    compiler_args = ["build", str(entry)]
    if command.opt:
        compiler_args += ["--opt", "2"]
    if command.osize:
        compiler_args.append("--osize")
    if command.debug:
        compiler_args.append("--debug")
    if command.lto:
        compiler_args.append("--lto")
    result = cpyte_toolchain.run_compiler(compiler_args, cwd=project_dir)
    if result.returncode != 0:
        style.print_error(f"Build failed with exit code {result.returncode}")
        sys.exit(result.returncode)
    style.print_success("Build complete")

    # Scorpion-ready projects also pre-compile a .sef artifact
    if command.scorpion or manifest.scorpion:
        style.print_header(f"Scorpion (RISC-V) build for {entry.name}")
        with style.Spinner("cross-compiling to SEF"):
            sef_rc, sef_path = cpyte_toolchain.emit_scorpion(
                entry,
                cwd=project_dir,
                pic=manifest.build.pic,
                exports=manifest.build.exports or None,
            )
        if sef_rc != 0:
            style.print_error(f"Scorpion build failed with exit code {sef_rc}")
            style.print_warning("Install the RISC-V toolchain (riscv*-elf-gcc) to cross-compile.")
            sys.exit(sef_rc)
        if sef_path.exists():
            style.print_success(f"Wrote {sef_path.name}")
        else:
            style.print_error(f"Expected SEF at {sef_path} but it was not produced")
            sys.exit(1)

    # Register project CLI tools declared in [cpm.bin]
    _register_project_bins(project_dir, manifest)


def _register_project_bins(project_dir: Path, manifest) -> None:
    """Create launchers in .cpm/bin for the project's own [cpm.bin] entries."""
    if not manifest.bin:
        return
    registered = []
    for tool, rel in manifest.bin.items():
        target = (project_dir / rel).resolve()
        if not target.exists():
            style.print_warning(f"[cpm.bin] '{tool}': target not found: {rel}")
            continue
        shim_dir = _bin_dir(project_dir)
        shim_dir.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", tool)
        shim = shim_dir / safe
        shim.write_text(_shim_body(manifest.name, manifest.version, safe, target, rel))
        shim.chmod(0o755)
        registered.append(safe)
    if registered:
        style.print_info(
            f"Registered CLI tools: {', '.join(registered)}\n"
            f'  Add to PATH: export PATH="$PATH:{_bin_dir(project_dir)}"')


def _find_project_entry(project_dir: Path, project_name: str) -> Path | None:
    """Locate the project's main .cpy entry point."""
    candidates = [
        project_dir / "main.cpy",
        project_dir / f"{project_name}.cpy",
        project_dir / "src" / "main.cpy",
        project_dir / "src" / f"{project_name}.cpy",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


# ---------------------------------------------------------------------------
# cpm run
# ---------------------------------------------------------------------------

def run_script(global_opt: GlobalOptions, command: RunCommand):
    """Run a script defined in the project.

    Resolution order:
        1. <script>.py — plain Python helper
        2. <script>.cpy — Cpyte source (compiled via the Cpyte compiler JIT)
        3. .cpm/modules/**/<script>.py / <script>.cpy
    """
    script_name = command.script
    args = command.args

    manifest = read_manifest()
    if not manifest.path:
        style.print_error("No cpy.toml found. Run 'cpm init' first.")
        return

    project_dir = manifest.path.parent

    # Look for the script as a Python file first
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

    # Then as a Cpyte source file
    cpy_file = project_dir / f"{script_name}.cpy"
    if cpy_file.exists():
        _run_cpy_file(cpy_file, args)
        return

    # Look for scripts in project .cpm/modules paths
    cpm_modules = project_dir / ".cpm" / "modules"
    if cpm_modules.exists():
        for module_dir in cpm_modules.iterdir():
            if module_dir.is_dir():
                for version_dir in module_dir.iterdir():
                    if version_dir.is_dir():
                        for ext in (".py", ".cpy"):
                            candidate = version_dir / f"{script_name}{ext}"
                            if candidate.exists():
                                if ext == ".py":
                                    style.print_info(f"Running {candidate}...")
                                    result = subprocess.run(
                                        [sys.executable, str(candidate)] + args,
                                        cwd=str(project_dir),
                                    )
                                    if result.returncode != 0:
                                        sys.exit(result.returncode)
                                    return
                                _run_cpy_file(candidate, args)
                                return

    style.print_error(f"Script '{script_name}' not found.")
    style.print_info(f"Looked for: {script_file}")


# ---------------------------------------------------------------------------
# cpm exec
# ---------------------------------------------------------------------------

def exec_cpy(global_opt: GlobalOptions, command: ExecCommand):
    """Execute a .cpy file with the Cpyte compiler."""
    source = Path(command.file).resolve()
    if not source.exists():
        style.print_error(f"File not found: {source}")
        return
    if source.suffix != ".cpy":
        style.print_warning(f"'{source.name}' is not a .cpy file")

    toolchain = cpyte_toolchain.detect_compiler()
    if not toolchain.available:
        style.print_error("Cpyte compiler not detected. Run 'cpm doctor' for details.")
        return

    style.print_info(
        f"  Executing {style.Color.BOLD_CYAN}{source.name}{style.Color.RESET} "
        f"with cpyte {toolchain.version}"
    )
    _run_cpy_file(source, command.args)


def _run_cpy_file(source: Path, args: list[str]) -> None:
    """Run a .cpy file through the Cpyte compiler JIT."""
    code = cpyte_toolchain.run_cpy(source, args)
    if code != 0:
        style.print_error(f"Execution failed with exit code {code}")
        sys.exit(code)


# ---------------------------------------------------------------------------
# cpm doctor
# ---------------------------------------------------------------------------

def doctor_project(global_opt: GlobalOptions, command: DoctorCommand):
    """Diagnose the Cpyte toolchain and the current project."""
    style.banner(title="Toolchain Diagnostics")

    report = cpyte_toolchain.diagnose()
    compiler = report["compiler"]

    style.box("Cpyte Compiler", [
        f"  detected   : {style.Color.GREEN}yes{style.Color.RESET}" if compiler["detected"]
        else f"  detected   : {style.Color.RED}no{style.Color.RESET}",
        f"  version    : {style.Color.BOLD}{compiler['version'] or '-'}{style.Color.RESET}",
        f"  binary     : {compiler['binary'] or '-'}",
        f"  module     : {compiler['module_path'] or '-'}",
        f"  llvm       : {report['llvm_version'] or '-'}",
    ])

    codegen = report.get("codegen")
    if codegen:
        lines = []
        for feature, ok in codegen.items():
            mark = f"{style.Color.GREEN}ok{style.Color.RESET}" if ok else f"{style.Color.RED}missing{style.Color.RESET}"
            lines.append(f"  {feature:14} {mark}")
        style.box("Codegen Features", lines)

    if not compiler["detected"]:
        if compiler["module_error"]:
            style.print_warning(f"  python import failed: {compiler['module_error']}")
        if compiler["binary_error"]:
            style.print_warning(f"  {compiler['binary_error']}")
        style.print_info("  Install: pip install cpyte")

    ws = report["workspace"]
    style.box("Project", [
        f"  name       : {ws['project'] or '-'}",
        f"  manifest   : {ws['manifest'] or '-'}",
        f"  .cpm dir   : {style.Color.GREEN}present{style.Color.RESET}" if ws["cpm_dir"]
        else f"  .cpm dir   : {style.Color.DIM}absent (run 'cpm install'){style.Color.RESET}",
    ])

    if compiler["detected"]:
        style.print_success("Toolchain looks good")
    else:
        style.print_error("Toolchain is incomplete — install the Cpyte compiler")


# ---------------------------------------------------------------------------
# cpm login / logout (device code flow)
# ---------------------------------------------------------------------------

def _resolve_server(global_opt: GlobalOptions, explicit: str = "") -> str:
    """Pick the registry server: CLI flag > stored default > DEFAULT_REPO."""
    if explicit:
        return explicit.rstrip("/")
    creds = auth_store.load_credentials()
    if creds:
        return creds.server
    if global_opt.server:
        return global_opt.server[0].rstrip("/")
    return DEFAULT_REPO


def login_device(global_opt: GlobalOptions, command: LoginCommand):
    """Log in to a registry using the device code flow.

    1. Ask the registry for a short human-readable code
    2. Open the browser at the verification URL
    3. Poll until the user approves (or denies / code expires)
    4. Store the returned API token locally
    """
    import time
    import webbrowser

    import requests as rq

    # NOTE: --server is a global option, so it lands in global_opt.server
    server = command.server or (global_opt.server[0] if global_opt.server else "") \
        or global_opt.config or ""
    if not server:
        creds = auth_store.load_credentials()
        server = creds.server if creds else DEFAULT_REPO
    server = server.rstrip("/")

    style.print_header(f"Logging in to {server}")

    try:
        resp = rq.post(f"{server}/auth/device/start", timeout=15)
    except Exception as exc:
        style.print_error(f"Cannot reach {server}: {exc}")
        sys.exit(1)
    if resp.status_code != 200:
        style.print_error(f"Registry does not support device login ({resp.status_code})")
        style.print_info("Update the registry server to the latest version.")
        sys.exit(1)

    data = resp.json()
    code = data["code"]
    verify_url = data.get("verify_url") or f"{server}/auth/device?code={code}"
    expires_in = int(data.get("expires_in", 900))

    style.print_info("To approve this login, open:")
    style.print_info(f"  {verify_url}")
    print()
    style.print_info("Or enter this code manually:")
    print(style.Color.BOLD_CYAN + f"  {code}" + style.Color.RESET)
    print()

    try:
        webbrowser.open(verify_url)
    except Exception:
        pass

    interval = max(1, int(data.get("interval", DEVICE_POLL_INTERVAL)))
    deadline = time.time() + min(expires_in, DEVICE_TIMEOUT) + 5

    with style.Spinner("waiting for approval"):
        while time.time() < deadline:
            try:
                poll = rq.post(
                    f"{server}/auth/device/poll",
                    json={"code": code},
                    timeout=10,
                )
            except Exception:
                time.sleep(interval)
                continue
            body = poll.json() if poll.status_code in (200, 400) else {}
            status = body.get("status", "")
            if poll.status_code == 200 and status == "approved":
                token = body["token"]
                email = body.get("email", "")
                path = auth_store.save_credentials(server, token, email)
                style.print_success(f"Logged in as {email}" if email else "Logged in")
                style.print_info(f"Credentials saved to {path}")
                return
            if status in ("denied", "expired"):
                break
            if status == "pending":
                time.sleep(interval)
                continue
            # unexpected response shape — back off and retry
            time.sleep(interval)

    style.print_error("Login was not approved in time" if status != "denied" else "Login denied")
    sys.exit(1)


def logout_device(global_opt: GlobalOptions, command: LogoutCommand):
    """Remove stored registry credentials."""
    server = command.server or (global_opt.server[0] if global_opt.server else "") \
        or global_opt.config or ""
    removed = auth_store.clear_credentials(server)
    creds = auth_store.list_servers()
    if not removed:
        style.print_warning("No stored credentials found" + (f" for {server}" if server else ""))
        return
    style.print_success(
        f"Logged out of {server.rstrip('/')}"
        if server else "Logged out (all servers)"
    )


# ---------------------------------------------------------------------------
# cpm report
# ---------------------------------------------------------------------------

def _json_or_error(resp):
    """Best-effort JSON decode of an HTTP response."""
    try:
        return resp.json()
    except ValueError:
        return {}


def report_package(global_opt: GlobalOptions, command: ReportCommand):
    """Report a package for malware or abuse."""
    import requests as rq

    server = command.server or (global_opt.server[0] if global_opt.server else "") \
        or global_opt.config or DEFAULT_REPO
    server = server.rstrip("/")

    token = command.token
    if not token:
        creds = auth_store.load_credentials(server)
        if creds:
            token = creds.token
            if global_opt.verbose:
                style.print_verbose(f"Using stored credentials for {server}")
    if not token:
        raise CLIError(
            "no auth token — run 'cpm login' first or pass --token"
        )

    payload = {
        "package": command.package,
        "reason": command.reason,
        "details": command.details,
    }
    if command.version:
        payload["version"] = command.version

    with style.Spinner(f"reporting {command.package}"):
        try:
            resp = rq.post(
                f"{server}/api/report",
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
                timeout=15,
            )
        except rq.RequestException as exc:
            raise CLIError(f"cannot reach {server}: {exc}")

    body = _json_or_error(resp)
    if resp.status_code == 201:
        style.print_success(
            f"Report #{body.get('id')} filed for {command.package} "
            f"({command.reason}) — admins will review it"
        )
    elif resp.status_code == 200 and body.get("updated"):
        style.print_success(
            f"Updated your open report #{body.get('id')} for {command.package}"
        )
    else:
        raise CLIError(body.get("error", f"report failed ({resp.status_code})"))


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
    import tarfile
    import tempfile
    from pathlib import Path

    import requests as rq

    server = command.server or global_opt.config or DEFAULT_PUBLISH_SERVER
    token = command.token
    if not token:
        creds = auth_store.load_credentials(server)
        if creds and creds.token:
            token = creds.token
            style.print_info(f"Using stored credentials for {server} ({creds.email})" if creds.email else f"Using stored credentials for {server}")
    package_dir = Path(command.directory).resolve()

    if not package_dir.exists():
        style.print_error(f"directory not found: {package_dir}")
        return

    # Validate the package manifest with the Cpyte compiler's own validator
    with style.Spinner("validating package.json"):
        ok, errors = cpyte_toolchain.validate_package_json(package_dir)
    if not ok:
        style.print_error(f"package.json failed validation for {command.name}:")
        for err in errors:
            style.print_error(f"  - {err}")
        return
    style.print_success("package.json is valid")

    # Auto-pin the compiler version for prebuilt artifacts
    cpyte_version = command.cpyte_version or cpyte_toolchain.get_cpyte_version()

    # Scorpion-ready packages: record the flag and expect a pre-compiled .sef
    pkg_json = read_package_json(package_dir)
    scorpion_ready = bool(pkg_json and pkg_json.metadata.get("scorpion"))
    if scorpion_ready:
        style.print_success("package.json declares scorpion = true")
        sef_files = list(package_dir.glob("*.sef"))
        if not sef_files:
            style.print_warning("No .sef artifact found — run 'cpm build' with scorpion enabled first.")

    # Toolchain requirements: recorded for capability-aware resolution
    toolchain_required = pkg_json.metadata.get("toolchain") if pkg_json else None
    if toolchain_required:
        style.print_success("package.json declares toolchain requirements:")
        for key, value in toolchain_required.items():
            style.print_info(f"  {key}: {value}")

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
        meta["llvm_version"] = command.llvm_version or cpyte_toolchain._llvm_version()
        meta["cpyte_version"] = cpyte_version
    if scorpion_ready:
        meta["scorpion"] = True
    if toolchain_required:
        meta["toolchain"] = toolchain_required

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
            if token:
                headers["Authorization"] = f"Bearer {token}"
            if not token:
                style.print_warning("No auth token — run 'cpm login' or pass --token")
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

            toolchain = metadata.get('toolchain', {})
            if toolchain:
                style.print_info("  Toolchain requirements:")
                for key, value in toolchain.items():
                    style.print_info(f"    {key}: {value}")
            
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
        style.print_error("No cpy.toml found. Are you in a CPM project?")
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

_KNOWN_OS = {"linux", "darwin", "windows"}
_KNOWN_ARCH = {"x86_64", "aarch64", "arm"}
_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]*$")
_VERSION_RE = re.compile(r"^\d+\.\d+(\.\d+)?([-+][0-9A-Za-z.-]+)?$")
_CONSTRAINT_RE = re.compile(r"^(\^|~|~=|>=|<=|==|!=|>|<)?\d+(\.\d+){0,3}(\.\*)?$")
_CHECKSUM_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def _constraint_satisfied(constraint: str, version: str) -> bool:
    """True if `version` satisfies `constraint` (caret/tilde/bare/specifier aware).

    Unlike sat._version_satisfies this actually understands '^' and '~'
    instead of silently accepting everything on parse failure.
    """
    from packaging.version import InvalidVersion, Version

    if not constraint or constraint in ("latest", "*"):
        return True
    try:
        actual = Version(version)
    except InvalidVersion:
        return False

    if constraint.startswith(("==", "!=", "<=", ">=", "<", ">", "~=")) \
            or "," in constraint or "||" in constraint:
        try:
            from packaging.specifiers import SpecifierSet
            return version in SpecifierSet(constraint)
        except Exception:
            return False

    m = re.match(r"^(\^|~|~=)?(\d+)(?:\.(\d+))?(?:\.(\d+))?$", constraint.strip())
    if not m:
        return False
    op, maj, mi, pa = m.group(1), int(m.group(2)), m.group(3), m.group(4)
    mi = int(mi) if mi is not None else 0
    pa = int(pa) if pa is not None else 0

    if op == "^":
        # ^X.Y.Z := >=X.Y.Z <(X+1).0.0 ; when X==0 pin minor; when 0.Y==0 pin patch
        if (actual.major, actual.minor, actual.micro) < (maj, mi, pa):
            return False
        if maj > 0:
            return actual < Version(f"{maj + 1}.0.0")
        if mi > 0:
            return actual < Version(f"0.{mi + 1}.0")
        return actual < Version(f"0.0.{pa + 1}")
    if op in ("~", "~="):
        # ~1.2.3 := >=1.2.3 <1.3.0
        return (actual.major, actual.minor, actual.micro) >= (maj, mi, pa) \
            and actual < Version(f"{maj}.{mi + 1}.0")

    # Bare version: major-version compatibility (CPM prebuilt contract).
    return actual.major == maj


class _Issue:
    """A validation finding: severity error/warn/info, optional fix action."""

    __slots__ = ("severity", "message", "hint", "fix")

    def __init__(self, severity, message, hint="", fix=None):
        self.severity = severity
        self.message = message
        self.hint = hint
        self.fix = fix


def _check_manifest_fields(manifest, root, fixable, issues):
    if not manifest.name:
        def _fix_name():
            derived = re.sub(r"[^a-z0-9._-]", "-", root.name.lower()).strip("-")
            if not derived:
                derived = "unnamed"
            elif not derived[0].isalpha():
                derived = "p-" + derived
            manifest.name = derived
            write_manifest(manifest)

        issues.append(_Issue(
            "error", "[cpm] name is missing",
            hint="required for publishing",
            fix=_fix_name if fixable else None,
        ))
    elif len(manifest.name) > 214 or not _NAME_RE.match(manifest.name):
        issues.append(_Issue(
            "error",
            f"[cpm] invalid project name: {manifest.name!r}",
            hint="letters/digits/._- only, must start with a letter",
        ))

    if not manifest.version or not _VERSION_RE.match(manifest.version):
        def _fix_version():
            manifest.version = "0.1.0"
            write_manifest(manifest)

        issues.append(_Issue(
            "error",
            "[cpm] version is missing" if not manifest.version
            else f"[cpm] invalid version: {manifest.version!r} (want X.Y[.Z])",
            hint="e.g. 0.1.0",
            fix=_fix_version if fixable else None,
        ))

    for label, value, known in (
        ("os", manifest.target.os, _KNOWN_OS),
        ("arch", manifest.target.arch, _KNOWN_ARCH),
    ):
        if value and value not in known:
            def _make_fix(lbl=label):
                def _fix_target():
                    if lbl == "os":
                        manifest.target.os = None
                    else:
                        manifest.target.arch = None
                    write_manifest(manifest)
                return _fix_target

            issues.append(_Issue(
                "error",
                f"[cpm.target] unknown {label}: {value!r}",
                hint=f"known values: {', '.join(sorted(known))}",
                fix=_make_fix() if fixable else None,
            ))

    if manifest.build.main and not (root / manifest.build.main).exists():
        issues.append(_Issue(
            "error",
            f"[cpm.build] main entry not found: {manifest.build.main}",
            hint="fix the path or create the file",
        ))
    for sym in manifest.build.exports:
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", sym):
            issues.append(_Issue("warn", f"[cpm.build] invalid export symbol: {sym!r}"))

    for tool, rel in manifest.bin.items():
        if not tool or not re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]*$", tool):
            issues.append(_Issue(
                "error",
                f"[cpm.bin] invalid tool name: {tool!r}",
                hint="letters/digits/._- only",
            ))
        if not rel:
            issues.append(_Issue("error", f"[cpm.bin] '{tool}' has empty target path"))
        elif Path(rel).is_absolute():
            issues.append(_Issue(
                "error",
                f"[cpm.bin] '{tool}' target must be a project-relative path, got {rel!r}",
            ))
        elif not (root / rel).exists():
            issues.append(_Issue(
                "error",
                f"[cpm.bin] '{tool}' target not found: {rel}",
                hint=".cpy targets run via JIT; native binaries are executed directly",
            ))

    for repo in manifest.repos:
        if not repo.startswith("https://"):
            issues.append(_Issue(
                "error",
                f"insecure repo URL: {repo}",
                hint="non-HTTPS registries can serve tampered packages",
            ))


def _check_dependencies(manifest, modules_dir, issues):
    from packaging.specifiers import InvalidSpecifier, SpecifierSet

    if not manifest.packages:
        issues.append(_Issue("info", "no dependencies declared"))
        return

    for pkg in manifest.packages:
        constraint = pkg.version.strip()
        if constraint == "latest":
            issues.append(_Issue(
                "warn",
                f"{pkg.name}@latest — unpinned dependency",
                hint=f"pin an exact version: cpm add {pkg.name}@<version>",
            ))
        elif constraint in ("", "*"):
            issues.append(_Issue("warn", f"{pkg.name}@* — wildcard matches any version"))
        elif "," not in constraint and "||" not in constraint \
                and not _CONSTRAINT_RE.match(constraint):
            try:
                SpecifierSet(constraint)
            except InvalidSpecifier:
                issues.append(_Issue(
                    "error",
                    f"{pkg.name}: malformed version constraint {constraint!r}",
                    hint='use forms like "1.2", "^2.0", "~1.3", ">=1.0,<2"',
                ))

        pkg_dir = modules_dir / pkg.name
        if not pkg_dir.exists() or not any(pkg_dir.iterdir()):
            issues.append(_Issue(
                "warn",
                f"{pkg.name} is declared but not installed",
                hint="run 'cpm install'",
            ))


def _check_lockfile(manifest, lockfile_path, modules_dir, issues):
    from packaging.version import InvalidVersion, Version

    if lockfile_path is None:
        if manifest.packages:
            issues.append(_Issue(
                "warn",
                "no cpm.lock found",
                hint="run 'cpm install' for reproducible builds",
            ))
        return

    try:
        lock = read_lockfile(lockfile_path)
    except Exception as exc:
        issues.append(_Issue("error", f"lockfile unreadable: {exc}"))
        return

    if not lock.entries:
        issues.append(_Issue("warn", f"{lockfile_path.name} is empty"))
        return

    for entry in lock.entries:
        label = f"{entry.name}@{entry.version}"

        # Supply-chain integrity: checksums are mandatory.
        if not entry.checksum:
            issues.append(_Issue(
                "error",
                f"{label}: locked without checksum",
                hint="re-run 'cpm install' to record sha256 hashes",
            ))
        elif not _CHECKSUM_RE.match(entry.checksum):
            issues.append(_Issue(
                "error",
                f"{label}: malformed checksum (want sha256:<64 hex>)",
            ))

        if entry.resolved and not entry.resolved.startswith("https://"):
            issues.append(_Issue(
                "error",
                f"{label}: resolved over insecure transport",
            ))

        if entry.name and entry.version:
            try:
                Version(entry.version)
            except InvalidVersion:
                issues.append(_Issue("error", f"{label}: invalid locked version"))

        if not (modules_dir / entry.name / entry.version).exists():
            issues.append(_Issue(
                "warn",
                f"{label}: locked but not installed",
                hint="run 'cpm install'",
            ))

    # Manifest <-> lockfile cross-check
    for pkg in manifest.packages:
        entries = lock.get_all(pkg.name)
        if not entries:
            issues.append(_Issue(
                "warn",
                f"{pkg.name}: no lockfile entry",
                hint="run 'cpm install'",
            ))
            continue
        constraint = pkg.version.strip()
        if not any(_constraint_satisfied(constraint, e.version) for e in entries):
            locked = ", ".join(sorted({e.version for e in entries}))
            issues.append(_Issue(
                "warn",
                f"{pkg.name}: locked {locked} does not satisfy '{constraint}'",
                hint=f"run 'cpm update {pkg.name}'",
            ))


def _check_security(global_opt, fixable, issues):
    """Force correct + secure local configuration."""
    cred_file = auth_store.auth_path()
    if cred_file.exists():
        mode = stat_mod.S_IMODE(cred_file.stat().st_mode)
        if mode != 0o600:
            def _fix_perms():
                cred_file.chmod(stat_mod.S_IRUSR | stat_mod.S_IWUSR)

            issues.append(_Issue(
                "error",
                f"{cred_file}: permissions {oct(mode)} expose your token "
                "to other users",
                hint="must be 0600",
                fix=_fix_perms if fixable else None,
            ))
        for cred in auth_store.list_servers():
            if cred.token and cred.server.startswith("http://"):
                issues.append(_Issue(
                    "warn",
                    f"auth token for {cred.server} is sent over plaintext HTTP",
                    hint="use an HTTPS registry URL",
                ))


def validate_manifest(global_opt: GlobalOptions, command: ValidateCommand):
    """Validate the project: manifest fields, deps, lockfile, security."""
    import time as _time

    started = _time.monotonic()
    manifest_path = find_manifest()
    if not manifest_path:
        style.print_error("No cpy.toml found. Are you in a CPM project?")
        sys.exit(1)

    project_root = manifest_path.parent
    modules_dir = project_root / ".cpm" / "modules"

    style.print_header(f"Validating {manifest_path}")

    issues: list[_Issue] = []

    try:
        manifest = read_manifest(manifest_path)
    except Exception as e:
        style.print_error(f"cpy.toml is not valid TOML: {e}")
        sys.exit(1)

    _check_manifest_fields(manifest, project_root, command.fix, issues)
    _check_dependencies(manifest, modules_dir, issues)
    _check_lockfile(manifest, find_lockfile(), modules_dir, issues)
    _check_security(global_opt, command.fix, issues)

    # Apply auto-fixes where available.
    fixed = 0
    remaining: list[_Issue] = []
    for issue in issues:
        if issue.fix is not None:
            try:
                issue.fix()
                fixed += 1
                style.print_success(f"fixed: {issue.message}")
                continue
            except Exception:
                pass
        remaining.append(issue)
    issues = remaining

    errors = [i for i in issues if i.severity == "error"]
    warns = [i for i in issues if i.severity == "warn"]
    infos = [i for i in issues if i.severity == "info"]

    for group, printer in ((errors, style.print_error),
                           (warns, style.print_warning),
                           (infos, style.print_info)):
        for issue in group:
            printer(issue.message)
            if issue.hint:
                print(f"      hint: {issue.hint}")

    elapsed_ms = (_time.monotonic() - started) * 1000
    failed = bool(errors) or (command.strict and warns)

    parts = []
    if errors:
        parts.append(f"{style.Color.BOLD_RED}{len(errors)} error(s){style.Color.RESET}")
    if warns:
        parts.append(f"{style.Color.BOLD_YELLOW}{len(warns)} warning(s){style.Color.RESET}")
    if fixed:
        parts.append(f"{style.Color.GREEN}{fixed} fixed{style.Color.RESET}")
    summary = ", ".join(parts) if parts else "all checks passed"

    if failed:
        style.print_error(f"\nValidation FAILED ({summary}, {elapsed_ms:.0f} ms)")
        if command.strict and warns and not errors:
            style.print_info("--strict: warnings treated as errors")
        sys.exit(1)

    style.print_success(f"\nValidation PASSED ({summary}, {elapsed_ms:.0f} ms)")
