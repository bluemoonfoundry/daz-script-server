# .dzpkg manifest.json schema (daz-script-server-5sw)

A `.dzpkg` is a zip with a `manifest.json` at its root plus a Python entry
point (and any other files the package needs). See `examples/hello_package/`
for a complete, working reference implementation (also packaged as
`examples/hello_package.dzpkg`).

```jsonc
{
  "schemaVersion": 1,             // required. Reject/upgrade unknown future versions rather than guess.
  "id": "my_package",             // required. [A-Za-z0-9_-]+ (same validation ZipInstaller already enforces).
  "version": "0.1.0",             // required.
  "displayName": "My Package",    // required. Shown in dialogs/messages; id is not.
  "description": "...",           // optional.
  "author": "...",                // optional.

  "entryPoint": "main.py",        // required. Relative path within the package; must define run(inputs: dict) -> Any.
  "interactive": true,            // required. false => run() is called immediately with inputs = {}, no dialog.

  "dependencies": ["numpy>=1.26"],// optional, defaults to []. uv pip install target list.
                                   // `dazpy` is ALWAYS implicit -- never declare it here.

  "inputs": [                     // required if interactive is true; ignored otherwise.
    {
      "name": "targetCount",      // required. Must be a valid Python identifier -- becomes a key in the inputs dict.
      "label": "Number of Targets", // required. Shown next to the widget.
      "type": "int",              // required. One of: int, float, string, bool, enum, file.
      "default": 5,               // required.
      "min": 1,                   // int/float only.
      "max": 100,                 // int/float only.
      "step": 1,                  // float only; spin box increment.
      "options": ["a", "b"],      // enum only; required for that type.
      "filter": "Images (*.png)"  // file only; passed to the native file picker.
    }
  ]
}
```

## Entry point contract

`entryPoint` must define:

```python
def run(inputs: dict):
    ...
    return some_json_serializable_value
```

`inputs` is a plain dict keyed by each declared input's `name` (or `{}` for
a non-interactive package). Whatever `run()` returns must be JSON-
serializable -- it becomes the result envelope's `"result"` field (see
`dsp_runner.py`'s module docstring for the exact envelope shape). A raised
exception is reported back as `{"success": false, "error": "..."}`, not a
crash.

Call back into the live DAZ Studio session that opened the package via
`dazpy` (`from dazpy import DazClient; DazClient()` -- no daemon involved,
just an HTTP call to this same plugin's existing port 18811).
