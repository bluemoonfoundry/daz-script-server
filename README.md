# Vangard DazScript Server

A DAZ Studio plugin that embeds an HTTP server inside DAZ Studio, enabling remote execution of DazScript via HTTP POST requests with JSON responses. This allows external tools and scripts to automate DAZ Studio operations programmatically.

## How It Works

Once the plugin is loaded and the server started, clients send HTTP requests containing a script path (or inline script code) and optional arguments. The plugin executes the script on DAZ Studio's main thread — where all scene and asset operations must run — and returns the result as JSON.

## Requirements

- **DAZ Studio 4.5+**
- **DAZ Studio 4.5+ SDK** (for building)
- **CMake 3.5+**
- **Windows**: Visual Studio 2019 or 2022 (MSVC)
- **macOS**: Xcode / clang with libc++

## Building

### 1. Obtain the DAZ Studio SDK

Download the DAZ Studio SDK from the [DAZ Developer portal](https://www.daz3d.com/daz-studio-4-5-sdk). Extract it somewhere accessible, e.g. `C:/DAZStudio4.5+ SDK`.

### 2. Configure

```bash
cmake -B build -S . -DDAZ_SDK_DIR="C:/path/to/DAZStudio4.5+ SDK"
```

### 3. Build

```bash
cmake --build build --config Release
```

Output: `build/lib/Release/DazScriptServer.dll` (Windows) or `build/lib/DazScriptServer.dylib` (macOS).

A convenience script is also provided:

```bash
./build.sh
```

## Installation

Copy the built DLL (or dylib) into DAZ Studio's `plugins` folder:

- **Windows (typical):** `C:\Program Files\DAZ 3D\DAZStudio4\plugins\`
- **macOS (typical):** `/Applications/DAZ 3D/DAZStudio4/plugins/`

To build and install in one step, pass `DAZ_STUDIO_EXE_DIR` at configure time and use the `--install` flag:

```bash
cmake -B build -S . \
  -DDAZ_SDK_DIR="C:/path/to/DAZStudio4.5+ SDK" \
  -DDAZ_STUDIO_EXE_DIR="C:/Program Files/DAZ 3D/DAZStudio4"

./build.sh --install
```

## Usage

### Starting the Server

After loading the plugin, open the pane via **Window → Panes → Daz Script Server**. Set the host and port (defaults: `127.0.0.1:18811`) and click **Start Server**.

### API

#### `GET /status`

Returns server status and version.

```json
{ "running": true, "version": "1.0.0.0" }
```

#### `POST /execute`

Executes a DazScript and returns the result.

**Request body:**

```json
{
  "scriptFile": "/absolute/path/to/script.dsa",
  "args": { "key": "value" }
}
```

Or with an inline script:

```json
{
  "script": "return Scene.getPrimarySelection().name;",
  "args": { "key": "value" }
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `scriptFile` | string | one of | Absolute path to a `.dsa` script file |
| `script` | string | one of | Inline DazScript code |
| `args` | object | no | Arguments accessible in the script via `getArguments()[0]` |

**Response:**

```json
{
  "success": true,
  "result": "My Node",
  "output": ["line printed by script"],
  "error": null
}
```

| Field | Description |
|---|---|
| `success` | `true` if the script executed without error |
| `result` | The script's return value (last evaluated expression) |
| `output` | Array of strings printed via `print()` during execution |
| `error` | Error message with line number if execution failed, otherwise `null` |

### Writing Scripts

**Accessing arguments** — use `getArguments()[0]`:

```javascript
var args = getArguments()[0];
print("Hello, " + args.name);
return args.value * 2;
```

**Using `include`** — use `scriptFile` (not `script`) so that `getScriptFileName()` resolves correctly:

```javascript
var includeDir = DzFile(getScriptFileName()).path();
include(includeDir + "/utils.dsa");

var args = getArguments()[0];
return myUtilFunction(args);
```

**Raising errors** — throw to populate the `error` field:

```javascript
var args = getArguments()[0];
if (!args.nodeId) throw new Error("nodeId is required");
return Scene.findNodeById(args.nodeId).name;
```

## Attribution

Networking is provided by [cpp-httplib](https://github.com/yhirose/cpp-httplib) (MIT License).
