"""Tests for cpytoml manifest parsing, including the scorpion flag."""

from __future__ import annotations

from cpyte_cpm.cli.manifest import Manifest, read_manifest, write_manifest


def test_manifest_default_scorpion_is_false() -> None:
    manifest = Manifest()
    assert manifest.scorpion is False


def test_manifest_round_trip_scorpion(tmp_path) -> None:
    manifest = Manifest(
        name="demo",
        version="1.0",
        prebuilt=True,
        scorpion=True,
        path=tmp_path / "cpytoml",
    )
    write_manifest(manifest)

    reloaded = read_manifest(tmp_path / "cpytoml")
    assert reloaded.scorpion is True
    assert reloaded.prebuilt is True


def test_manifest_parse_scorpion_disabled(tmp_path) -> None:
    path = tmp_path / "cpytoml"
    path.write_text('[cpm]\nname = "demo"\nscorpion = false\n')

    reloaded = read_manifest(path)
    assert reloaded.scorpion is False


def test_manifest_serializes_scorpion_key(tmp_path) -> None:
    manifest = Manifest(scorpion=True, path=tmp_path / "cpytoml")
    text = manifest.toml_str()
    assert "scorpion = true" in text


def test_manifest_build_defaults_pic_true() -> None:
    manifest = Manifest()
    assert manifest.build.pic is True
    assert manifest.build.exports == []
    assert manifest.build.main == ""


def test_manifest_parse_build_section(tmp_path) -> None:
    path = tmp_path / "cpytoml"
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
        path=tmp_path / "cpytoml",
    )
    manifest.build.main = "main.cpy"
    manifest.build.pic = False
    manifest.build.exports = ["bigint_add"]
    write_manifest(manifest)

    reloaded = read_manifest(tmp_path / "cpytoml")
    assert reloaded.build.main == "main.cpy"
    assert reloaded.build.pic is False
    assert reloaded.build.exports == ["bigint_add"]
