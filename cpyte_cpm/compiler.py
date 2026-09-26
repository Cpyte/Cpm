"""Deep integration with the Cpyte compiler.

CPM is a *compiler-pipeline* package manager: it exists to feed the Cpyte
compiler. This module makes that relationship explicit and toolchain-aware.

Responsibilities:
    - Detect the installed Cpyte compiler (module + `cpy` binary)
    - Report compiler & LLVM versions for toolchain pinning
    - Validate package.json manifests using the compiler's own validator
    - Invoke the compiler for build / run / emit
    - Diagnose the toolchain (`cpm doctor`)
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Distribution names on PyPI / the Cpyte registry
COMPILER_DIST = "cpyte"


@dataclass
class CompilerInfo:
    """Snapshot of the detected Cpyte compiler toolchain."""

    available: bool = False
    version: str = ""
    binary: str | None = None
    llvm_version: str = ""
    module_error: str = ""
    binary_error: str = ""
    module_path: str = ""

    @property
    def ready(self) -> bool:
        return self.available and bool(self.version)


def _module_available() -> tuple[str, str]:
    """Return (version, error) for the `cpyte` Python module."""
    try:
        import cpyte

        version = getattr(cpyte, "__version__", "")
        if not version:
            try:
                from importlib.metadata import version as _mv

                version = _mv(COMPILER_DIST)
            except Exception:
                version = ""
        return version, ""
    except ImportError as e:
        return "", str(e)


def _llvm_version() -> str:
    """Read LLVM version via llvmlite if present."""
    try:
        import llvmlite.binding as llvm

        v = llvm.llvm_version_info
        return f"{v[0]}.{v[1]}.{v[2]}"
    except Exception:
        return ""


def detect_compiler() -> CompilerInfo:
    """Detect the Cpyte compiler toolchain in the current environment."""
    info = CompilerInfo()

    version, mod_err = _module_available()
    info.version = version
    info.module_error = mod_err

    cpy_bin = shutil.which("cpy")
    if cpy_bin:
        info.binary = cpy_bin
    else:
        info.binary_error = "no 'cpy' binary on PATH"

    if version or cpy_bin:
        info.available = True

    if version:
        info.llvm_version = _llvm_version()

    if version:
        try:
            import cpyte

            info.module_path = os.path.dirname(cpyte.__file__)
        except Exception:
            pass

    return info


def get_cpyte_version() -> str:
    """Best-effort Cpyte compiler version for pinning prebuilt artifacts.

    Falls back to a known-good published version so locking still works
    when the compiler isn't importable.
    """
    try:
        import cpyte

        v = getattr(cpyte, "__version__", "")
        if v:
            return v
    except Exception:
        pass
    try:
        from importlib.metadata import version as _mv

        return _mv(COMPILER_DIST)
    except Exception:
        return "2.6.0"


def compiler_command() -> list[str]:
    """Return argv prefix that runs the Cpyte compiler CLI.

    Prefers the `cpy` binary; falls back to `python -m cpyte`.
    """
    cpy_bin = shutil.which("cpy")
    if cpy_bin:
        return [cpy_bin]
    return [sys.executable, "-m", COMPILER_DIST]


def run_compiler(
    args: list[str], cwd: Path | None = None, capture: bool = False
) -> subprocess.CompletedProcess:
    """Run the Cpyte compiler CLI with the given args."""
    cmd = compiler_command() + args
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=capture,
    )


def build_project(
    source: Path,
    output: Path,
    opt_level: int = 3,
    mode: str = "aot",
    pic: bool = False,
) -> int:
    """Compile a `.cpy` file with the Cpyte compiler.

    modes: aot (machine object), jit (run), emit-llvm (.ll), scorpion (.sef)
    """
    args = []
    if mode in ("aot", "jit", "emit-llvm", "scorpion"):
        args.append(f"--{mode}")
    if mode == "scorpion" and pic:
        args.append("--pic")
    args.append(str(source))
    if mode == "aot":
        args.append("-o")
        args.append(str(output))
    result = run_compiler(args, cwd=source.parent)
    return result.returncode


def run_cpy(source: Path, args: list[str] | None = None) -> int:
    """Execute a `.cpy` script via the compiler's JIT."""
    cmd = ["--jit", str(source)] + (args or [])
    result = run_compiler(cmd, cwd=source.parent)
    return result.returncode


def emit_scorpion(
    source: Path,
    cwd: Path | None = None,
    pic: bool = True,
    exports: list[str] | None = None,
) -> tuple[int, Path]:
    """Cross-compile a `.cpy` file for Scorpion (RISC-V), producing a `.sef`.

    With ``pic=True`` the build uses the dynamic SEF v2 path (PIC codegen,
    load-time relocation, import/export records). ``exports`` lists symbols
    to mark as exported library entry points (passed as ``--export NAME``).

    Returns (returncode, sef_path). The SEF is written next to the source
    file (e.g. ``main.cpy`` → ``main.sef``).
    """
    sef_path = source.with_suffix(".sef")
    args = ["--scorpion"]
    if pic:
        args.append("--pic")
    if exports:
        for name in exports:
            args.append("--export")
            args.append(name)
    args.append(str(source))
    result = run_compiler(args, cwd=cwd or source.parent)
    return result.returncode, sef_path


# ---------------------------------------------------------------------------
# Toolchain capability detection
# ---------------------------------------------------------------------------

_CODE_GEN_PROBES: dict[str, dict] = {
    # System-header codegen (setjmp/longjmp) — broke on compilers before 2.7.2
    "setjmp": {
        "mode": "jit",
        "platforms": ("darwin",),
        "source": (
            'import "ApplicationServices/ApplicationServices.h"\n\n'
            "def main() -> int:\n"
            "    return 0\n"
        ),
    },
    # Read-only `(name)` parameter views
    "const_params": {
        "mode": "jit",
        "source": (
            "def f((x): int) -> int:\n"
            "    return x\n\n"
            "def main() -> int:\n"
            "    return f(5)\n"
        ),
    },
    # SEF v2 cross-compilation to RISC-V
    "scorpion": {
        "mode": "scorpion",
        "source": ("def main() -> int:\n    return 0\n"),
    },
}

_codegen_feature_cache: dict[str, bool] = {}


def has_codegen_feature(feature: str) -> bool:
    """Probe whether the installed compiler's codegen supports ``feature``.

    Probes compile a tiny program with the real toolchain, so the answer
    reflects the *actual* compiler rather than a version table. Results are
    memoized for the process lifetime.

    Unknown features report unavailable so capability-aware resolution fails
    loudly instead of shipping a package the compiler cannot build. Features
    that only apply to another platform are reported available.
    """
    if feature in _codegen_feature_cache:
        return _codegen_feature_cache[feature]

    spec = _CODE_GEN_PROBES.get(feature)
    if spec is None:
        _codegen_feature_cache[feature] = False
        return False

    platforms = spec.get("platforms")
    if platforms and sys.platform not in platforms:
        _codegen_feature_cache[feature] = True
        return True

    ok = False
    with tempfile.TemporaryDirectory(prefix="cpm-probe-") as td:
        probe = Path(td) / "_probe.cpy"
        probe.write_text(spec["source"])
        if spec.get("mode") == "scorpion":
            rc, _ = emit_scorpion(probe)
            ok = rc == 0
        else:
            ok = run_cpy(probe) == 0

    _codegen_feature_cache[feature] = ok
    return ok


def probe_codegen_features() -> dict[str, bool]:
    """Probe every known codegen feature (used by ``cpm doctor``)."""
    return {feature: has_codegen_feature(feature) for feature in _CODE_GEN_PROBES}


def toolchain_capabilities() -> dict:
    """Static toolchain capabilities for capability-aware resolution.

    Returns ``{"compiler": <version>, "llvm": <version>}`` from the detected
    toolchain (empty when no compiler is installed). Codegen features are
    probed on demand via :func:`has_codegen_feature`.
    """
    info = detect_compiler()
    caps = {}
    if info.version:
        caps["compiler"] = info.version
    if info.llvm_version:
        caps["llvm"] = info.llvm_version
    return caps


# ---------------------------------------------------------------------------
# Manifest validation via the compiler's own validator
# ---------------------------------------------------------------------------


def validate_package_json(package_dir: Path) -> tuple[bool, list[str]]:
    """Validate a package's package.json using the Cpyte compiler validator.

    Returns (ok, errors). Falls back to an internal schema check when the
    compiler isn't installed so publish still guards against bad manifests.
    """
    manifest_path = package_dir / "package.json"
    if not manifest_path.exists():
        return False, [f"missing package.json in {package_dir}"]

    try:
        from cpyte.package_manifest import ManifestParser, ManifestValidator
    except Exception:
        return _validate_package_json_fallback(package_dir)

    try:
        manifest = ManifestParser.parse_file(str(manifest_path))
    except Exception as e:
        return False, [f"could not parse package.json: {e}"]

    errors = ManifestValidator.validate_manifest(manifest)
    return not errors, list(errors)


def _validate_package_json_fallback(package_dir: Path) -> tuple[bool, list[str]]:
    """Schema-level fallback validation when cpyte is unavailable."""
    manifest_path = package_dir / "package.json"
    try:
        with open(manifest_path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        return False, [f"invalid package.json: {e}"]

    errors: list[str] = []
    if not data.get("name"):
        errors.append("package.json is missing required field 'name'")
    if not data.get("version"):
        errors.append("package.json is missing required field 'version'")

    caps = data.get("capabilities", {})
    for kw in caps.get("keywords", []):
        if not isinstance(kw, str) or not (kw[0].isalpha() or kw[0] == "_"):
            errors.append(f"invalid keyword '{kw}': must be a valid identifier")

    for tag in caps.get("tags", []):
        if not tag.startswith("@"):
            errors.append(f"invalid tag '{tag}': tags must start with '@'")

    return not errors, errors


# ---------------------------------------------------------------------------
# Toolchain diagnostics (cpm doctor)
# ---------------------------------------------------------------------------


def diagnose() -> dict[str, Any]:
    """Produce a structured toolchain report."""
    info = detect_compiler()

    report: dict[str, Any] = {
        "compiler": {
            "detected": info.available,
            "version": info.version or None,
            "binary": info.binary,
            "module_path": info.module_path or None,
            "module_error": info.module_error or None,
            "binary_error": info.binary_error or None,
        },
        "llvm_version": info.llvm_version or None,
    }

    report["toolchain_capabilities"] = toolchain_capabilities()
    if info.available:
        report["codegen"] = probe_codegen_features()

    # Workspace / registry checks
    manifest = _safe_read_manifest()
    report["workspace"] = {
        "project": manifest.name if manifest else None,
        "manifest": str(manifest.path) if manifest and manifest.path else None,
        "cpm_dir": _cpm_dir_present(),
    }
    return report


def _cpm_dir_present() -> bool:
    try:
        return Path.cwd().joinpath(".cpm", "modules").is_dir()
    except Exception:
        return False


def _safe_read_manifest():
    try:
        from .manifest import read_manifest

        return read_manifest()
    except Exception:
        return None
