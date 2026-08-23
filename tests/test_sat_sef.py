"""Tests for SEF (Scorpion) resolution mode."""

from __future__ import annotations

from cpyte_cpm.cli import sat
from cpyte_cpm.cli.sat import resolve_get


class FakeRepo:
    """Minimal stand-in for fetch_repo_multi / find_package_metadata."""

    def __init__(self, metadata: dict):
        self._metadata = metadata

    def __call__(self, repos: list[str], path: str) -> dict:
        if self._metadata is None:
            raise RuntimeError(f"no metadata for {path}")
        return dict(self._metadata)


def test_instruction_marks_sef() -> None:
    inst = sat._build_instruction(
        {"name": "foo", "url": "http://x", "version": "1.0"},
        sef=True,
    )
    assert inst["sef"] is True


def test_instruction_without_sef() -> None:
    inst = sat._build_instruction(
        {"name": "foo", "url": "http://x", "version": "1.0"},
        sef=False,
    )
    assert "sef" not in inst


def test_resolve_get_sef_accepts_scorpion_package(monkeypatch) -> None:
    monkeypatch.setattr(
        sat, "fetch_repo_multi",
        FakeRepo({"name": "lib", "url": "http://x/lib.tar.gz", "version": "1.0", "scorpion": True}),
    )
    instructions = resolve_get(["lib@1.0"], ["http://repo"], sef=True)
    assert len(instructions) == 1
    assert instructions[0]["GET"] == "lib"
    assert instructions[0]["sef"] is True


def test_resolve_get_sef_accepts_sef_package(monkeypatch) -> None:
    monkeypatch.setattr(
        sat, "fetch_repo_multi",
        FakeRepo({"name": "lib", "url": "http://x/lib.tar.gz", "version": "1.0", "sef": True}),
    )
    instructions = resolve_get(["lib@1.0"], ["http://repo"], sef=True)
    assert len(instructions) == 1
    assert instructions[0]["GET"] == "lib"


def test_resolve_get_sef_skips_plain_source_package(monkeypatch) -> None:
    monkeypatch.setattr(
        sat, "fetch_repo_multi",
        FakeRepo({"name": "lib", "url": "http://x/lib.tar.gz", "version": "1.0"}),
    )
    instructions = resolve_get(["lib@1.0"], ["http://repo"], sef=True)
    assert instructions == []


def test_resolve_get_non_sef_still_resolves(monkeypatch) -> None:
    monkeypatch.setattr(
        sat, "fetch_repo_multi",
        FakeRepo({"name": "lib", "url": "http://x/lib.tar.gz", "version": "1.0"}),
    )
    instructions = resolve_get(["lib@1.0"], ["http://repo"], sef=False)
    assert len(instructions) == 1
    assert "sef" not in instructions[0]
