# Working in pm

`pm.ysh` is a ~2900-line YSH script implementing Kominka Linux's package manager. It resolves, builds, installs, and publishes packages. The companion server (`~/d/repo/server/`) is a Rust service that stores and serves the binary package index.

Read `YSH.md` first — it is the canonical style guide and gotcha reference for this codebase. This file covers what is specific to *this* project.

## Repository layout

```
pm.ysh                   Main script (~2900 lines)
packages/                Package definitions (one dir per package, each with PKGBUILD.ysh)
YSH.md                   YSH language reference and style guide
README.md                User-facing overview
~/d/repo/server/src/     Rust repo server
  packages.rs            Route handlers + data model
  s3.rs                  S3/R2 storage abstraction
  auth.rs                Token/session authentication
```

## pm.ysh architecture

### Key globals (imported from ENV at startup)

| Variable | Purpose |
|----------|---------|
| `KOMINKA_PATH` | Colon-separated search path for package definitions |
| `KOMINKA_ROOT` | Install root (empty = `/`) |
| `KOMINKA_REPO` | Repo server base URL |
| `KOMINKA_COMPRESS` | Tarball compression: `gz`, `xz`, `zst` |
| `KOMINKA_TOKEN` | Bearer token for uploads |
| `R2_PUBLIC_URL` | If set, downloads go directly to R2, bypassing the server |

### Package record

`pkg_load` (line ~470) is the central loader. It returns a typed `Dict` from three possible sources — a `PKGBUILD.ysh` file, the installed db at `/var/db/kominka/installed/{pkg}/`, or the remote index. The same `Dict` shape flows through every downstream proc:

```
{name, ver, rel, deps, mkdeps, sources, checksums, nostrip, path}
```

Packages are **never mutated globally** — each proc receives the record as a parameter (named `p` by convention). Source paths beginning with `remote:` are remote index entries, not filesystem paths.

### Dependency resolution

- `pkg_depends` (line ~1246): recursive dep-graph traversal; tracks explicit vs implicit deps
- `pkg_order` (line ~1317): topological sort
- **Makedep skip optimization**: if a runtime dep already has a binary in `~/.cache/kominka/bin/`, its build-only deps are skipped entirely

### Upload flow (`pkg_upload`, line ~706)

Two paths depending on tarball size:

- **< 50 MB**: `POST /api/upload` with the tarball body; server returns `{"ok":true,"sha256":"..."}`
- **≥ 50 MB** (Cloudflare proxy limit): `POST /api/upload-url` → `PUT` directly to R2 → `POST /api/update-index` with `X-Sha256`

### Storage

```
~/.cache/kominka/bin/           Binary cache: pkg@ver-rel.tar.gz
~/.cache/kominka/packages.json  Cached package index (per arch)
/var/db/kominka/installed/{pkg}/
  version                       "ver rel"  (or "system 1" for pre-installed)
  depends                       One dep per line, prefixed "runtime:" or "make:"
  manifest                      Newline-separated installed file paths
```

## PKGBUILD.ysh format

```ysh
#!/usr/local/bin/ysh

var name      = 'example'
var ver       = '1.0.0'
var rel       = '1'
var deps      = ['musl', 'zlib']      # runtime deps
var mkdeps    = ['make', 'zig']       # build-only deps

var sources   = [
    'https://example.com/example-VERSION.tar.gz',
    'files/my.patch patch',           # second field is destination subdir
]
var checksums = ['sha256hexhere...']

proc build(dest) {
    # dest is the staging directory (DESTDIR)
    ./configure --prefix=/usr
    make
    make DESTDIR=$dest install
}
```

**Source URL substitutions**: `VERSION`, `RELEASE`, `MAJOR`, `MINOR`, `PATCH`, `ARCH`, `GOARCH`, `IDENT`, `PACKAGE` are replaced from the package's own fields.

**Source types**:
- `https://...` — downloaded and verified against checksum
- `git+https://repo.git@branch` — checked out into `src/`
- `files/name` — copied from the package's `files/` directory
- `files/name subdir` — copied into `subdir/` inside the build tree

**Arch-specific checksums**: use `checksums_aarch64` or `checksums_x86_64` to override `checksums` for a specific arch.

**Metapackages**: set `sources = []` and have `build` do nothing (`true`). The `deps` list carries all meaning.

**`nostrip`**: set `var nostrip = true` to skip binary stripping (needed for Go, Rust, and packages with split debug info).

### PKGBUILD conventions

- Keep `build()` under 50 lines; split helpers into nested procs if needed.
- Pass compiler flags as a list, then splice: `var flags = ['-O2', ...]; cc @flags`.
- Use `$[ENV.KOMINKA_ROOT]` (or the imported `$_kr` pattern in git's PKGBUILD) to prefix library paths when cross-building against the sysroot.
- `command -v cc` is more reliable than `$CC` — the zig cc wrapper is on PATH.
- Comments explaining *why* a flag exists are expected and should be preserved.

## Server API (`~/d/repo/server/`)

### Data model (`packages.rs`)

```rust
PackageEntry { ver, rel, deps: Vec<String>, mkdeps: Vec<String>, sha256 }
PackageIndex { _version: 1, packages: HashMap<name, PackageEntry> }
```

The index lives in S3 at `{arch}/packages.json`. Tarballs live at `{arch}/{pkg}/{ver}-{rel}.tar.gz`.

### Endpoints

**GET**

| Path | Description |
|------|-------------|
| `/{arch}/packages.json` | Package index (in-memory, served from `state.indexes`) |
| `/{arch}/{pkg}/{ver}-{rel}.tar.gz` | Tarball; 302→R2 if `R2_PUBLIC_URL` configured |
| `/health` | `{"status":"ok"}` |

**POST** (all require `Authorization: Bearer <token>` or session cookie)

| Path | Headers | Body | Returns |
|------|---------|------|---------|
| `/api/upload` | X-Arch, X-Pkg, X-Ver, X-Rel, X-Deps, X-Mkdeps | binary tarball | `{"ok":true,"sha256":"..."}` 201 |
| `/api/upload-url` | X-Arch, X-Pkg, X-Ver, X-Rel | — | `{"url":"..."}` 200 |
| `/api/update-index` | X-Arch, X-Pkg, X-Ver, X-Rel, X-Sha256, X-Deps, X-Mkdeps | — | `{"ok":true}` 201 |
| `/api/publish` | — | `{arch,pkg,ver,rel,deps,mkdeps}` JSON | `{"ok":true}` 201 — metapackages |
| `/api/reindex` | — | `{arch,pkg,ver,rel,deps,mkdeps}` JSON | `{"ok":true}` 200 — re-registers existing R2 object |
| `/api/delete` | — | `{arch,pkg}` JSON | `{"ok":true}` 200 |

**Deps/mkdeps encoding**: comma-separated string in X-headers (`"curl,zlib"`); JSON array in body endpoints.

**Package name rules** (`valid_pkg_name`): lowercase alphanumeric, `.`, `-`, `_`; must start with alphanumeric.

**Known architectures**: `aarch64-linux-gnu`, `x86_64-linux-gnu`.

### Authentication

`auth::authenticated()` checks in order:
1. `Authorization: Bearer <token>` → SQLite token lookup
2. Same bearer token → JWT verification (if JWKS URL configured)
3. `kominka_session` cookie → browser session

Returns 401 `{"error":"unauthorized"}` if none match.

## YSH patterns used in pm.ysh

The codebase makes heavy use of patterns that can trip up edits — see `YSH.md` for full details. The most common ones in pm.ysh:

**ENV access** — env vars are not shell vars in `ysh:all`. They are imported at the top of pm.ysh into regular vars:
```ysh
var KOMINKA_ROOT = ENV => get("KOMINKA_ROOT", "")
```
After import, use `$KOMINKA_ROOT` normally. Do not add `ENV.X` references deep in the file; import at the top instead.

**Dict mutation inside procs** — `setvar d[k] = v` looks for a local `var d`. For globals use `setglobal d[k] = v`. `call list->append(x)` works on both because it mutates in-place.

**No `||` on proc calls** — `my_proc || die` triggers OILS-ERR-301. Use:
```ysh
try { my_proc }
if failed { die "msg" }
```

**Splice, don't split** — `@flags` splices a list as separate words; `$flags` would pass the whole list as one string. Always build flag lists and splice.

**Globbing** — bare `*.tar.gz` does not expand. Use `@[glob('*.tar.gz')]`.

**Backslash in expression context** — `var x = '\n'` is OILS-ERR-20. Use `u'\n'` (J8) or `$[newline]`.

## Common tasks

### Add a new package

1. Create `packages/{name}/PKGBUILD.ysh` with the fields above.
2. Run `pm c {name}` to generate checksums (or paste them from the upstream release page).
3. Test with `pm b {name}` — the build runs in a temp dir, staging to a `dest/` prefix.
4. Upload with `pm p {name}` (requires auth token).

### Bump a package version

1. Update `ver` and optionally `rel` in `PKGBUILD.ysh`.
2. Update `checksums` (run `pm c {name}` or compute `sha256sum` on the new source).
3. Rebuild and upload.

### Modify pm.ysh

- The main dispatch is `args` proc near the end of the file (~line 2616). New commands go there.
- Keep new procs under 50 lines; if larger, extract helpers.
- Proc names use hyphens (`pkg-install`), var/func names use underscores (`find_version`).
- Do not add banner/separator comments.
- Preserve existing comments that explain non-obvious constants or behavior.

### Modify the server

Server is at `~/d/repo/server/`. It uses `tiny_http` with thread-per-request. Route dispatch is in `packages.rs:route()`. All index mutations go through `update_index()` which holds the write lock, updates the in-memory `state.indexes`, and persists to S3.

Build with `cargo build` (not `--release`). The server binary is not in this repo.
