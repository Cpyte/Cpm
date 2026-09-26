"""Tests for CLI tool registration (bin entries).

Covers:
- [cpm.bin] in cpytoml (Manifest round-trip)
- "bin" in package.json (PackageJson)
- shim generation via executor.register_bins / _unregister_bins
- validate errors for broken bin declarations
"""

import json
import os
import stat
from pathlib import Path

import pytest

from cpyte_cpm.cli import executor
from cpyte_cpm.cli.manifest import Manifest, PackageJson, _parse_toml, read_package_json


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_installed_pkg(
    root: Path, name: str = "@std/tool", version: str = "1.0", bins: dict | None = None
) -> Path:
    """Create a fake installed module with package.json + bin targets."""
    mod = executor._module_path(root, name, version)
    (mod / "src").mkdir(parents=True)
    (mod / "src" / "cli.cpy").write_text("def main(): pass\n")
    native = mod / "native"
    native.write_text("#!/bin/sh\necho native-ok\n")
    native.chmod(0o755)
    pkg = {"name": name, "version": version}
    if bins is not None:
        pkg["bin"] = bins
    (mod / "package.json").write_text(json.dumps(pkg))
    return mod


@pytest.fixture
def messages(monkeypatch):
    """Capture style output so warnings are assertable."""
    out = []

    def _rec(name):
        def fn(*args, **kwargs):
            out.append((name, " ".join(str(a) for a in args)))

        return fn

    for fn_name in ("print_warning", "print_info", "print_verbose", "print_error"):
        monkeypatch.setattr(executor.style, fn_name, _rec(fn_name))
    return out


# ---------------------------------------------------------------------------
# manifest parsing
# ---------------------------------------------------------------------------


class TestManifestBin:
    def test_roundtrip(self):
        m = Manifest(name="demo")
        m.bin = {"mytool": "src/tool.cpy", "native": "bin/out"}
        s = m.toml_str()
        assert "[cpm.bin]" in s
        m2 = Manifest()
        _parse_toml(s, m2)
        assert m2.bin == {"mytool": "src/tool.cpy", "native": "bin/out"}

    def test_parse_quoted_keys(self):
        m = Manifest()
        _parse_toml('[cpm]\nname="x"\n\n[cpm.bin]\n"@scope/cli" = "tools/x.cpy"\n', m)
        assert m.bin == {"@scope/cli": "tools/x.cpy"}

    def test_absent_section(self):
        m = Manifest()
        _parse_toml('[cpm]\nname = "x"\n', m)
        assert m.bin == {}


class TestPackageJsonBin:
    def test_bin_parsed(self, tmp_path):
        (tmp_path / "package.json").write_text(
            json.dumps({"name": "x", "version": "1.0", "bin": {"t": "a.cpy"}})
        )
        pj = read_package_json(tmp_path)
        assert isinstance(pj, PackageJson)
        assert pj.bin == {"t": "a.cpy"}

    def test_no_bin(self, tmp_path):
        (tmp_path / "package.json").write_text(
            json.dumps({"name": "x", "version": "1.0"})
        )
        assert read_package_json(tmp_path).bin == {}

    def test_missing_file(self, tmp_path):
        assert read_package_json(tmp_path) is None


# ---------------------------------------------------------------------------
# shim generation
# ---------------------------------------------------------------------------


class TestRegisterBins:
    def test_jit_and_native_shims(self, tmp_path):
        mod = _make_installed_pkg(
            tmp_path, bins={"tool-cli": "src/cli.cpy", "tool-native": "native"}
        )
        reg = executor.register_bins(tmp_path, "@std/tool", "1.0", module_dir=mod)
        assert reg == ["tool-cli", "tool-native"]

        bindir = tmp_path / ".cpm" / "bin"
        jit = (bindir / "tool-cli").read_text()
        assert "--jit" in jit
        assert 'exec cpy --jit "$TARGET"' in jit
        assert 'cpyte --jit "$TARGET"' in jit  # fallback

        native_shim = (bindir / "tool-native").read_text()
        assert "--jit" not in native_shim
        # executable bit set on both
        for name in ("tool-cli", "tool-native"):
            mode = (bindir / name).stat().st_mode
            assert mode & stat.S_IXUSR

    def test_native_shim_runs(self, tmp_path):
        mod = _make_installed_pkg(tmp_path, bins={"tool-native": "native"})
        executor.register_bins(tmp_path, "@std/tool", "1.0", module_dir=mod)
        out = os.popen(str(tmp_path / ".cpm" / "bin" / "tool-native")).read()
        assert "native-ok" in out

    def test_missing_target_skipped_with_warning(self, tmp_path, messages):
        mod = _make_installed_pkg(tmp_path, bins={"broken": "nope.cpy"})
        reg = executor.register_bins(tmp_path, "@std/tool", "1.0", module_dir=mod)
        assert reg == []
        assert any("missing target" in text for _, text in messages)

    def test_tool_name_sanitized(self, tmp_path):
        mod = _make_installed_pkg(tmp_path, bins={"weird/name!": "src/cli.cpy"})
        reg = executor.register_bins(tmp_path, "@std/tool", "1.0", module_dir=mod)
        assert reg == ["weird_name_"]

    def test_no_package_json(self, tmp_path):
        assert executor.register_bins(tmp_path, "x", "1.0") == []


class TestUnregisterBins:
    def test_removes_owned_only(self, tmp_path):
        mod_a = _make_installed_pkg(
            tmp_path, "@std/a", "1.0", bins={"a-cli": "src/cli.cpy"}
        )
        mod_b = _make_installed_pkg(
            tmp_path, "@std/b", "2.0", bins={"b-cli": "src/cli.cpy"}
        )
        executor.register_bins(tmp_path, "@std/a", "1.0", module_dir=mod_a)
        executor.register_bins(tmp_path, "@std/b", "2.0", module_dir=mod_b)

        removed = executor._unregister_bins(tmp_path, "@std/a")
        assert removed == 1
        bindir = tmp_path / ".cpm" / "bin"
        assert not (bindir / "a-cli").exists()
        assert (bindir / "b-cli").exists()

    def test_no_bin_dir(self, tmp_path):
        assert executor._unregister_bins(tmp_path, "@std/a") == 0


# ---------------------------------------------------------------------------
# capabilities banner
# ---------------------------------------------------------------------------


class TestInstalledCapabilities:
    def test_banner_shows_surface(self, tmp_path, messages):
        mod = _make_installed_pkg(tmp_path, bins={})
        (mod / "package.json").write_text(
            json.dumps(
                {
                    "name": "@std/tool",
                    "version": "1.0",
                    "capabilities": {
                        "keywords": ["await"],
                        "operators": ["<|>"],
                        "tags": ["@async"],
                        "macros": ["m1"],
                        "custom_types": ["Result"],
                    },
                }
            )
        )
        executor.print_installed_capabilities("@std/tool", "1.0", module_dir=mod)
        texts = [t for _, t in messages]
        joined = "\n".join(texts)
        assert "adds to the language" in joined
        assert "keywords:      await" in joined
        assert "operators:     <|>" in joined
        assert "custom types:  Result" in joined

    def test_no_capabilities_no_output(self, tmp_path, messages):
        mod = _make_installed_pkg(tmp_path, bins={})
        executor.print_installed_capabilities("@std/tool", "1.0", module_dir=mod)
        assert messages == []


# ---------------------------------------------------------------------------
# validate integration
# ---------------------------------------------------------------------------


class TestValidateBinChecks:
    @staticmethod
    def _project(tmp_path: Path, cpytoml: str) -> Path:
        root = tmp_path / "proj"
        root.mkdir(exist_ok=True)
        (root / "cpy.toml").write_text(cpytoml)
        return root

    def _issues_for(self, tmp_path, cpytoml):
        from cpyte_cpm.cli.things import _check_manifest_fields

        m = Manifest(path=self._project(tmp_path, cpytoml) / "cpy.toml")
        _parse_toml(cpytoml, m)
        issues = []
        _check_manifest_fields(m, m.path.parent, False, issues)
        return issues

    def test_missing_target_is_error(self, tmp_path):
        issues = self._issues_for(
            tmp_path,
            '[cpm]\nname="p"\nversion="1.0"\n\n[cpm.bin]\n'
            '"cli" = "does/not/exist.cpy"\n',
        )
        msgs = [i.message for i in issues]
        assert any("[cpm.bin] 'cli' target not found" in msg for msg in msgs)

    def test_absolute_target_is_error(self, tmp_path):
        issues = self._issues_for(
            tmp_path,
            f'[cpm]\nname="p"\nversion="1.0"\n\n[cpm.bin]\n'
            f'"cli" = "{tmp_path}/abs.cpy"\n',
        )
        assert any("project-relative" in i.message for i in issues)

    def test_bad_tool_name_is_error(self, tmp_path):
        issues = self._issues_for(
            tmp_path, '[cpm]\nname="p"\nversion="1.0"\n\n[cpm.bin]\n"!bad!" = "x.cpy"\n'
        )
        assert any("invalid tool name" in i.message for i in issues)

    def test_valid_bin_passes(self, tmp_path):
        root = self._project(
            tmp_path,
            '[cpm]\nname="p"\nversion="1.0"\n\n[cpm.bin]\n"cli" = "tool.cpy"\n',
        )
        (root / "tool.cpy").write_text("def main(): pass\n")
        issues = []
        from cpyte_cpm.cli.things import _check_manifest_fields

        m = Manifest(path=root / "cpy.toml")
        _parse_toml((root / "cpy.toml").read_text(), m)
        _check_manifest_fields(m, root, False, issues)
        assert not [i for i in issues if "[cpm.bin]" in i.message]
