# pm — Kominka Package Manager

`pm.ysh` is a ~2800-line YSH script. It resolves, builds, installs, and publishes packages for Kominka Linux.

## Commands

| Command | Description |
|---------|-------------|
| `pm i pkg` | Install binary from repo, auto-resolve runtime deps |
| `pm b pkg` | Build from source, resolve build+runtime deps |
| `pm p pkg` | Upload built tarball to repo server |
| `pm u` | Update local package index from repo server |
| `pm t pkg` | Show full dependency tree |
| `pm l` | List installed packages |
| `pm s` | Show package info |

## Package Format

Each package is a directory containing `PKGBUILD.ysh`:

```ysh
var name     = 'example'
var ver      = '1.0.0'
var rel      = '1'
var deps     = ['musl', 'zlib']      # runtime dependencies
var mkdeps   = ['zig', 'make']       # build-only dependencies

var sources  = ['https://example.com/example-VERSION.tar.gz']
var checksums = ['sha256hash...']

proc build(dest) {
    # dest is the staging directory
    env CC="$(command -v zig) cc -target $(uname -m)-linux-musl" \
    ./configure --prefix=/usr
    make
    make DESTDIR=$dest install
}
```

## Key Behaviors

- **Parallel downloads** with live progress display
- **Binary cache** at `~/.cache/kominka/bin/` — pre-seeded tarballs skip downloads
- **Makedep skip optimization** — if a runtime dep has a pre-built binary, its makedeps are skipped
- **Explicit typed parameters** — each package operation receives the loaded package record as a `p Dict`, no shared mutable globals for package state
- **Retry with backoff** — download failures are retried up to 5 times with exponential backoff

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `KOMINKA_PATH` | `/packages` | Path to package definitions |
| `KOMINKA_ROOT` | `` | Install root (empty = `/`) |
| `KOMINKA_REPO` | `` | Repo server URL |
| `KOMINKA_GET` | `` | Downloader binary (curl or wget) |
| `KOMINKA_INSECURE` | `` | Skip TLS verification if `1` |
| `KOMINKA_COMPRESS` | `gz` | Tarball compression format |
| `KOMINKA_FORCE` | `` | Force reinstall if `1` |
| `KOMINKA_STRIP` | `` | Strip binaries if `1` |
| `KOMINKA_TOKEN` | `` | Auth token for `pm p` uploads |

## Storage Layout

```
~/.cache/kominka/bin/       Binary cache (pkg@ver-rel.tar.gz)
/var/db/kominka/installed/  Installed package database
  {pkg}/version             "ver rel" or "system 1"
  {pkg}/depends             Runtime deps, one per line
  {pkg}/manifest            Installed file paths
```
