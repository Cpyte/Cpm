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
    path.write_text('[[package]]\nname = "foo"\nversion = "1.0"\nsef = true\n')

    reloaded = read_lockfile(path)
    assert reloaded.entries[0].sef is True


def test_lockfile_parse_sef_disabled(tmp_path) -> None:
    path = tmp_path / "cpm.lock"
    path.write_text('[[package]]\nname = "foo"\nversion = "1.0"\nsef = false\n')

    reloaded = read_lockfile(path)
    assert reloaded.entries[0].sef is False


# ---------------------------------------------------------------------------
# Syntax handling: comments, multi-line arrays, quoted punctuation
# ---------------------------------------------------------------------------


def test_lockfile_trailing_comments_are_stripped(tmp_path) -> None:
    path = tmp_path / "cpm.lock"
    path.write_text(
        "[[package]]\n"
        'name = "foo"          # direct dep\n'
        'version = "1.0"\n'
        'resolved = "https://repo.example.com/foo.tar.gz"   # mirror\n'
        'checksum = "sha256:abc123"  # from registry\n'
        "sef = true   # SEF artifact\n"
    )

    entry = read_lockfile(path).entries[0]
    assert entry.name == "foo"
    assert entry.resolved == "https://repo.example.com/foo.tar.gz"
    assert entry.checksum == "sha256:abc123"
    assert entry.sef is True


def test_lockfile_multiline_dependencies_array(tmp_path) -> None:
    path = tmp_path / "cpm.lock"
    path.write_text(
        "[[package]]\n"
        'name = "foo"\n'
        'version = "1.0"\n'
        "dependencies = [\n"
        '  "@std/encoding@1.2.0",  # base\n'
        '  "@std/math@1.0.0",\n'
        "]\n"
    )

    entry = read_lockfile(path).entries[0]
    assert entry.dependencies == ["@std/encoding@1.2.0", "@std/math@1.0.0"]


def test_lockfile_value_with_comma_survives_round_trip(tmp_path) -> None:
    path = tmp_path / "cpm.lock"
    write_lockfile(
        Lockfile(
            path=path,
            entries=[
                LockEntry(
                    name="foo",
                    version="1.0",
                    resolved="https://repo.example.com/a,b.tar.gz",
                    dependencies=["dep,with,commas@1.0"],
                )
            ],
        )
    )

    entry = read_lockfile(path).entries[0]
    assert entry.resolved == "https://repo.example.com/a,b.tar.gz"
    assert entry.dependencies == ["dep,with,commas@1.0"]


def test_lockfile_keys_outside_package_block_are_ignored(tmp_path) -> None:
    path = tmp_path / "cpm.lock"
    path.write_text('version = "9.9"\n\n[[package]]\nname = "foo"\nversion = "1.0"\n')

    reloaded = read_lockfile(path)
    assert len(reloaded.entries) == 1
    assert reloaded.entries[0].version == "1.0"
