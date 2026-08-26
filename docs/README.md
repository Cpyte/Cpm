# CPM Documentation

CPM is the package manager for the Cpyte language. It handles dependency
resolution, installation, builds, SEF (Scorpion RISC-V) artifacts, publishing
to registries, and CLI tool registration.

## Guides

| Document | Contents |
|----------|----------|
| [Project structure](PROJECT_STRUCTURE.md) | Directory layout overview, quick start |
| [Manifest reference](MANIFEST.md) | Every `cpy.toml` field, defaults, validation rules |
| [Packages](PACKAGES.md) | `package.json` format, capabilities/extensions, CLI launchers (`bin`) |
| [Dependencies & lockfile](DEPENDENCIES.md) | Constraint grammar, platform deps, resolution order, `cpm.lock` format |
| [Builds & artifacts](BUILDS.md) | Entry-point resolution, build modes, SEF/Scorpion, prebuilt IR |
| [Registry & publishing](REGISTRY.md) | Registry API, auth, publish flow, search, malware reports |

## The manifest file: `cpy.toml`

Every project is described by a `cpy.toml` at its root:

```toml
[cpm]
name = "my-app"
version = "1.0.0"

[cpm.dependencies]
"@std/json" = "^2.0"
```

> **Legacy note:** older projects used an extensionless `cpytoml` filename.
> It is still discovered automatically, but all tooling now writes `cpy.toml`.
> Rename with `mv cpytoml cpy.toml` when convenient.

## Quick start

```console
$ cpm init                 # scaffold cpy.toml + main.cpy
$ cpm add @std/json@^1.0   # add + install a dependency
$ cpm build                # compile the entry point
$ cpm run main             # JIT-run a script in the project
```

Install from a local directory while developing:

```console
$ cpm install-local ../my-lib
```

Check that everything is wired up correctly:

```console
$ cpm validate [--fix] [--strict]
```
