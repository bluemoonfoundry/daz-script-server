"""Pluggable asset finders: Daz Studio's content database, or the content browser."""

from __future__ import annotations

import json
import os
import http.client
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from ._content_types import file_type_matches
from ._recipe_issue import RecipeIssue
from ._script_builder import ScriptBuilder
from .exceptions import DazError

if TYPE_CHECKING:
    from .client import DazClient


# How long a search may take to fill its result container (ms).  On DS4 the
# broadest query is stable after ~1.6 s; an empty result is taken as final once
# nothing has arrived for _SEARCH_EMPTY_MS.
_SEARCH_BOUND_MS = 5000
_SEARCH_EMPTY_MS = 3000
_SEARCH_STABLE_MS = 750
# Studio returns at most this many search results.
_STUDIO_SEARCH_CAP = 1200
# product_files lists at most this many files of one product.
_PRODUCT_FILES_CAP = 1000


def _studio_script(op: str, phrase: str, type_: str | None, limit: int,
                   sku: str | None, product: str | None) -> str:
    """Read-only query of Studio's content database (DS4-confirmed; DS6 pending).

    Result shape (all the Python side relies on)::

        {"cms": bool, "timed_out": bool, "assets": [{"path","product","sku","type"}]}

    ``searchForAssets`` returns an empty container that fills asynchronously, so
    the script pumps ``processEvents()`` until the count is stable, bounded by
    ``_SEARCH_BOUND_MS`` (``timed_out`` is then true and the partial result is
    returned; resolution reports it as ``search_incomplete``).  Studio caps a
    search at 1200 results.  Products are looked up synchronously: SKU via
    ``findProductByStoreToken("DAZ 3D", sku)``, so only SKUs of the "DAZ 3D" store
    resolve; name via ``findProductsByName`` (exact title).  ``product_files``
    lists at most 1000 files of a product (``_PRODUCT_FILES_CAP``), silently
    truncated beyond that.  ``path`` is the content path
    (``"/" + getRelativeFilePath()``); Studio exposes no asset id.  Never opens a
    file or pops a dialog.
    """
    args = ScriptBuilder.to_js({"op": op, "phrase": phrase, "type": type_, "limit": limit,
                                "sku": sku, "product": product})
    return ScriptBuilder.iife(f"""// asset_finder:{op}
var _a = {args};
var _mgr = App.getAssetMgr();
if (!_mgr || !_mgr.isConnectedToCMS()) return {{ cms: false, timed_out: false, assets: [] }};
var _out = [], _timedOut = false;
function _add(_x) {{
    _out.push({{ path: "/" + String(_x.getRelativeFilePath()),
                 product: String(_x.productName || ""), sku: String(_x.productID || ""),
                 type: String(_x.contentType || "") }});
}}
function _collect(_c) {{
    if (!_c) return;
    var _n = _c.getNumAssets();
    for (var _i = 0; _i < _n && _out.length < _a.limit; _i++) _add(_c.getAsset(_i));
}}
function _pump(_r) {{
    // true when the bound was hit before the count settled
    var _t0 = new Date().getTime(), _last = -1, _since = _t0;
    while (true) {{
        processEvents();
        var _n = _r.getNumAssets(), _now = new Date().getTime();
        if (_n !== _last) {{ _last = _n; _since = _now; }}
        if (_n > 0 && _now - _since > {_SEARCH_STABLE_MS}) return false;
        if (_n === 0 && _now - _t0 > {_SEARCH_EMPTY_MS}) return false;
        if (_now - _t0 > {_SEARCH_BOUND_MS}) return true;
    }}
}}
if (_a.op === "search") {{
    var _r = _mgr.searchForAssets(_a.phrase, [], [], _a.type ? [_a.type] : [], 0);
    if (_r) {{ _timedOut = _pump(_r); _collect(_r); }}
}} else if (_a.sku) {{
    var _p = _mgr.findProductByStoreToken("DAZ 3D", _a.sku);
    if (_p && (!_a.product || String(_p.title) === _a.product)) _collect(_p);
}} else if (_a.product) {{
    var _ps = _mgr.findProductsByName(_a.product) || [];
    for (var _k = 0; _k < _ps.length; _k++)
        if (String(_ps[_k].title) === _a.product) _collect(_ps[_k]);
}}
return {{ cms: true, timed_out: _timedOut, assets: _out }};""")


@dataclass(frozen=True)
class AssetCandidate:
    path: str
    product: str | None
    sku: str | None
    asset_id: str | None
    type: str | None
    score: float = 0.0


class FinderUnavailable(DazError):
    """The finder cannot answer (content database off, browser down)."""


class AssetFinder(Protocol):
    @property
    def name(self) -> str: ...

    def search(self, phrase: str, *, type: str | None, limit: int = 10) -> list[AssetCandidate]: ...

    def product_files(self, *, sku: str | None = None,
                      product: str | None = None) -> list[AssetCandidate]: ...


def _opt(value: Any) -> str | None:
    return str(value) if value not in (None, "") else None


class StudioFinder:
    name = "studio"

    def __init__(self, client: DazClient) -> None:
        self._client = client
        # True when the last query hit the search time bound (partial result).
        self.timed_out = False
        # True when the last search was cut at a cap (Studio's 1200, or *limit*):
        # more matches may exist than were returned (final review I2).
        self.truncated = False

    def _run(self, script: str) -> list[AssetCandidate]:
        value = self._client.execute(script, timeout=30).value
        if not isinstance(value, dict):
            raise FinderUnavailable("content_database_unavailable: Studio returned no result")
        if not value.get("cms"):
            raise FinderUnavailable("content_database_unavailable")
        self.timed_out = bool(value.get("timed_out"))  # read by resolution: search_incomplete
        return [AssetCandidate(path=str(a.get("path", "")), product=_opt(a.get("product")),
                               sku=_opt(a.get("sku")), asset_id=_opt(a.get("asset_id")),
                               type=_opt(a.get("type")))
                for a in value.get("assets") or [] if isinstance(a, dict)]

    def search(self, phrase: str, *, type: str | None, limit: int = 10) -> list[AssetCandidate]:
        # The type filter runs here (friendly names and prefixes), not in the script.
        cap = _STUDIO_SEARCH_CAP if type else limit
        found = self._run(_studio_script("search", phrase, None, cap, None, None))
        truncated = len(found) >= cap
        if type:
            found = [c for c in found if file_type_matches(type, c.type)]
        self.truncated = truncated or len(found) > limit
        return found[:limit]

    def product_files(self, *, sku: str | None = None,
                      product: str | None = None) -> list[AssetCandidate]:
        """Files of the product with *sku* (store "DAZ 3D" only) or the exact title
        *product*; at most ``_PRODUCT_FILES_CAP`` (1000)."""
        return self._run(_studio_script("product_files", "", None, _PRODUCT_FILES_CAP, sku, product))


class ContentBrowserFinder:
    name = "content_browser"

    def __init__(self, url: str, token: str | None = None, timeout: float = 10.0) -> None:
        self._url = url.rstrip("/")
        self._token = token
        self._timeout = timeout
        # True when the last search was cut at its limit (final review I2).
        self.truncated = False

    def _request(self, path: str, body: dict | None = None) -> Any:
        headers = {"Accept": "application/json"}
        data = None
        if body is not None:
            data = ScriptBuilder.to_js(body).encode()
            headers["Content-Type"] = "application/json"
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        req = urllib.request.Request(self._url + path, data=data, headers=headers,
                                     method="POST" if body is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException) as e:
            raise FinderUnavailable(f"content browser at {self._url} unavailable: {e}") from e
        if not isinstance(data, dict):
            raise FinderUnavailable(f"content browser at {self._url} returned unexpected JSON")
        return data

    def product_files(self, *, sku: str | None = None,
                      product: str | None = None) -> list[AssetCandidate]:
        name = None
        if not sku:
            if not product:
                return []
            page = self._request("/api/v1/products?" + urllib.parse.urlencode(
                {"name_query": product, "page_size": 25}))
            hits = [p for p in page.get("products") or [] if p.get("name") == product]
            if not hits:
                return []
            sku, name = hits[0].get("sku"), hits[0].get("name")
            if not sku:
                return []
        data = self._request(f"/api/v1/products/{urllib.parse.quote(str(sku), safe='')}/assets")
        return [self._file(f, str(sku), name or product) for f in data.get("files") or []]

    @staticmethod
    def _file(f: dict, sku: str, product: str | None, score: float = 0.0) -> AssetCandidate:
        path = f.get("resolved_path") or (str(f.get("path", "")).rstrip("/") + "/" + str(f.get("filename", "")))
        return AssetCandidate(path=path, product=product, sku=sku, asset_id=None,
                              type=_opt(f.get("content_type")), score=score)

    def search(self, phrase: str, *, type: str | None, limit: int = 10) -> list[AssetCandidate]:
        asked = min(limit * 3, 100) if type else limit
        data = self._request("/api/v1/query", {"prompt": phrase, "limit": asked})
        out: list[AssetCandidate] = []
        hits = data.get("results") or []
        for hit in hits:
            meta = hit.get("metadata") or {}
            sku = meta.get("sku") or hit.get("id")
            if not sku:
                continue
            try:
                files = self._request(
                    f"/api/v1/products/{urllib.parse.quote(str(sku), safe='')}/assets")
            except FinderUnavailable:
                continue  # one bad product must not discard the other hits
            for f in files.get("files") or []:
                if type and not file_type_matches(type, f.get("content_type")):
                    continue
                out.append(self._file(f, str(sku), meta.get("name"),
                                      float(hit.get("relevance_score") or 0.0)))
        self.truncated = len(hits) >= asked or len(out) > limit
        return out[:limit]


def select_finder(client: DazClient, finder: AssetFinder | None = None,
                  env: Mapping[str, str] = os.environ) -> tuple[AssetFinder, list[RecipeIssue]]:
    if finder is not None:
        return finder, []
    url = env.get("DAZ_BROWSER_URL")
    if not url:
        return StudioFinder(client), []
    token = env.get("DAZ_BROWSER_TOKEN") or None
    try:
        ContentBrowserFinder(url, token, timeout=2.0)._request("/api/v1/filters")
    except FinderUnavailable as e:
        return StudioFinder(client), [RecipeIssue(
            "", "finder_fallback",
            f"content browser at {url} is not reachable ({e}); using Studio's content database")]
    return ContentBrowserFinder(url, token), []
