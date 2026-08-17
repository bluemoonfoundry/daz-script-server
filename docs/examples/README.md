# Examples Have Moved

The example scripts that used to live in this directory now live in their
own repository:

**[bluemoonfoundry/daz-script-server-examples](https://github.com/bluemoonfoundry/daz-script-server-examples)**

That repo is kept up to date with the current `dazpy` API, is organized by
category (`fundamentals`, `character`, `animation`, `bvh`, `geometry`,
`rendering`, `export`, `ai_vision`, `ml_data`), and has a per-example
`README.md` plus a categorized index in its own root `README.md`.

```bash
git clone https://github.com/bluemoonfoundry/daz-script-server-examples.git
```

Two examples formerly under `docs/examples/rendering/` — `sprite_matrix` and
`comfyui_enhance` — remain in *this* repo, at
[`tests/fixtures/rendering/`](../../tests/fixtures/rendering/), because this
repo's own test suite imports them directly as unit-test fixtures. They are
not general-purpose examples; see the examples repo for the equivalent
documented, standalone versions.
