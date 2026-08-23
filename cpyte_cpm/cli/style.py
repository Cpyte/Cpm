"""Terminal styling utilities for CPM.

Provides colored output with automatic TTY detection and NO_COLOR support,
plus terminal effects: gradient banners, animated spinners, progress bars,
box panels, and a rich status glyph set. Pure ANSI — no external deps.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from collections.abc import Iterator
from typing import Any

# ---------------------------------------------------------------------------
# Terminal capability detection
# ---------------------------------------------------------------------------

_NO_COLOR = os.environ.get("NO_COLOR") is not None
_FORCE_COLOR = os.environ.get("FORCE_COLOR") is not None
_IS_TTY = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()
_IS_ERR_TTY = hasattr(sys.stderr, "isatty") and sys.stderr.isatty()


def _supports_color() -> bool:
    if _NO_COLOR:
        return False
    if _FORCE_COLOR:
        return True
    if not (_IS_TTY or _IS_ERR_TTY):
        return False
    term = os.environ.get("TERM", "")
    if "dumb" in term:
        return False
    return True


_COLORS = _supports_color()


def _tty() -> bool:
    """True if we should animate (TTY + color + not quiet)."""
    return _COLORS and _IS_TTY and not _QUIET


# ---------------------------------------------------------------------------
# ANSI codes
# ---------------------------------------------------------------------------

class Color:
    """ANSI color codes."""
    RESET = "\033[0m" if _COLORS else ""
    BOLD = "\033[1m" if _COLORS else ""
    DIM = "\033[2m" if _COLORS else ""
    ITALIC = "\033[3m" if _COLORS else ""
    UNDERLINE = "\033[4m" if _COLORS else ""
    BLINK = "\033[5m" if _COLORS else ""
    REVERSE = "\033[7m" if _COLORS else ""
    STRIKE = "\033[9m" if _COLORS else ""

    RED = "\033[31m" if _COLORS else ""
    GREEN = "\033[32m" if _COLORS else ""
    YELLOW = "\033[33m" if _COLORS else ""
    BLUE = "\033[34m" if _COLORS else ""
    MAGENTA = "\033[35m" if _COLORS else ""
    CYAN = "\033[36m" if _COLORS else ""
    WHITE = "\033[37m" if _COLORS else ""

    BOLD_RED = "\033[1;31m" if _COLORS else ""
    BOLD_GREEN = "\033[1;32m" if _COLORS else ""
    BOLD_YELLOW = "\033[1;33m" if _COLORS else ""
    BOLD_BLUE = "\033[1;34m" if _COLORS else ""
    BOLD_CYAN = "\033[1;36m" if _COLORS else ""
    BOLD_MAGENTA = "\033[1;35m" if _COLORS else ""


# Glyphs (ASCII, no emoji)
GLYPH_OK = "\u2713"      # ✓
GLYPH_BAD = "\u2717"     # ✗
GLYPH_WARN = "\u26a0"    # ⚠
GLYPH_ARROW = "\u25b8"   # ▸
GLYPH_DOT = "\u25cf"     # ●
GLYPH_SPIN = "\u25d0"    # ◐
GLYPH_CHECKBOX = "\u2610"  # ☐

SPINNER_FRAMES = ["\u25d0", "\u25d3", "\u25d1", "\u25d2"]  # ◐ ◓ ◑ ◒
# Fallback spinner for narrow terminals
_SPINNER_ASCII = ["|", "/", "-", "\\"]


# ---------------------------------------------------------------------------
# Gradient helpers
# ---------------------------------------------------------------------------

def _rgb(code: int) -> tuple[int, int, int]:
    return ((code >> 16) & 0xFF, (code >> 8) & 0xFF, code & 0xFF)


def _fg(rgb: tuple[int, int, int]) -> str:
    if not _COLORS:
        return ""
    return f"\033[38;2;{rgb[0]};{rgb[1]};{rgb[2]}m"


def _bg(rgb: tuple[int, int, int]) -> str:
    if not _COLORS:
        return ""
    return f"\033[48;2;{rgb[0]};{rgb[1]};{rgb[2]}m"


def _lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))  # type: ignore[return-value]


def gradient(text: str, start=(0, 168, 255), end=(0, 255, 136), bold: bool = True) -> str:
    """Render text with a horizontal color gradient."""
    if not _COLORS or not text:
        return text
    out = []
    n = max(len(text) - 1, 1)
    for i, ch in enumerate(text):
        c = _lerp(start, end, i / n)
        out.append(_fg(c) + ch)
    return "".join(out) + Color.RESET


def rainbow(text: str) -> str:
    """Rainbow gradient text."""
    palette = [
        (255, 51, 51), (255, 170, 51), (255, 255, 51),
        (51, 255, 51), (51, 255, 255), (51, 102, 255), (170, 51, 255),
    ]
    out = []
    for i, ch in enumerate(text):
        out.append(_fg(palette[i % len(palette)]) + ch)
    return "".join(out) + Color.RESET


# ---------------------------------------------------------------------------
# Global flags
# ---------------------------------------------------------------------------

_QUIET = False
_JSON_MODE = False


def set_quiet(quiet: bool):
    global _QUIET
    _QUIET = quiet


def set_json_mode(enabled: bool):
    global _JSON_MODE
    _JSON_MODE = enabled


def is_quiet() -> bool:
    return _QUIET


def is_json_mode() -> bool:
    return _JSON_MODE


# ---------------------------------------------------------------------------
# Basic messages
# ---------------------------------------------------------------------------

def print_error(msg: str, file=sys.stderr):
    """Print an error message to stderr."""
    print(f"{Color.BOLD_RED}{GLYPH_BAD} error:{Color.RESET} {msg}", file=file)


def print_warning(msg: str, file=sys.stderr):
    """Print a warning message to stderr."""
    if not _QUIET:
        print(f"{Color.BOLD_YELLOW}{GLYPH_WARN} warning:{Color.RESET} {msg}", file=file)


def print_success(msg: str):
    """Print a success message."""
    if not _QUIET:
        print(f"{Color.GREEN}{GLYPH_OK} {msg}{Color.RESET}")


def print_info(msg: str):
    """Print an info message."""
    if not _QUIET:
        print(msg)


def print_verbose(msg: str):
    """Print a verbose-only message."""
    if not _QUIET:
        print(f"{Color.DIM}{msg}{Color.RESET}")


def print_ok(msg: str):
    """Print a green ok-line."""
    print_success(msg)


def print_package(name: str, version: str = None):
    """Print a styled package name."""
    if version:
        return f"{Color.CYAN}{name}{Color.RESET}@{Color.BOLD}{version}{Color.RESET}"
    return f"{Color.CYAN}{name}{Color.RESET}"


def print_status(status: str, msg: str):
    """Print a status line with colored prefix."""
    if not _QUIET:
        print(f"  {status} {msg}")


def print_header(msg: str):
    """Print a section header."""
    if not _QUIET:
        print(f"\n{Color.BOLD}{GLYPH_ARROW} {msg}{Color.RESET}")


def print_step(current: int, total: int, msg: str):
    """Print a step indicator like [1/5] message."""
    if not _QUIET:
        tag = f"[{Color.BOLD_CYAN}{current}/{total}{Color.RESET}]"
        print(f"{tag} {msg}")


def print_download(name: str, version: str, size: int = None):
    """Print a download status with optional size."""
    if not _QUIET:
        pkg = print_package(name, version)
        if size:
            size_str = _format_size(size)
            print(f"  {Color.BLUE}{GLYPH_ARROW} downloading{Color.RESET} {pkg} ({size_str})...")
        else:
            print(f"  {Color.BLUE}{GLYPH_ARROW} downloading{Color.RESET} {pkg}...")


def print_installed(name: str, version: str, mode: str = "source", cached: bool = False):
    """Print an installed status message."""
    if not _QUIET:
        pkg = print_package(name, version)
        source = f" [{mode}]" if mode else ""
        cache = f" {Color.DIM}(cached){Color.RESET}" if cached else ""
        print(f"  {Color.GREEN}{GLYPH_OK} installed{Color.RESET} {pkg}{source}{cache}")


def print_removed(name: str):
    """Print a removed status message."""
    if not _QUIET:
        print(f"  {Color.RED}{GLYPH_BAD} removed{Color.RESET} {print_package(name)}")


def print_skipped(name: str, version: str, reason: str):
    """Print a skipped status message."""
    if not _QUIET:
        pkg = print_package(name, version)
        print(f"  {Color.DIM}{GLYPH_DOT} skipped{Color.RESET} {pkg} ({reason})")


def print_already_installed(name: str, version: str):
    """Print already installed status."""
    if not _QUIET:
        pkg = print_package(name, version)
        print(f"  {Color.DIM}{GLYPH_DOT} exists{Color.RESET} {pkg}")


def _format_size(size_bytes: int) -> str:
    """Format bytes to human readable string."""
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.0f}{unit}" if unit == "B" else f"{size_bytes:.1f}{unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f}TB"


# ---------------------------------------------------------------------------
# Effects: banner, panels, spinner, progress
# ---------------------------------------------------------------------------

_BANNER_ART = [
    "  ____ ____  __  __ ",
    " / ___|  _ \\|  \\/  |",
    "| |   | |_) | |\\/| |",
    "| |___|  __/| |  | |",
    " \\____|_|   |_|  |_|",
]


def banner(title: str = None):
    """Print a gradient CPM banner."""
    if _QUIET or not _COLORS:
        return
    for line in _BANNER_ART:
        print(gradient(line, start=(0, 120, 255), end=(0, 255, 170)))
    if title:
        print(f"  {Color.BOLD}{title}{Color.RESET}")
    print()


def box(title: str, lines: list[str], color="BOLD_CYAN"):
    """Draw a box panel with a title and content lines."""
    if _QUIET:
        return
    width = max([len(l) for l in lines] + [len(title)]) + 4
    border = getattr(Color, color, "BOLD_CYAN")
    top = "┌─ " + title + " " + "─" * (width - len(title) - 2) + "┐"
    print(f"{border}{top}{Color.RESET}")
    for line in lines:
        print(f"{border}│{Color.RESET} {line}")
    bottom = "└" + "─" * (width - 1) + "┘"
    print(f"{border}{bottom}{Color.RESET}")


def pipeline():
    """Print the CPM pipeline diagram."""
    if _QUIET:
        return
    stages = [
        ("Resolve", Color.BLUE),
        ("Lower", Color.CYAN),
        ("Optimize", Color.MAGENTA),
        ("Execute", Color.GREEN),
    ]
    parts = []
    for name, col in stages:
        parts.append(f"{Color.BOLD}{col}{name}{Color.RESET}")
    line = "  " + f" {Color.DIM}{GLYPH_ARROW}{Color.RESET} ".join(parts)
    print(line)


class Spinner:
    """Animated spinner for long-running operations.

    Usage:
        with Spinner("resolving packages") as sp:
            ...work...
            sp.set_text("downloading...")
    """

    def __init__(self, text: str = "", file=None):
        self.text = text
        self.file = file or sys.stdout
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._frames = SPINNER_FRAMES if _COLORS else _SPINNER_ASCII

    def __enter__(self) -> Spinner:
        if _tty():
            self._thread = threading.Thread(target=self._animate, daemon=True)
            self._stop.clear()
            self._thread.start()
        else:
            self._print_static()
        return self

    def __exit__(self, *exc) -> None:
        if self._thread:
            self._stop.set()
            self._thread.join(timeout=0.3)
            sys.stdout.write("\r" + " " * (len(self._line()) + 4) + "\r")
            sys.stdout.flush()
        self._print_done()

    def set_text(self, text: str):
        self.text = text

    def _line(self) -> str:
        return f" {GLYPH_SPIN} {self.text}" if self.text else " working..."

    def _animate(self):
        idx = 0
        while not self._stop.is_set():
            frame = self._frames[idx % len(self._frames)]
            line = f"\r{Color.BOLD_CYAN}{frame}{Color.RESET} {self.text}"
            sys.stdout.write(line)
            sys.stdout.flush()
            idx += 1
            self._stop.wait(0.1)

    def _print_static(self):
        if self.text and not _QUIET:
            print(f"  {Color.DIM}{GLYPH_ARROW} {self.text}...{Color.RESET}")

    def _print_done(self):
        if _tty() or not self.text:
            return
        print(f"  {Color.GREEN}{GLYPH_OK} {self.text} — done{Color.RESET}")


def progress_bar(iterable: Iterator[Any], total: int = None, label: str = "", width: int = 24) -> Iterator[Any]:
    """Iterate with an inline progress bar. Yields items from iterable."""
    total = total or len(iterable)  # type: ignore[arg-type]
    animate = _tty()
    done = 0
    for item in iterable:
        done += 1
        pct = done / total if total else 1.0
        filled = int(width * pct)
        bar = ("\u2588" * filled) + ("\u2591" * (width - filled))
        line = f"\r  {Color.CYAN}{bar}{Color.RESET} {Color.BOLD}{done:>{len(str(total))}}/{total}{Color.RESET} {label}"
        if animate:
            sys.stdout.write(line)
            sys.stdout.flush()
        yield item
    if animate:
        sys.stdout.write("\r" + " " * (len(line) + 4) + "\r")  # type: ignore[possibly-undefined]
        sys.stdout.flush()


def pulse(seconds: float = 0.15):
    """Print a short animated pulse line for fun."""
    if not _tty():
        return
    for i in range(6):
        dots = "\u25cf" * (i + 1)
        sys.stdout.write(f"\r  {gradient(dots)}")
        sys.stdout.flush()
        time.sleep(seconds)
    sys.stdout.write("\r" + " " * 20 + "\r")
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# JSON output
# ---------------------------------------------------------------------------

class JsonOutput:
    """Context manager for JSON output mode."""

    def __init__(self):
        self.data: dict[str, Any] = {}

    def set(self, key: str, value: Any):
        self.data[key] = value
        return self

    def add_item(self, key: str, item: dict):
        if key not in self.data:
            self.data[key] = []
        self.data[key].append(item)
        return self

    def print(self):
        if _JSON_MODE:
            print(json.dumps(self.data, indent=2))
