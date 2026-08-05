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
