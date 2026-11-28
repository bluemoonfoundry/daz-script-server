"""S3 (yau7.9.3): Qt 4 / Qt 6 API differences live in include/QtCompat.h.

Source scan (no Qt needed): the APIs that differ between the two Qt versions
are only spelled out in QtCompat.h, and its whole-string regex keeps the
PCRE trailing-newline quirk out on Studio 6.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPAT = ROOT / "include" / "QtCompat.h"

# API spellings that differ between Qt 4.8 and Qt 6; use QtCompat instead.
DIVERGENT = {
    "QRegExp": "QtCompat::WholeMatch",
    "QRegularExpression": "QtCompat::WholeMatch",
    "QStandardPaths": "QtCompat::writableLocation",
    "QDesktopServices": "QtCompat::writableLocation",
    "Qt::SkipEmptyParts": "QtCompat::SkipEmptyParts",
    "QString::SkipEmptyParts": "QtCompat::SkipEmptyParts",
    "setCodec(": "QtCompat::setUtf8",
    "QUuid::WithoutBraces": "QtCompat::uuidWithoutBraces",
}


def _sources():
    for d in ("src", "include"):
        for p in sorted((ROOT / d).iterdir()):
            if p.suffix in (".cpp", ".h") and p.name not in ("httplib.h", "miniz.h", "miniz.c",
                                                            "QtCompat.h"):
                yield p


def _code(text):
    """Text with // and /* */ comments removed (string contents kept)."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


class TestQtCompat(unittest.TestCase):
    def test_divergent_apis_only_in_qtcompat(self):
        for path in _sources():
            code = _code(path.read_text(encoding="utf-8", errors="replace"))
            for api, instead in DIVERGENT.items():
                with self.subTest(file=path.name, api=api):
                    self.assertNotIn(api, code, f"{path.name}: use {instead} (include/QtCompat.h)")

    def test_whole_match_is_anchored_on_both_qts(self):
        src = COMPAT.read_text(encoding="utf-8")
        self.assertIn("QRegularExpression::anchoredPattern(pattern)", src)
        self.assertIn("rx.exactMatch(s)", src)
        # Qt 4 matches on a per-call QRegExp: a shared static one isn't thread-safe.
        self.assertRegex(src, r"QRegExp rx\(m_pattern\);")

    def test_validators_use_whole_match(self):
        for rel, needle in (("src/RequestValidator.cpp", "WholeMatch valid("),
                            ("src/ZipInstaller.cpp", "WholeMatch idPattern("),
                            ("src/PackageManifest.cpp", "WholeMatch pattern(")):
            with self.subTest(file=rel):
                self.assertIn(needle, (ROOT / rel).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
