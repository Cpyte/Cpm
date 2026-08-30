# Packages

A **package** is a directory of Cpyte sources plus metadata. There are two
metadata files to know about:

| File | Where | Purpose |
|------|-------|---------|
| `package.json` | package source (authored) | Capabilities, extensions, CLI tools, human metadata |
| `package.toml` | installed copy (generated) | Install record: name, exact version, mode, repo |

## `package.json`

```json
{
  "name": "@std/json",
  "version": "1.0.0",
  "bin": { "json-cli": "src/cli.cpy" },
  "capabilities": {
    "keywords":     ["await"],
    "operators":    ["<|>"],
    "tags":         ["@async"],
    "macros":       ["assert_eq"],
    "custom_types": ["Result"]
  },
  "extensions": {
    "parser_hooks":  ["parser_hooks.py"],
    "semantic_hooks": [],
    "codegen_hooks": ["codegen_hooks.py"],
    "runtime_hooks": []
  },
  "dependencies": [],
  "metadata": {
    "description": "JSON encode/decode for Cpyte",
    "author": "Cpyte Team",
    "license": "MIT"
  }
}
```

### Fields

- **`name`** — required. Plain (`mylib`) or group-scoped (`@std/json`).
- **`version`** — required for publishing; semver-ish `X.Y[.Z]`.
- **`bin`** — optional map of CLI tool name → project-relative path.
  See [CLI launchers](#cli-launchers-bin).
- **`capabilities`** — language surface the package adds. All sets are
  optional and default empty:
  - `keywords`, `operators`, `tags`, `macros`, `custom_types`
- **`extensions`** — hook files loaded by the compiler when the package is
  active: `parser_hooks`, `semantic_hooks`, `codegen_hooks`, `runtime_hooks`
  (each a list of Python files relative to the package root).
- **`dependencies`** — list of specs like `"@std/strbuilder@^0.1"`.
- **`metadata`** — free-form; `description` and `keywords` inside
  `metadata.keywords` feed registry search.

On install, CPM prints the language surface a package adds:

```
@demo/cap@1.0.0 adds to the language:
    keywords:       await, stream
    operators:      |>, <|>
    macros:         async_def
    custom types:   Stream, Future
```

`metadata.description` and `metadata.keywords` feed registry search, and the
`capabilities` map is exposed by the registry's metadata/search responses so
`cpm info` and `cpm search` can show them too.

## CLI launchers (`bin`)

Packages can ship command-line tools, pip console-scripts style.

**Declaration** — either in the package's `package.json`:

```json
"bin": { "tool-name": "src/tool.cpy" }
```

…or in a project's own `cpy.toml`:

```toml
[cpm.bin]
tool-name = "src/tool.cpy"
```

**Behavior**

- `.cpy` targets run through the compiler JIT
  (`cpy --jit <file>` with a `python3 -m cpyte` fallback).
- Any other target (e.g. a compiled binary) is executed directly.
- On install/build CPM writes an executable POSIX shim per entry to
  `<project>/.cpm/bin/<tool>` and prints a PATH hint:

  ```
  export PATH="$PATH:/path/to/project/.cpm/bin"
  ```

- Uninstalling removes shims owned by that package.
- Tool names are sanitized to `[A-Za-z0-9._-]`; entries with missing targets
  are skipped with a warning at install time and rejected by
  `cpm validate`.

## Installed layout: `.cpm/modules`

Dependencies extract under `.cpm/modules/<name>/<exact-version>/`
(group packages nest as `modules/@group/name/version`). Each install contains:

- `package.toml` — generated install record
- `package.json` — copied from the package source
- sources (`*.cpy`) and/or prebuilt artifacts (`*.ll`, `*.sef`)
