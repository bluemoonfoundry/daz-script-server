"""
Static checks on the install order in DzPackageImporter::read()
(src/DzPackageImporter.cpp).

No running server needed (runs in `python tests.py unit` / CI). read() drives
modal dialogs and links dzcore, so it can't run outside DAZ Studio; these tests
check its source instead, the same way test_route_security.py checks the route
table.

Guards:
  * daz-script-server-yau7.4.1: ZipInstaller::commit() replaces any existing
    install of the package id, so the inputs dialog (collectInputs) must run
    before it. Cancel must then only discard the staging dir.
  * every early return between extractToStaging() and commit() removes the
    staging dir (ZipInstaller.h: caller must commit() or remove it).
"""

import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMPORTER_CPP = os.path.join(ROOT, "src", "DzPackageImporter.cpp")

READ_SIGNATURE = "DzError DzPackageImporter::read("
STAGE_CALL = "installer.extractToStaging("
COMMIT_CALL = "installer.commit("
INPUTS_CALL = "collectInputs("
CLEANUP_CALL = "PortableFs::removeRecursively(stage.stagingDir)"
RETURN_RE = re.compile(r"\breturn\s+(DZ_\w+)\s*;")


def read_body(src):
    """Source of DzPackageImporter::read(), from its signature to the closing
    brace at column 0."""
    start = src.index(READ_SIGNATURE)
    end = src.index("\n}\n", start)
    return src[start:end]


def pre_commit_returns(body):
    """(code, block_source) for each return between the staging step and the
    commit() call. block_source runs from the opening brace of the enclosing
    block to the return, so a cleanup call in that block is visible."""
    stage_at = body.index(STAGE_CALL)
    commit_at = body.index(COMMIT_CALL)
    # The first return after extractToStaging() is its own failure branch,
    # where no staging dir exists yet.
    first = RETURN_RE.search(body, stage_at)
    region_start = first.end() if first and first.start() < commit_at else stage_at
    for m in RETURN_RE.finditer(body, region_start, commit_at):
        block_open = body.rindex("{", region_start, m.start())
        yield m.group(1), body[block_open:m.start()]


class PackageImporterOrderTest(unittest.TestCase):
    def setUp(self):
        with open(IMPORTER_CPP, encoding="utf-8") as f:
            self.body = read_body(f.read())

    def test_inputs_dialog_runs_before_commit(self):
        inputs_at = self.body.find(INPUTS_CALL)
        commit_at = self.body.find(COMMIT_CALL)
        self.assertNotEqual(inputs_at, -1, "read() no longer calls collectInputs()")
        self.assertNotEqual(commit_at, -1, "read() no longer calls installer.commit()")
        self.assertLess(
            inputs_at, commit_at,
            "collectInputs() must run before installer.commit(): commit() "
            "overwrites the existing install, so a Cancel after it loses the "
            "old version (yau7.4.1)")

    def test_cancel_discards_staging_dir(self):
        returns = dict(pre_commit_returns(self.body))
        self.assertIn(
            "DZ_USER_CANCELLED_OPERATION", returns,
            "the inputs-dialog cancel must return before installer.commit()")
        self.assertIn(
            CLEANUP_CALL, returns["DZ_USER_CANCELLED_OPERATION"],
            "cancelling the inputs dialog must remove the staging dir")

    def test_every_pre_commit_return_removes_staging_dir(self):
        returns = list(pre_commit_returns(self.body))
        self.assertTrue(returns, "expected early returns between staging and commit")
        for code, block in returns:
            with self.subTest(code=code):
                self.assertIn(
                    CLEANUP_CALL, block,
                    "return %s between extractToStaging() and commit() leaks "
                    "the staging dir" % code)


if __name__ == "__main__":
    unittest.main()
