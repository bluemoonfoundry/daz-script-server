"""
Static checks on package archive extraction and package file writes.

No running server needed (runs in `python tests.py unit` / CI); the package
code links dzcore, so its source is checked instead, as in
test_package_importer_waits.py.

Guard (daz-script-server-yau7.4.4):
- ZipInstaller rejects, per path segment, Windows device names (CON, NUL,
  COM1, LPT1, with or without an extension), ':' (NTFS alternate data
  streams such as "foo:bar"), and trailing dots/spaces (Win32 strips them,
  so ".. " would open "..").
- Every package file write checks the bytes written and flush()/error(),
  because QFile::close() returns void and a full disk otherwise reports a
  truncated file as success.
"""

import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read_src(name):
    with open(os.path.join(ROOT, "src", name), encoding="utf-8") as f:
        return f.read()


def function_body(src, signature):
    start = src.index(signature)
    brace = src.index("{", start)
    depth = 0
    for i in range(brace, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[brace:i + 1]
    raise AssertionError("unbalanced braces after " + signature)


class ZipPathSegmentTest(unittest.TestCase):
    def setUp(self):
        self.src = read_src("ZipInstaller.cpp")

    def test_every_segment_is_checked(self):
        body = function_body(self.src, "bool isSafeRelativePath(")
        self.assertIn("isSafePathSegment(segment)", body)

    def test_reserved_device_names(self):
        body = function_body(self.src, "bool isWindowsReservedName(")
        for name in ("CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"):
            self.assertIn('"%s"' % name, body)
        self.assertIn('"COM"', body)
        self.assertIn('"LPT"', body)
        # The extension is ignored: "nul.txt" is the NUL device.
        self.assertIn("section(QLatin1Char('.'), 0, 0)", body)
        self.assertIn("toUpper()", body)

    def test_segment_rejects_colon_and_trailing_dot_space(self):
        body = function_body(self.src, "bool isSafePathSegment(")
        self.assertIn("QLatin1Char(':')", body)
        self.assertIn("endsWith(QLatin1Char('.'))", body)
        self.assertIn("endsWith(QLatin1Char(' '))", body)
        self.assertIn("isWindowsReservedName(segment)", body)


class CheckedWritesTest(unittest.TestCase):
    def test_extracted_entry_close_is_checked(self):
        src = read_src("ZipInstaller.cpp")
        self.assertRegex(src, r"const bool flushed = destFile\.flush\(\);\s*destFile\.close\(\);")
        self.assertIn("if (!flushed || destFile.error() != QFile::NoError)", src)

    def test_importer_writes_are_checked(self):
        src = read_src("DzPackageImporter.cpp")
        runner = function_body(src, "QString DzPackageImporter::writeDspRunner(")
        self.assertIn("out.write(contents) == contents.size() && out.flush()", runner)
        self.assertIn("out.error() != QFile::NoError", runner)
        run = function_body(src, "QVariantMap DzPackageImporter::runPackage(")
        self.assertIn("inputsFile.write(inputsBytes) != inputsBytes.size() || !inputsFile.flush()", run)

    def test_status_file_write_is_checked(self):
        src = read_src("PackageDependencyInstaller.cpp")
        body = function_body(src, "void PackageDependencyInstaller::writeStatusFile(")
        self.assertIn("statusFile.write(bytes) == bytes.size() && statusFile.flush()", body)
        self.assertIn("QFile::remove(statusFile.fileName())", body)

    def test_no_bare_unchecked_writes(self):
        # A statement that is only `x.write(...);` discards the result.
        bare = re.compile(r"^\s*\w+(?:\.|->)write\([^;]*\);\s*$", re.M)
        for name in ("ZipInstaller.cpp", "DzPackageImporter.cpp",
                     "PackageDependencyInstaller.cpp"):
            self.assertEqual(bare.findall(read_src(name)), [], name)


if __name__ == "__main__":
    unittest.main()
