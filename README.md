# Vangard DazScript Server

A DAZ Studio plugin that embeds an HTTP server inside DAZ Studio, enabling remote execution of DazScript via HTTP requests with JSON responses. External tools can automate DAZ Studio operations — moving nodes, querying the scene, triggering renders — without any manual interaction.

## How It Works

Once the plugin is loaded and the server started, clients send HTTP requests containing a script (inline or by file path) and optional arguments. The plugin executes the script on DAZ Studio's main thread — where all scene and asset operations must run — and returns the result as JSON.

For high-frequency callers, the **script registry** lets you register a named script once and call it repeatedly by ID, avoiding the overhead of retransmitting the full script text on every request.

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

After loading the plugin, open the pane via **Window → Panes → Daz Script Server**. The pane header shows the current plugin version. Configure:

- **Host**: IP address to bind to (default: `127.0.0.1` for localhost only)
- **Port**: Port number (default: `18811`)
- **Timeout**: Request timeout in seconds (default: `30s`, range: `5–300s`)
- **Auto Start**: Check to start the server automatically when DAZ Studio loads

Click **Start Server** to begin accepting requests. The active request count is shown next to the status. All settings are saved automatically.

### Authentication

The server uses API token authentication to prevent unauthorized script execution. On first start, a random token is automatically generated and saved to `~/.daz3d/dazscriptserver_token.txt`.

**To use the API:**
1. Copy the token from the plugin UI (click the **Copy** button next to the token field)
2. Include it in every HTTP request via the `X-API-Token` header (or `Authorization: Bearer <token>`)

**Security notes:**
- Anyone with the token can execute arbitrary DazScript — keep it secure
- If compromised, click **Regenerate** in the UI to rotate the token
- Authentication can be disabled via the checkbox (not recommended outside a trusted network)
- Failed auth attempts are logged in the Request Log with timestamp and client IP

### IP Whitelist

Optionally restrict which client IPs can make requests:

1. Check **Enable IP Whitelist** in the plugin pane
2. Enter a comma-separated list of allowed IPs (e.g. `127.0.0.1, 192.168.1.50`)

Requests from non-whitelisted IPs receive `403 Forbidden` regardless of authentication state.

### Rate Limiting

To prevent runaway clients from overloading DAZ Studio:

1. Check **Enable Rate Limiting** in the plugin pane
2. Set **Max Requests** (default: 60) and **Window (seconds)** (default: 60)

Clients that exceed the limit receive `429 Too Many Requests`. The window is sliding per client IP.

### Advanced Limits

Under the **Advanced Limits** section of the pane:

| Setting | Default | Description |
|---|---|---|
| Max Concurrent Requests | 10 | Max simultaneous in-flight requests |
| Max Body Size (MB) | 5 | Request body size cap |
| Max Script Length (KB) | 1024 | Inline `script` field size cap |

### Request Logging

The plugin displays a real-time log of all requests:

| Column | Description |
|---|---|
| Timestamp | `HH:mm:ss` when the request was received |
| Client IP | Source IP address |
| Status | `OK`, `ERR`, `WARN`, `AUTH FAILED`, `BLOCKED`, `RATE LIMIT`, `REGISTRY` |
| Duration | Script execution time in milliseconds |
| Script identifier | Filename, registry ID, or first 40 chars of inline scripts |

Click **Clear Log** to reset the log view (up to 1000 lines are retained).

---

## API

All endpoints except `/status` require the `X-API-Token` header when authentication is enabled.

```
X-API-Token: your-token-here
```

Or using the Authorization header:

```
Authorization: Bearer your-token-here
```

---

### `GET /status`

Returns server status. No authentication required.

**Response:**
```json
{ "running": true, "version": "1.2.0" }
```

---

### `GET /health`

Returns runtime health information. Useful for monitoring.

**Response:**
```json
{
  "status": "ok",
  "version": "1.2.0",
  "running": true,
  "auth_enabled": true,
  "active_requests": 0,
  "uptime_seconds": 3600
}
```

---

### `GET /metrics`

Returns cumulative request counters. Counters persist across DAZ Studio restarts (saved to QSettings).

**Response:**
```json
{
  "total_requests": 142,
  "successful_requests": 139,
  "failed_requests": 3,
  "auth_failures": 1,
  "active_requests": 0,
  "uptime_seconds": 3600,
  "success_rate_percent": 97.89
}
```

---

### `POST /execute`

Executes a DazScript and returns the result.

**Request body:**

```json
{
  "script": "(function(){ return Scene.getNumNodes(); })()",
  "args": { "key": "value" }
}
```

Or with a script file:

```json
{
  "scriptFile": "/absolute/path/to/script.dsa",
  "args": { "key": "value" }
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `scriptFile` | string | one of | Absolute path to a `.dsa` script file |
| `script` | string | one of | Inline DazScript code (max configurable KB) |
| `args` | object | no | Arguments accessible inside the script via `getArguments()[0]` |

If both `scriptFile` and `script` are provided, `scriptFile` takes precedence.

**Response:**

```json
{
  "success": true,
  "result": 318,
  "output": [],
  "error": null,
  "request_id": "a3f2c1d0"
}
```

| Field | Description |
|---|---|
| `success` | `true` if the script executed without error |
| `result` | The script's return value |
| `output` | Lines printed via `print()` during execution |
| `error` | Error message (with line number) if execution failed, otherwise `null` |
| `request_id` | Unique ID for this request, useful for correlating logs |

---

## Script Registry

The registry lets you upload a script once and call it by name on every subsequent request. This avoids re-sending large script bodies, reduces latency, and makes logs easier to read.

**Registry is session-only** — scripts are stored in memory and cleared when DAZ Studio restarts. Clients should re-register on `404` responses from `/scripts/:id/execute`.

---

### `POST /scripts/register`

Register (or update) a named script. The `name` becomes the script's ID.

**Request body:**

```json
{
  "name": "scene-info",
  "description": "Return figures, cameras, lights, and node count",
  "script": "(function(){ return { nodes: Scene.getNumNodes() }; })()"
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | string | yes | Script ID: 1–64 chars, `[A-Za-z0-9_-]` only |
| `script` | string | yes | DazScript source |
| `description` | string | no | Human-readable description |

**Response:**

```json
{
  "success": true,
  "id": "scene-info",
  "registered_at": "2026-03-27T10:15:00",
  "updated": false
}
```

`updated: true` when an existing script with the same name is replaced.

---

### `GET /scripts`

List all registered scripts.

**Response:**

```json
{
  "scripts": [
    {
      "id": "scene-info",
      "description": "Return figures, cameras, lights, and node count",
      "registered_at": "2026-03-27T10:15:00"
    }
  ],
  "count": 1
}
```

---

### `POST /scripts/:id/execute`

Execute a registered script by ID.

```
POST /scripts/scene-info/execute
```

**Request body** (optional):

```json
{ "args": { "label": "FN Ethan" } }
```

Only `args` is read from the body — the script text is already stored in the registry.

**Response:** Same format as `POST /execute`.

If the script ID is not found, returns `404`:

```json
{ "success": false, "error": "Script not found: 'scene-info'" }
```

---

### `DELETE /scripts/:id`

Remove a script from the registry.

```
DELETE /scripts/scene-info
```

**Response:**

```json
{ "success": true, "id": "scene-info" }
```

Returns `404` if the script ID does not exist.

---

## HTTP Status Codes

| Code | Meaning |
|---|---|
| `200` | Success |
| `400` | Malformed request (bad JSON, missing required field, validation error) |
| `401` | Missing or invalid API token |
| `403` | Client IP not in whitelist |
| `404` | Registry script ID not found |
| `413` | Request body exceeds configured size limit |
| `429` | Rate limit exceeded or concurrent request limit reached |

---

## Writing Scripts

**Accessing arguments** inside a script (both `/execute` and registry execute):

```javascript
var args = getArguments()[0];
print("Hello, " + args.name);
return args.value * 2;
```

**Returning values** — wrap in an IIFE; do not use a bare top-level `return`:

```javascript
(function(){
    var node = Scene.findNodeByLabel("FN Ethan");
    return { label: node.getLabel(), pos: node.getWSPos() };
})()
```

**Raising errors** — throw to populate the `error` field and set `success: false`:

```javascript
var args = getArguments()[0];
if (!args.label) throw new Error("label is required");
var node = Scene.findNodeByLabel(args.label);
if (!node) throw "Node not found: " + args.label;
return node.getLabel();
```

**Using `include`** — use `scriptFile` (not `script`) so `getScriptFileName()` resolves correctly:

```javascript
var includeDir = DzFile(getScriptFileName()).path();
include(includeDir + "/utils.dsa");
var args = getArguments()[0];
return myUtilFunction(args);
```

**Python client example with registry:**

```python
import requests, os

token_path = os.path.expanduser("~/.daz3d/dazscriptserver_token.txt")
with open(token_path) as f:
    token = f.read().strip()

BASE = "http://127.0.0.1:18811"
HEADERS = {"X-API-Token": token}

# Register once at startup (re-register on 404 after DAZ Studio restart)
requests.post(f"{BASE}/scripts/register", headers=HEADERS, json={
    "name": "node-count",
    "script": "(function(){ return Scene.getNumNodes(); })()"
})

# Call many times without resending the script
for _ in range(10):
    r = requests.post(f"{BASE}/scripts/node-count/execute", headers=HEADERS)
    print(r.json()["result"])
```

---

## Attribution

Networking is provided by [cpp-httplib](https://github.com/yhirose/cpp-httplib) (MIT License).
