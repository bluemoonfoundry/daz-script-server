"""
Static checks on the route table in src/DzScriptServerPane.cpp.

No running server needed (runs in `python tests.py unit` / CI). It guards
against two regressions from ASSESSMENT.md:

  * a POST route without a request-body size limit (daz-script-server-5d6f.1)
  * an authenticated route that skips the IP whitelist / rate limiter
    (daz-script-server-5d6f.2)

A live check that a non-whitelisted client gets 403 needs the whitelist turned
on in the DAZ Studio pane, which can't be automated. The middleware itself is
covered at runtime; this test proves that every route goes through it.
"""

import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PANE_CPP = os.path.join(ROOT, "src", "DzScriptServerPane.cpp")

# Routes that are public on purpose (no auth, no whitelist).
PUBLIC_ROUTES = {("GET", "/status"), ("GET", "/health"), ("GET", "/metrics")}

# Companion-plugin catch-alls (applyPluginRoutes) are checked separately below.
CATCH_ALL = "/(.*)"

ROUTE_RE = re.compile(r'm_pServer->(Get|Post|Put|Delete|Patch)\s*\(\s*"([^"]+)"')


def _read_source():
    with open(PANE_CPP, encoding="utf-8") as f:
        return f.read()


def _setup_routes_body(src):
    start = src.index("void DzScriptServerPane::setupRoutes()")
    end = src.index("void DzScriptServerPane::applyPluginRoutes()", start)
    # applyPluginRoutes() is defined after setupRoutes(); only the catch-alls live there.
    return src[start:end]


def _routes(body):
    """Yield (method, path, handler_source) for each route in setupRoutes()."""
    matches = list(ROUTE_RE.finditer(body))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        yield m.group(1).upper(), m.group(2), body[m.end():end]


# Job routes delegate to runJobRoute(), which runs the write chain itself
# (test_run_job_route_runs_write_chain_first checks that).
JOB_ROUTE_RE = re.compile(r"runJobRoute\(req, res, \w+\.get\(\), (true|false)\)")


def _runs_write_chain(handler):
    return "m_pWriteChain->run(ctx)" in handler or bool(JOB_ROUTE_RE.search(handler))


def _chain_middleware(body, chain):
    pattern = re.compile(re.escape(chain) + r"->add\(new (\w+)\(")
    return pattern.findall(body)


class TestRouteSecurity(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.src = _read_source()
        cls.body = _setup_routes_body(cls.src)
        cls.routes = list(_routes(cls.body))

    def test_routes_were_found(self):
        self.assertGreater(len(self.routes), 15)

    def test_write_chain_composition(self):
        self.assertEqual(
            _chain_middleware(self.body, "m_pWriteChain"),
            ["IPWhitelistMiddleware", "RateLimitMiddleware",
             "BodySizeMiddleware", "AuthMiddleware"],
        )

    def test_read_chain_composition(self):
        self.assertEqual(
            _chain_middleware(self.body, "m_pReadChain"),
            ["IPWhitelistMiddleware", "AuthMiddleware"],
        )

    def test_no_auth_only_chain(self):
        self.assertNotIn("m_pAuthChain", self.src)

    def test_every_authenticated_route_runs_whitelist(self):
        for method, path, handler in self.routes:
            if (method, path) in PUBLIC_ROUTES:
                continue
            with self.subTest(route=f"{method} {path}"):
                self.assertTrue(
                    _runs_write_chain(handler) or "m_pReadChain->run(ctx)" in handler,
                    "route must run m_pWriteChain or m_pReadChain")

    def test_every_post_and_delete_route_uses_write_chain(self):
        for method, path, handler in self.routes:
            if method not in ("POST", "DELETE", "PUT", "PATCH"):
                continue
            with self.subTest(route=f"{method} {path}"):
                self.assertTrue(_runs_write_chain(handler), "route must run m_pWriteChain")
                self.assertNotIn("m_pReadChain->run(ctx)", handler)

    def test_run_job_route_runs_write_chain_first(self):
        start = self.src.index("void DzScriptServerPane::runJobRoute(")
        end = self.src.index("void DzScriptServerPane::setupRoutes()", start)
        body = self.src[start:end]
        chain = body.index("m_pWriteChain->run(ctx)")
        self.assertNotIn("m_pReadChain", body)
        # Nothing request-specific (headers, idempotency replay, handler) may
        # happen before the chain has authenticated the caller.
        for later in ("x-correlation-id", "m_idempotency.begin(", "handler->handle(ctx)"):
            with self.subTest(step=later):
                self.assertLess(chain, body.index(later))

    def test_job_submission_routes_are_idempotent(self):
        found = {(m, p): h for m, p, h in self.routes}
        for key in (("POST", "/execute/async"), ("POST", "/scripts/([^/]+)/async"),
                    ("POST", "/render"), ("POST", "/render/batch"),
                    ("POST", "/render/animation")):
            with self.subTest(route=key):
                m = JOB_ROUTE_RE.search(found[key])
                self.assertIsNotNone(m)
                self.assertEqual(m.group(1), "true")

    def test_save_copy_and_register_use_write_chain(self):
        found = {(m, p): h for m, p, h in self.routes}
        for key in (("POST", "/scene/save-copy"), ("POST", "/scripts/register")):
            with self.subTest(route=key):
                self.assertIn(key, found)
                self.assertIn("m_pWriteChain->run(ctx)", found[key])

    def test_plugin_catch_all_runs_chains(self):
        start = self.src.index("void DzScriptServerPane::applyPluginRoutes()")
        end = self.src.index('m_pServer->Get   ("/(.*)"', start)
        dispatch = self.src[start:end]
        self.assertRegex(
            dispatch,
            r'\(method == "GET"\)\s*\?\s*\*m_pReadChain\s*:\s*\*m_pWriteChain')
        # The chain must run after route matching (unknown paths stay 404)
        # and before the plugin slot is invoked.
        not_found = dispatch.index("ErrorCode::ROUTE_NOT_FOUND")
        chain_run = dispatch.index("chain.run(ctx)")
        invoke = dispatch.index("QMetaObject::invokeMethod(receiver.data()")
        self.assertLess(not_found, chain_run)
        self.assertLess(chain_run, invoke)

    def test_capabilities_route_table_matches_setup_routes(self):
        """GET /capabilities reports kCapabilityRoutes; it must list exactly the
        routes setupRoutes() registers, with auth matching PUBLIC_ROUTES."""
        start = self.src.index("const CapabilityRoute kCapabilityRoutes[]")
        end = self.src.index("};", start)
        entries = re.findall(
            r'\{\s*"(\w+)",\s*"([^"]+)",\s*(true|false),\s*"(\w+)"\s*\}',
            self.src[start:end])
        # The table may name placeholders ({id}, {artifact_id}); compare each
        # ([^/]+) capture against any {name}.
        table = {(m, re.sub(r"\{\w+\}", "{id}", p)): auth == "true"
                 for m, p, auth, _ in entries}
        self.assertEqual(len(table), len(entries), "duplicate capability route")

        registered = {(m, p.replace("([^/]+)", "{id}")) for m, p, _ in self.routes}
        self.assertEqual(set(table), registered)
        for key, auth in table.items():
            with self.subTest(route=key):
                self.assertEqual(auth, key not in PUBLIC_ROUTES)

    def test_artifact_routes_use_read_chain_and_validate_ids(self):
        """Artifact downloads are authenticated reads whose URL segments are
        IDs looked up in the job's manifest, never filesystem paths."""
        found = {(m, p): h for m, p, h in self.routes}
        for path in ("/artifacts/([^/]+)", "/artifacts/([^/]+)/([^/]+)"):
            with self.subTest(route=path):
                self.assertIn("m_pReadChain->run(ctx)", found[("GET", path)])
        def body(signature):
            fn = self.src[self.src.index(signature):]
            return fn[:fn.index("\n}\n")]

        # Shared lookup: IDs validated, then the manifest, then the file.
        opener = body("static bool openDeclaredArtifact(")
        self.assertLess(opener.index("artifactIdsValid(req, res)"), opener.index("findArtifact("))
        self.assertLess(opener.index("findArtifact("), opener.index("ArtifactFile::openForRead("))

        serve = body("static void serveArtifact(")
        self.assertIn("openDeclaredArtifact(", serve)
        self.assertNotIn("ArtifactFile::openForRead(", serve)
        # httplib only answers Range with 206 when the handler leaves status unset.
        self.assertNotIn("res.status", serve[serve.index("const QByteArray disposition"):])

        # ?thumbnail: same lookup, IDs checked before anything else, and the
        # worker never touches QtGui or blocks on the main thread unbounded.
        thumb = body("void DzScriptServerPane::serveArtifactThumbnail(")
        self.assertLess(thumb.index("artifactIdsValid(req, res)"), thumb.index("openDeclaredArtifact("))
        self.assertNotIn("ArtifactFile::openForRead(", thumb)
        self.assertNotIn("QImage", thumb)
        self.assertNotIn("BlockingQueuedConnection", thumb)
        self.assertIn("Qt::QueuedConnection", thumb)
        self.assertIn("tryAcquire(1, kMainThreadTimeoutMs)", thumb)
        route = found[("GET", "/artifacts/([^/]+)/([^/]+)")]
        self.assertLess(route.index("m_pReadChain->run(ctx)"), route.index("serveArtifactThumbnail("))

    def test_capabilities_route_uses_read_chain(self):
        found = {(m, p): h for m, p, h in self.routes}
        self.assertIn("m_pReadChain->run(ctx)", found[("GET", "/capabilities")])

    def test_httplib_payload_limit_set_from_config(self):
        self.assertRegex(
            self.src,
            r"set_payload_max_length\(\s*maxBodyBytes\s*\)",
        )
        self.assertRegex(
            self.src,
            r"maxBodyBytes\s*=\s*static_cast<size_t>\(m_nMaxBodySizeMB\)\s*\*\s*1024\s*\*\s*1024",
        )

    def test_httplib_413_gets_json_body(self):
        self.assertIn("set_error_handler", self.src)
        self.assertIn("ErrorCode::BODY_TOO_LARGE", self.src)


if __name__ == "__main__":
    unittest.main()
