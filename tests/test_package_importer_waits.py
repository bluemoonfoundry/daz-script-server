"""
Static check on the local QEventLoop waits in src/DzPackageImporter.cpp.

No running server needed (runs in `python tests.py unit` / CI); the importer
links dzcore, so its source is checked instead, as in
test_package_importer_order.py.

Guard (daz-script-server-yau7.4.2): QEventLoop::exec() clears the loop's exit
flag when it starts, so a quit() delivered before exec() is lost and exec()
blocks forever. PackageDependencyInstaller::run() emits finished() inside the
call when the package is already resolved (re-import), and
PythonToolchainBootstrapper::ensureReady() emits stepFailed() inside the call
when the base dir can't be created. Every loop.exec() must therefore be
skipped when the waiter has already seen its signal.
"""

import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMPORTER_CPP = os.path.join(ROOT, "src", "DzPackageImporter.cpp")

# `if (!waiter.<flag>) {\n\t\tloop.exec();` or the one-line form.
GUARDED_EXEC_RE = re.compile(r"if\s*\(\s*!\s*waiter\.(\w+)\s*\)\s*\{?\s*loop\.exec\(\)\s*;")


class PackageImporterWaitTest(unittest.TestCase):
    def setUp(self):
        with open(IMPORTER_CPP, encoding="utf-8") as f:
            self.src = f.read()

    def test_every_loop_exec_is_guarded(self):
        code = "\n".join(l for l in self.src.splitlines()
                         if not l.lstrip().startswith("//"))
        total = code.count("loop.exec()")
        guarded = GUARDED_EXEC_RE.findall(self.src)
        self.assertGreaterEqual(total, 3)
        self.assertEqual(len(guarded), total,
            "every loop.exec() must be skipped when the waiter already fired "
            "(a quit() before exec() is lost)")

    def test_waiters_record_completion(self):
        for waiter, flag in (("ToolchainWaiter", "done"),
                             ("DependencyWaiter", "done"),
                             ("ProcessWaiter", "finished")):
            start = self.src.index("class %s " % waiter)
            body = self.src[start:self.src.index("};", start)]
            self.assertIn("bool %s = false;" % flag, body, waiter)
            self.assertIn("%s = true;" % flag, body, waiter)

    def test_toolchain_failure_marks_done(self):
        start = self.src.index("class ToolchainWaiter ")
        body = self.src[start:self.src.index("};", start)]
        failed = body[body.index("void onStepFailed"):]
        self.assertIn("done = true;", failed[:failed.index("}") + 1])


if __name__ == "__main__":
    unittest.main()
