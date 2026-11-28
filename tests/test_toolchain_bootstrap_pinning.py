"""
Static checks on the uv install step in src/PythonToolchainBootstrapper.cpp.

No running server needed (runs in `python tests.py unit` / CI); the
bootstrapper links dzcore, so its source is checked instead, as in
test_package_importer_waits.py.

Guard (daz-script-server-yau7.4.6): uv used to be installed by piping
astral's install script into a shell (`irm ... | iex` / `curl ... | sh`),
unpinned and unverified, so a compromised endpoint ran code in the user's
session. It must now download one pinned release archive, check its SHA-256
against a digest compiled into the plugin, and only then extract uv -- with
no shell or script interpreter in between.
"""

import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src", "PythonToolchainBootstrapper.cpp")


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


class ToolchainBootstrapPinningTest(unittest.TestCase):
    def setUp(self):
        with open(SRC, encoding="utf-8") as f:
            self.src = f.read()
        self.code = "\n".join(l for l in self.src.splitlines()
                              if not l.lstrip().startswith("//"))

    def test_no_shell_piped_installer(self):
        for banned in ("install.ps1", "install.sh", "iex", "| sh",
                       "powershell", "/bin/sh", "astral.sh"):
            self.assertNotIn(banned, self.code, banned)

    def test_version_pinned(self):
        m = re.search(r'kUvVersion\s*=\s*"(\d+\.\d+\.\d+)"', self.code)
        self.assertIsNotNone(m, "kUvVersion must be an exact x.y.z version")
        self.assertIn("releases/download/%1/%2", self.code)

    def test_every_asset_has_sha256(self):
        assets = re.findall(
            r'const UvAsset kUvAsset = \{\s*"([^"]+)",\s*"([^"]+)",\s*"([^"]+)",\s*\};',
            self.code)
        names = {a[0] for a in assets}
        self.assertEqual(names, {"uv-x86_64-pc-windows-msvc.zip",
                                 "uv-aarch64-apple-darwin.tar.gz",
                                 "uv-x86_64-apple-darwin.tar.gz"})
        for name, digest, _ in assets:
            self.assertRegex(digest, r"^[0-9a-f]{64}$", name)
        self.assertEqual(len({a[1] for a in assets}), len(assets),
                         "each asset needs its own digest")

    def test_curl_run_by_absolute_path(self):
        body = function_body(self.code, "QString curlPath()")
        self.assertIn("System32/curl.exe", body)
        self.assertIn('"/usr/bin/curl"', body)
        install = function_body(self.code, "void PythonToolchainBootstrapper::installUv()")
        self.assertIn("m_process->start(curl, arguments);", install)
        self.assertIn('"=https"', install)

    def test_checksum_gates_extraction(self):
        body = function_body(
            self.code, "void PythonToolchainBootstrapper::onDownloadUvFinished(")
        hash_at = body.index("FileSha256::hexDigest(")
        compare_at = body.index("actual != QByteArray(kUvAsset.sha256)")
        extract_at = body.index("extractUv();")
        self.assertLess(hash_at, compare_at)
        self.assertLess(compare_at, extract_at)
        mismatch = body[compare_at:extract_at]
        self.assertIn("cleanUpUvDownload();", mismatch)
        self.assertIn("return;", mismatch)
        # extractUv() is reached from nowhere else.
        self.assertEqual(self.code.count("extractUv();"), 1)


if __name__ == "__main__":
    unittest.main()
