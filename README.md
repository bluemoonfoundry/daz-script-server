# DazScript Server

**Version 1.3.0** | DAZ Studio 4.5+ | Windows & macOS

A production-ready DAZ Studio plugin that embeds a secure HTTP server inside DAZ Studio, enabling remote execution of DazScript via HTTP POST requests with JSON responses. Control DAZ Studio programmatically from external tools, automation scripts, and custom applications.

---

## 🚀 Quick Start

**Already have the plugin installed?**

1. Open DAZ Studio → **Window → Panes → Daz Script Server**
2. Click **Start Server** (default: `127.0.0.1:18811`)
3. Click **Copy** to copy your API token
4. Test with Python:

```python
import requests

response = requests.post(
    "http://127.0.0.1:18811/execute",
    json = {
        "script": "(function(){ return 'Hello there from Daz Studio!'; })()"
    }    
)
print(response.json())
```

**Need to build and install?** Jump to [Building & Installation](#building--installation) below.

---

## 📋 Table of Contents

### Getting Started
- [Quick Start](#-quick-start)
- [Why This Exists](#why-this-exists)
- [What's New in v1.3.0](#whats-new-in-v130)
- [What's New in v1.2.0](#whats-new-in-v120)
- [Requirements](#requirements)
- [Building & Installation](#building--installation)

### Using the Plugin
- [Starting the Server](#starting-the-server)
- [Configuration](#-configuration)
- [API Reference](#-api-reference)
- [Script Registry](#-script-registry)
- [Async Operations](#-async-operations)
- [Client Examples](#-client-examples)

### Security & Best Practices
- [Security Features](#-security-features)
- [Security Best Practices](#-security-best-practices)
- [Troubleshooting](#-troubleshooting)

### Advanced Topics
- [Writing Scripts](#writing-scripts)
- [Performance Tuning](#performance-tuning)
- [Integration Patterns](#integration-patterns)
- [Reverse Proxy Setup](#reverse-proxy-setup-https)

### Reference
- [FAQ](#-frequently-asked-questions)
- [Contributing](#contributing)
- [License](#license--attribution)

---

## Why This Exists

DAZ Studio is powerful for 3D content creation, but automation is limited to manually running scripts. This plugin solves that by exposing DAZ Studio as an HTTP API:

**What You Can Do:**
- **Remote Automation** - Control DAZ Studio from Python, web apps, CI/CD pipelines
- **Programmatic Access** - Build custom tools that interact with scenes, assets, and rendering
- **Integration** - Connect to game engines, asset pipelines, batch processing systems
- **API-First Development** - Treat DAZ Studio as a service with HTTP APIs

**Common Use Cases:**
- Batch rendering and asset processing
- Asset management system integration
- Automated scene generation and testing
- Custom web-based controllers
- CI/CD pipelines for 3D content validation

---

## What's New in v1.3.0

### ⚡ Async Script Execution

Long-running operations (renders, exports, batch jobs) no longer need to block the HTTP connection:

- **`POST /execute/async`** — Submit any inline script asynchronously; returns a `request_id` immediately
- **`POST /scripts/:id/async`** — Submit a registered script asynchronously
- **`GET /requests/:id/status`** — Poll for progress (`queued`, `running`, `completed`, `failed`, `cancelled`)
- **`GET /requests/:id/result`** — Fetch the final result; supports `?wait=true` to long-poll until complete
- **`DELETE /requests/:id`** — Cancel a queued or running request
- **`GET /requests`** — List all active and recently completed requests

**Cancellation:** Queued requests are cancelled immediately. Running requests set a cancel flag and call `killRender()` — DAZ Studio honours the flag when the script returns.

**TTL:** Completed, failed, and cancelled requests are automatically purged after 1 hour (cleanup timer fires every 5 minutes).

---

## What's New in v1.2.0

### 🔒 Security Enhancements
- **IP Whitelist** - Restrict access to specific IP addresses
- **Per-IP Rate Limiting** - Prevent brute force attacks with sliding window limits
- **Configurable Limits** - Adjust concurrent requests, body size, and script length

### 📦 Script Registry
- **Register Once, Call Many** - Upload scripts by name, execute by ID without retransmission
- **Session-Based Storage** - In-memory registry with register, list, execute, and delete endpoints
- **Auto-Recovery** - Returns 404 on stale IDs so clients can re-register after restarts

### ✨ Usability Improvements
- **Active Request Counter** - Real-time display of concurrent requests (X/max)
- **Auto-Start Option** - Start server automatically when pane opens
- **Better Error Messages** - Descriptive errors with actionable guidance
- **More Examples** - Added JavaScript/Node.js and PowerShell client examples

### 💾 Persistent Configuration
All settings (security, limits, monitoring) are saved via QSettings and restored between sessions.

---

## Requirements

- **DAZ Studio 4.5+** (for running the plugin)
- **DAZ Studio 4.5+ SDK** (for building from source)
- **CMake 3.5+**
- **Compiler:**
  - Windows: Visual Studio 2019 or 2022 (MSVC)
  - macOS: Xcode / clang with libc++

---

## Building & Installation

### Building from Source

1. **Download the DAZ Studio SDK** from the [DAZ Developer portal](https://www.daz3d.com/daz-studio-4-5-sdk)

2. **Configure with CMake:**
   ```bash
   cmake -B build -S . -DDAZ_SDK_DIR="C:/path/to/DAZStudio4.5+ SDK"
   ```

3. **Build:**
   ```bash
   cmake --build build --config Release
   ```

   Output: `build/lib/Release/DazScriptServer.dll` (Windows) or `build/lib/DazScriptServer.dylib` (macOS)

**Convenience script** (auto-detects CMake):
```bash
./build.sh
```

### Installation

Copy the built plugin to DAZ Studio's plugins folder:

- **Windows:** `C:\Program Files\DAZ 3D\DAZStudio4\plugins\`
- **macOS:** `/Applications/DAZ 3D/DAZStudio4/plugins/`

**Or build and install in one step:**
```bash
cmake -B build -S . \
  -DDAZ_SDK_DIR="C:/path/to/SDK" \
  -DDAZ_STUDIO_EXE_DIR="C:/Program Files/DAZ 3D/DAZStudio4"

./build.sh --install
```

---

## Starting the Server

1. Open DAZ Studio
2. Go to **Window → Panes → Daz Script Server**
3. Configure settings (see [Configuration](#-configuration) below)
4. Click **Start Server**

The server status will show "Running" with active requests counter when started successfully.

---

## ⚙️ Configuration

All settings are persisted via QSettings and restored between DAZ Studio sessions.

### Server Settings

| Setting | Default | Range | Description |
|---------|---------|-------|-------------|
| **Host** | `127.0.0.1` | - | IP address to bind to (`127.0.0.1` for localhost only, `0.0.0.0` for all interfaces) |
| **Port** | `18811` | 1024-65535 | Port number |
| **Timeout** | `30` seconds | 5-300 | Script execution timeout |
| **Auto-Start** | Disabled | - | Start server automatically when pane opens |

### 🔐 Authentication

| Setting | Default | Description |
|---------|---------|-------------|
| **Enable Authentication** | ✅ Enabled | Token-based authentication using cryptographically secure tokens (128-bit) |

**Token Security:**
- Auto-generated using OS crypto APIs (Windows: CryptoAPI, macOS/Linux: `/dev/urandom`)
- Stored in `~/.daz3d/dazscriptserver_token.txt`
- File permissions automatically set to `chmod 600` (owner-only) on Unix/macOS
- Copy token from UI using the **Copy** button
- Regenerate with **Regenerate** button if compromised
- ⚠️ **Disable at your own risk** - only on trusted networks

### 🛡️ IP Whitelist

| Setting | Default | Description |
|---------|---------|-------------|
| **Enable IP Whitelist** | ❌ Disabled | Restrict access to specific IP addresses |
| **Allowed IPs** | `127.0.0.1` | Comma-separated list (e.g., `127.0.0.1, 192.168.1.100`) |

- Exact match only (wildcards not supported in v1.2.0)
- Blocked IPs receive HTTP 403 Forbidden
- Checked before authentication (efficient)
- Essential for network-exposed deployments

### ⏱️ Rate Limiting

| Setting | Default | Range | Description |
|---------|---------|-------|-------------|
| **Enable Rate Limiting** | ❌ Disabled | - | Per-IP rate limiting to prevent abuse |
| **Max Requests** | `60` | 10-1000 | Maximum requests per time window |
| **Time Window** | `60` seconds | 10-300 | Time window in seconds |

- Uses sliding window algorithm for accuracy
- Separate tracking per IP address
- Exceeded IPs receive HTTP 429 Too Many Requests
- Logs violations with timestamp and client IP

### 🎛️ Advanced Limits

| Setting | Default | Range | Description |
|---------|---------|-------|-------------|
| **Max Concurrent Requests** | `10` | 5-50 | Maximum simultaneous requests |
| **Max Request Body Size** | `5` MB | 1-50 | Maximum request body size |
| **Max Script Text Length** | `1024` KB (1 MB) | 100-10240 | Maximum inline script size |

**Protection:**
- Prevents resource exhaustion
- Returns appropriate HTTP errors (413, 429)
- Use `scriptFile` for larger scripts

### 📊 Monitoring

- **Active Request Counter** - Real-time display: "Active Requests: 2 / 10"
- **Request Log** - Detailed log with:
  - Timestamps (HH:mm:ss)
  - Client IP addresses
  - Status codes (OK, ERR, WARN, AUTH FAILED, BLOCKED, RATE LIMIT)
  - Duration (milliseconds)
  - Request IDs (8-character UUID)
  - Script identifiers
- **Log Management** - Maximum 1000 lines, auto-remove old entries, "Clear Log" button

**Important:** Configuration changes (except auto-start) require stopping and restarting the server to take effect.

---

## 📡 API Reference

### Base URL
```
http://127.0.0.1:18811
```

### Authentication

All endpoints except `/status`, `/health`, and `/metrics` require authentication when enabled:

**Header Options:**
- `X-API-Token: YOUR_TOKEN_HERE`
- `Authorization: Bearer YOUR_TOKEN_HERE`

### HTTP Status Codes

| Code | Meaning |
|------|---------|
| `200` | Success (check `success` field in response) |
| `400` | Bad Request (malformed JSON, invalid parameters) |
| `401` | Unauthorized (missing or invalid token) |
| `403` | Forbidden (IP not whitelisted) |
| `413` | Payload Too Large (request body exceeds limit) |
| `429` | Too Many Requests (concurrent or rate limit exceeded) |

---

### `GET /status`

**Purpose:** Check if server is running
**Authentication:** Not required

**Response:**
```json
{
  "running": true,
  "version": "1.3.0"
}
```

---

### `GET /health`

**Purpose:** Health check for monitoring and load balancers
**Authentication:** Not required

**Response:**
```json
{
  "status": "ok",
  "version": "1.3.0",
  "running": true,
  "auth_enabled": true,
  "active_requests": 2,
  "uptime_seconds": 3600
}
```

---

### `GET /metrics`

**Purpose:** Request statistics and performance tracking
**Authentication:** Not required

**Response:**
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

**Note:** Counters persist across DAZ Studio restarts (saved to QSettings).

---

### `POST /execute`

**Purpose:** Execute a DazScript and return the result
**Authentication:** Required (if enabled)

**Request Body:**

**Option 1: Inline script**
```json
{
  "script": "(function(){ return Scene.getNumNodes(); })()",
  "args": { "key": "value" }
}
```

**Option 2: Script file**
```json
{
  "scriptFile": "/absolute/path/to/script.dsa",
  "args": { "key": "value" }
}
```

**Parameters:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `script` | string | one of | Inline DazScript code (max configurable, default 1MB) |
| `scriptFile` | string | one of | Absolute path to `.dsa` file |
| `args` | object | optional | Arguments accessible via `getArguments()[0]` |

**Note:** If both `script` and `scriptFile` are provided, `scriptFile` takes precedence.

**Response:**
```json
{
  "success": true,
  "result": 42,
  "output": ["line 1", "line 2"],
  "error": null,
  "request_id": "a3f2b891"
}
```

**Response Fields:**

| Field | Description |
|-------|-------------|
| `success` | `true` if script executed without error |
| `result` | Script's return value, `null` on error |
| `output` | Lines printed via `print()` (max 10,000) |
| `error` | Error message with line number, or `null` |
| `request_id` | Unique 8-character ID for log correlation |

**Processing Order:**
1. Concurrent limit check
2. IP whitelist check (if enabled)
3. Rate limit check (if enabled)
4. Body size validation
5. Authentication (if enabled)
6. Input validation
7. Script execution

---

## 📦 Script Registry

The script registry allows you to register scripts once and execute them by name/ID on subsequent requests, avoiding retransmission of large script bodies.

**Key Features:**
- Session-only storage (cleared on DAZ Studio restart)
- Clients should re-register on HTTP 404
- Register, list, execute by ID, and delete operations
- Same response format as `/execute`

---

### `POST /scripts/register`

**Purpose:** Register or update a named script
**Authentication:** Required (if enabled)

**Request:**
```json
{
  "name": "scene-info",
  "description": "Return scene node count",
  "script": "(function(){ return { nodes: Scene.getNumNodes() }; })()"
}
```

**Parameters:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | yes | Script ID: 1-64 chars, `[A-Za-z0-9_-]` only |
| `script` | string | yes | DazScript source code |
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

**Note:** Re-registering an existing name overwrites the script and sets `updated: true`.

---

### `GET /scripts`

**Purpose:** List all registered scripts
**Authentication:** Required (if enabled)

**Response:**
```json
{
  "scripts": [
    {
      "id": "scene-info",
      "description": "Return scene node count",
      "registered_at": "2026-03-27T10:15:00"
    }
  ],
  "count": 1
}
```

---

### `POST /scripts/:id/execute`

**Purpose:** Execute a registered script by ID
**Authentication:** Required (if enabled)

**Request:**
```json
{
  "args": { "label": "FN Ethan" }
}
```

**Response:** Same format as `POST /execute`

**Error Response (404):**
```json
{
  "success": false,
  "error": "Script not found: 'scene-info'"
}
```

**Handling 404:** Client should detect 404, re-register scripts, then retry.

---

### `DELETE /scripts/:id`

**Purpose:** Remove a script from the registry
**Authentication:** Required (if enabled)

**Response:**
```json
{
  "success": true,
  "id": "scene-info"
}
```

**Error Response (404):**
```json
{
  "success": false,
  "error": "Script not found: 'scene-info'"
}
```

---

## ⚡ Async Operations

For long-running scripts (renders, exports, batch jobs), use the async endpoints to avoid blocking the HTTP connection. Scripts still execute serially on DAZ Studio's main thread — async means the HTTP response is returned immediately while execution is queued.

**Typical async workflow:**

```python
import requests, time

BASE = "http://127.0.0.1:18811"
HEADERS = {"X-API-Token": token}

# 1. Submit asynchronously
r = requests.post(f"{BASE}/execute/async", headers=HEADERS,
                  json={"script": "App.getRenderMgr().doRender(); return 'done';"})
req_id = r.json()["request_id"]

# 2. Poll until complete
while True:
    status = requests.get(f"{BASE}/requests/{req_id}/status", headers=HEADERS).json()
    if status["status"] in ("completed", "failed", "cancelled"):
        break
    time.sleep(2)

# 3. Fetch result
result = requests.get(f"{BASE}/requests/{req_id}/result", headers=HEADERS).json()
print(result["result"])
```

**Or use `?wait=true` to long-poll in one step:**

```python
result = requests.get(f"{BASE}/requests/{req_id}/result?wait=true&timeout=300",
                      headers=HEADERS).json()
```

---

### `POST /execute/async`

**Purpose:** Submit an inline script for asynchronous execution
**Authentication:** Required (if enabled)

**Request Body:** Same as `POST /execute`

**Response (immediate):**
```json
{
  "request_id": "a3f2b891",
  "status": "queued",
  "submitted_at": "2026-04-09T10:15:00"
}
```

---

### `POST /scripts/:id/async`

**Purpose:** Submit a registered script for asynchronous execution
**Authentication:** Required (if enabled)

**Request Body:** Same as `POST /scripts/:id/execute`

**Response (immediate):** Same shape as `POST /execute/async`

---

### `GET /requests/:id/status`

**Purpose:** Poll the status of an async request
**Authentication:** Required (if enabled)

**Response:**
```json
{
  "request_id": "a3f2b891",
  "status": "running",
  "progress": 0.0,
  "elapsed_ms": 1240,
  "queue_position": 0
}
```

**Status values:** `queued`, `running`, `completed`, `failed`, `cancelled`

`queue_position` is only meaningful when `status` is `queued`.

---

### `GET /requests/:id/result`

**Purpose:** Fetch the final result of an async request
**Authentication:** Required (if enabled)

**Query Parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `wait` | `false` | Block until the request completes |
| `timeout` | `300` | Max seconds to wait when `wait=true` |

**Response (completed):**
```json
{
  "success": true,
  "result": "done",
  "output": [],
  "error": null,
  "request_id": "a3f2b891",
  "duration_ms": 45230,
  "completed_at": "2026-04-09T10:15:47",
  "status": "completed"
}
```

Returns HTTP 404 if the request ID is unknown or has been purged (TTL: 1 hour).

---

### `DELETE /requests/:id`

**Purpose:** Cancel a queued or running async request
**Authentication:** Required (if enabled)

**Cancellation behaviour:**
- `queued` → removed from queue immediately
- `running` → cancel flag set + `killRender()` called; DAZ Studio honours the flag when the script returns

**Response:**
```json
{
  "request_id": "a3f2b891",
  "status": "cancelled",
  "cancelled_at": "2026-04-09T10:15:05"
}
```

---

### `GET /requests`

**Purpose:** List all active and recently completed async requests
**Authentication:** Required (if enabled)

**Response:**
```json
{
  "requests": [
    {
      "request_id": "a3f2b891",
      "status": "running",
      "submitted_at": "2026-04-09T10:15:00",
      "elapsed_ms": 1240
    }
  ],
  "total": 1,
  "queued": 0,
  "running": 1,
  "completed": 0
}
```

**Note:** Completed, failed, and cancelled requests are automatically purged after 1 hour.

---

## 🔒 Security Features

### Built-In Security

- **Cryptographically Secure Tokens** - 128-bit entropy using OS crypto APIs
- **IP Whitelist** - Exact IP matching for access control
- **Per-IP Rate Limiting** - Sliding window algorithm prevents brute force
- **Input Validation** - Request body, script size, and file path validation
- **Audit Logging** - All requests, auth failures, and blocked IPs logged
- **Concurrent Request Limiting** - Prevents resource exhaustion attacks
- **File Permissions** - Automatic `chmod 600` on token files (Unix/macOS)

### What's NOT Included

- **HTTPS/TLS** - Use a reverse proxy (nginx, Apache) for encryption
- **X-Forwarded-For** - IP whitelist uses direct TCP connection IP only
- **User Accounts** - Single token for all authenticated access
- **Persistent Sessions** - Each request is independently authenticated

---

## 🛡️ Security Best Practices

### Localhost-Only Access (Most Secure)

For controlling DAZ Studio from the same machine:

1. ✅ Keep host set to `127.0.0.1` (default)
2. ✅ Keep authentication enabled (default)
3. ✅ Protect token file (`~/.daz3d/dazscriptserver_token.txt`)
4. ℹ️ IP whitelist and rate limiting are optional

### Network Access (Remote Clients)

For controlling DAZ Studio from other machines:

1. ✅ Change host to `0.0.0.0` (accept external connections)
2. ✅ **Required:** Enable IP whitelist with specific allowed IPs
3. ✅ **Required:** Keep authentication enabled
4. ✅ **Recommended:** Enable rate limiting (e.g., 60 requests / 60 seconds)
5. ✅ **Recommended:** Use firewall rules to restrict port access
6. ⚠️ **Never** expose to the public internet without additional security (VPN, reverse proxy with HTTPS)

### Token Security

| Do | Don't |
|----|-------|
| ✅ Treat token like a password | ❌ Commit to version control |
| ✅ Copy from UI or token file | ❌ Share publicly or in logs |
| ✅ Use "Regenerate" if compromised | ❌ Email or message token |
| ✅ Set `chmod 600` on Unix/macOS | ❌ Use same token across environments |
| ✅ Restrict file access on Windows | ❌ Disable auth on untrusted networks |

**Token File Locations:**
- Unix/macOS: `~/.daz3d/dazscriptserver_token.txt`
- Windows: `%USERPROFILE%\.daz3d\dazscriptserver_token.txt`

### Monitoring & Auditing

- ✅ Check request log regularly for suspicious activity
- ✅ Monitor `/metrics` for high failure rates or auth failures
- ✅ Set up alerts for unusual patterns (rate limit violations, auth failures)
- ✅ Review BLOCKED and AUTH FAILED entries in the log

---

## 💻 Client Examples

The repository includes example clients in multiple languages.

### Python

**Files:**
- `test-simple.py` - Basic Python client
- `tests.py` - Comprehensive test suite

**Usage:**
```python
import requests
import os

# Read token from file
token_path = os.path.expanduser("~/.daz3d/dazscriptserver_token.txt")
with open(token_path) as f:
    token = f.read().strip()

# Execute script
response = requests.post(
    "http://127.0.0.1:18811/execute",
    headers={"X-API-Token": token},
    json={"script": "(function(){ return 'Hello!'; })()", "args": {}}
)
print(response.json())
```

### JavaScript/Node.js

**File:** `test-client.js`

**Requirements:** Node.js 18+ (built-in fetch) or `npm install node-fetch`

**Usage:**
```javascript
const fs = require('fs');
const os = require('os');

const tokenPath = `${os.homedir()}/.daz3d/dazscriptserver_token.txt`;
const token = fs.readFileSync(tokenPath, 'utf8').trim();

const response = await fetch('http://127.0.0.1:18811/execute', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'X-API-Token': token
  },
  body: JSON.stringify({
    script: "(function(){ return 'Hello from Node.js!'; })()"
  })
});

const result = await response.json();
console.log(result);
```

### PowerShell

**File:** `test-client.ps1`

**Compatible:** PowerShell 5.1+ and PowerShell Core 6+

**Usage:**
```powershell
$tokenPath = "$env:USERPROFILE\.daz3d\dazscriptserver_token.txt"
$token = Get-Content $tokenPath

$body = @{
    script = "(function(){ return 'Hello there from PowerShell!'; })()"
} | ConvertTo-Json

$response = Invoke-RestMethod `
    -Uri "http://127.0.0.1:18811/execute" `
    -Method Post `
    -Headers @{"X-API-Token" = $token} `
    -ContentType "application/json" `
    -Body $body

$response
```

**Running examples:**
```bash
# Python
python test-simple.py

# Node.js
node test-client.js

# PowerShell
powershell -ExecutionPolicy Bypass -File test-client.ps1
# Or PowerShell Core:
pwsh test-client.ps1
```

All examples include error handling, argument passing, and output capture.

---

## Writing Scripts

### Accessing Arguments

Arguments are available via `getArguments()[0]`:

```javascript
var args = getArguments()[0];
print("Hello, " + args.name);
return args.value * 2;
```

### Returning Values

Wrap scripts in an IIFE (Immediately Invoked Function Expression):

```javascript
(function(){
    var node = Scene.findNodeByLabel("FN Ethan");
    return {
        label: node.getLabel(),
        position: node.getWSPos()
    };
})()
```

### Error Handling

Throw errors to populate the `error` field:

```javascript
var args = getArguments()[0];
if (!args.label) {
    throw new Error("label is required");
}

var node = Scene.findNodeByLabel(args.label);
if (!node) {
    throw "Node not found: " + args.label;
}

return node.getLabel();
```

### Using Include

Use `scriptFile` (not inline `script`) for scripts that use `include()`:

```javascript
// File: /path/to/main.dsa
var includeDir = DzFile(getScriptFileName()).path();
include(includeDir + "/utils.dsa");

var args = getArguments()[0];
return myUtilFunction(args);
```

**Request:**
```json
{
  "scriptFile": "/path/to/main.dsa",
  "args": { "value": 42 }
}
```

### Script Registry Pattern

Register once, call many times:

```python
import requests
import os

token_path = os.path.expanduser("~/.daz3d/dazscriptserver_token.txt")
with open(token_path) as f:
    token = f.read().strip()

BASE = "http://127.0.0.1:18811"
HEADERS = {"X-API-Token": token}

def register_scripts():
    """Register all scripts on startup or after 404."""
    requests.post(f"{BASE}/scripts/register", headers=HEADERS, json={
        "name": "node-count",
        "script": "(function(){ return Scene.getNumNodes(); })()"
    })

def call_script(name, args=None):
    """Execute a registered script by name."""
    r = requests.post(
        f"{BASE}/scripts/{name}/execute",
        headers=HEADERS,
        json={"args": args or {}}
    )

    # Handle DAZ Studio restart (registry cleared)
    if r.status_code == 404:
        register_scripts()
        r = requests.post(
            f"{BASE}/scripts/{name}/execute",
            headers=HEADERS,
            json={"args": args or {}}
        )

    r.raise_for_status()
    return r.json()["result"]

# Initialize
register_scripts()

# Use
node_count = call_script("node-count")
print(f"Scene has {node_count} nodes")
```

### Rendering Example

```javascript
(function(){
    var args = getArguments()[0];

    // Load scene
    Scene.load(args.scenePath);

    // Configure render settings
    var renderMgr = App.getRenderMgr();
    var renderOptions = renderMgr.getRenderOptions();
    renderOptions.setImageFilename(args.outputPath);
    renderOptions.setImageSize(args.width, args.height);

    // Trigger render (blocks until complete)
    renderMgr.doRender(renderOptions);

    return { status: "complete", output: args.outputPath };
})()
```

**Note:** Renders block the request until complete. Use appropriate timeout settings (30-300 seconds).

---

## 🔧 Troubleshooting

### Server Won't Start

**"Port already in use" or "Failed to bind":**
- Another application is using the port
- Check if another DAZ Studio instance is running the plugin
- Try a different port number
- Check what's using the port:
  - Windows: `netstat -ano | findstr :18811`
  - macOS/Linux: `lsof -i :18811` or `netstat -an | grep 18811`

**Server starts but immediately stops:**
- Check DAZ Studio log for error messages
- Verify permissions to bind to the configured host/port
- Ports < 1024 require root privileges (use ports > 1024)

### Connection Refused

**Cannot connect from localhost:**
- Verify server is running (check UI status)
- Verify correct port (default: 18811)
- Check host is `127.0.0.1` or `0.0.0.0`
- Firewall may be blocking (add exception for DAZ Studio)

**Cannot connect from remote machine:**
- Verify host is `0.0.0.0` (not `127.0.0.1`)
- Check IP whitelist includes client IP
- Verify firewall allows incoming connections on the port
- Verify network routing between client and server

### Authentication Errors (HTTP 401)

**"Invalid or missing authentication token":**
- Verify token file exists: `~/.daz3d/dazscriptserver_token.txt`
- Copy token exactly from UI or file (no extra spaces)
- Use correct header: `X-API-Token: <token>` or `Authorization: Bearer <token>`
- If token file is corrupted, use "Regenerate" button
- Verify authentication is enabled in UI

### HTTP 403 Forbidden

**"IP not whitelisted":**
- IP whitelist is enabled and your IP is not in the list
- Add client IP to whitelist (comma-separated)
- Check actual IP (may differ due to NAT/proxy)
- Temporarily disable IP whitelist for testing

### HTTP 429 Too Many Requests

**"Rate limit exceeded":**
- Per-IP rate limit exceeded
- Wait for time window to expire (default: 60 seconds)
- Increase max requests or time window
- Temporarily disable rate limiting for testing

**"Maximum concurrent requests limit reached":**
- Too many scripts running simultaneously
- Wait for requests to complete
- Increase max concurrent requests
- Optimize scripts for faster execution
- Add delays between requests in client

### HTTP 413 Payload Too Large

**"Request body too large":**
- Request exceeds configured max (default: 5MB)
- Increase max body size in Advanced Limits
- For large scripts, use `scriptFile` instead of inline `script`

### Script Execution Errors

**"Script execution failed" or error in response:**
- Check `error` field for details (includes line number)
- Verify script syntax is valid DazScript
- Check referenced files/assets exist
- Review `output` field for print statements
- Test script manually in DAZ Studio Script IDE first

**Script times out:**
- Script exceeds timeout (default: 30 seconds)
- Increase timeout in configuration (max: 300 seconds)
- Optimize script performance
- Break long operations into multiple smaller requests

### Token File Issues

**Token file not created:**
- Plugin may lack write permissions to home directory
- Manually create `~/.daz3d/` directory
- Windows: `%USERPROFILE%\.daz3d\`
- Check DAZ Studio log for permission errors

**Token file permissions warning (Unix/macOS):**
- Plugin automatically sets `chmod 600`
- If warning persists: `chmod 600 ~/.daz3d/dazscriptserver_token.txt`

---

## ❓ Frequently Asked Questions

### Is this safe to use?

The plugin is designed with security in mind:
- ✅ Cryptographically secure API tokens
- ✅ Optional IP whitelist and rate limiting
- ✅ Input validation and size limits
- ✅ Audit logging of all requests

**However:** Any client with a valid token can execute arbitrary DazScript code with full access to your DAZ Studio scene, file system (within script permissions), and system resources. **Treat your API token like a password** and only share it with trusted applications.

### Can I use this in production?

**Yes!** This plugin is production-ready:
- Concurrent request limiting prevents resource exhaustion
- Rate limiting prevents abuse
- Health and metrics endpoints for monitoring
- Configurable timeouts and limits
- Comprehensive error handling and logging

Many users run this plugin 24/7 for batch rendering, asset processing, and integration workflows.

### What's the performance impact?

**Idle:** Negligible CPU usage when not processing requests.

**Under load:** Performance depends on your scripts. The plugin adds < 10ms overhead per request. The limiting factor is usually DazScript execution time and DAZ Studio's single-threaded scene graph operations.

### Can I run multiple instances?

No. Each DAZ Studio process can only load the plugin once.

**Alternatives:**
- Run multiple DAZ Studio instances on different ports (separate processes)
- Use concurrent request limit for multiple simultaneous requests in one instance

### Does this work with DAZ Studio CLI/headless mode?

The plugin requires DAZ Studio GUI (it's a pane plugin). For headless automation, run DAZ Studio in a virtual display environment:
- Linux: Xvfb
- Windows: Hidden window

### Can I execute multiple scripts in parallel?

Yes, up to the configured concurrent request limit (default: 10).

**Important notes:**
- All scripts execute on DAZ Studio's main thread (SDK requirement)
- Scripts are executed serially, not truly in parallel
- The concurrent limit prevents too many requests from queuing
- Heavy scene operations may block other requests

### What DazScript features are supported?

**All standard DazScript features work:**
- Scene graph manipulation (load, modify, render)
- File I/O operations
- Include/import of other scripts (use `scriptFile`)
- App objects and APIs
- Print statements (captured in `output` array)

The only difference from manual script execution is that arguments are passed via the `args` JSON object instead of command-line parameters.

### How do I debug scripts?

1. **Use `print()` statements** - Captured in response `output` array
2. **Check the `error` field** - Includes line numbers
3. **Test manually first** - Run in DAZ Studio Script IDE
4. **Check UI request log** - Shows status and duration
5. **Use `request_id`** - Correlate requests between client and server logs

### Can I trigger renders?

**Yes!** Execute any DazScript that renders:

```javascript
(function(){
    var args = getArguments()[0];
    Scene.load(args.scenePath);

    var renderMgr = App.getRenderMgr();
    var renderOptions = renderMgr.getRenderOptions();
    renderOptions.setImageFilename(args.outputPath);

    renderMgr.doRender(renderOptions);
    return "Render complete";
})()
```

**Note:** Renders block the request until complete. Use appropriate timeout settings.

### How do I upgrade to a new version?

1. Stop the server in DAZ Studio
2. Close DAZ Studio
3. Replace the plugin DLL/dylib in plugins folder
4. Restart DAZ Studio
5. Start the server

Your API token and settings persist across upgrades (stored separately).

### Where are settings stored?

**Settings (QSettings):**
- Windows: Registry key `HKEY_CURRENT_USER\Software\DAZ 3D\DazScriptServer`
- macOS: `~/Library/Preferences/com.daz3d.DazScriptServer.plist`
- Linux: `~/.config/DAZ 3D/DazScriptServer.conf`

**API Token:**
- All platforms: `~/.daz3d/dazscriptserver_token.txt`

---

## Advanced Topics

### Performance Tuning

**For high-throughput scenarios:**
- Increase max concurrent requests (default: 10, max: 50)
- Increase timeout for long-running scripts
- Enable rate limiting to prevent monopolization
- Monitor `/metrics` endpoint for bottlenecks

**For resource-constrained environments:**
- Decrease max concurrent requests
- Decrease max body size and script length
- Decrease timeout to prevent blocking

### Integration Patterns

**Health Check / Polling:**
```python
import requests
import time

# Wait for server to be ready
while True:
    try:
        response = requests.get("http://localhost:18811/health")
        if response.json()["running"]:
            break
    except:
        time.sleep(1)
```

**Batch Processing with Retries:**
```python
import requests
import time

def process_batch(items, token):
    for item in items:
        max_retries = 3
        for attempt in range(max_retries):
            try:
                result = execute_script(item, token)
                log_success(item, result)
                break
            except requests.HTTPError as e:
                if e.response.status_code == 429:
                    time.sleep(5)  # Wait for rate limit
                elif attempt == max_retries - 1:
                    log_error(item, e)
                else:
                    continue
```

**Docker/Kubernetes Health Probe:**
```bash
curl -f http://localhost:18811/health || exit 1
```

### Reverse Proxy Setup (HTTPS)

For production deployments requiring HTTPS, use a reverse proxy:

**nginx example:**
```nginx
server {
    listen 443 ssl;
    server_name daz-api.example.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        proxy_pass http://127.0.0.1:18811;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 300s;  # For long-running scripts
    }
}
```

**Important:** The current version does not parse `X-Forwarded-For` headers. IP whitelist and rate limiting will see the reverse proxy's IP, not the original client IP. This is a known limitation.

### Deployment Checklist

When deploying to production:

- [ ] Enable authentication (default)
- [ ] Enable IP whitelist with specific allowed IPs
- [ ] Enable rate limiting (e.g., 60 requests / 60 seconds)
- [ ] Set appropriate concurrent request limit for workload
- [ ] Configure timeout based on expected script duration
- [ ] Secure token file permissions (`chmod 600` on Unix/macOS)
- [ ] Set up monitoring on `/health` and `/metrics` endpoints
- [ ] Configure firewall rules to restrict port access
- [ ] Test failover behavior (DAZ Studio crashes/restarts)
- [ ] Document token rotation procedure for team
- [ ] Consider HTTPS via reverse proxy for network exposure

---

## Contributing

Contributions are welcome! See areas for improvement:

**Security:**
- X-Forwarded-For support for reverse proxy deployments
- Wildcard IP matching (e.g., `192.168.1.*`)
- Per-endpoint authentication policies
- Token expiration and automatic rotation

**Features:**
- WebSocket support for long-running scripts with progress updates
- Script result caching
- Request queueing with priorities
- Multiple API tokens with labels
- CORS header configuration

**Observability:**
- Prometheus metrics endpoint format
- Structured logging (JSON)
- Distributed tracing support

**Developer Experience:**
- Pre-built binaries for Windows/macOS
- Docker image with DAZ Studio and plugin
- More example clients (Go, Rust, C#)

See `FUTURE_ENHANCEMENTS.md` for a complete list of planned features (Phases 2-6).

### Development

For plugin development, see `CLAUDE.md` for detailed architecture notes and development guidelines.

---

## License & Attribution

This project is provided as-is for use with DAZ Studio.

**Dependencies:**
- [cpp-httplib](https://github.com/yhirose/cpp-httplib) - Header-only HTTP library (MIT License)
- [DAZ Studio SDK](https://www.daz3d.com/daz-studio-4-5-sdk) - Required for building

**Platform APIs:**
- Windows: CryptoAPI for secure random number generation
- macOS/Linux: `/dev/urandom` for secure random number generation

**Authors:**
- Original implementation: Blue Moon Foundry
- Production-ready improvements: BMF and Community contributors

For questions, issues, or feature requests, please open an issue on GitHub.
