"""Minimal TOML lexing helpers shared by the manifest and lockfile parsers.

CPM owns two small TOML files (``cpy.toml`` and ``cpm.lock``) that people also
hand-edit, so it reads them with a deliberately small reader instead of taking
a TOML dependency.  This module holds the lexical pieces both readers need so
the syntax rules cannot drift apart:

  * ``#`` comments, including trailing ones after a value
  * inline arrays continued over several lines
  * basic (escape-processed) and literal strings
  * array items containing commas or brackets

Outside that subset (inline tables, dates, multi-line strings, dotted keys)
is not supported: callers simply ignore what they do not recognise.
"""

from __future__ import annotations

from collections.abc import Iterator

__all__ = [
    "iter_statements",
    "parse_array",
    "strip_comment",
    "toml_array",
    "toml_string",
    "unquote",
]

_OPEN_BRACKETS = "[{"
_CLOSE_BRACKETS = "]}"
_QUOTES = "\"'"

_ESCAPES = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "b": "\b",
    "f": "\f",
    '"': '"',
    "'": "'",
    "\\": "\\",
}


def _scan(text: str):
    """Yield (index, char, in_string, escaped) for each char of text.

    ``in_string`` is the quote character when inside a quoted string, else "".
    ``escaped`` is True when the char is escaped inside a basic string.
    """
    quote = ""
    escaped = False
    for index, char in enumerate(text):
        if escaped:
            escaped = False
            yield index, char, quote, True
            continue
        if quote:
            if char == "\\" and quote == '"':
                escaped = True
            elif char == quote:
                quote = ""
            yield index, char, quote, False
            continue
        if char in _QUOTES:
            quote = char
            yield index, char, quote, False
            continue
        yield index, char, "", False


def strip_comment(line: str) -> str:
    """Drop a trailing ``#`` comment, keeping ``#`` inside quoted strings."""
    for _index, char, in_string, _escaped in _scan(line):
        if char == "#" and not in_string:
            return line[:_index]
    return line


def _bracket_delta(text: str) -> int:
    """Return the net bracket depth added by text (ignoring quoted text)."""
    depth = 0
    for _index, char, in_string, _escaped in _scan(text):
        if in_string:
            continue
        if char in _OPEN_BRACKETS:
            depth += 1
        elif char in _CLOSE_BRACKETS:
            depth -= 1
    return depth


def _is_table_header(line: str) -> bool:
    return line.startswith("[") and line.endswith("]")


def _table_name(line: str) -> tuple[str, bool]:
    """Return (table name, is_array) for a ``[table]`` / ``[[table]]`` line."""
    is_array = line.startswith("[[")
    return line.strip("[]").strip(), is_array


def iter_statements(content: str) -> Iterator[tuple[str, bool, str]]:
    """Yield ``(table, is_array, statement)`` triples for TOML-ish content.

    ``table`` is the enclosing table name ("" before the first header) and
    ``is_array`` distinguishes ``[[table]]`` from ``[table]``.  Table headers
    yield an empty ``statement``; a ``key = value`` statement yields the
    joined text of a single logical line, with comments removed and inline
    arrays continued over several lines folded back onto one line.
    """
    table = ""
    pending = ""
    depth = 0

    for raw_line in content.splitlines():
        line = strip_comment(raw_line).strip()
        if not line:
            continue

        if not pending and _is_table_header(line):
            table, is_array = _table_name(line)
            yield table, is_array, ""
            continue

        pending = f"{pending} {line}" if pending else line
        depth += _bracket_delta(line)
        if depth > 0:
            continue

        depth = 0
        if pending:
            yield table, False, pending
        pending = ""

    if pending:
        yield table, False, pending


def _unescape(text: str) -> str:
    out: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\\" and index + 1 < len(text):
            nxt = text[index + 1]
            if nxt == "u" and index + 6 <= len(text):
                try:
                    out.append(chr(int(text[index + 2 : index + 6], 16)))
                    index += 6
                    continue
                except ValueError:
                    pass
            out.append(_ESCAPES.get(nxt, "\\" + nxt))
            index += 2
            continue
        out.append(char)
        index += 1
    return "".join(out)


def unquote(value: str) -> str:
    """Return the text of a quoted TOML string, or the value unchanged."""
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in _QUOTES:
        body = value[1:-1]
        return _unescape(body) if value[0] == '"' else body
    return value


def _split_items(inner: str) -> list[str]:
    """Split an array body on commas that are outside quoted strings."""
    items: list[str] = []
    current: list[str] = []
    depth = 0
    for _index, char, in_string, _escaped in _scan(inner):
        if not in_string:
            if char in _OPEN_BRACKETS:
                depth += 1
            elif char in _CLOSE_BRACKETS:
                depth -= 1
            elif char == "," and depth == 0:
                items.append("".join(current))
                current = []
                continue
        current.append(char)
    items.append("".join(current))
    return items


def parse_array(value: str) -> list[str]:
    """Parse an inline array such as ``["a", "b"]`` into its string items.

    Returns an empty list when the value is not an array.  Items are unquoted,
    so a value that is not a quoted string is returned as-is.
    """
    value = value.strip()
    if not value.startswith("["):
        return []

    inner = value[1:]
    if inner.rstrip().endswith("]"):
        inner = inner.rstrip()[:-1]

    items = [unquote(item) for item in _split_items(inner)]
    return [item for item in items if item]


def toml_string(value: str) -> str:
    """Serialize a string as a TOML basic string."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    escaped = escaped.replace("\n", "\\n").replace("\t", "\\t").replace("\r", "\\r")
    return f'"{escaped}"'


def toml_array(values) -> str:
    """Serialize a list of strings as a TOML inline array."""
    return "[" + ", ".join(toml_string(str(value)) for value in values) + "]"
