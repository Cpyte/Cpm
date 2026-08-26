# Builds & artifacts

## Entry-point resolution

`cpm build` locates the project entry in this order:

1. `[cpm.build]` `main = "…"` (explicit override)
2. `main.cpy`
3. `<project_name>.cpy`
4. `src/main.cpy`
5. `src/<project_name>.cpy`

A tool-only project (no entry, only `[cpm.bin]`) is valid: the warning is
printed, CLI launchers are still registered.

## Build modes

| Command / flag | Mode | Output |
|----------------|------|--------|
| `cpm build` | AOT (`--aot`) | native object/binary via LLVM |
| `cpy --jit file.cpy` | JIT | run immediately |
| `cpy --emit-llvm file.cpy` | IR | `.ll` text |
| `cpm build --scorpion` / `scorpion = true` | Scorpion | RISC-V `.sef` binary |

Quality flags: `--opt` (opt level 2), `--osize`, `--debug`, `--lto`.

Outputs land in `build/`.

## SEF — Scorpion Executable Format

SEF is CPM's portable RISC-V artifact format for the Scorpion VM/toolchain.

- **Static SEF** — single flat image.
- **Dynamic SEF v2** (`pic = true`, default) — position-independent code with
  relocations; `exports = ["sym", …]` marks library symbols.
- Emit with `cpm build --scorpion`; inspect with `cpm sef <subcommand>`
  (`size`, `dump`, `check`).
- Cross-compilation requires the `riscv*-elf-gcc` toolchain; `cpm doctor`
  reports toolchain readiness and supported codegen features.

Install-time counterpart: `sef = true` in `cpy.toml` resolves SEF artifacts
from the registry instead of source.

## Prebuilt IR

With `prebuilt = true`, dependencies resolve to registry-hosted LLVM IR
(`.ll`). Pin `llvm_version` when consumers must agree on a specific LLVM;
`cpm doctor` shows the detected compiler/LLVM versions.

## After-build hooks

Once the build succeeds, project tools declared in `[cpm.bin]` are
( re-)registered into `.cpm/bin` — see
[Packages → CLI launchers](PACKAGES.md#cli-launchers-bin).
