# CPM Compiler Specification

## 1. Overview

CPM (Cpyte Package Manager) is a dependency resolver and installer that treats
package management as a compilation pipeline. Source code (import statements)
is the input; an executed instruction stream is the output.

```
Source:  import @std.json
              ↓
Resolve: context-dependent version lookup
              ↓
Lower:   flat instruction IR
              ↓
Optimize: deduplicate pass
              ↓
Execute: download → verify → cache → install
```

---

## 2. Core Principle

> The version belongs in the dependency manifest; the import belongs to the code.

```python
import @std.json          # clean — no version in source
```

The same `import @std.json` resolves differently depending on context:

| Context            | Resolves to                        |
| ------------------ | ---------------------------------- |
| Application code   | Project's declared (or locked) version |
| Inside `package_a` | `package_a`'s declared version     |

---

## 3. Version Resolution

### 3.1 Rules

```
Declared in manifest
    → resolve according to version requirement
    → lock exact resolved version in cpm.lock

Not declared (first use)
    → resolve latest compatible version from repo
    → lock it in cpm.lock
```

### 3.2 Context Model

Each package has its own dependency scope. A package's imports resolve
against *that package's* declared dependencies, not the project root's.

```
my-app
├── cpytoml                  # declares @std/json@2.0
├── src/
│   └── main.py              # import @std.json → @std/json@2.0
└── dependencies/
    └── @std/json@2.0/
        └── package.toml     # may declare its own deps

package_a
├── package.toml             # declares @std/json@1.0
└── src/
    └── lib.py               # import @std.json → @std/json@1.0
```

This means `package_a` and `my-app` can depend on different versions
of `@std/json` without conflict. They coexist in separate scopes.

### 3.3 Conflict Detection

Conflict only occurs when two packages in the *same* dependency chain
require incompatible versions of the same dependency.

```
my-app
├── @std/json@2.0
└── package_a
    └── @std/json@1.0       # fine — different scope

my-app
├── package_a
│   └── @std/json@^1.0      # resolves to 1.5
└── package_b
    └── @std/json@^1.0      # resolves to 1.8

# If package_a requires ^1.0 and package_b requires ^2.0:
# → CONFLICT (same ancestor scope, incompatible ranges)
```

### 3.4 Version Range Semantics

| Syntax     | Meaning                          |
| ---------- | -------------------------------- |
| `1.0`      | Exact version `1.0`              |
| `^1.0`     | Compatible with `1.0` (≥1.0, <2.0) |
| `~1.0`     | Approximate `1.0` (≥1.0, <1.1)  |
| `>=1.0`    | At least `1.0`                   |
| `latest`   | Latest version from repo         |
| (absent)   | Treated as `latest`              |

---

## 4. Manifest Format

### 4.1 Project Manifest: `cpytoml`

Located at the project root. Declares direct dependencies and target platform.

```toml
[cpm]
name = "my-app"
version = "1.0"
prebuilt = false

[cpm.target]
os = "linux"
arch = "x86_64"
features = ["gui", "ssl"]

[cpm.dependencies]
"@std/json" = "^2.0"
"@std/http" = "1.0"
"package_a" = "latest"
```

### 4.2 Package Manifest: `package.toml`

Located in each dependency's directory. Declares the package's own
dependencies and metadata.

```toml
[package]
name = "@std/json"
version = "2.0.0"
description = "JSON utilities"

[package.dependencies]
"@std/encoding" = "^1.0"
```

### 4.3 Version Resolution Priority

```
1. cpm.lock (exact locked version)     → use if present
2. cpytoml / package.toml (constraint)  → resolve within range
3. No declaration                       → resolve latest
```

---

## 5. Claims System

Claims allow packages to declare platform support. The resolver filters
packages based on the project's target platform.

### 5.1 Package Claims (in registry metadata)

Packages declare what platforms they support:

```json
{
  "name": "win32-api",
  "version": "1.0.0",
  "url": "...",
  "checksum": "...",
  "claims": {
    "os": ["windows"],
    "arch": ["x86_64", "aarch64"],
    "features": ["gui"]
  }
}
```

### 5.2 Project Target (in cpytoml)

The project declares what platform it targets:

```toml
[cpm.target]
os = "linux"
arch = "x86_64"
features = ["gui", "ssl"]
```

### 5.3 Matching Rules

| Claim        | Rule                                          |
| ------------ | --------------------------------------------- |
| `os`         | Target OS must be in the package's OS list    |
| `arch`       | Target arch must be in the package's arch list|
| `features`   | All required features must be enabled         |
| (absent)     | Package supports all platforms                 |

### 5.4 Resolution Behavior

When resolving dependencies:

1. Read target from `[cpm.target]` in cpytoml
2. For each package, check if its claims match the target
3. Skip packages whose claims don't match
4. Continue with packages that match

```
Project target: linux/x86_64

Packages:
  @std/json     (no claims)        → install ✓
  win32-api     (os: windows)      → skip ✗
  posix-api     (os: linux)        → install ✓
```

### 5.5 CLI Override

Use `--target` to override the manifest target:

```bash
cpm install --target darwin/aarch64
cpm add @std/json --target windows/x86_64
```

### 5.6 Auto-Detection

If no target is specified in the manifest or CLI, CPM auto-detects
from the current platform:

| `platform.system()` | OS        |
| ------------------- | --------- |
| Linux               | linux     |
| Darwin              | darwin    |
| Windows             | windows   |

| `platform.machine()` | Arch     |
| -------------------- | -------- |
| x86_64               | x86_64   |
| AMD64                | x86_64   |
| arm64 / aarch64      | aarch64  |

---

## 6. Lockfile Format: `cpm.lock`

Stores exact resolved versions for reproducible builds. TOML format.

```toml
[[package]]
name = "@std/json"
version = "2.0.3"
resolved = "https://repo.example.com/@std/json/2.0.3.tar.gz"
checksum = "sha256:abc123..."
dependencies = ["@std/encoding@1.2.0"]

[[package]]
name = "@std/encoding"
version = "1.2.0"
resolved = "https://repo.example.com/@std/encoding/1.2.0.tar.gz"
checksum = "sha256:def456..."
dependencies = []
```

### 6.1 Lockfile Semantics

- If `cpm.lock` exists, resolve from it (deterministic).
- If a package is not in `cpm.lock`, resolve from repo and add entry.
- `cpm update` regenerates `cpm.lock` from current constraints.
- `cpm install` without `cpm.lock` creates it.

---

## 7. Directory Layout

### 7.1 Global Cache (`~/.cpm/`)

```
~/.cpm/
├── cache/                          # downloaded archives
│   └── @std/
│       └── json/
│           └── 2.0.3/
│               └── 2.0.3.tar.gz
├── modules/                        # installed packages (per-project symlinked)
│   └── @std/
│       └── json/
│           └── 2.0.3/
│               ├── src/
│               └── package.toml
└── registry/                       # cached metadata
    └── group/
        └── std/
            └── json/
                ├── 2.0.3.json
                └── latest.json
```

### 7.2 Project Layout

```
my-app/
├── cpytoml                         # project manifest
├── cpm.lock                        # lockfile
└── .cpm/                           # project-local installed packages
    └── modules/
        └── @std/
            └── json/
                └── 2.0.3/          # extracted package
```

---

## 8. Compiler Pipeline

### 8.1 Stage 1: Resolve

Input: list of package specs from manifest or import statements.
Output: nested dependency tree with resolved versions.

```
resolve(["@std/json@^2.0", "package_a"], repo)
    ↓
[
    {"name": "@std/json", "version": "2.0.3", "deps": [...]},
    {"name": "package_a", "version": "1.0.0", "deps": [
        {"name": "@std/json", "version": "1.5.0", "deps": [...]}
    ]}
]
```

### 8.2 Stage 2: Lower

Input: nested dependency tree.
Output: flat instruction IR (before dedup).

```
[
    {"GET": "@std/json", "version": "2.0.3", "url": "...", "checksum": "sha256:..."},
    {"GET": "package_a", "version": "1.0.0", "url": "...", "checksum": "sha256:..."},
    {"GET": "@std/json", "version": "1.5.0", "url": "...", "checksum": "sha256:..."}
]
```

### 8.3 Stage 3: Optimize (Deduplicate)

Input: flat instruction IR with potential duplicates.
Output: deduplicated instruction stream.

Key: identity is `name@version`, not just `name`. Different versions
of the same package are *not* duplicates.

```
@std/json@2.0.3 and @std/json@1.5.0 are DIFFERENT entries.
```

### 8.4 Stage 4: Execute

Input: deduplicated instruction stream.
Output: packages installed to `~/.cpm/modules/`.

```
For each instruction:
    1. Check cache → hit? skip download
    2. Download archive
    3. Verify checksum
    4. Extract to modules
    5. Lock in cpm.lock
```

---

## 9. Instruction IR

### 9.1 Opcodes

| Opcode       | Fields                              | Description            |
| ------------ | ----------------------------------- | ---------------------- |
| `GET`        | `name`, `version`, `url`, `checksum` | Download and install   |
| `REMOVE`     | `name`, `version`                   | Uninstall package      |
| `CHECK_CACHE`| `name`, `version`, `checksum`       | Verify cache integrity |
| `RESOLVE`    | `name`, `constraint`                | Resolve version from repo |

### 9.2 Instruction Format

```json
{
    "GET": "@std/json",
    "version": "2.0.3",
    "url": "https://repo.example.com/group/std/json/2.0.3.tar.gz",
    "checksum": "sha256:abc123def456..."
}
```

### 9.3 Reserved for Future Expansion

```
{"DOWNLOAD": "@std/json", "url": "...", "dest": "cache/@std/json/2.0.3/"}
{"VERIFY": "@std/json", "checksum": "sha256:..."}
{"EXTRACT": "@std/json", "from": "cache/...", "to": "modules/..."}
{"LINK": "@std/json", "from": "modules/...", "to": "project/.cpm/..."}
{"INSTALL": "@std/json", "version": "2.0.3"}
```

---

## 10. Package Name Resolution

### 10.1 URL Path Mapping

| Package Name   | Metadata Path                     |
| -------------- | --------------------------------- |
| `foo`          | `metadata/foo/{version}`          |
| `@std/json`    | `metadata/group/std/json/{version}` |
| `@a/b/c`       | `metadata/group/a/b/c/{version}`  |

### 10.2 Import → Package Mapping

Source code:
```python
import @std.json
```

Parser extracts: `@std.json`

CPM resolves:
```
@std.json → @std/json → look up in current context's dependencies
```

The `.` in import statements maps to `/` in package names.

---

## 11. Checksum Format

```
algorithm:hex_digest

Examples:
sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
sha512:cf83e1357eefb8bdf1542850d66d8007d620e4050b5715dc83f4a921d36ce9ce...
```

---

## 12. Error Model

| Error                    | Condition                          |
| ------------------------ | ---------------------------------- |
| `CycleDetected`          | A → B → C → A in dependency graph |
| `VersionConflict`        | Two packages require incompatible versions |
| `ChecksumMismatch`       | Downloaded archive doesn't match expected hash |
| `PackageNotFound`        | Package or version not in repo     |
| `MissingManifest`        | No `cpytoml` found when required   |
| `LockfileStale`          | `cpm.lock` out of date with `cpytoml` |

---

## 13. CLI Commands

| Command          | Action                                        |
| ---------------- | --------------------------------------------- |
| `cpm init`       | Create empty `cpytoml`                        |
| `cpm add P@V`    | Add to `cpytoml` + install + lock             |
| `cpm remove P`   | Remove from `cpytoml` + uninstall + relock    |
| `cpm install`    | Read `cpytoml`, resolve, install, write lock  |
| `cpm install P`  | Install specific package(s)                   |
| `cpm update`     | Re-resolve all, update lock                   |
| `cpm update P`   | Re-resolve specific package(s)                |
| `cpm build`      | Build the project                             |
| `cpm run SCRIPT` | Run a script from manifest                    |

---

## 14. Implementation Modules

| Module         | Responsibility                              |
| -------------- | ------------------------------------------- |
| `parser.py`    | CLI argument parsing                        |
| `commands.py`  | Command dataclasses                         |
| `manifest.py`  | `cpytoml` read/write                        |
| `lockfile.py`  | `cpm.lock` read/write (TODO)                |
| `sat.py`       | Dependency resolver + instruction builder   |
| `executor.py`  | Instruction stream executor                 |
| `gethins.py`   | HTTP transport (repo fetch)                 |
| `things.py`    | Command handlers (orchestrates pipeline)    |
| `main.py`      | Entry point + dispatch                      |
| `errors.py`    | Error types                                 |
