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

**Note:** CPM uses the Cpyte package registry at https://cypackage.5gnew.io.vn/ as the default package source for Cpyte packages. The default registry is configured in pyproject.toml.

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
| `cpm info <pkg>` | Show detailed package information |
| `cpm list` | List installed packages |
| `cpm validate` | Validate project manifest and lockfile |
| `cpm search <query>` | Search for packages in registry |
| `cpm publish` | Publish a package to the registry |
| `cpm unpublish` | Remove a package from the registry |

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

## Additional Commands

### Package Information

```bash
cpm info @std/json          # Show package metadata and details
```

Displays:
- Package version and URL
- Platform claims (OS, architecture, features)
- Dependencies
- Installation status

### List Installed Packages

```bash
cpm list                    # List all installed packages in current project
```

Shows installed packages with versions from the lockfile, with status indicators.

### Validate Project

```bash
cpm validate                # Validate manifest and lockfile
```

Checks:
- Manifest TOML syntax
- Required fields (name, version)
- Dependency declarations
- Lockfile presence and consistency
- Target platform configuration

### Search Packages

```bash
cpm search json             # Search for packages matching a query
```

Searches both local installed packages and remote registry.

## Extension Packages

CPM supports extension packages that extend the Cpyte compiler with custom syntax, keywords, operators, and compiler hooks. Extension packages use a `package.json` manifest to declare their capabilities.

### Extension Package Structure

```
.cpm/modules/
├── package_name/
│   └── version/
│       ├── package.json         # Extension manifest
│       ├── parser_hooks.py      # Custom syntax parsing
│       ├── semantic_hooks.py    # Type checking extensions
│       ├── codegen_hooks.py     # LLVM IR generation
│       ├── runtime_hooks.py     # Runtime code injection
│       ├── *.cpy                # Main entry point (optional)
│       └── *.ll                 # Prebuilt LLVM IR (optional)
```

### package.json Format

```json
{
  "name": "package_name",
  "version": "1.0.0",
  "capabilities": {
    "keywords": ["async", "await", "defer"],
    "operators": ["~~"],
    "tags": ["@async", "@callback"],
    "macros": ["async_def"],
    "custom_types": ["Promise", "Future"]
  },
  "extensions": {
    "parser_hooks": ["parser_hooks.py"],
    "semantic_hooks": ["semantic_hooks.py"],
    "codegen_hooks": ["codegen_hooks.py"],
    "runtime_hooks": ["runtime_hooks.py"]
  },
  "dependencies": [],
  "metadata": {
    "description": "Package description",
    "author": "Author name",
    "license": "MIT"
  }
}
```

### Extension Capabilities

- **Keywords**: Custom language keywords that extend the lexer
- **Operators**: Custom operators for expressions
- **Tags**: Custom tags for annotations and metadata
- **Macros**: Compile-time macro definitions
- **Custom Types**: New type definitions

### Extension Hooks

- **Parser Hooks**: Extend the parser with custom syntax rules
- **Semantic Hooks**: Add custom type checking and analysis rules
- **Codegen Hooks**: Extend LLVM IR generation
- **Runtime Hooks**: Inject runtime code and libraries

### Extension-Only Packages

Packages can provide only extensions without any `.cpy` or `.ll` files. These packages:
- Provide keywords, operators, and compiler hooks
- Can be imported successfully by the compiler
- Are useful for language feature extensions

### Viewing Extension Capabilities

```bash
cpm info package_name      # Shows extension capabilities if available
```

The `cpm info` command displays extension capabilities for installed packages:

```
Extension Capabilities:
  Keywords: async, await, defer
  Operators: ~~
  Tags: @async, @callback
  Custom Types: Promise, Future
  Extension Hooks:
    Parser: parser_hooks.py
    Semantic: semantic_hooks.py
    Codegen: codegen_hooks.py
    Runtime: runtime_hooks.py
```

### Package Discovery

Extension packages are discovered automatically by the Cpyte compiler:
- Pre-loaded before compilation from `.cpm/modules/`
- Keywords registered during lexing
- Hooks loaded during appropriate compilation phases
- No CPM configuration required

## License

MIT
