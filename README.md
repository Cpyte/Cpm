# CPM — Cpyte Package Manager

A compiler-pipeline dependency resolver and installer for the [Cpyte](https://gitea.5gnew.io.vn/Cpyte-Project/Cpyte) programming language.

```
import @std.json
          ↓
Resolve → Lower → Optimize → Execute
```

## Install

```bash
pip install cpyte-cpm
```

**Note:** CPM uses the Cpyte package registry at https://cypackage.5gnew.io.vn/ as the default package source for Cpyte packages.

## Quick Start

```bash
cpm init                        # create cpytoml
cpm add @std/json@^2.0          # add a dependency
cpm install                     # install all from manifest
```

## Commands

| Command | Description |
|---------|-------------|
| `cpm init` | Initialize a new project (`cpytoml`) |
| `cpm add <pkg>` | Add packages to manifest + install |
| `cpm remove <pkg>` | Remove packages + uninstall |
| `cpm install` | Install all dependencies from manifest |
| `cpm install <pkg>` | Install specific packages |
| `cpm update` | Re-resolve and update all packages |
| `cpm update <pkg>` | Re-resolve specific packages |
| `cpm build` | Build the project |
| `cpm run <script>` | Run a named script |

## Global Flags

```
-v, --verbose        Verbose output
-q, --quiet          Suppress output
-y, --yes            Auto-confirm prompts
--offline            Offline mode (skip network)
--no-cache           Disable cache
--config <path>      Custom config / repo URL
--target <platform>  Target platform (e.g. linux/x86_64)
--llvm-version <V>   LLVM version for prebuilt packages
```

## Manifest (`cpytoml`)

```toml
[cpm]
name = "my-app"
version = "1.0"
prebuilt = false
llvm_version = "18.1.0"

[cpm.target]
os = "linux"
arch = "x86_64"
features = ["gui", "ssl"]

[cpm.dependencies]
"@std/json" = "^2.0"
"@std/http" = "1.0"
"package_a" = "latest"
```

## Claims System

Packages declare platform support; CPM filters based on your target.

**Package metadata (registry):**
```json
{
  "name": "win32-api",
  "claims": { "os": ["windows"], "arch": ["x86_64"] }
}
```

**Resolution:**
| Target | `win32-api` (windows) | `posix-api` (linux) | `@std/json` (any) |
|--------|----------------------|--------------------|--------------------|
| `linux/x86_64` | skip | install | install |
| `windows/x86_64` | install | skip | install |

Auto-detects from current platform when no target is specified.

## Prebuilt Mode

When the registry serves precompiled LLVM IR:

```toml
[cpm]
prebuilt = true
llvm_version = "18.1.0"
```

CPM fetches `.ll` artifacts from `metadata/prebuilt/...` and skips source packages
with incompatible LLVM versions (major version must match).

## Lockfile (`cpm.lock`)

Auto-generated. Pins exact versions for reproducible builds.

```toml
[[package]]
name = "@std/json"
version = "2.0.3"
resolved = "https://repo.example.com/group/std/json/2.0.3.tar.gz"
checksum = "sha256:abc123..."
dependencies = ["@std/encoding@1.2.0"]
llvm_version = "18.1.0"
cpyte_version = "0.5.0"
```

## Directory Layout

```
~/.cpm/
├── cache/<name>/<version>/     # downloaded archives
└── modules/<name>/<version>/   # extracted packages
```

## License

MIT
