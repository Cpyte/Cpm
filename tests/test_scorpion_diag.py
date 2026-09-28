"""Tests for Scorpion/SEF toolchain diagnosis and build failure reporting."""

from __future__ import annotations

import pytest

from cpyte_cpm import compiler
from cpyte_cpm.cli import style, things


def _make_runtime(root) -> "object":
    """Create a runtime_scorpion.c laid out like an installed compiler."""
    runtime_c = root / "lib" / "python3" / "site-packages" / "cpyte" / "runtime_scorpion.c"
    runtime_c.parent.mkdir(parents=True, exist_ok=True)
    runtime_c.write_text("/* runtime */")
    return runtime_c


# ---------------------------------------------------------------------------
# detect_scorpion
# ---------------------------------------------------------------------------


def test_detect_scorpion_finds_cross_compiler(monkeypatch) -> None:
    monkeypatch.setattr(compiler.shutil, "which", lambda n: "/bin/riscv64-elf-gcc" if n == "riscv64-elf-gcc" else None)
    monkeypatch.setattr(compiler, "_scorpion_elf2sef_path", lambda: (None, "expected at /x"))

    info = compiler.detect_scorpion()

    assert info.cc == "/bin/riscv64-elf-gcc"
    assert info.can_compile is True


def test_detect_scorpion_no_cross_compiler(monkeypatch) -> None:
    monkeypatch.setattr(compiler.shutil, "which", lambda n: None)

    info = compiler.detect_scorpion()

    assert info.cc is None
    assert info.can_compile is False
    assert info.can_emit_dynamic is False


def test_prefers_riscv32_candidate(monkeypatch) -> None:
    monkeypatch.setattr(compiler.shutil, "which", lambda n: f"/bin/{n}")
    monkeypatch.setattr(compiler, "_scorpion_elf2sef_path", lambda: ("/x/elf2sef.py", ""))

    info = compiler.detect_scorpion()

    assert info.cc == "/bin/riscv32-unknown-elf-gcc"


def test_can_emit_dynamic_requires_both(monkeypatch) -> None:
    monkeypatch.setattr(compiler.shutil, "which", lambda n: f"/bin/{n}")
    monkeypatch.setattr(compiler, "_scorpion_elf2sef_path", lambda: (None, "expected at /x"))

    assert compiler.detect_scorpion().can_emit_dynamic is False

    monkeypatch.setattr(compiler, "_scorpion_elf2sef_path", lambda: ("/x/elf2sef.py", ""))
    assert compiler.detect_scorpion().can_emit_dynamic is True


# ---------------------------------------------------------------------------
# _elf2sef_for — mirrors the compiler's WEW-scorpion lookup
# ---------------------------------------------------------------------------


def test_elf2sef_prefers_bundled_copy(tmp_path) -> None:
    """cpyte >= 4.3.2 ships elf2sef.py inside the package; that wins."""
    runtime_c = _make_runtime(tmp_path)
    bundled = runtime_c.parent / "elf2sef.py"
    bundled.write_text("# bundled converter")

    # a stale sibling checkout must not take precedence
    sibling = tmp_path / "lib" / "WEW-scorpion" / "tools"
    sibling.mkdir(parents=True)
    (sibling / "elf2sef.py").write_text("# sibling converter")

    found, error = compiler._elf2sef_for(str(runtime_c))

    assert error == ""
    assert found == str(bundled)


def test_elf2sef_falls_back_to_sibling_checkout(tmp_path) -> None:
    """Older cpyte releases only find the converter in a source checkout."""
    runtime_c = _make_runtime(tmp_path)
    base = tmp_path / "lib" / "WEW-scorpion" / "tools"
    base.mkdir(parents=True)
    (base / "elf2sef.py").write_text("# sibling converter")

    found, error = compiler._elf2sef_for(str(runtime_c))

    assert error == ""
    assert found is not None
    assert "WEW-scorpion" in found


def test_elf2sef_missing_names_both_fallbacks(tmp_path) -> None:
    runtime_c = _make_runtime(tmp_path)
    found, error = compiler._elf2sef_for(str(runtime_c))

    assert found is None
    assert "not bundled" in error
    assert "WEW-scorpion" in error
    assert "4.3.2" in error


def test_elf2sef_lookup_is_relative_to_install_prefix(tmp_path) -> None:
    """Resolution is anchored to the install prefix, not the current directory."""
    elsewhere = tmp_path / "somewhere" / "else"
    elsewhere.mkdir(parents=True)
    _make_runtime(tmp_path)
    _make_runtime(elsewhere)
    (tmp_path / "lib" / "WEW-scorpion" / "tools").mkdir(parents=True)
    (tmp_path / "lib" / "WEW-scorpion" / "tools" / "elf2sef.py").write_text("# conv")

    _, error = compiler._elf2sef_for(str(_make_runtime(elsewhere)))

    # a different install prefix must not see the first prefix's converter
    assert "WEW-scorpion" in error


def test_scorpion_runtime_c_falls_back_to_local_import(monkeypatch) -> None:
    """`python -m cpyte` runs in our own environment, so use the local module."""
    monkeypatch.setattr(compiler, "compiler_command", lambda: ["python", "-m", "cpyte"])
    runtime_c, error = compiler._scorpion_runtime_c()
    assert error == ""
    assert runtime_c and runtime_c.endswith("runtime_scorpion.c")


def test_scorpion_runtime_c_queries_the_binary_interpreter(monkeypatch, tmp_path) -> None:
    """The `cpy` binary can be a different cpyte than the one we imported."""
    binary = tmp_path / "cpy"
    binary.write_text("#!/usr/bin/env fake-python3\n")

    seen: dict = {}

    class FakeResult:
        returncode = 0
        stdout = "/somewhere/else/cpyte/runtime_scorpion.c\n"
        stderr = ""

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        return FakeResult()

    monkeypatch.setattr(compiler, "compiler_command", lambda: [str(binary)])
    monkeypatch.setattr(compiler.subprocess, "run", fake_run)

    runtime_c, error = compiler._scorpion_runtime_c()

    assert error == ""
    assert runtime_c == "/somewhere/else/cpyte/runtime_scorpion.c"
    # `env fake-python3` must resolve to the interpreter, not the word "env"
    assert seen["cmd"][0] == "fake-python3"


def test_scorpion_runtime_c_reports_missing_cpyte(monkeypatch, tmp_path) -> None:
    binary = tmp_path / "cpy"
    binary.write_text("#!/usr/bin/python3\n")

    class FakeResult:
        returncode = 1
        stdout = ""
        stderr = "ModuleNotFoundError: No module named 'cpyte'\n"

    monkeypatch.setattr(compiler, "compiler_command", lambda: [str(binary)])
    monkeypatch.setattr(compiler.subprocess, "run", lambda *a, **k: FakeResult())

    runtime_c, error = compiler._scorpion_runtime_c()

    assert runtime_c is None
    assert "cpyte" in error


def test_scorpion_runtime_c_rejects_missing_shebang(monkeypatch, tmp_path) -> None:
    binary = tmp_path / "cpy"
    binary.write_text("not a script\n")

    monkeypatch.setattr(compiler, "compiler_command", lambda: [str(binary)])

    runtime_c, error = compiler._scorpion_runtime_c()

    assert runtime_c is None
    assert "interpreter" in error


def test_elf2sef_path_reports_missing_runtime(monkeypatch) -> None:
    monkeypatch.setattr(
        compiler, "_scorpion_runtime_c", lambda: ("/nope/runtime_scorpion.c", "")
    )
    found, error = compiler._scorpion_elf2sef_path()

    assert found is None
    assert "runtime_scorpion.c" in error


# ---------------------------------------------------------------------------
# Spinner failure reporting
# ---------------------------------------------------------------------------


def test_spinner_success_prints_done(capsys, monkeypatch) -> None:
    monkeypatch.setattr(style, "_tty", lambda: False)
    with style.Spinner("compiling"):
        pass
    assert "done" in capsys.readouterr().out


def test_spinner_fail_prints_failed(capsys, monkeypatch) -> None:
    monkeypatch.setattr(style, "_tty", lambda: False)
    with style.Spinner("compiling") as sp:
        sp.fail()
    out = capsys.readouterr().out
    assert "failed" in out
    assert "done" not in out


def test_spinner_exception_marks_failed(capsys, monkeypatch) -> None:
    monkeypatch.setattr(style, "_tty", lambda: False)
    with pytest.raises(ValueError):
        with style.Spinner("compiling"):
            raise ValueError("boom")
    assert "failed" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# _explain_scorpion_failure
# ---------------------------------------------------------------------------


def test_explain_mentions_toolchain_when_absent(monkeypatch, capfd) -> None:
    monkeypatch.setattr(
        things.cpyte_toolchain,
        "detect_scorpion",
        lambda: compiler.ScorpionInfo(),
    )
    things._explain_scorpion_failure(pic=True)
    out = capfd.readouterr().err
    assert "riscv" in out
    assert "present" not in out


def test_explain_blames_converter_not_toolchain(monkeypatch, capfd) -> None:
    monkeypatch.setattr(
        things.cpyte_toolchain,
        "detect_scorpion",
        lambda: compiler.ScorpionInfo(
            cc="/opt/homebrew/bin/riscv64-elf-gcc",
            elf2sef=None,
            elf2sef_error="expected at /opt/homebrew/WEW-scorpion/tools/elf2sef.py",
        ),
    )
    things._explain_scorpion_failure(pic=True)
    out = capfd.readouterr().err

    # toolchain is present, so the old "install riscv" advice must be gone
    assert "is present" in out
    assert "converter is not installed" in out
    assert "pic = false" in out
    assert "Install the RISC-V toolchain" not in out


def test_explain_static_failure_defers_to_compiler(monkeypatch, capfd) -> None:
    monkeypatch.setattr(
        things.cpyte_toolchain,
        "detect_scorpion",
        lambda: compiler.ScorpionInfo(
            cc="/opt/homebrew/bin/riscv64-elf-gcc",
            elf2sef=None,
            elf2sef_error="missing",
        ),
    )
    things._explain_scorpion_failure(pic=False)
    out = capfd.readouterr().err
    assert "compiler output above" in out
