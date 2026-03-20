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

After loading the plugin, open the pane via **Window → Panes → Daz Script Server**. Configure:
- **Host**: IP address to bind to (default: `127.0.0.1` for localhost only)
- **Port**: Port number (default: `18811`)
- **Timeout**: Request timeout in seconds (default: `30s`, range: `5-300s`)

Click **Start Server** to begin accepting requests. Settings are automatically saved.

### Authentication

The server uses API token authentication to prevent unauthorized script execution. On first start, a cryptographically secure random token (128-bit) is automatically generated using platform crypto APIs (Windows: CryptoAPI, macOS/Linux: /dev/urandom) and saved to `~/.daz3d/dazscriptserver_token.txt`.

**To use the API:**
1. Copy the token from the plugin UI (click the "Copy" button)
2. Include it in your HTTP requests via the `X-API-Token` header

**Security notes:**
- **Cryptographically secure**: Tokens are generated using OS-provided crypto APIs, not predictable PRNGs
- Keep the token secure - anyone with it can execute arbitrary DazScript code
- The token file permissions are automatically set to owner-only (`chmod 600`) on Unix/macOS
- On Windows, manually restrict file access to your user account only
- If the token is compromised, use the "Regenerate" button to create a new one
- Authentication can be disabled via the checkbox (not recommended unless on a trusted network)
- Failed authentication attempts are logged in the Request Log with timestamp and client IP

### Request Logging

The plugin displays a real-time log of all requests with:
- **Timestamp** - When the request was received (HH:mm:ss)
- **Client IP** - Source IP address of the request
- **Status** - OK (success), ERR (error), WARN (warning), AUTH FAILED (authentication failure)
- **Duration** - Script execution time in milliseconds
- **Script identifier** - Filename for script files, or first 40 characters of inline scripts

Use the "Clear Log" button to clear the log view.

### API

#### `GET /status`

Returns server status and version.

```json
{ "running": true, "version": "1.1.0" }
```

#### `GET /health`

Returns detailed server health information (no authentication required).

```json
{
  "status": "ok",
  "version": "1.1.0",
  "running": true,
  "auth_enabled": true,
  "active_requests": 2,
  "uptime_seconds": 3600
}
```

Use for monitoring, health checks, and load balancer probes.

#### `GET /metrics`

Returns request statistics and performance metrics (no authentication required).

```json
{
  "total_requests": 1523,
  "successful_requests": 1489,
  "failed_requests": 28,
  "auth_failures": 6,
  "active_requests": 2,
  "uptime_seconds": 86400,
  "success_rate_percent": 97.77
}
```

Use for monitoring, alerting, and performance tracking.

#### `POST /execute`

Executes a DazScript and returns the result.

**Authentication:**
Include your API token in the request header:
```
X-API-Token: your-token-here
```

Or using the Authorization header:
```
Authorization: Bearer your-token-here
```

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
| `scriptFile` | string | one of | Absolute path to a `.dsa` script file (must exist and be absolute) |
| `script` | string | one of | Inline DazScript code (max 1MB) |
| `args` | object | no | Arguments accessible in the script via `getArguments()[0]` |

**Validation:**
- Request body size limit: 5MB
- Script text limit: 1MB
- Script file must be an absolute path and exist
- Either `scriptFile` or `script` must be provided (not both)
- If both are provided, `scriptFile` takes precedence

**Rate Limiting:**
- Maximum 10 concurrent requests
- Returns HTTP 429 (Too Many Requests) if limit exceeded

**Response:**

```json
{
  "success": true,
  "result": "My Node",
  "output": ["line printed by script"],
  "error": null,
  "request_id": "a3f2b891"
}
```

| Field | Description |
|---|---|
| `success` | `true` if the script executed without error |
| `result` | The script's return value (last evaluated expression) |
| `output` | Array of strings printed via `print()` during execution (max 10,000 lines) |
| `error` | Error message with line number if execution failed, otherwise `null` |
| `request_id` | Unique 8-character identifier for debugging and log correlation |

### Writing Scripts

**Python example with authentication:**

```python
import requests

# Read token from file
with open(os.path.expanduser("~/.daz3d/dazscriptserver_token.txt")) as f:
    token = f.read().strip()

# Make authenticated request
response = requests.post(
    "http://127.0.0.1:18811/execute",
    headers={"X-API-Token": token},
    json={"script": "return 'Hello';", "args": {}}
)
print(response.json())
```

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
