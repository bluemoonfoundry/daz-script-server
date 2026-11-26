"""Pluggable asset finders: Daz Studio's content database, or the content browser."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from ._recipe_issue import RecipeIssue
from ._script_builder import ScriptBuilder
from .exceptions import DazError

if TYPE_CHECKING:
    from .client import DazClient


def _studio_script(op: str, phrase: str, type_: str | None, limit: int,
                   sku: str | None, product: str | None) -> str:
    # Provisional until the Task 1 live probe confirms these calls.
    # Result shape (all the Python side relies on):
    #   {"cms": bool, "assets": [{"path","product","sku","asset_id","type"}]}
    # Never opens a file or pops a dialog: read-only database queries.
    args = ScriptBuilder.to_js({"op": op, "phrase": phrase, "type": type_, "limit": limit,
                                "sku": sku, "product": product})
    return ScriptBuilder.iife(f"""// asset_finder:{op}
var _a = {args};
var _mgr = App.getAssetMgr();
if (!_mgr || !_mgr.isConnectedToCMS()) return {{ cms: false, assets: [] }};
var _out = [];
function _add(_x) {{
    _out.push({{ path: String(_x.getAsFilePath ? _x.getAsFilePath() : (_x.originalPath + "/" + _x.originalFilename)),
                 product: String(_x.productName || ""), sku: String(_x.productID || ""),
                 asset_id: String(_x.assetID()), type: String(_x.contentType || "") }});
}}
function _collect(_c) {{
    if (!_c) return;
    var _n = _c.getNumAssets();
    for (var _i = 0; _i < _n && _out.length < _a.limit; _i++) _add(_c.getAsset(_i));
}}
var _types = _a.type ? [_a.type] : [];
if (_a.op === "search") {{
    _collect(_mgr.searchForAssets(_a.phrase, [], [], _types, 0));
}} else {{
    var _prods = _mgr.searchForProducts(_a.product || _a.sku || "", [], [], [], 0);
    var _kids = _prods ? _prods.getChildContainers() : [];
    for (var _k = 0; _k < _kids.length; _k++) {{
        var _name = String(_kids[_k].getContainerName());
        if (_a.product && _name !== _a.product) continue;
        _collect(_kids[_k]);
    }}
}}
return {{ cms: true, assets: _out }};""")


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
    name: str

    def search(self, phrase: str, *, type: str | None, limit: int = 10) -> list[AssetCandidate]: ...

    def product_files(self, *, sku: str | None = None,
                      product: str | None = None) -> list[AssetCandidate]: ...


def _opt(value: Any) -> str | None:
    return str(value) if value not in (None, "") else None


class StudioFinder:
    name = "studio"

    def __init__(self, client: "DazClient") -> None:
        self._client = client

    def _run(self, script: str) -> list[AssetCandidate]:
        value = self._client.execute(script, timeout=30).value
        if not isinstance(value, dict):
            raise FinderUnavailable("content_database_unavailable: Studio returned no result")
        if not value.get("cms"):
            raise FinderUnavailable("content_database_unavailable")
        return [AssetCandidate(path=str(a.get("path", "")), product=_opt(a.get("product")),
                               sku=_opt(a.get("sku")), asset_id=_opt(a.get("asset_id")),
                               type=_opt(a.get("type")))
                for a in value.get("assets") or [] if isinstance(a, dict)]

    def search(self, phrase: str, *, type: str | None, limit: int = 10) -> list[AssetCandidate]:
        return self._run(_studio_script("search", phrase, type, limit, None, None))

    def product_files(self, *, sku: str | None = None,
                      product: str | None = None) -> list[AssetCandidate]:
        return self._run(_studio_script("product_files", "", None, 1000, sku, product))


class ContentBrowserFinder:
    name = "content_browser"

    def __init__(self, url: str, token: str | None = None, timeout: float = 10.0) -> None:
        self._url = url.rstrip("/")
        self._token = token
        self._timeout = timeout

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
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise FinderUnavailable(f"content browser at {self._url} unavailable: {e}") from e

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
        data = self._request("/api/v1/query", {"prompt": phrase, "limit": limit})
        out: list[AssetCandidate] = []
        for hit in data.get("results") or []:
            meta = hit.get("metadata") or {}
            sku = meta.get("sku") or hit.get("id")
            if not sku:
                continue
            files = self._request(f"/api/v1/products/{urllib.parse.quote(str(sku), safe='')}/assets")
            for f in files.get("files") or []:
                if type and f.get("content_type") != type:
                    continue
                out.append(self._file(f, str(sku), meta.get("name"),
                                      float(hit.get("relevance_score") or 0.0)))
        return out[:limit]


def select_finder(client: "DazClient", finder: AssetFinder | None = None,
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
