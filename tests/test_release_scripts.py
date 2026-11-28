"""Offline tests for the release-gating scripts (S9, yau7.9.9):
scripts/check_sdk_tag.py and scripts/check_version_consistency.py."""

import contextlib
import importlib.util
import io
import struct
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sdk_tag = _load("check_sdk_tag")
versions = _load("check_version_consistency")


# ─── check_sdk_tag ───────────────────────────────────────────────────────────

SDK = (6, 26, 2026, 27900)
MIN_SDK = (6, 25, 2025, 1)


def _dzversion_h(sdk=SDK, min_sdk=MIN_SDK):
    lines = []
    for prefix, v in (("DZ_SDK_VERSION", sdk), ("DZ_MIN_SDK_VERSION", min_sdk)):
        for field, n in zip(("MAJOR", "MINOR", "REV", "BUILD"), v):
            lines.append(f"#define {prefix}_{field} {n}")
    return "\n".join(lines) + "\n"


def _tag(version=SDK, layout=1):
    return struct.pack(sdk_tag.TAG_FORMAT, sdk_tag.MAGIC, layout, *version)


class TestSdkTag(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        (self.dir / "dzversion.h").write_text(_dzversion_h(), encoding="utf-8")

    def _plugin(self, payload: bytes) -> Path:
        p = self.dir / "plugin.dll"
        p.write_bytes(b"MZ\0\0junk" + payload + b"\0trailer")
        return p

    def _main(self, payload: bytes):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            try:
                sdk_tag.main(["x", str(self._plugin(payload)), str(self.dir)])
            except SystemExit as exc:
                return exc.code, out.getvalue()
        return 0, out.getvalue()

    def test_tag_size_matches_sdk_static_assert(self):
        self.assertEqual(sdk_tag.TAG_SIZE, 28)

    def test_reads_sdk_versions(self):
        self.assertEqual(sdk_tag.read_sdk_versions(self.dir), (MIN_SDK, SDK))

    def test_missing_define_exits(self):
        (self.dir / "dzversion.h").write_text("#define DZ_SDK_VERSION_MAJOR 6\n", encoding="utf-8")
        with self.assertRaises(SystemExit) as cm:
            sdk_tag.read_sdk_versions(self.dir)
        self.assertIn("not found", str(cm.exception.code))

    def test_find_tags(self):
        data = b"xx" + _tag() + b"yy" + sdk_tag.MAGIC + b"\0short"
        self.assertEqual(sdk_tag.find_tags(data), [(1, SDK)])
        self.assertEqual(sdk_tag.find_tags(b"no tag here"), [])

    def test_magic_prefix_without_nul_is_not_a_tag(self):
        self.assertEqual(sdk_tag.find_tags(sdk_tag.MAGIC + b"X" * 20), [])

    def test_matching_tag_passes(self):
        code, out = self._main(_tag())
        self.assertEqual(code, 0)
        self.assertIn("SDK tag OK", out)

    def test_missing_tag_fails(self):
        code, _ = self._main(b"")
        self.assertIn("no DzPluginSDKVersionTag", str(code))

    def test_duplicate_tags_fail(self):
        code, _ = self._main(_tag() + _tag())
        self.assertIn("2 SDK tags", str(code))

    def test_version_mismatch_fails(self):
        code, _ = self._main(_tag(version=(6, 25, 2025, 1)))
        self.assertIn("!= SDK version", str(code))

    def test_usage_on_wrong_argc(self):
        with self.assertRaises(SystemExit) as cm:
            sdk_tag.main(["x"])
        self.assertIn("Usage", str(cm.exception.code))


# ─── check_version_consistency ───────────────────────────────────────────────

V = "9.8.7"


def _tree(root: Path, version=V, **overrides):
    files = {
        "dazpy/__init__.py": f'__version__ = "{version}"\n',
        "pyproject.toml": ('[project]\ndynamic = ["version"]\n\n[tool.setuptools.dynamic]\n'
                           'version = {attr = "dazpy.__version__"}\n'),
        "include/common_version.h": (
            "#define DZSRV_MAJOR 9\n#define DZSRV_MINOR 8\n#define DZSRV_REV 7\n"
            f'#define DZSRV_VERSION_STR "{version}"\n'),
        "docs/conf.py": f'release = "{version}"\n',
        "openapi.yaml": f"openapi: 3.0.3\ninfo:\n  title: x\n  version: {version}\n",
        "README.md": f"**Version {version}**\n\n## What's New in v{version}\n\n- x\n",
        "CHANGELOG.md": f"# Changelog\n\n## [{version}] - 2026-01-01\n",
    }
    files.update(overrides)
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


class TestVersionConsistency(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def _run(self, argv=()):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = versions.main(list(argv), root=self.root)
        return rc, out.getvalue()

    def test_consistent_tree_passes(self):
        _tree(self.root)
        rc, out = self._run()
        self.assertEqual(rc, 0, out)
        self.assertIn(f"Version {V} is consistent", out)

    def test_real_repo_passes(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(versions.main([]), 0, out.getvalue())

    def test_matching_tag_passes_with_or_without_v(self):
        _tree(self.root)
        self.assertEqual(self._run(["--tag", f"v{V}"])[0], 0)
        self.assertEqual(self._run(["--tag", V])[0], 0)

    def test_tag_without_version_bump_fails(self):
        _tree(self.root)
        rc, out = self._run(["--tag", "v9.8.8"])
        self.assertEqual(rc, 1)
        self.assertIn("release tag: '9.8.8'", out)

    def test_each_location_is_checked(self):
        cases = {
            "docs/conf.py": 'release = "1.0.0"\n',
            "openapi.yaml": "info:\n  version: 1.0.0\n",
            "CHANGELOG.md": "## [1.0.0] - 2026-01-01\n",
            "include/common_version.h": (
                "#define DZSRV_MAJOR 9\n#define DZSRV_MINOR 8\n#define DZSRV_REV 6\n"
                f'#define DZSRV_VERSION_STR "{V}"\n'),
        }
        for rel, text in cases.items():
            with self.subTest(file=rel):
                _tree(self.root, **{rel: text})
                rc, out = self._run()
                self.assertEqual(rc, 1)
                self.assertIn(rel, out)

    def test_hardcoded_pyproject_version_fails(self):
        _tree(self.root, **{"pyproject.toml": f'[project]\nversion = "{V}"\n'})
        rc, out = self._run()
        self.assertEqual(rc, 1)
        self.assertIn("must not hard-code", out)

    def test_missing_dunder_version_fails(self):
        _tree(self.root, **{"dazpy/__init__.py": "# nothing\n"})
        rc, out = self._run()
        self.assertEqual(rc, 1)
        self.assertIn("no __version__", out)

    def test_readme_needs_whats_new_for_this_version(self):
        _tree(self.root, **{"README.md": f"**Version {V}**\n\n## What's New in v9.8.6\n"})
        rc, out = self._run()
        self.assertEqual(rc, 1)
        self.assertIn("What's New", out)

    def test_whats_new_range_heading_counts(self):
        _tree(self.root, **{"README.md": f"**Version {V}**\n\n## What's New in v9.8.5 – v{V}\n"})
        self.assertEqual(self._run()[0], 0)


if __name__ == "__main__":
    unittest.main()
