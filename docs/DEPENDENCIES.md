# Dependencies & the lockfile

## Constraint grammar

| Form | Meaning |
|------|---------|
| `1.0` | Same-major compatibility: `>=1.0.0, <2.0.0` |
| `^1.2` / `^1.2.3` | Caret: `>=1.2.3, <2.0.0` (never breaks major) |
| `~1.2.3` | Tilde: `>=1.2.3, <1.3.0` (patch-level changes only) |
| `latest` | Floating; resolved at install, pinned in `cpm.lock` |
| `=1.2.3` | Exact version |
| `>1`, `<2`, `>=1,<3` | Comparison specifiers (comma = AND) |

Pre-release and build metadata suffixes are accepted on concrete versions
(`1.0.0-beta.1+exp`). Constraints that cannot be parsed by the built-in
grammar fall back to Python's `SpecifierSet`; anything still unparsable is
rejected by `cpm validate`.

## Resolution order

1. **Lockfile** (`cpm.lock`) — if a locked entry satisfies the manifest
   constraint and its checksum verifies, it is reused.
2. **Registry** — for each repo (manifest `repos`, then default registry),
   `/metadata/<path>/<version>` is queried; the returned tarball URL +
   sha256 checksum are used.
3. **Local** — `cpm install-local <dir>` bypasses resolution entirely.

Install modes:

| Mode | Trigger | Artifact |
|------|---------|----------|
| source (default) | `prebuilt=false, sef=false` | `.cpy` sources |
| prebuilt | `prebuilt=true` | LLVM IR `.ll` from registry |
| SEF | `sef=true` or package claims SEF | Scorpion RISC-V `.sef` |

Artifacts are cached in `~/.cpm/cache/<name>/<version>/` (checksum-verified)
and copied into `<project>/.cpm/modules/…`. Platform-scoped deps
(`[cpm.dependencies.<os>]`) install only when the resolved target matches.

## Lockfile: `cpm.lock`

Written at project root after every successful resolve/install. Format:

```toml
[[packages]]
name = "@std/json"
version = "1.0.0"
resolved = "https://cypackage.5gnew.io.vn/packages/group/std/json/1.0.tar.gz"
checksum = "sha256:2edfcea8…"   # required by validate
```

Rules enforced by `cpm validate`:

- every lock entry **must** carry a `sha256:<64 hex>` checksum (error)
- `resolved` must be HTTPS (error)
- locked version must be valid semver-ish and satisfy the manifest constraint
- installed module version must match the lock entry
- lock checksums are re-computed against installed files when possible

## Commands

```console
$ cpm add "@std/json@^2.0"     # add to cpy.toml + resolve + install
$ cpm remove @std/json          # remove from manifest + uninstall
$ cpm install                   # install everything from the lockfile
$ cpm update                    # re-resolve constraints, refresh lockfile
$ cpm list                      # show installed packages
$ cpm info @std/json            # registry metadata for a package
```
