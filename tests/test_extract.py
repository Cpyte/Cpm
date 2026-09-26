"""Regression tests for extraction + cache install correctness.

Covers the ~/.cpm pollution and module-layout bugs:
- archives are flattened (single root dir stripped, no nested wrapper)
- macOS/editor junk (._*, .DS_Store, __MACOSX) is never installed
- cache never leaks the .tar.gz or pre-extracted dirs into the project
- modules contain only pristine package contents, in the right place
"""

import tarfile
import zipfile
from pathlib import Path

from cpyte_cpm.cli import executor

CACHE = None


def _make_pkg_dir(root: Path, name: str = "pkgroot") -> Path:
    pkg = root / name
    (pkg / "src").mkdir(parents=True, exist_ok=True)
    (pkg / "package.json").write_text("{}")
    (pkg / "src" / "main.cpy").write_text("def main(): pass")
    return pkg


def _make_tar(path: Path, pkg_root: Path, include_junk: bool = True):
    """Create a single-root .tar.gz; optionally embed macOS junk members."""
    import io

    path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(path, "w:gz") as tf:
        for child in sorted(pkg_root.rglob("*")):
            arc = "pkgroot/" + str(child.relative_to(pkg_root))
            tf.add(child, arcname=arc)
        if include_junk:
            for j in (
                "pkgroot/._package.json",
                "._pkgroot",
                "pkgroot/._src",
                "pkgroot/src/._main.cpy",
                "__MACOSX",
                ".DS_Store",
            ):
                info = tarfile.TarInfo(name=j)
                info.size = 4
                tf.addfile(info, io.BytesIO(b"JUNK"))
    return path


# ---------------------------------------------------------------------------
# extraction: normalization
# ---------------------------------------------------------------------------


class TestExtractNormalization:
    def test_flattens_single_root_dir(self, tmp_path):
        pkg = _make_pkg_dir(tmp_path / "build")
        tar = _make_tar(tmp_path / "cache" / "1.0.tar.gz", pkg)
        dest = tmp_path / "out"
        executor._extract(tar, dest)
        assert (dest / "package.json").exists()
        assert (dest / "src" / "main.cpy").exists()
        # no nested pkgroot wrapper
        assert not (dest / "pkgroot").exists()

    def test_strips_macos_junk_from_extraction(self, tmp_path):
        pkg = _make_pkg_dir(tmp_path / "build")
        tar = _make_tar(tmp_path / "cache" / "1.0.tar.gz", pkg, include_junk=True)
        dest = tmp_path / "out"
        executor._extract(tar, dest)
        files = {str(p.relative_to(dest)) for p in dest.rglob("*") if p.is_file()}
        assert files == {"package.json", "src/main.cpy"}
        assert not any("._" in f or f in (".DS_Store", "__MACOSX") for f in files)


# ---------------------------------------------------------------------------
# cache -> module install
# ---------------------------------------------------------------------------


class TestInstallFromCache:
    def _setup_cache(self, tmp_path):
        pkg = _make_pkg_dir(tmp_path / "build")
        tar = _make_tar(
            tmp_path / "cache" / "x" / "1.0" / "1.0.tar.gz", pkg, include_junk=True
        )
        # pre-extract into cache, mimicking a prior download
        executor._extract(tar, tmp_path / "cache" / "x" / "1.0")
        return tmp_path

    def test_installs_clean_flat_layout(self, tmp_path, monkeypatch):
        monkeypatch.setattr(executor, "CACHE_DIR", tmp_path / "cache")
        self._setup_cache(tmp_path)
        executor._install_from_cache(tmp_path / "proj", "x", "1.0")
        mod = tmp_path / "proj" / ".cpm" / "modules" / "x" / "1.0"
        assert (mod / "package.json").exists()
        assert (mod / "src" / "main.cpy").exists()
        # no archive, no AppleDouble junk, no nested wrapper in the module
        files = {str(p.relative_to(mod)) for p in mod.rglob("*") if p.is_file()}
        assert files == {"package.json", "src/main.cpy"}

    def test_archives_are_selected_over_extracted_files(self, tmp_path, monkeypatch):
        """Even if cache holds extracted files + the tar, the tar is used."""
        monkeypatch.setattr(executor, "CACHE_DIR", tmp_path / "cache")
        self._setup_cache(tmp_path)
        # cache now contains 1.0.tar.gz AND package.json/src (from _extract)
        executor._install_from_cache(tmp_path / "proj", "x", "1.0")
        mod = tmp_path / "proj" / ".cpm" / "modules" / "x" / "1.0"
        assert (mod / "src" / "main.cpy").exists()
        assert not (mod / "1.0.tar.gz").exists()

    def test_removes_stale_target_first(self, tmp_path, monkeypatch):
        monkeypatch.setattr(executor, "CACHE_DIR", tmp_path / "cache")
        self._setup_cache(tmp_path)
        stale = tmp_path / "proj" / ".cpm" / "modules" / "x" / "1.0"
        (stale / "old").mkdir(parents=True)
        executor._install_from_cache(tmp_path / "proj", "x", "1.0")
        assert not (stale / "old").exists()
        assert (stale / "src" / "main.cpy").exists()
