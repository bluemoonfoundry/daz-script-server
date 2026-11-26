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


class PackageTimeoutTest(unittest.TestCase):
    """Guard (daz-script-server-yau7.4.3): the wait on the package process is
    bounded by a single-shot QTimer, and a timeout kills the process."""

    def setUp(self):
        with open(IMPORTER_CPP, encoding="utf-8") as f:
            self.src = f.read()
        start = self.src.index("QVariantMap DzPackageImporter::runPackage(")
        self.body = self.src[start:self.src.index("\n}\n", start)]

    def test_timer_bounds_the_process_wait(self):
        body = self.body
        self.assertIn("setSingleShot(true)", body)
        self.assertRegex(body, r"SIGNAL\(timeout\(\)\),\s*&loop,\s*SLOT\(quit\(\)\)")
        self.assertRegex(body, r"SIGNAL\(timeout\(\)\),\s*&waiter,\s*SLOT\(onTimeout\(\)\)")
        start = body.index("timeout.start(timeoutSeconds * 1000)")
        self.assertLess(start, body.index("loop.exec()"),
                        "the timer must be running before the loop blocks")

    def test_timeout_kills_the_process(self):
        branch = self.body[self.body.index("if (waiter.timedOut"):]
        branch = branch[:branch.index("return QVariantMap();")]
        self.assertIn("process.kill();", branch)

    def test_timeout_is_read_from_the_manifest(self):
        start = self.src.index("bool readManifest(")
        manifest_fn = self.src[start:self.src.index("\n}\n", start)]
        self.assertIn('readTimeoutSeconds(manifest.value("timeoutSeconds")', manifest_fn,
                      "timeoutSeconds must be validated before commit()")
        self.assertIn("timeoutSeconds,", self.src[self.src.index("runPackage(venvPython"):])

    def test_waiter_records_timeout(self):
        start = self.src.index("class ProcessWaiter ")
        body = self.src[start:self.src.index("};", start)]
        self.assertIn("bool timedOut = false;", body)
        self.assertIn("void onTimeout() { timedOut = true; }", body)


if __name__ == "__main__":
    unittest.main()
