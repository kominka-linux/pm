"""Cheap/fast tests for pm that don't require building packages.

These tests exercise search, list, dependency resolution, checksum,
source resolution, argument validation, and version output by
manually populating the installed database and repo directories.

Every test class is duplicated for the YSH port via subclassing.
"""

import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PM_YSH = ROOT / "pm.ysh"
REPO = (ROOT / "packages").resolve()
YSH = shutil.which("ysh") or "/usr/local/bin/ysh"
HAS_YSH = os.path.isfile(YSH) and os.access(YSH, os.X_OK)


class CheapPMTestCase(unittest.TestCase):
    """Base class with isolated kominka environment and manual db population."""

    PM_INTERPRETER = YSH
    PM_SCRIPT = PM_YSH

    def setUp(self):
        self.tmpdir = os.path.realpath(tempfile.mkdtemp(prefix="pm-cheap-"))
        self.kominka_root = Path(self.tmpdir) / "root"
        self.kominka_cache = Path(self.tmpdir) / "cache"
        self.kominka_tmpdir = Path(self.tmpdir) / "proc"

        (self.kominka_root / "var/db/kominka/installed").mkdir(parents=True)
        (self.kominka_root / "var/db/kominka/choices").mkdir(parents=True)

        self.env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": self.tmpdir,
            "LOGNAME": os.environ.get("LOGNAME", "testuser"),
            "KOMINKA_PATH": str(REPO),
            "KOMINKA_ROOT": str(self.kominka_root),
            "KOMINKA_COLOR": "0",
            "KOMINKA_PROMPT": "0",
            "KOMINKA_COMPRESS": "gz",
            "KOMINKA_TMPDIR": str(self.kominka_tmpdir),
            "XDG_CACHE_HOME": str(self.kominka_cache),
        }

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def pm(self, *args, env_override=None, check=True):
        env = {**self.env}
        if env_override:
            env.update(env_override)
        result = subprocess.run(
            [self.PM_INTERPRETER, str(self.PM_SCRIPT), *args],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )
        if check and result.returncode != 0:
            self.fail(
                f"pm {' '.join(args)} exited {result.returncode}\n"
                f"stdout: {result.stdout}\n"
                f"stderr: {result.stderr}"
            )
        return result

    def fake_install(self, name, version="1.0 1", depends="", manifest=None):
        """Populate the installed db for a package without building it.

        Creates the db entry with version, build, manifest, and optionally
        depends files — mimicking what a real install leaves behind.
        """
        db = self.kominka_root / "var/db/kominka/installed" / name
        db.mkdir(parents=True, exist_ok=True)
        (db / "version").write_text(version + "\n")
        if depends:
            (db / "depends").write_text(depends + "\n")
        # pkg_find_version checks that the build file is executable.
        build = db / "build"
        build.write_text("#!/bin/sh\n")
        build.chmod(0o755)
        if manifest is None:
            # Real manifests include the db entries themselves.
            db_prefix = f"/var/db/kominka/installed/{name}"
            lines = [
                f"/usr/bin/{name}",
                f"{db_prefix}/manifest",
                f"{db_prefix}/version",
                f"{db_prefix}/build",
            ]
            if depends:
                lines.append(f"{db_prefix}/depends")
            lines.append(f"{db_prefix}/")
            manifest = "\n".join(lines) + "\n"
        (db / "manifest").write_text(manifest)
        return db

    def create_repo_pkg(self, name, version="1.0 1", depends="", sources="",
                        build=None):
        """Create a minimal package as a PKGBUILD.ysh in a temporary repo."""
        repo = Path(self.tmpdir) / "extra-repo" / name
        repo.mkdir(parents=True)

        ver_parts = version.split()
        pkgver = ver_parts[0]
        pkgrel = ver_parts[1] if len(ver_parts) > 1 else "1"

        # Parse depends into runtime and make deps.
        runtime_deps = []
        make_deps = []
        if depends:
            for line in depends.strip().splitlines():
                parts = line.split()
                if not parts:
                    continue
                if len(parts) >= 2 and parts[1] == "make":
                    make_deps.append(parts[0])
                else:
                    runtime_deps.append(parts[0])

        deps_str = repr(runtime_deps)
        mkdeps_str = repr(make_deps)

        sources_list = [s for s in sources.splitlines() if s] if sources else []
        sources_str = repr(sources_list)

        build_body = build or textwrap.dedent("""\
            mkdir -p "$dest/usr/bin"
            printf 'mock' > "$dest/usr/bin/{name}"
        """).format(name=name)

        pkgbuild = textwrap.dedent(f"""\
            #!/usr/local/bin/ysh

            var name    = {name!r}
            var ver     = {pkgver!r}
            var rel     = {pkgrel!r}
            var deps    = {deps_str}
            var mkdeps  = {mkdeps_str}
            var nostrip = false
            var sources = {sources_str}
            var checksums = []

            proc build(dest) {{
                {build_body.strip()}
            }}
        """)
        (repo / "PKGBUILD.ysh").write_text(pkgbuild)
        (repo / "PKGBUILD.ysh").chmod(0o755)
        self.env["KOMINKA_PATH"] = str(repo.parent) + ":" + self.env["KOMINKA_PATH"]
        return repo


class HelpTests:
    def test_no_args_prints_usage(self):
        r = self.pm()
        self.assertIn("pm [a|b|c|d|h|i|l|p|r|s|u|U|v]", r.stderr)

    def test_help_mentions_all_commands(self):
        r = self.pm()
        for cmd in ["alternatives", "build", "checksum", "download",
                     "install", "list", "remove", "search", "update",
                     "upgrade", "version"]:
            self.assertIn(cmd, r.stderr, f"Help missing '{cmd}'")

    def test_version(self):
        r = self.pm("v")
        self.assertIn("5.5.28", r.stdout)


class SearchTests:
    def test_search_finds_package(self):
        r = self.pm("s", "zlib")
        self.assertIn("zlib", r.stdout)

    def test_search_finds_multiple(self):
        for pkg in ["boringssl", "curl", "glibc", "busybox"]:
            r = self.pm("s", pkg)
            self.assertIn(pkg, r.stdout)

    def test_search_missing_fails(self):
        r = self.pm("s", "nonexistent-pkg-xyz", check=False)
        self.assertNotEqual(r.returncode, 0)

    def test_search_finds_repo_pkg(self):
        """Search should find packages we add to the repo."""
        self.create_repo_pkg("mypkg")
        r = self.pm("s", "mypkg")
        self.assertIn("mypkg", r.stdout)

    def test_search_prints_all_matches(self):
        """If a package exists in multiple repos, all paths are printed."""
        self.create_repo_pkg("zlib", version="999.0 1")
        r = self.pm("s", "zlib")
        lines = [l for l in r.stdout.strip().split("\n") if "zlib" in l]
        self.assertGreaterEqual(len(lines), 2)


class ListTests:
    def test_list_empty(self):
        r = self.pm("l", check=False)
        # SH version errors (glob expands to literal *), YSH returns 0 (empty glob).
        # In either case, no package names should appear in output.
        self.assertEqual(r.stdout.strip(), "")

    def test_list_fake_installed(self):
        self.fake_install("mypkg", "2.3 1")
        r = self.pm("l")
        self.assertIn("mypkg", r.stdout)
        self.assertIn("2.3-1", r.stdout)

    def test_list_multiple(self):
        self.fake_install("alpha", "1.0 1")
        self.fake_install("bravo", "2.0 2")
        r = self.pm("l")
        self.assertIn("alpha", r.stdout)
        self.assertIn("bravo", r.stdout)

    def test_list_specific_package(self):
        self.fake_install("target", "3.0 1")
        self.fake_install("other", "1.0 1")
        r = self.pm("l", "target")
        self.assertIn("target", r.stdout)
        self.assertNotIn("other", r.stdout)

    def test_list_specific_missing(self):
        r = self.pm("l", "nonexistent", check=False)
        self.assertNotEqual(r.returncode, 0)

    def test_list_version_format(self):
        """Output should be 'name version-release'."""
        self.fake_install("fmt", "4.5.6 3")
        r = self.pm("l")
        self.assertIn("fmt 4.5.6-3", r.stdout)


class DependencyTests:
    def test_circular_dependency_detected(self):
        self.create_repo_pkg("pkg-a", depends="pkg-b")
        self.create_repo_pkg("pkg-b", depends="pkg-a")
        r = self.pm("b", "pkg-a", check=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("Circular", r.stderr)

    def test_missing_dependency_fails(self):
        """A package depending on something that doesn't exist should fail."""
        self.create_repo_pkg("lonely", depends="ghost-pkg")
        r = self.pm("b", "lonely", check=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("not found", r.stderr)

    def test_deep_dependency_chain(self):
        """A -> B -> C -> D. Building A should discover all deps."""
        self.create_repo_pkg("dep-d")
        self.create_repo_pkg("dep-c", depends="dep-d")
        self.create_repo_pkg("dep-b", depends="dep-c")
        self.create_repo_pkg("dep-a", depends="dep-b")
        r = self.pm("b", "dep-a", check=False)
        # Should get past dep resolution without circular or missing dep errors.
        self.assertNotIn("Circular", r.stderr)
        # Check specifically for "'X' not found" (package not found), not
        # generic "not found" which appears in tool discovery messages.
        self.assertNotIn("' not found", r.stderr)

    def test_diamond_dependency(self):
        """A -> B, A -> C, B -> D, C -> D. No circular error."""
        self.create_repo_pkg("dia-d")
        self.create_repo_pkg("dia-c", depends="dia-d")
        self.create_repo_pkg("dia-b", depends="dia-d")
        self.create_repo_pkg("dia-a", depends="dia-b\ndia-c")
        r = self.pm("b", "dia-a", check=False)
        self.assertNotIn("Circular", r.stderr)
        self.assertNotIn("' not found", r.stderr)


class ChecksumTests:
    def test_checksum_generates_file(self):
        repo = self.create_repo_pkg("ckpkg", sources="data.tar.gz")
        (repo / "data.tar.gz").write_bytes(b"fake tarball content")

        r = self.pm("c", "ckpkg")
        # pm c prints checksums to stdout for pasting into PKGBUILD.ysh.
        content = (r.stdout + r.stderr).strip()
        # Find the hash line (64 hex chars).
        lines = [l for l in content.splitlines() if len(l) == 64 and
                 all(c in "0123456789abcdef" for c in l)]
        self.assertEqual(len(lines), 1)

    def test_checksum_no_sources(self):
        self.create_repo_pkg("nosrc")
        r = self.pm("c", "nosrc")
        self.assertEqual(r.returncode, 0)

    def test_checksum_multiple_sources(self):
        repo = self.create_repo_pkg("multi", sources="file1.txt\nfile2.txt")
        (repo / "file1.txt").write_text("aaa")
        (repo / "file2.txt").write_text("bbb")

        r = self.pm("c", "multi")
        combined = r.stdout + r.stderr
        lines = [l for l in combined.splitlines() if len(l) == 64 and
                 all(c in "0123456789abcdef" for c in l)]
        self.assertEqual(len(lines), 2)

    def test_checksum_deterministic(self):
        """Running checksum twice should produce the same result."""
        repo = self.create_repo_pkg("det", sources="payload.bin")
        (repo / "payload.bin").write_bytes(b"\x00\x01\x02" * 100)

        r1 = self.pm("c", "det")
        r2 = self.pm("c", "det")
        self.assertEqual(r1.stdout + r1.stderr, r2.stdout + r2.stderr)

    def test_checksum_skips_git_sources(self):
        """git+ sources should not generate checksums."""
        repo = self.create_repo_pkg("gitpkg",
                                    sources="git+https://example.com/repo\nlocal.txt")
        (repo / "local.txt").write_text("data")

        r = self.pm("c", "gitpkg")
        combined = r.stdout + r.stderr
        # Only local.txt gets a hash — git sources are skipped.
        lines = [l for l in combined.splitlines() if len(l) == 64 and
                 all(c in "0123456789abcdef" for c in l)]
        self.assertEqual(len(lines), 1)


class DownloadTests:
    def test_download_local_sources(self):
        repo = self.create_repo_pkg("localpkg", sources="localfile.txt")
        (repo / "localfile.txt").write_text("content")

        r = self.pm("d", "localpkg")
        self.assertEqual(r.returncode, 0)
        combined = r.stdout + r.stderr
        self.assertIn("found", combined)

    def test_download_missing_source_fails(self):
        self.create_repo_pkg("badpkg", sources="nonexistent-file.tar.gz")

        r = self.pm("d", "badpkg", check=False)
        self.assertNotEqual(r.returncode, 0)

    def test_download_no_sources_ok(self):
        self.create_repo_pkg("nosrc2")
        r = self.pm("d", "nosrc2")
        self.assertEqual(r.returncode, 0)


class VersionSubstitutionTests:
    def test_version_placeholder(self):
        repo = self.create_repo_pkg("subst", version="2.5.3 1",
                                    sources="data-VERSION.txt")
        (repo / "data-2.5.3.txt").write_text("content")

        r = self.pm("d", "subst")
        self.assertEqual(r.returncode, 0)

    def test_major_minor_patch_placeholders(self):
        """MAJOR, MINOR, PATCH should also be substituted."""
        repo = self.create_repo_pkg("mmp", version="3.7.11 1",
                                    sources="data-MAJOR-MINOR-PATCH.txt")
        (repo / "data-3-7-11.txt").write_text("content")

        r = self.pm("d", "mmp")
        self.assertEqual(r.returncode, 0)


class ArgumentValidationTests:
    def test_invalid_chars_rejected(self):
        for bad in ["pkg!bad", "pkg[x]", "pkg x"]:
            r = self.pm("b", bad, check=False)
            self.assertNotEqual(
                r.returncode, 0,
                f"Should reject package name '{bad}'",
            )

    def test_slash_in_non_install_rejected(self):
        r = self.pm("b", "some/path", check=False)
        self.assertNotEqual(r.returncode, 0)

    def test_slash_in_install_allowed(self):
        """Install accepts '/' (for tarball paths)."""
        # This will fail because the file doesn't exist, but it should
        # NOT fail on argument validation.
        r = self.pm("i", "/tmp/no-such-file.tar.gz", check=False)
        # Should fail because file is missing, not because of '/'.
        self.assertNotEqual(r.returncode, 0)
        # The error should NOT be about invalid arguments.
        self.assertNotIn("Invalid argument", r.stderr)

    def test_wildcard_rejected(self):
        r = self.pm("b", "pkg*", check=False)
        self.assertNotEqual(r.returncode, 0)


class RemoveDependentTests:
    """Test remove's dependent checking without building."""

    def test_remove_blocks_on_dependents(self):
        """Can't remove a package that others depend on."""
        self.fake_install("base-lib", "1.0 1")
        self.fake_install("consumer", "1.0 1", depends="base-lib")
        r = self.pm("r", "base-lib", check=False)
        self.assertNotEqual(r.returncode, 0)

    def test_remove_force_overrides_dependent_check(self):
        self.fake_install("base-lib", "1.0 1")
        self.fake_install("consumer", "1.0 1", depends="base-lib")
        # Create the file that the manifest references.
        f = self.kominka_root / "usr/bin/base-lib"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("mock")
        r = self.pm("r", "base-lib", env_override={"KOMINKA_FORCE": "1"})
        self.assertEqual(r.returncode, 0)

    def test_remove_orphan_succeeds(self):
        """Removing a package with no dependents should succeed."""
        self.fake_install("orphan", "1.0 1")
        # Create the file that the manifest references.
        f = self.kominka_root / "usr/bin/orphan"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("mock")
        r = self.pm("r", "orphan")
        self.assertEqual(r.returncode, 0)
        self.assertFalse(
            (self.kominka_root / "var/db/kominka/installed/orphan").exists()
        )


class UpdateTests:
    """Test that pm U detects and applies release bumps."""

    def test_upgrade_detects_release_bump(self):
        """Bump release 1 -> 2 in repo; pm U should report it."""
        repo = self.create_repo_pkg("upgpkg", version="1.0 1")
        # Build and install v1.0-1.
        self.pm("b", "upgpkg")
        self.pm("i", "upgpkg", env_override={"KOMINKA_FORCE": "1"})
        # Verify installed.
        r = self.pm("l")
        self.assertIn("upgpkg 1.0-1", r.stdout)
        # Bump release in PKGBUILD.ysh.
        txt = (repo / "PKGBUILD.ysh").read_text()
        (repo / "PKGBUILD.ysh").write_text(txt.replace("var rel     = '1'", "var rel     = '2'"))
        # pm U should detect the update.
        r = self.pm("U", env_override={"KOMINKA_PROMPT": "0"})
        combined = r.stdout + r.stderr
        self.assertIn("upgpkg 1.0-1 => 1.0-2", combined)

    def test_upgrade_applies_release_bump(self):
        """After pm U, installed version should reflect the new release."""
        repo = self.create_repo_pkg("relup", version="2.0 1")
        self.pm("b", "relup")
        self.pm("i", "relup", env_override={"KOMINKA_FORCE": "1"})
        # Bump release in PKGBUILD.ysh.
        txt = (repo / "PKGBUILD.ysh").read_text()
        (repo / "PKGBUILD.ysh").write_text(txt.replace("var rel     = '1'", "var rel     = '2'"))
        self.pm("U", env_override={"KOMINKA_PROMPT": "0"})
        r = self.pm("l")
        self.assertIn("relup 2.0-2", r.stdout)

    def test_upgrade_no_change_when_current(self):
        """If installed == repo version, pm U should report nothing."""
        self.create_repo_pkg("curpkg", version="1.0 1")
        self.pm("b", "curpkg")
        self.pm("i", "curpkg", env_override={"KOMINKA_FORCE": "1"})
        r = self.pm("U", env_override={"KOMINKA_PROMPT": "0"})
        combined = r.stdout + r.stderr
        self.assertNotIn("=>", combined)

    def test_upgrade_detects_version_bump(self):
        """Bump upstream version 1.0 -> 2.0; pm U should report it."""
        repo = self.create_repo_pkg("verbump", version="1.0 1")
        self.pm("b", "verbump")
        self.pm("i", "verbump", env_override={"KOMINKA_FORCE": "1"})
        # Update version in PKGBUILD.ysh
        txt = (repo / "PKGBUILD.ysh").read_text()
        (repo / "PKGBUILD.ysh").write_text(txt.replace("var ver     = '1.0'", "var ver     = '2.0'"))
        r = self.pm("U", env_override={"KOMINKA_PROMPT": "0"})
        combined = r.stdout + r.stderr
        self.assertIn("verbump 1.0-1 => 2.0-1", combined)


class MakeDepTests:
    """Test that make (build-only) deps are handled correctly."""

    def test_build_skips_make_deps_of_installed_packages(self):
        """pm b should not pull make deps of already-installed packages.

        Mirrors the CI scenario: boringssl is installed (has cmake/go/samurai
        as make deps), curl depends on boringssl at runtime.  pm b curl must
        NOT resolve cmake/go/samurai.  Crucially, the make deps themselves
        are NOT installed — only the parent is.
        """
        # buildtool is a make dep of mylib — exists in repo but NOT installed.
        self.create_repo_pkg("buildtool", version="1.0 1")
        # mylib has buildtool as a make dep.
        self.create_repo_pkg("mylib", version="1.0 1", depends="buildtool make")
        # Mark mylib as installed WITHOUT installing buildtool.
        self.fake_install("mylib", version="1.0 1", depends="buildtool make")
        # myapp depends on mylib at runtime.
        self.create_repo_pkg("myapp", version="1.0 1", depends="mylib")

        # Build myapp — should NOT try to build buildtool since mylib is installed.
        r = self.pm("b", "myapp", env_override={"KOMINKA_FORCE": "1"})
        combined = r.stdout + r.stderr
        self.assertNotIn("buildtool", combined)

    def test_build_includes_make_deps_of_uninstalled_packages(self):
        """pm b should pull make deps of packages that need building."""
        self.create_repo_pkg("compiler", version="1.0 1")
        lib_repo = self.create_repo_pkg("mylib2", version="1.0 1",
                                         depends="compiler make")
        self.create_repo_pkg("myapp2", version="1.0 1", depends="mylib2")

        # mylib2 is NOT installed — its make dep (compiler) should be resolved.
        r = self.pm("b", "myapp2", env_override={"KOMINKA_FORCE": "1"})
        combined = r.stdout + r.stderr
        self.assertIn("compiler", combined)

    def test_install_succeeds_with_uninstalled_make_dep(self):
        """pm i must not fail when make deps are absent on the target system.

        Regression: pkg_installable was checking all depends-file entries
        including make deps, so 'pm i boringssl' would fail with
        'Package not installable' because cmake/go/samurai weren't installed.
        Make deps are build-time only and must be invisible at install time.

        Note: test_install_skips_all_make_deps uses KOMINKA_FORCE=1 which
        bypasses pkg_installable entirely — it cannot catch this regression.

        The scenario: package built in CI (make deps present), tarball
        uploaded to R2, then installed on a fresh system lacking make deps.
        Simulated by building to populate the binary cache, then wiping the
        installed db to represent the fresh-system state.
        """
        self.create_repo_pkg("buildtool", version="1.0 1")
        self.create_repo_pkg("mypkg4", version="1.0 1", depends="buildtool make")

        # Build — populates the binary cache with mypkg4's tarball.
        self.pm("b", "mypkg4")

        # Wipe the installed db: simulate a fresh system that has the tarball
        # (via KOMINKA_BIN_MIRROR / pre-downloaded cache) but has never had
        # buildtool or mypkg4 installed.
        db = self.kominka_root / "var/db/kominka/installed"
        shutil.rmtree(db / "buildtool", ignore_errors=True)
        shutil.rmtree(db / "mypkg4",    ignore_errors=True)

        # Install WITHOUT KOMINKA_FORCE — pkg_installable must skip make deps.
        self.pm("i", "mypkg4")

        r = self.pm("l")
        self.assertIn("mypkg4", r.stdout)
        self.assertNotIn("buildtool", r.stdout)

    def test_install_skips_all_make_deps(self):
        """pm i should not install make deps as new packages."""
        self.create_repo_pkg("devtool2", version="1.0 1")
        self.create_repo_pkg("mypkg3", version="1.0 1", depends="devtool2 make")
        # Only build mypkg3 (devtool2 gets built as make dep).
        self.pm("b", "mypkg3")
        # Remove devtool2 that was installed during build.
        self.pm("r", "devtool2", env_override={"KOMINKA_FORCE": "1"})
        # Now pm i should NOT reinstall devtool2.
        self.pm("i", "mypkg3", env_override={"KOMINKA_FORCE": "1"})
        r = self.pm("l")
        self.assertNotIn("devtool2", r.stdout)


class ParallelInstallTests:
    """Test that pm i with multiple packages installs all of them."""

    def test_multi_install_all_present(self):
        """pm i pkg1 pkg2 pkg3 should install all three."""
        self.create_repo_pkg("alpha", version="1.0 1")
        self.create_repo_pkg("bravo", version="2.0 1")
        self.create_repo_pkg("charlie", version="3.0 1")
        self.pm("b", "alpha")
        self.pm("b", "bravo")
        self.pm("b", "charlie")
        self.pm("i", "alpha", "bravo", "charlie",
                env_override={"KOMINKA_FORCE": "1"})
        r = self.pm("l")
        self.assertIn("alpha", r.stdout)
        self.assertIn("bravo", r.stdout)
        self.assertIn("charlie", r.stdout)

    def test_multi_install_files_correct(self):
        """Each package's files should land in the rootfs."""
        self.create_repo_pkg("foo", version="1.0 1")
        self.create_repo_pkg("bar", version="1.0 1")
        self.pm("b", "foo")
        self.pm("b", "bar")
        self.pm("i", "foo", "bar",
                env_override={"KOMINKA_FORCE": "1"})
        self.assertTrue(
            (self.kominka_root / "usr/bin/foo").exists())
        self.assertTrue(
            (self.kominka_root / "usr/bin/bar").exists())


@unittest.skipUnless(HAS_YSH, "ysh interpreter not found")
class YSH_MakeDepTests(CheapPMTestCase, MakeDepTests):
    PM_INTERPRETER = YSH
    PM_SCRIPT = PM_YSH


@unittest.skipUnless(HAS_YSH, "ysh interpreter not found")
class YSH_ParallelInstallTests(CheapPMTestCase, ParallelInstallTests):
    PM_INTERPRETER = YSH
    PM_SCRIPT = PM_YSH


@unittest.skipUnless(HAS_YSH, "ysh interpreter not found")
class YSH_UpdateTests(CheapPMTestCase, UpdateTests):
    PM_INTERPRETER = YSH
    PM_SCRIPT = PM_YSH


@unittest.skipUnless(HAS_YSH, "ysh interpreter not found")
class YSH_HelpTests(CheapPMTestCase, HelpTests):
    PM_INTERPRETER = YSH
    PM_SCRIPT = PM_YSH

@unittest.skipUnless(HAS_YSH, "ysh interpreter not found")
class YSH_SearchTests(CheapPMTestCase, SearchTests):
    PM_INTERPRETER = YSH
    PM_SCRIPT = PM_YSH

@unittest.skipUnless(HAS_YSH, "ysh interpreter not found")
class YSH_ListTests(CheapPMTestCase, ListTests):
    PM_INTERPRETER = YSH
    PM_SCRIPT = PM_YSH

@unittest.skipUnless(HAS_YSH, "ysh interpreter not found")
class YSH_DependencyTests(CheapPMTestCase, DependencyTests):
    PM_INTERPRETER = YSH
    PM_SCRIPT = PM_YSH

@unittest.skipUnless(HAS_YSH, "ysh interpreter not found")
class YSH_ChecksumTests(CheapPMTestCase, ChecksumTests):
    PM_INTERPRETER = YSH
    PM_SCRIPT = PM_YSH

@unittest.skipUnless(HAS_YSH, "ysh interpreter not found")
class YSH_DownloadTests(CheapPMTestCase, DownloadTests):
    PM_INTERPRETER = YSH
    PM_SCRIPT = PM_YSH

@unittest.skipUnless(HAS_YSH, "ysh interpreter not found")
class YSH_VersionSubstitutionTests(CheapPMTestCase, VersionSubstitutionTests):
    PM_INTERPRETER = YSH
    PM_SCRIPT = PM_YSH

@unittest.skipUnless(HAS_YSH, "ysh interpreter not found")
class YSH_ArgumentValidationTests(CheapPMTestCase, ArgumentValidationTests):
    PM_INTERPRETER = YSH
    PM_SCRIPT = PM_YSH

@unittest.skipUnless(HAS_YSH, "ysh interpreter not found")
class YSH_RemoveDependentTests(CheapPMTestCase, RemoveDependentTests):
    PM_INTERPRETER = YSH
    PM_SCRIPT = PM_YSH


@unittest.skipUnless(HAS_YSH, "ysh interpreter not found")
class YSH_SyntaxTests(unittest.TestCase):
    """Static syntax checks: ysh -n catches parse errors without execution."""

    def _check(self, path):
        result = subprocess.run(
            [YSH, "-n", str(path)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            self.fail(f"{path.name}: {result.stderr.strip()}")

    def test_pm_ysh_parses(self):
        self._check(PM_YSH)

    def test_pkgbuilds_parse(self):
        pkgbuilds = sorted(REPO.glob("*/PKGBUILD.ysh"))
        self.assertTrue(pkgbuilds, "No PKGBUILD.ysh fixtures found")
        for pkgbuild in pkgbuilds:
            with self.subTest(pkg=pkgbuild.parent.name):
                self._check(pkgbuild)


if __name__ == "__main__":
    unittest.main()
