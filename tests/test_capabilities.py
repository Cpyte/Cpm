"""Tests for capability-aware resolution against the installed toolchain."""

from __future__ import annotations

from cpyte_cpm.cli.sat import _matches_toolchain, _version_satisfies


def test_version_satisfies_bare_version_requires_major_match() -> None:
    assert _version_satisfies("2.7.0", "2.7.2")
    assert _version_satisfies("2.0", "2.9.1")
    assert not _version_satisfies("2.0", "3.0.0")


def test_version_satisfies_specifiers() -> None:
    assert _version_satisfies(">=2.7.0", "2.7.2")
    assert _version_satisfies(">=22", "22.1.0")
    assert not _version_satisfies(">=2.8.0", "2.7.2")
    assert _version_satisfies("<23", "22.1.0")
    assert _version_satisfies("==2.7.2", "2.7.2")
    assert not _version_satisfies("==2.7.2", "2.7.1")
    assert _version_satisfies(">=2.7,<2.8", "2.7.2")
    assert not _version_satisfies(">=2.7,<2.8", "2.8.0")


def test_version_satisfies_empty_or_invalid() -> None:
    assert _version_satisfies("", "2.7.2")
    assert _version_satisfies(">=x.y", "2.7.2")  # unparseable → assume compatible


def test_matches_toolchain_no_requirements_passes() -> None:
    assert _matches_toolchain({}, {"compiler": "2.7.2"}) == (True, "")
    assert _matches_toolchain(None, {}) == (True, "")


def test_matches_toolchain_compiler_ok() -> None:
    required = {"compiler": ">=2.7.0"}
    detected = {"compiler": "2.7.2"}
    assert _matches_toolchain(required, detected) == (True, "")


def test_matches_toolchain_compiler_too_old() -> None:
    required = {"compiler": ">=2.7.0"}
    detected = {"compiler": "2.6.1"}
    ok, reason = _matches_toolchain(required, detected)
    assert ok is False
    assert "2.7.0" in reason and "2.6.1" in reason


def test_matches_toolchain_llvm_mismatch() -> None:
    required = {"llvm": ">=22"}
    detected = {"compiler": "2.7.2", "llvm": "18.1.0"}
    ok, reason = _matches_toolchain(required, detected)
    assert ok is False
    assert "18.1.0" in reason


def test_matches_toolchain_missing_toolchain() -> None:
    required = {"compiler": ">=2.7.0"}
    assert _matches_toolchain(required, {}) == (False, "requires compiler >=2.7.0 (toolchain not detected)")


def test_matches_toolchain_unknown_codegen_feature_fails_loudly(monkeypatch) -> None:
    from cpyte_cpm.cli import sat
    monkeypatch.setattr(sat, "has_codegen_feature", lambda f: False)
    required = {"codegen": ["definitely_not_a_feature_xyz"]}
    ok, reason = _matches_toolchain(required, {"compiler": "2.7.2"})
    assert ok is False
    assert "definitely_not_a_feature_xyz" in reason


def test_matches_toolchain_codegen_satisfied(monkeypatch) -> None:
    from cpyte_cpm.cli import sat
    monkeypatch.setattr(sat, "has_codegen_feature", lambda f: True)
    required = {"codegen": ["scorpion", "setjmp"]}
    assert _matches_toolchain(required, {"compiler": "2.7.2"}) == (True, "")


def test_matches_toolchain_codegen_missing(monkeypatch) -> None:
    from cpyte_cpm.cli import sat
    monkeypatch.setattr(sat, "has_codegen_feature", lambda f: False)
    required = {"codegen": ["scorpion"]}
    ok, reason = _matches_toolchain(required, {"compiler": "2.7.2"})
    assert ok is False
    assert "scorpion" in reason


def test_matches_toolchain_all_dimensions(monkeypatch) -> None:
    from cpyte_cpm.cli import sat
    monkeypatch.setattr(sat, "has_codegen_feature", lambda f: True)
    required = {"compiler": ">=2.7.0", "llvm": ">=22", "codegen": ["scorpion"]}
    detected = {"compiler": "2.7.2", "llvm": "22.1.0"}
    ok, reason = _matches_toolchain(required, detected)
    assert ok is True, reason


def test_toolchain_capabilities_shape() -> None:
    from cpyte_cpm.compiler import toolchain_capabilities

    caps = toolchain_capabilities()
    assert isinstance(caps, dict)
    for key in ("compiler", "llvm"):
        if key in caps:
            assert isinstance(caps[key], str) and caps[key]
