# dazpy

Python SDK for [DazScriptServer](https://github.com/bluemoonfoundry/daz-script-server),
a DAZ Studio plugin that runs DazScript sent over HTTP.

dazpy wraps the plugin's HTTP API in typed Python objects: scenes, nodes,
bones, morphs, materials, cameras, lights, renders, and declarative scene
recipes. It needs the plugin installed and running inside DAZ Studio.

## Install

```bash
pip install dazpy            # sync client (requests)
pip install "dazpy[aio]"     # adds the asyncio client (httpx)
```

Requires Python 3.10+.

## Quick start

In DAZ Studio, open **Window → Panes → Daz Script Server** and click
**Start Server** (default `127.0.0.1:18811`). Then:

```python
from dazpy import DazClient, DazScene

client = DazClient()   # loads the token from ~/.daz3d/dazscriptserver_token.txt
scene = DazScene(client)

print(scene.num_nodes(), "nodes in scene")
figure = scene.find_skeleton_by_label("Genesis 9")
figure.find_bone("neck1").set_local_rotation(0, 15, 0)
```

## Scene recipes

`dazpy.recipe` validates, plans, applies and observes declarative scene
recipes (JSON). With `"recipe_version": 2` a recipe can name content by path,
product, SKU or search phrase, check every preset and fitted item against its
figure before anything loads, take over a figure built by hand, and add,
replace or remove its hair and clothing by label or content type:

```python
from dazpy.recipe import apply, pin, validate

recipe = {"recipe_version": 2, "id": "vn-a", "actors": {"abby": {
    "node": "Abby",
    "wearing": [{"replace": {"type": "hair"}, "key": "hair",
                 "with": {"find": "Bunched Hair Updo", "type": "hair"}}]}}}
print(validate(recipe, scene).errors)   # e.g. ambiguous_asset with the candidates
```

Studio's content search matches broadly, so a `find` often lists several
candidates. Pick one and pin it (`pin(recipe, scene)` or a `resolved` path).
See the scene recipes guide in the API reference for every error and warning
code.

## Documentation

- API reference: https://bluemoonfoundry.github.io/daz-script-server/
- Plugin, HTTP API, and security setup:
  https://github.com/bluemoonfoundry/daz-script-server#readme

## License

dazpy is MIT licensed (see `LICENSE`). The DazScriptServer plugin it talks
to is licensed separately under AGPL v3; dazpy communicates with it only
over HTTP and does not include plugin code.
