"""Terminal styling utilities for CPM.

Provides colored output with automatic TTY detection and NO_COLOR support.
"""

import os
import sys
import json
from typing import Any


# Check if terminal supports color
_NO_COLOR = os.environ.get("NO_COLOR") is not None
_FORCE_COLOR = os.environ.get("FORCE_COLOR") is not None
_IS_TTY = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def _supports_color() -> bool:
    if _NO_COLOR:
        return False
    if _FORCE_COLOR:
        return True
    if not _IS_TTY:
        return False
    term = os.environ.get("TERM", "")
    if "dumb" in term:
        return False
    return True


_COLORS = _supports_color()


class Color:
    """ANSI color codes."""
    RESET = "\033[0m" if _COLORS else ""
    BOLD = "\033[1m" if _COLORS else ""
    DIM = "\033[2m" if _COLORS else ""
    ITALIC = "\033[3m" if _COLORS else ""
    UNDERLINE = "\033[4m" if _COLORS else ""

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


# Global quiet flag
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


def print_error(msg: str, file=sys.stderr):
    """Print an error message to stderr."""
    print(f"{Color.BOLD_RED}error:{Color.RESET} {msg}", file=file)


def print_warning(msg: str, file=sys.stderr):
    """Print a warning message to stderr."""
    if not _QUIET:
        print(f"{Color.BOLD_YELLOW}warning:{Color.RESET} {msg}", file=file)


def print_success(msg: str):
    """Print a success message."""
    if not _QUIET:
        print(f"{Color.GREEN}{msg}{Color.RESET}")


def print_info(msg: str):
    """Print an info message."""
    if not _QUIET:
        print(msg)


def print_verbose(msg: str):
    """Print a verbose-only message."""
    if not _QUIET:
        print(f"{Color.DIM}{msg}{Color.RESET}")


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
        print(f"\n{Color.BOLD}{msg}{Color.RESET}")


def print_step(current: int, total: int, msg: str):
    """Print a step indicator like [1/5] message."""
    if not _QUIET:
        print(f"[{current}/{total}] {msg}")


def print_download(name: str, version: str, size: int = None):
    """Print a download status with optional size."""
    if not _QUIET:
        pkg = print_package(name, version)
        if size:
            size_str = _format_size(size)
            print(f"  {Color.BLUE}downloading{Color.RESET} {pkg} ({size_str})...")
        else:
            print(f"  {Color.BLUE}downloading{Color.RESET} {pkg}...")


def print_installed(name: str, version: str, mode: str = "source", cached: bool = False):
    """Print an installed status message."""
    if not _QUIET:
        pkg = print_package(name, version)
        source = f" [{mode}]" if mode else ""
        cache = f" {Color.DIM}(cached){Color.RESET}" if cached else ""
        print(f"  {Color.GREEN}installed{Color.RESET} {pkg}{source}{cache}")


def print_removed(name: str):
    """Print a removed status message."""
    if not _QUIET:
        print(f"  {Color.RED}removed{Color.RESET} {print_package(name)}")


def print_skipped(name: str, version: str, reason: str):
    """Print a skipped status message."""
    if not _QUIET:
        pkg = print_package(name, version)
        print(f"  {Color.DIM}skipped{Color.RESET} {pkg} ({reason})")


def print_already_installed(name: str, version: str):
    """Print already installed status."""
    if not _QUIET:
        pkg = print_package(name, version)
        print(f"  {Color.DIM}exists{Color.RESET} {pkg}")


def _format_size(size_bytes: int) -> str:
    """Format bytes to human readable string."""
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.0f}{unit}" if unit == "B" else f"{size_bytes:.1f}{unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f}TB"


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
