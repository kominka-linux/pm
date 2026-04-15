# Source Mirroring Plan

Mirror upstream package sources in the Kominka repo server, with optional preprocessing
to strip unnecessary files (test suites, benchmarks, fuzz corpora) before archiving.

## Goals

- Every package build produces a processed `.tar.bz2` source archive uploaded alongside
  the binary tarball.
- Subsequent builds pull from the mirror instead of upstream, making builds faster and
  reproducible even if upstream disappears.
- `pm src <pkg>` backfills the mirror for packages already in the repo without rebuilding.
- `KOMINKA_MIRROR` (per-file unprocessed mirror) is removed; sources live in the repo.

## PKGBUILD changes

Packages may define an optional `process(src)` proc:

```ysh
proc process(src) {
    # src is the build working directory (all sources extracted).
    # CWD is also set to src. Use relative paths freely.
    rm -rf $src/test $src/fuzz $src/third_party/googletest
}
```

Called after all sources are extracted and `.git/` directories are stripped, before
`build(dest)`. If not defined, sources are still repacked (for mirroring) but unmodified.

## pm.ysh changes

### New cache directory

`~/.cache/kominka/src/` (`mir_dir`) — stores processed source tarballs named
`{pkg}@{ver}-{rel}.tar.bz2`. Always bzip2-compressed.

### Build flow (`pm b`)

Before each package's source downloads, check whether the remote index has `src_sha256`
for this package at the current `ver`-`rel`. If yes:

1. Download `{KOMINKA_REPO}/src/{pkg}/{ver}-{rel}.tar.bz2` to `mir_dir`.
2. Verify SHA256 against `src_sha256` from the index.
3. Extract into `mak_dir/{pkg}/` — skip all upstream downloads, `.git` strip, and
   `process()` (already done when mirror was created).

If no mirror is available, fall back to the normal path:

1. Download upstream sources (`pkg_source`).
2. Verify upstream checksums (`pkg_verify`).
3. Extract (`pkg_extract`).
4. Strip all `.git/` directories unconditionally.
5. Call `process(src)` if defined in PKGBUILD.ysh.

Either way, pack `mak_dir/{pkg}/` as `mir_dir/{pkg}@{ver}-{rel}.tar.bz2` before calling
`build(dest)`. The tarball captures the exact state the build will see.

### Upload flow (`pm p`)

After uploading the binary tarball, upload the source tarball:

- If `mir_dir/{pkg}@{ver}-{rel}.tar.bz2` exists: `POST /api/upload-src`.
- If not: print a hint to run `pm b` first.
- Source upload failure is a warning, not a fatal error.

### Download (`pm d`)

Prefers the mirror: tries `pkg_mirror_use` first; falls back to upstream `pkg_source`.

### New command: `pm src <pkg>...`

Backfill source mirrors without building binaries:

1. `index_refresh` — fetch the latest packages.json.
2. For each package, skip if already mirrored at current `ver`-`rel`.
3. Download upstream sources, verify checksums, extract, strip `.git/`, call `process()`.
4. Pack source tarball and upload to `/api/upload-src`.

Metapackages (`sources = []`) are skipped.

### Removed

- `KOMINKA_MIRROR` env var and all associated logic in `pkg_source`.

## Server changes (`server/src/packages.rs`)

### `PackageEntry` — new field

```rust
#[serde(default, skip_serializing_if = "Option::is_none")]
pub src_sha256: Option<String>,
```

Omitted from `packages.json` when absent, so existing index entries are unaffected.
Set by `/api/upload-src` after a successful source upload.

### New endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/src/{pkg}/{ver}-{rel}.tar.bz2` | No | Serve source tarball; 302→R2 if configured |
| `POST` | `/api/upload-src` | Bearer token | Upload source tarball; headers: X-Pkg, X-Ver, X-Rel |

`/api/upload-src`:
- Stores tarball at `src/{pkg}/{ver}-{rel}.tar.bz2` in S3.
- Computes SHA256, updates `src_sha256` on the matching entry in all arch indexes.
- Returns `{"ok":true}` 201.

Sources are arch-independent, so there is no arch prefix in the S3 key or URL.

## Implementation status

Complete. All procs and server handlers are implemented.
