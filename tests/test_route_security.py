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

# Companion-plugin catch-alls dispatch to plugin slots. Tracked separately.
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
                self.assertRegex(
                    handler, r"m_p(Write|Read)Chain->run\(ctx\)",
                    "route must run m_pWriteChain or m_pReadChain")

    def test_every_post_and_delete_route_uses_write_chain(self):
        for method, path, handler in self.routes:
            if method not in ("POST", "DELETE", "PUT", "PATCH"):
                continue
            with self.subTest(route=f"{method} {path}"):
                self.assertIn("m_pWriteChain->run(ctx)", handler)
                self.assertNotIn("m_pReadChain->run(ctx)", handler)

    def test_save_copy_and_register_use_write_chain(self):
        found = {(m, p): h for m, p, h in self.routes}
        for key in (("POST", "/scene/save-copy"), ("POST", "/scripts/register")):
            with self.subTest(route=key):
                self.assertIn(key, found)
                self.assertIn("m_pWriteChain->run(ctx)", found[key])

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
