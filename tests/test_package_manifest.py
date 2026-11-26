"""
Checks on .dzpkg manifest validation (daz-script-server-yau7.4.5).

No running server needed (runs in `python tests.py unit` / CI). The validators
live in src/PackageManifest.cpp, which needs Qt, so this test lifts the
dependency regex out of that file and runs it with Python's re module (the
pattern is written in the subset both engines share), then checks statically
that DzPackageImporter and PackageDependencyInstaller call the validators.

Threat: manifest "dependencies" entries are passed to `uv pip install` as
separate arguments, so an entry starting with '-' became an option
(--index-url <attacker index>); "entryPoint" was joined onto the package dir
with QDir::filePath, which accepts absolute paths and "..".
"""

import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST_CPP = os.path.join(ROOT, "src", "PackageManifest.cpp")
IMPORTER_CPP = os.path.join(ROOT, "src", "DzPackageImporter.cpp")
INSTALLER_CPP = os.path.join(ROOT, "src", "PackageDependencyInstaller.cpp")
CMAKE = os.path.join(ROOT, "src", "CMakeLists.txt")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def function_body(src, signature):
    start = src.index(signature)
    end = src.index("\n}\n", start)
    return src[start:end]


def dependency_pattern():
    """kDependencyPattern from PackageManifest.cpp: adjacent C string
    literals joined, C escapes ("\\\\[") undone."""
    src = read(MANIFEST_CPP)
    m = re.search(r"kDependencyPattern\s*=\s*((?:\s*\"(?:[^\"\\]|\\.)*\")+)\s*;", src)
    assert m, "kDependencyPattern not found in PackageManifest.cpp"
    literals = re.findall(r"\"((?:[^\"\\]|\\.)*)\"", m.group(1))
    return re.compile("".join(literals).replace("\\\\", "\\"))


VALID = [
    "numpy",
    "Pillow",
    "opencv-python",
    "zope.interface",
    "a",
    "requests[security]",
    "requests[security,socks]",
    "numpy==1.26.4",
    "numpy>=1.24,<2",
    "numpy >= 1.24, < 2",
    "torch~=2.1",
    "foo===1.0",
    "foo!=1.5.*",
    "foo==1.0+local.1",
    "foo==2.0rc1",
]

INVALID = [
    "",
    "-r",
    "--index-url",
    "--index-url=https://evil.example/simple",
    "--extra-index-url https://evil.example/simple",
    "-e git+https://evil.example/repo.git",
    "-",
    ".",
    "../evil",
    "./local_pkg",
    "/abs/path/pkg.whl",
    "C:\\pkgs\\evil.whl",
    "foo @ https://evil.example/foo.whl",
    "foo@https://evil.example/foo.whl",
    "https://evil.example/foo.whl",
    "git+https://evil.example/repo.git",
    "foo; python_version<'3.8'",
    "foo --index-url https://evil.example",
    "foo\n--index-url=https://evil.example",
    "_foo",
    "foo-",
    "foo[",
    "foo==",
    "foo==1.0 bar",
    "foo==1.0;rm",
]


class DependencyPatternTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pattern = dependency_pattern()

    def matches(self, dependency):
        # QRegExp::exactMatch / anchored QRegularExpression; Python's "$"
        # also matches before a trailing newline, so use fullmatch.
        return self.pattern.fullmatch(dependency) is not None

    def test_plain_requirements_accepted(self):
        for dep in VALID:
            with self.subTest(dep=dep):
                self.assertTrue(self.matches(dep), dep)

    def test_options_urls_paths_markers_rejected(self):
        for dep in INVALID:
            with self.subTest(dep=dep):
                self.assertFalse(self.matches(dep), dep)

    def test_pattern_has_no_engine_specific_syntax(self):
        # Must mean the same thing to QRegExp (Qt4), QRegularExpression (PCRE)
        # and Python re: no lookarounds, lazy quantifiers, \s, \d, etc.
        src = self.pattern.pattern
        for token in ("(?=", "(?!", "(?<", "*?", "+?", "\\s", "\\d", "\\w"):
            self.assertNotIn(token, src)


class ValidationWiringTest(unittest.TestCase):
    def test_read_manifest_validates_dependencies_and_entry_point(self):
        body = function_body(read(IMPORTER_CPP), "bool readManifest(")
        self.assertIn("PackageManifest::readDependencies(", body)
        self.assertIn("PackageManifest::validateEntryPoint(stagingDir", body)

    def test_manifest_read_before_commit(self):
        src = read(IMPORTER_CPP)
        body = function_body(src, "DzError DzPackageImporter::read(")
        self.assertLess(body.index("readManifest("), body.index("installer.commit("),
                        "manifest must be validated on the staged copy, before commit()")

    def test_read_does_not_coerce_dependencies_with_toStringList(self):
        body = function_body(read(IMPORTER_CPP), "DzError DzPackageImporter::read(")
        self.assertNotIn('value("dependencies").toStringList()', body)

    def test_installer_guards_before_uv(self):
        body = function_body(read(INSTALLER_CPP), "void PackageDependencyInstaller::installDeps(")
        guard = body.find("PackageManifest::isValidDependency(")
        self.assertNotEqual(guard, -1, "installDeps() must re-check each dependency")
        self.assertLess(guard, body.index("arguments += m_dependencies"))

    def test_installer_run_does_not_fail_synchronously(self):
        # A finished() emitted inside run() fires before ensureDependencies()
        # enters loop.exec(), whose quit() is then lost (yau7.4.2).
        body = function_body(read(INSTALLER_CPP), "void PackageDependencyInstaller::run(")
        self.assertNotIn("fail(", body)

    def test_built(self):
        cmake = read(CMAKE)
        self.assertIn("PackageManifest.cpp", cmake)
        self.assertIn("../include/PackageManifest.h", cmake)

    def test_entry_point_checks(self):
        body = function_body(read(MANIFEST_CPP), "bool validateEntryPoint(")
        for needle in ("QDir::isAbsolutePath(", "QLatin1Char(':')", 'QLatin1String("..")',
                       "canonicalFilePath()", "isFile()", "startsWith(root + QLatin1Char('/')"):
            with self.subTest(check=needle):
                self.assertIn(needle, body)


if __name__ == "__main__":
    unittest.main()
