"""Tests for the deep cpm validate command."""

import stat

import pytest

from cpyte_cpm.cli import style
from cpyte_cpm.cli.commands import GlobalOptions, ValidateCommand
from cpyte_cpm.cli.things import validate_manifest


def _run_project(cmd, cwd, tmp_path):
    """Chdir into the project and run validate (manifest discovery is cwd-based)."""
    import os

    prev = os.getcwd()
    os.chdir(str(cwd))
    try:
        validate_manifest(GlobalOptions(verbose=False, quiet=False), cmd)
    finally:
        os.chdir(prev)


def _project(tmp_path, toml):
    proj = tmp_path / "proj"
    proj.mkdir(exist_ok=True)
    (proj / "cpytoml").write_text(toml)
    return proj


def _cmd(fix=False, strict=False):
    return ValidateCommand(fix=fix, strict=strict)


GOOD = '[cpm]\nname = "demo"\nversion = "1.2.3"\n[cpm.dependencies]\n# none\n'
LOCK_OK = (
    "[[package]]\n"
    'name = "@std/json"\n'
    'version = "1.1.0"\n'
)


def _locked_project(tmp_path, constraint="^1.0", lock_extra="", installed=True):
    proj = _project(
        tmp_path,
        f'[cpm]\nname = "x"\nversion = "1.0"\n'
        f'[cpm.dependencies]\n"@std/json" = "{constraint}"\n',
    )
    if installed:
        modules = proj / ".cpm" / "modules" / "@std/json"
        (modules / "1.1.0").mkdir(parents=True)
    (proj / "cpm.lock").write_text(LOCK_OK + lock_extra)
    return proj




@pytest.fixture(autouse=True)
def clean_auth(monkeypatch, tmp_path):
    """Isolate XDG_CONFIG_HOME so auth checks never touch real credentials."""
    xdg = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    return xdg / "cpm" / "auth.toml"


@pytest.fixture
def messages(monkeypatch):
    """Record styled output (errors/warnings/info go to import-time stderr)."""
    box = []

    def _rec(sev):
        def _fn(msg, *a, **k):
            box.append(f"{sev}: {msg}")
        return _fn

    monkeypatch.setattr(style, "print_error", _rec("error"))
    monkeypatch.setattr(style, "print_warning", _rec("warn"))
    monkeypatch.setattr(style, "print_info", _rec("info"))
    monkeypatch.setattr(style, "print_success", _rec("ok"))
    monkeypatch.setattr(style, "print_header", lambda *a, **k: None)
    return box


GOOD = '[cpm]\nname = "demo"\nversion = "1.2.3"\n[cpm.dependencies]\n# none\n'


class TestValidate:
    def test_valid_project_passes(self, tmp_path, messages):
        proj = _project(tmp_path, GOOD)
        _run_project(_cmd(), proj, tmp_path)
        assert any("PASSED" in m for m in messages)

    def test_missing_name_and_version_are_errors(self, tmp_path, messages):
        proj = _project(tmp_path, '[cpm]\nversion = "1.0"\n')
        with pytest.raises(SystemExit):
            _run_project(_cmd(), proj, tmp_path)
        joined = "\n".join(messages)
        assert "name is missing" in joined
        assert "FAILED" in joined

    def test_invalid_version_rejected(self, tmp_path, messages):
        proj = _project(tmp_path, '[cpm]\nname = "x"\nversion = "abc"\n')
        with pytest.raises(SystemExit):
            _run_project(_cmd(), proj, tmp_path)
        assert any("invalid version" in m for m in messages)

    def test_unknown_target_os(self, tmp_path, messages):
        proj = _project(
            tmp_path,
            '[cpm]\nname = "x"\nversion = "1.0"\n[cpm.target]\nos = "win95"\n',
        )
        with pytest.raises(SystemExit):
            _run_project(_cmd(), proj, tmp_path)
        assert any("unknown os" in m for m in messages)

    def test_unknown_target_arch(self, tmp_path, messages):
        proj = _project(
            tmp_path,
            '[cpm]\nname = "x"\nversion = "1.0"\n[cpm.target]\narch = "mips"\n',
        )
        with pytest.raises(SystemExit):
            _run_project(_cmd(), proj, tmp_path)
        assert any("unknown arch" in m for m in messages)

    def test_missing_build_main(self, tmp_path, messages):
        proj = _project(
            tmp_path,
            '[cpm]\nname = "x"\nversion = "1.0"\n'
            '[cpm.build]\nmain = "ghost.cpy"\n',
        )
        with pytest.raises(SystemExit):
            _run_project(_cmd(), proj, tmp_path)
        assert any("main entry not found" in m for m in messages)

    def test_insecure_repo_url(self, tmp_path, messages):
        proj = _project(
            tmp_path,
            '[cpm]\nname = "x"\nversion = "1.0"\n'
            'repos = ["http://reg.example.com"]\n',
        )
        with pytest.raises(SystemExit):
            _run_project(_cmd(), proj, tmp_path)
        assert any("insecure repo URL" in m for m in messages)

    def test_malformed_constraint(self, tmp_path, messages):
        proj = _project(
            tmp_path,
            '[cpm]\nname = "x"\nversion = "1.0"\n'
            '[cpm.dependencies]\n"foo" = "not-a-version"\n',
        )
        with pytest.raises(SystemExit):
            _run_project(_cmd(), proj, tmp_path)
        assert any("malformed version constraint" in m for m in messages)


    def _global():
        return GlobalOptions(verbose=False, quiet=False)

    @staticmethod
    def _cmd(fix=False, strict=False):
        return ValidateCommand(fix=fix, strict=strict)

    @staticmethod
    def _project(tmp_path, toml):
        proj = tmp_path / "proj"
        proj.mkdir(exist_ok=True)
        (proj / "cpytoml").write_text(toml)
        return proj


class TestFixes:
    def test_fix_repairs_name_version_target(self, tmp_path, messages):
        proj = _project(
            tmp_path,
            '[cpm]\nversion = "oops"\n[cpm.target]\nos = "win95"\n',
        )
        _run_project(_cmd(fix=True), proj, tmp_path)
        content = (proj / "cpytoml").read_text()
        assert 'name = "proj"' in content
        assert 'version = "0.1.0"' in content
        assert 'os = "win95"' not in content
        assert any("fixed:" in m for m in messages)
        assert not any("FAILED" in m for m in messages)

    def test_no_fix_leaves_file_untouched(self, tmp_path, messages):
        original = '[cpm]\nversion = "oops"\n'
        proj = _project(tmp_path, original)
        with pytest.raises(SystemExit):
            _run_project(_cmd(), proj, tmp_path)
        assert (proj / "cpytoml").read_text() == original



LOCK_OK = (
    "[[package]]\n"
    'name = "@std/json"\n'
    'version = "1.1.0"\n'
)


def _locked_project(tmp_path, constraint="^1.0", lock_extra="", installed=True):
    proj = _project(
        tmp_path,
        f'[cpm]\nname = "x"\nversion = "1.0"\n'
        f'[cpm.dependencies]\n"@std/json" = "{constraint}"\n',
    )
    if installed:
        modules = proj / ".cpm" / "modules" / "@std/json"
        (modules / "1.1.0").mkdir(parents=True)
    (proj / "cpm.lock").write_text(LOCK_OK + lock_extra)
    return proj


class TestLockfileChecks:
    def test_lock_entry_without_checksum_is_error(self, tmp_path, messages):
        proj = _locked_project(tmp_path)
        with pytest.raises(SystemExit):
            _run_project(_cmd(), proj, tmp_path)
        assert any("locked without checksum" in m for m in messages)

    def test_malformed_checksum_is_error(self, tmp_path, messages):
        proj = _locked_project(tmp_path, lock_extra='checksum = "deadbeef"\n')
        with pytest.raises(SystemExit):
            _run_project(_cmd(), proj, tmp_path)
        assert any("malformed checksum" in m for m in messages)

    def test_insecure_resolved_url_is_error(self, tmp_path, messages):
        proj = _locked_project(
            tmp_path,
            lock_extra='checksum = "sha256:' + "a" * 64 + '"\n'
            'resolved = "http://evil.example.com/x.tar.gz"\n',
        )
        with pytest.raises(SystemExit):
            _run_project(_cmd(), proj, tmp_path)
        assert any("insecure transport" in m for m in messages)

    def test_locked_version_not_satisfying_constraint_warns(self, tmp_path, messages):
        proj = _locked_project(tmp_path, constraint="^2.0",
                               lock_extra='checksum = "sha256:' + "b" * 64 + '"\n')
        _run_project(_cmd(), proj, tmp_path)
        joined = "\n".join(messages)
        assert "does not satisfy" in joined
        assert "PASSED" in joined

    def test_fully_consistent_lockfile_passes(self, tmp_path, messages):
        proj = _locked_project(
            tmp_path,
            lock_extra='checksum = "sha256:' + "c" * 64 + '"\n'
            'resolved = "https://cypackage.5gnew.io.vn/x.tar.gz"\n',
        )
        _run_project(_cmd(), proj, tmp_path)
        assert any("PASSED" in m for m in messages)

    def test_declared_but_not_installed_warns(self, tmp_path, messages):
        proj = _locked_project(tmp_path, installed=False,
                               lock_extra='checksum = "sha256:' + "d" * 64 + '"\n')
        _run_project(_cmd(), proj, tmp_path)
        assert any("not installed" in m for m in messages)



class TestSecurityStrict:
    def test_loose_auth_perms_detected_and_fixed(self, tmp_path, messages, clean_auth):
        clean_auth.parent.mkdir(parents=True, exist_ok=True)
        clean_auth.write_text('[servers."https://example.com"]\ntoken = "t"\n')
        clean_auth.chmod(0o644)

        proj = _project(tmp_path, GOOD)
        with pytest.raises(SystemExit):  # error without --fix
            _run_project(_cmd(), proj, tmp_path)
        assert any("expose your token" in m for m in messages)
        assert stat.S_IMODE(clean_auth.stat().st_mode) == 0o644

        messages.clear()
        _run_project(_cmd(fix=True), proj, tmp_path)
        assert stat.S_IMODE(clean_auth.stat().st_mode) == 0o600
        assert any("fixed:" in m for m in messages)

    def test_plaintext_server_token_warns(self, tmp_path, messages, clean_auth):
        clean_auth.parent.mkdir(parents=True, exist_ok=True)
        clean_auth.write_text('[servers."http://127.0.0.1:5000"]\ntoken = "tok"\n')
        clean_auth.chmod(0o600)
        proj = _project(tmp_path, GOOD)
        _run_project(_cmd(), proj, tmp_path)
        joined = "\n".join(messages)
        assert "plaintext HTTP" in joined
        assert "PASSED" in joined

    def test_strict_treats_warnings_as_errors(self, tmp_path, messages):
        proj = _locked_project(
            tmp_path,
            constraint="latest",
            lock_extra='checksum = "sha256:' + "e" * 64 + '"\n',
        )
        _run_project(_cmd(), proj, tmp_path)  # passes
        assert any("PASSED" in m for m in messages)

        messages.clear()
        with pytest.raises(SystemExit):  # strict fails
            _run_project(_cmd(strict=True), proj, tmp_path)
        assert any("FAILED" in m for m in messages)
        assert any("--strict" in m for m in messages)

    def test_no_manifest_exits_1(self, tmp_path, messages):
        empty = tmp_path / "empty"
        empty.mkdir()
        with pytest.raises(SystemExit):
            _run_project(_cmd(), empty, tmp_path)

