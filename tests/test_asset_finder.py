import json
import socket
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace

from dazpy._asset_finder import (AssetCandidate, ContentBrowserFinder, FinderUnavailable,
                                 StudioFinder, select_finder)

AUTH = []


class _H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, obj):
        AUTH.append(self.headers.get("Authorization"))
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/api/v1/products/123/assets"):
            self._send({"sku": "123", "files": [
                {"path": "/People/G9/Hair", "filename": "x.duf", "content_type": "Follower/Hair"},
                {"path": "/a", "filename": "b.duf", "resolved_path": "C:/lib/a/b.duf"}]})
        elif self.path.startswith("/api/v1/products?"):
            self._send({"products": [{"sku": "123", "name": "Ponytail"}], "total": 1})
        elif self.path == "/api/v1/filters":
            self._send({"categories": [], "artists": [], "compatible_figures": []})
        else:
            self.send_error(404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        req = json.loads(self.rfile.read(n))
        assert req == {"prompt": "ponytail", "limit": 5}, req
        self._send({"total_hits": 1, "limit": 5, "offset": 0, "results": [
            {"id": "123", "distance": 0.1, "relevance_score": 0.9,
             "metadata": {"sku": "123", "name": "Ponytail"}}]})


def _server():
    srv = HTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def _stop(srv):
    srv.shutdown()
    srv.server_close()


def _dead_url():
    with socket.socket() as sk:
        sk.bind(("127.0.0.1", 0))
        return f"http://127.0.0.1:{sk.getsockname()[1]}"


def _client(value):
    scripts = []

    def execute(script, *a, **kw):
        scripts.append(script)
        return SimpleNamespace(value=value)
    return SimpleNamespace(execute=execute, scripts=scripts)


class StudioFinderTests(unittest.TestCase):
    def test_studio_search_parses_script_result(self):
        c = _client({"cms": True, "assets": [{
            "path": "/People/G9/Hair/x.duf", "product": "Flirty Casual Ponytail",
            "sku": "123", "type": "Follower/Hair"}]})
        out = StudioFinder(c).search("ponytail", type="Follower/Hair")
        self.assertEqual(out, [AssetCandidate("/People/G9/Hair/x.duf", "Flirty Casual Ponytail",
                                              "123", None, "Follower/Hair")])
        self.assertIn("searchForAssets", c.scripts[0])

    def test_studio_cms_off_raises(self):
        with self.assertRaises(FinderUnavailable) as cm:
            StudioFinder(_client({"cms": False})).search("x", type=None)
        self.assertIn("content_database_unavailable", str(cm.exception))


class ContentBrowserTests(unittest.TestCase):
    def setUp(self):
        self.srv, self.url = _server()
        self.addCleanup(_stop, self.srv)
        AUTH.clear()

    def test_content_browser_search(self):
        out = ContentBrowserFinder(self.url, "t").search("ponytail", type="Follower/Hair", limit=5)
        self.assertEqual(len(out), 1)
        self.assertEqual((out[0].path, out[0].sku, out[0].product, out[0].score),
                         ("/People/G9/Hair/x.duf", "123", "Ponytail", 0.9))
        self.assertEqual(set(AUTH), {"Bearer t"})

    def test_content_browser_product_files(self):
        f = ContentBrowserFinder(self.url, "t")
        out = f.product_files(sku="123")
        self.assertEqual([c.path for c in out], ["/People/G9/Hair/x.duf", "C:/lib/a/b.duf"])
        self.assertEqual([c.path for c in f.product_files(product="Ponytail")],
                         [c.path for c in out])

    def test_unreachable_raises(self):
        with self.assertRaises(FinderUnavailable):
            ContentBrowserFinder(_dead_url()).product_files(sku="123")


class SelectTests(unittest.TestCase):
    def test_select_explicit_wins(self):
        f = object()
        self.assertEqual(select_finder(_client(None), f, {"DAZ_BROWSER_URL": "http://127.0.0.1:1"}), (f, []))

    def test_select_env_down_falls_back(self):
        f, issues = select_finder(_client(None), None, {"DAZ_BROWSER_URL": _dead_url()})
        self.assertIsInstance(f, StudioFinder)
        self.assertEqual([i.code for i in issues], ["finder_fallback"])

    def test_select_env_up(self):
        srv, url = _server()
        self.addCleanup(_stop, srv)
        f, issues = select_finder(_client(None), None, {"DAZ_BROWSER_URL": url})
        self.assertIsInstance(f, ContentBrowserFinder)
        self.assertEqual(issues, [])

    def test_select_no_env(self):
        f, issues = select_finder(_client(None), None, {})
        self.assertIsInstance(f, StudioFinder)
        self.assertEqual(issues, [])


if __name__ == "__main__":
    unittest.main()
