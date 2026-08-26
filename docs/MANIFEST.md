# Manifest reference: `cpy.toml`

The manifest lives at the project root and is named `cpy.toml`
(legacy extensionless `cpytoml` files are still read).

It is parsed by a minimal TOML reader; supported value types are strings,
booleans, inline string arrays, and `[section]` tables. Comments (`#`) are
allowed everywhere.

## `[cpm]` — project identity & toolchain

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | string | *(required to publish)* | Package name. Pattern: `[A-Za-z][A-Za-z0-9._-]*`, max 214 chars. Group packages use `@group/name`. |
| `version` | string | `"0.1.0"` | `X.Y` or `X.Y.Z`, optional `-pre` / `+build` suffixes. Must be valid semver-ish for publishing. |
| `prebuilt` | bool | `false` | Resolve **prebuilt LLVM IR** artifacts from the registry instead of source. |
| `scorpion` | bool | `false` | Also emit a Scorpion (RISC-V) `.sef` binary on every `cpm build`. |
| `sef` | bool | `false` | Resolve/install **SEF artifacts** for dependencies instead of source. |
| `llvm_version` | string | `""` | Pin a specific LLVM version for prebuilt compatibility. |
| `repos` | string[] | `[]` | Extra registry base URLs. HTTPS only; validated by `cpm validate`. |

Legacy: `packages = ["foo@^1.0", ...]` inline array in `[cpm]` is still parsed.

## `[cpm.target]` — platform claims

| Field | Type | Default | Values |
|-------|------|---------|--------|
| `os` | string | auto-detect | `linux`, `darwin`, `windows` |
| `arch` | string | auto-detect | `x86_64`, `aarch64`, `arm` |
| `features` | string[] | `[]` | Free-form feature gates a dependency may require (e.g. `"gui"`, `"ssl"`) |

Auto-detection maps `platform.system()` → os and `platform.machine()` → arch
(`AMD64 → x86_64`, `arm64 → aarch64`). Unknown os/arch values are validation
errors.

## `[cpm.build]` — build configuration

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `main` | string | auto-detected | Entry-point override. Without it CPM looks for `main.cpy`, `<project>.cpy`, `src/main.cpy`, `src/<project>.cpy` (in that order). |
| `pic` | bool | `true` | Dynamic SEF v2: position-independent code + relocations. |
| `exports` | string[] | `[]` | Library symbols exported by dynamic SEF builds. Symbols must match `[A-Za-z_][A-Za-z0-9_]*` (warned otherwise). |

## `[cpm.bin]` — CLI tool registration

Map of **tool name → project-relative path**. See [Packages → CLI launchers](PACKAGES.md#cli-launchers-cpmbin).

```toml
[cpm.bin]
greet = "src/greet.cpy"     # .cpy → runs via compiler JIT
serve  = "build/serve"      # native binaries run directly
```

Validation rules enforced by `cpm validate`:

- tool name must match `[A-Za-z0-9][A-Za-z0-9._-]*` (error)
- target path must be relative (error) and exist (error)
- empty targets are errors

## `[cpm.dependencies]` — direct dependencies

```toml
[cpm.dependencies]
"@std/json" = "^2.0"
"@std/http" = "1.0"
"local-tool" = "latest"

[cpm.dependencies.linux]
"posix-api" = "1.0"         # only installed when targeting linux

[cpm.dependencies.windows]
"win32-api" = "1.0"
```

Keys are package names (quoted if they contain `@` or `.`), values are
version constraints — see [Dependencies](DEPENDENCIES.md#constraint-grammar)
for the full grammar. Platform-scoped tables merge with the common set based
on the resolved target.

## Example: complete manifest

```toml
[cpm]
name = "my-app"
version = "1.2.0"
prebuilt = false
scorpion = true
sef = false
llvm_version = ""
repos = ["https://cypackage.5gnew.io.vn"]

[cpm.target]
os = "linux"
arch = "x86_64"
features = ["ssl"]

[cpm.build]
main = "src/main.cpy"
pic = true
exports = ["app_main"]

[cpm.bin]
my-app = "src/main.cpy"

[cpm.dependencies]
"@std/json" = "^2.0"
```

## Validation summary

`cpm validate` checks all of the above plus lockfile consistency and
security posture (file permissions, HTTPS-only repos). Run with `--fix` to
auto-repair name/version/target issues and tighten file permissions, and
`--strict` to escalate warnings into failures.
