"""Tests for cpm.lock lockfile management, including the sef flag."""

from __future__ import annotations

from cpyte_cpm.cli.lockfile import LockEntry, Lockfile, read_lockfile, write_lockfile


def test_lockfile_default_sef_is_false() -> None:
    entry = LockEntry(name="foo", version="1.0")
    assert entry.sef is False


def test_lockfile_round_trip_sef(tmp_path) -> None:
    path = tmp_path / "cpm.lock"
    lock = Lockfile(
        path=path,
        entries=[
            LockEntry(
                name="@std/json",
                version="2.0.3",
                resolved="https://repo.example.com/group/std/json/2.0.3.tar.gz",
                checksum="sha256:abc123",
                sef=True,
            )
        ],
    )
    write_lockfile(lock)

    reloaded = read_lockfile(path)
    assert len(reloaded.entries) == 1
    assert reloaded.entries[0].sef is True


def test_lockfile_serializes_sef_key(tmp_path) -> None:
    lock = Lockfile(
        entries=[LockEntry(name="foo", version="1.0", sef=True)],
    )
    text = lock.toml_str()
    assert "sef = true" in text


def test_lockfile_omits_sef_key_when_false(tmp_path) -> None:
    lock = Lockfile(
        entries=[LockEntry(name="foo", version="1.0", sef=False)],
    )
    text = lock.toml_str()
    assert "sef = true" not in text


def test_lockfile_parse_sef_enabled(tmp_path) -> None:
    path = tmp_path / "cpm.lock"
    path.write_text(
        '[[package]]\n'
        'name = "foo"\n'
        'version = "1.0"\n'
        "sef = true\n"
    )

    reloaded = read_lockfile(path)
    assert reloaded.entries[0].sef is True


def test_lockfile_parse_sef_disabled(tmp_path) -> None:
    path = tmp_path / "cpm.lock"
    path.write_text(
        '[[package]]\n'
        'name = "foo"\n'
        'version = "1.0"\n'
        "sef = false\n"
    )

    reloaded = read_lockfile(path)
    assert reloaded.entries[0].sef is False
