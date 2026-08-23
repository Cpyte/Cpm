"""Credential storage for CPM registry authentication.

Stores tokens in a user-local TOML file:

    ~/.config/cpm/auth.toml

    default_server = "https://cypackage.5gnew.io.vn"

    [servers."https://cypackage.5gnew.io.vn"]
    token = "cpm_..."
    email = "you@example.com"

The file is created with 0600 permissions. Tokens are issued via the
device code flow (``cpm login``) and used automatically by commands
that talk to the registry (publish, unpublish, ...).
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

try:
    import tomllib
except ImportError:  # Python < 3.11
    tomllib = None


def _escape(value: str) -> str:
    """Escape a string for a TOML basic string literal."""
    out = []
    for ch in value:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch in "\n\r\t":
            out.append(f"\\u{ord(ch):04X}")
        else:
            out.append(ch)
    return "".join(out)


def _dumps(data: dict) -> str:
    """Serialize {str: str|dict} to TOML. Nested dicts become [a."b"] sections."""
    lines: list[str] = []

    def emit(table: dict, path: tuple) -> None:
        scalars = {k: v for k, v in table.items() if not isinstance(v, dict)}
        if scalars and path:
            header = ".".join(f'"{_escape(part)}"' for part in path)
            if lines:
                lines.append("")
            lines.append(f"[{header}]")
        for key, value in scalars.items():
            lines.append(f'{key} = "{_escape(str(value))}"')
        for key, value in table.items():
            if isinstance(value, dict):
                emit(value, path + (key,))

    emit(data, ())
    return "\n".join(lines) + "\n"


def auth_path() -> Path:
    """Path of the credentials file (respects XDG_CONFIG_HOME)."""
    config_home = os.environ.get("XDG_CONFIG_HOME") or str(
        Path.home() / ".config"
    )
    return Path(config_home) / "cpm" / "auth.toml"


@dataclass(frozen=True)
class Credentials:
    server: str
    token: str = ""
    email: str = ""


def _read_file() -> dict:
    path = auth_path()
    if not path.exists() or tomllib is None:
        return {}
    try:
        return tomllib.loads(path.read_text())
    except Exception:
        return {}


def save_credentials(server: str, token: str, email: str = "") -> Path:
    """Persist credentials for a registry server. Returns the file path."""
    server = server.rstrip("/")
    data = _read_file()
    servers = data.setdefault("servers", {})
    servers[server] = {"token": token, "email": email}
    if not data.get("default_server"):
        data["default_server"] = server

    path = auth_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    existed = path.exists()
    path.write_text(_dumps(data))
    if not existed:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600
    return path


def load_credentials(server: str = "") -> Credentials | None:
    """Load stored credentials.

    With no server argument, falls back to the default_server entry.
    """
    data = _read_file()
    servers = data.get("servers", {})
    server = (server or data.get("default_server", "")).rstrip("/")
    if not server or server not in servers:
        return None
    entry = servers[server]
    return Credentials(
        server=server,
        token=entry.get("token", ""),
        email=entry.get("email", ""),
    )


def clear_credentials(server: str = "") -> bool:
    """Remove stored credentials for a server (or all). Returns True if removed."""
    data = _read_file()
    servers = data.get("servers", {})
    changed = False
    if not server:
        if servers:
            data["servers"] = {}
            data.pop("default_server", None)
            changed = True
    else:
        server = server.rstrip("/")
        if server in servers:
            del servers[server]
            if data.get("default_server") == server and servers:
                data["default_server"] = next(iter(servers))
            elif not servers:
                data.pop("default_server", None)
            changed = True
    if changed:
        path = auth_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_dumps(data))
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return changed


def list_servers() -> list[Credentials]:
    """List all stored credential entries."""
    data = _read_file()
    result = []
    for server, entry in sorted(data.get("servers", {}).items()):
        result.append(
            Credentials(
                server=server,
                token=entry.get("token", ""),
                email=entry.get("email", ""),
            )
        )
    return result
