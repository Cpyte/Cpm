"""Tests for cpytoml manifest parsing, including the scorpion and sef flags."""

from __future__ import annotations

from cpyte_cpm.cli.manifest import (
    MANIFEST_NAME,
    Manifest,
    PackageSpec,
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


# ---------------------------------------------------------------------------
# Syntax handling: comments, multi-line arrays, platform-scoped tables
# ---------------------------------------------------------------------------


def test_trailing_comment_is_stripped_from_string_values(tmp_path) -> None:
    path = tmp_path / "cpy.toml"
    path.write_text(
        '[cpm]\nname = "my-app"   # the project\nversion = "1.2"  # semver\n'
    )

    reloaded = read_manifest(path)
    assert reloaded.name == "my-app"
    assert reloaded.version == "1.2"


def test_trailing_comment_does_not_flip_boolean_values(tmp_path) -> None:
    path = tmp_path / "cpy.toml"
    path.write_text(
        "[cpm]\n"
        'name = "demo"\n'
        "sef = true   # install SEF artifacts\n"
        "\n"
        "[cpm.build]\n"
        "pic = true               # dynamic SEF v2\n"
    )

    reloaded = read_manifest(path)
    assert reloaded.sef is True
    assert reloaded.build.pic is True


def test_hash_inside_quoted_value_is_kept(tmp_path) -> None:
    path = tmp_path / "cpy.toml"
    path.write_text('[cpm]\nname = "rel#1"\n')

    assert read_manifest(path).name == "rel#1"


def test_multiline_array_is_parsed(tmp_path) -> None:
    path = tmp_path / "cpy.toml"
    path.write_text(
        "[cpm]\n"
        'name = "demo"\n'
        "repos = [\n"
        '  "https://a.example.com",\n'
        '  "https://b.example.com",\n'
        "]\n"
        "\n"
        "[cpm.target]\n"
        "features = [\n"
        '  "ssl",  # required by @std/http\n'
        '  "gui",\n'
        "]\n"
    )

    reloaded = read_manifest(path)
    assert reloaded.repos == ["https://a.example.com", "https://b.example.com"]
    assert reloaded.target.features == ["ssl", "gui"]


def test_array_item_with_comma_is_one_item(tmp_path) -> None:
    path = tmp_path / "cpy.toml"
    path.write_text('[cpm]\nrepos = ["https://a.example.com/?a=1,2"]\n')

    assert read_manifest(path).repos == ["https://a.example.com/?a=1,2"]


def test_platform_scoped_dependencies_use_manifest_target(tmp_path) -> None:
    path = tmp_path / "cpy.toml"
    path.write_text(
        "[cpm.target]\n"
        'os = "linux"\n'
        "\n"
        "[cpm.dependencies]\n"
        '"@std/json" = "^2.0"\n'
        "\n"
        "[cpm.dependencies.linux]\n"
        '"posix-api" = "1.0"\n'
        "\n"
        "[cpm.dependencies.windows]\n"
        '"win32-api" = "1.0"\n'
    )

    names = [p.name for p in read_manifest(path).packages]
    assert names == ["@std/json", "posix-api"]


def test_platform_scoped_dependencies_honour_target_override(tmp_path) -> None:
    path = tmp_path / "cpy.toml"
    path.write_text(
        "[cpm.dependencies]\n"
        '"@std/json" = "^2.0"\n'
        "\n"
        "[cpm.dependencies.windows]\n"
        '"win32-api" = "1.0"\n'
    )

    reloaded = read_manifest(path, target_os="windows")
    assert [p.name for p in reloaded.packages] == ["@std/json", "win32-api"]


def test_platform_scoped_dependency_overrides_common_version(tmp_path) -> None:
    path = tmp_path / "cpy.toml"
    path.write_text(
        "[cpm.target]\n"
        'os = "linux"\n'
        "\n"
        "[cpm.dependencies]\n"
        '"posix-api" = "1.0"\n'
        "\n"
        "[cpm.dependencies.linux]\n"
        '"posix-api" = "2.0"\n'
    )

    reloaded = read_manifest(path)
    assert [(p.name, p.version) for p in reloaded.packages] == [("posix-api", "2.0")]


def test_quoted_keys_with_trailing_comment(tmp_path) -> None:
    path = tmp_path / "cpy.toml"
    path.write_text(
        "[cpm]\n"
        'name = "x"\n'
        "\n"
        "[cpm.bin]\n"
        '"@scope/cli" = "tools/x.cpy"   # launcher\n'
    )

    assert read_manifest(path).bin == {"@scope/cli": "tools/x.cpy"}


def test_manifest_writer_output_is_reparsable(tmp_path) -> None:
    m = Manifest(
        name='quote"name',
        version="1.0",
        repos=["https://a.example.com/?a=1,2"],
        path=tmp_path / "cpy.toml",
    )
    m.target.features = ['gui', "it's"]
    m.build.exports = ["a", "b"]
    m.add(PackageSpec.parse("@std/json@^2.0"))
    write_manifest(m)

    reloaded = read_manifest(m.path)
    assert reloaded.name == 'quote"name'
    assert reloaded.repos == ["https://a.example.com/?a=1,2"]
    assert reloaded.target.features == ["gui", "it's"]
    assert reloaded.build.exports == ["a", "b"]
    assert [(p.name, p.version) for p in reloaded.packages] == [("@std/json", "^2.0")]


def test_rewrite_keeps_platform_scoped_tables(tmp_path) -> None:
    path = tmp_path / "cpy.toml"
    path.write_text(
        "[cpm.dependencies]\n"
        '"@std/json" = "^2.0"\n'
        "\n"
        "[cpm.dependencies.linux]\n"
        '"posix-api" = "1.0"\n'
        "\n"
        "[cpm.dependencies.windows]\n"
        '"win32-api" = "1.0"\n'
    )

    m = read_manifest(path, target_os="linux")
    m.add(PackageSpec.parse("newdep@1.2.3"))
    write_manifest(m)

    text = path.read_text()
    assert "[cpm.dependencies.linux]" in text
    assert "[cpm.dependencies.windows]" in text
    # the linux-scoped package must not be widened to the common table
    common, _, scoped = text.partition("[cpm.dependencies.linux]")
    assert '"posix-api"' not in common
    assert '"@std/json" = "^2.0"' in common
    assert '"newdep" = "1.2.3"' in common
    assert '"posix-api" = "1.0"' in scoped


def test_version_bump_of_scoped_package_stays_scoped(tmp_path) -> None:
    path = tmp_path / "cpy.toml"
    path.write_text('[cpm.dependencies.linux]\n"posix-api" = "1.0"\n')

    m = read_manifest(path, target_os="linux")
    m.add(PackageSpec.parse("posix-api@3.0.0"))
    write_manifest(m)

    assert '"posix-api" = "3.0.0"' in path.read_text()
    reloaded = read_manifest(path, target_os="linux")
    assert [(p.name, p.version) for p in reloaded.packages] == [("posix-api", "3.0.0")]


def test_remove_drops_scoped_package_everywhere(tmp_path) -> None:
    path = tmp_path / "cpy.toml"
    path.write_text(
        "[cpm.dependencies]\n"
        '"@std/json" = "^2.0"\n'
        "\n"
        "[cpm.dependencies.linux]\n"
        '"posix-api" = "1.0"\n'
    )

    m = read_manifest(path, target_os="linux")
    assert m.remove("posix-api") is True
    write_manifest(m)

    reloaded = read_manifest(path, target_os="linux")
    assert [(p.name, p.version) for p in reloaded.packages] == [("@std/json", "^2.0")]
    assert "posix-api" not in path.read_text()
