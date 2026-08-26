"""Tests for cpytoml manifest parsing, including the scorpion and sef flags."""

from __future__ import annotations

from cpyte_cpm.cli.manifest import (
    MANIFEST_NAME,
    Manifest,
    find_manifest,
    read_manifest,
    write_manifest,
)


def test_manifest_default_scorpion_is_false() -> None:
    manifest = Manifest()
    assert manifest.scorpion is False


def test_manifest_default_sef_is_false() -> None:
    manifest = Manifest()
    assert manifest.sef is False


def test_manifest_round_trip_scorpion(tmp_path) -> None:
    manifest = Manifest(
        name="demo",
        version="1.0",
        prebuilt=True,
        scorpion=True,
        path=tmp_path / "cpy.toml",
    )
    write_manifest(manifest)

    reloaded = read_manifest(tmp_path / "cpy.toml")
    assert reloaded.scorpion is True
    assert reloaded.prebuilt is True


def test_manifest_round_trip_sef(tmp_path) -> None:
    manifest = Manifest(
        name="demo",
        version="1.0",
        sef=True,
        path=tmp_path / "cpy.toml",
    )
    write_manifest(manifest)

    reloaded = read_manifest(tmp_path / "cpy.toml")
    assert reloaded.sef is True


def test_manifest_parse_scorpion_disabled(tmp_path) -> None:
    path = tmp_path / "cpy.toml"
    path.write_text('[cpm]\nname = "demo"\nscorpion = false\n')

    reloaded = read_manifest(path)
    assert reloaded.scorpion is False


def test_manifest_parse_sef_disabled(tmp_path) -> None:
    path = tmp_path / "cpy.toml"
    path.write_text('[cpm]\nname = "demo"\nsef = false\n')

    reloaded = read_manifest(path)
    assert reloaded.sef is False


def test_manifest_serializes_scorpion_key(tmp_path) -> None:
    manifest = Manifest(scorpion=True, path=tmp_path / "cpy.toml")
    text = manifest.toml_str()
    assert "scorpion = true" in text


def test_manifest_serializes_sef_key(tmp_path) -> None:
    manifest = Manifest(sef=True, path=tmp_path / "cpy.toml")
    text = manifest.toml_str()
    assert "sef = true" in text


def test_manifest_build_defaults_pic_true() -> None:
    manifest = Manifest()
    assert manifest.build.pic is True
    assert manifest.build.exports == []
    assert manifest.build.main == ""


def test_manifest_parse_build_section(tmp_path) -> None:
    path = tmp_path / "cpy.toml"
    path.write_text(
        "[cpm]\n"
        'name = "libbignum"\n'
        "scorpion = true\n\n"
        "[cpm.build]\n"
        'main = "lib.cpy"\n'
        "pic = false\n"
        'exports = ["bigint_add", "bigint_print"]\n'
    )

    reloaded = read_manifest(path)
    assert reloaded.scorpion is True
    assert reloaded.build.main == "lib.cpy"
    assert reloaded.build.pic is False
    assert reloaded.build.exports == ["bigint_add", "bigint_print"]


def test_manifest_build_round_trip(tmp_path) -> None:
    manifest = Manifest(
        name="demo",
        scorpion=True,
        path=tmp_path / "cpy.toml",
    )
    manifest.build.main = "main.cpy"
    manifest.build.pic = False
    manifest.build.exports = ["bigint_add"]
    write_manifest(manifest)

    reloaded = read_manifest(tmp_path / "cpy.toml")
    assert reloaded.build.main == "main.cpy"
    assert reloaded.build.pic is False
    assert reloaded.build.exports == ["bigint_add"]


def test_find_manifest_prefers_cpy_toml_with_legacy_fallback(tmp_path):
    """cpy.toml wins; extensionless cpytoml is still discovered."""
    (tmp_path / "cpytoml").write_text('[cpm]\nname = "legacy"\nversion = "1.0.0"\n')
    assert find_manifest(tmp_path) == tmp_path / "cpytoml"
    assert read_manifest(find_manifest(tmp_path)).name == "legacy"

    (tmp_path / "cpy.toml").write_text('[cpm]\nname = "modern"\nversion = "2.0.0"\n')
    assert find_manifest(tmp_path) == tmp_path / "cpy.toml"
    assert read_manifest(find_manifest(tmp_path)).name == "modern"


def test_write_manifest_uses_cpy_dot_toml(tmp_path):
    m = Manifest(name="fresh", version="0.1.0")
    m.path = tmp_path / MANIFEST_NAME
    write_manifest(m)
    assert m.path.name == "cpy.toml"
    assert read_manifest(m.path).name == "fresh"
