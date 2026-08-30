# Registry & publishing

The default registry is `https://cypackage.5gnew.io.vn` (a Gitea-backed
Flask app). All transport is HTTPS; the CLI refuses plain-HTTP repos with a
warning under validate.

## Naming

| Kind | Example | URL path |
|------|---------|----------|
| plain | `mylib` | `/packages/mylib/<ver>.tar.gz` |
| group-scoped | `@std/json` | `/packages/group/std/json/<ver>.tar.gz` |
| nested scope | `@org/sub/pkg` | `/packages/org/sub/pkg/<ver>.tar.gz` |

Metadata mirrors the same path shape: `/metadata/<path>/<version>` returns
`{"name", "version", "url", "checksum", "requires"}`.

## Authentication

```console
$ cpm login --server https://cypackage.5gnew.io.vn
```

1. The CLI opens/prints an approval URL and polls with a device code.
2. You approve in the browser (optionally confirm a TOTP second factor).
3. A `cpm_…` API token is stored in `~/.config/cpm/auth.toml`
   (mode 0600, XDG_CONFIG_HOME aware) together with your email.

Publishing requires the `scope_*_publish` grant on your account.
`cpm logout` revokes locally stored credentials.

## Publishing

```console
$ cpm publish . --name @std/json --pkg-version 1.0
✓ Published @std/json@1.0
Checksum: sha256:2edfcea8…
```

Flow: package.json is validated → tarball built → uploaded with your token →
the registry extracts asynchronously and writes a sidecar
`<temp>.meta.json` consumed by its job worker → metadata/search become
visible. Re-publishing the same version replaces the artifact.

`cpm unpublish <name>@<version>` removes it (owner/admin only).

## Search

```console
$ cpm search json                 # or: GET /search?q=json&page=2&per_page=20
```

Matches package names, descriptions and keywords across the database **and**
on-disk packages. Results include a `capabilities` map (language keywords,
operators, tags, macros, custom types) read from each package's
`package.json`; these also feed keyword matching. Pagination via `page`/
`per_page` (≤50); responses carry `X-Total-Count`, `X-Page`, `X-Per-Page`.

## Malware reports & quarantine

Report a suspicious package (auth required):

```console
$ cpm report @suspect/pkg --reason typosquatting --details "imitates @std/json"
```

Reasons: `malware`, `typosquatting`, `spam`, `license`, `other`. One open
report per reporter per package — repeat submissions update it.

Admins review at `/admin/reports`: mark *reviewing / resolved / dismissed*,
or **quarantine** — quarantined packages disappear from search and their
metadata/download endpoints are blocked until un-quarantined. Web form for
reports: `/report/<package>`.

## Registry API summary

| Endpoint | Auth | Purpose |
|----------|------|---------|
| `GET /search?q=&page=` | – | search + pagination |
| `GET /metadata/<path>/<ver>` | – | resolution metadata |
| `GET /packages/…tar.gz` | – | artifact download |
| `POST /publish` | token (+scope) | upload tarball |
| `GET /auth/device` | browser | device-code approval |
| `POST /api/report` | token/session | file malware report |
| `GET /api/reports?status=` | admin | list reports |
| `POST /admin/reports/<id>/status` | admin | triage report |
| `POST /admin/reports/<id>/quarantine` | admin | toggle quarantine |
