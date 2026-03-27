# Vangard DazScript Server

**Version 1.2.0** | DAZ Studio 4.5+ | Windows & macOS

A production-ready DAZ Studio plugin that embeds a secure HTTP server inside DAZ Studio, enabling remote execution of DazScript via HTTP POST requests with JSON responses. This allows external tools, automation scripts, and custom applications to programmatically control DAZ Studio operations.

## What's New in v1.2.0

**Security Enhancements:**
- ✅ IP Whitelist - Restrict access to specific IP addresses
- ✅ Per-IP Rate Limiting - Prevent brute force attacks with sliding window rate limits
- ✅ Configurable Advanced Limits - Adjust concurrent requests, body size, and script length

**Usability Improvements:**
- ✅ Active Request Counter - Real-time display of concurrent requests (X/max)
- ✅ Auto-Start Option - Optionally start server when pane opens
- ✅ Improved Error Messages - Descriptive errors with actionable guidance
- ✅ Additional Client Examples - JavaScript/Node.js and PowerShell examples included

**All Settings Persisted** - Every configuration option (security, limits, monitoring) is saved via QSettings and restored between sessions.

See the full changelog in `IMPROVEMENTS_SUMMARY.md` and `FUTURE_ENHANCEMENTS.md`.

## Table of Contents

- [Quick Start](#quick-start)
- [Why This Exists](#why-this-exists)
- [How It Works](#how-it-works)
- [Features](#features)
- [Requirements](#requirements)
- [Building](#building)
- [Installation](#installation)
- [Usage](#usage)
  - [Starting the Server](#starting-the-server)
  - [Configuration](#configuration)
  - [Authentication](#authentication)
  - [Request Logging](#request-logging)
  - [API](#api)
- [Security Best Practices](#security-best-practices)
- [Writing Scripts](#writing-scripts)
- [Troubleshooting](#troubleshooting)
- [Frequently Asked Questions](#frequently-asked-questions)
- [Client Examples](#client-examples)
- [Advanced Topics](#advanced-topics)
- [Contributing](#contributing)
- [License & Attribution](#license--attribution)

## Quick Start

**Already have the plugin installed?**

1. Open DAZ Studio → **Window → Panes → Daz Script Server**
2. Click **Start Server** (default: `127.0.0.1:18811`)
3. Click **Copy** to copy your API token
4. Test with Python:
   ```python
   import requests

   response = requests.post(
       "http://127.0.0.1:18811/execute",
       headers={"X-API-Token": "YOUR_TOKEN_HERE"},
       json={"script": "return 'Hello from DAZ Studio!';"}
   )
   print(response.json())
   ```

**Need to build and install?** See [Building](#building) and [Installation](#installation) below.

## Why This Exists

DAZ Studio is a powerful 3D content creation tool, but its automation capabilities are limited to manually running DazScript files or using the built-in Script IDE. This plugin solves several key problems:

- **Remote Automation**: Control DAZ Studio from external applications (Python scripts, web apps, CI/CD pipelines)
- **Programmatic Access**: Build custom tools that interact with DAZ Studio's scene graph, assets, and rendering engine
- **Integration**: Connect DAZ Studio to larger workflows (game engines, asset pipelines, batch processing)
- **API-First Development**: Treat DAZ Studio as a service that can be controlled via HTTP APIs

Common use cases:
- Batch rendering and asset processing
- Integration with asset management systems
- Automated scene generation and testing
- Custom web-based DAZ Studio controllers
- CI/CD pipelines for 3D content validation

## How It Works

Once the plugin is loaded and the server started, clients send HTTP requests containing a script path (or inline script code) and optional arguments. The plugin executes the script on DAZ Studio's main thread — where all scene and asset operations must run — and returns the result as JSON with captured output and error information.

## Features

### Security
- **API Token Authentication**: Cryptographically secure tokens (128-bit) using OS crypto APIs
- **IP Whitelist**: Restrict access to specific IP addresses (exact matching)
- **Per-IP Rate Limiting**: Prevent brute force attacks with configurable sliding window rate limits
- **Input Validation**: Comprehensive validation of request bodies, script sizes, and file paths
- **Audit Logging**: All requests, auth failures, and blocked IPs logged with timestamps and IDs

### Reliability
- **Concurrent Request Limiting**: Configurable max concurrent requests (5-50, default 10) prevents resource exhaustion
- **Request Timeouts**: Configurable script execution timeout (5-300 seconds, default 30)
- **Graceful Error Handling**: Descriptive error messages with actionable guidance
- **Port Conflict Detection**: Clear error messages when port is already in use

### Observability
- **Health Check Endpoint**: `/health` for monitoring and load balancer probes
- **Metrics Endpoint**: `/metrics` with request counts, success rates, and uptime
- **Real-Time Request Log**: UI displays all requests with timestamps, IPs, status, duration, and request IDs
- **Active Request Counter**: Live display of current concurrent requests (X/max)

### Usability
- **Auto-Start Option**: Optionally start server automatically when pane opens
- **Persistent Configuration**: All settings saved via QSettings and restored between sessions
- **Configurable Limits**: Adjust concurrent requests, body size, and script length limits in UI
- **Example Clients**: Included examples in Python, JavaScript/Node.js, and PowerShell

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

### Configuration

The plugin provides extensive configuration options, all persisted between DAZ Studio sessions via QSettings:

#### Server Settings
- **Host**: IP address to bind to (default: `127.0.0.1` for localhost only)
  - Use `127.0.0.1` to accept only local connections (most secure)
  - Use `0.0.0.0` to accept connections from any IP (requires IP whitelist for security)
- **Port**: Port number (default: `18811`)
- **Request Timeout**: Script execution timeout in seconds (range: 5-300, default: 30)
  - Scripts exceeding this timeout will be terminated
- **Auto-start**: Optionally start server automatically when pane opens (disabled by default)

#### Authentication
- **Enable Authentication**: Token-based authentication (enabled by default)
  - When enabled, all `/execute` requests must include a valid API token
  - Token is displayed in the UI (masked) with copy and regenerate buttons
  - Token stored in `~/.daz3d/dazscriptserver_token.txt` (owner-only permissions on Unix/macOS)
- **Disable at Your Own Risk**: Only disable authentication on trusted networks where unauthorized script execution is acceptable

#### IP Whitelist
- **Enable IP Whitelist**: Restrict access to specific IP addresses (disabled by default)
- **Allowed IPs**: Comma-separated list of IP addresses (default: `127.0.0.1`)
  - Example: `127.0.0.1, 192.168.1.100, 192.168.1.101`
  - Exact match only (wildcards not supported in v1.2.0)
  - Blocked IPs receive HTTP 403 Forbidden before authentication check
  - Useful for network-exposed deployments where only specific clients should access the server

#### Rate Limiting
- **Enable Per-IP Rate Limiting**: Prevent brute force attacks and abuse (disabled by default)
- **Max Requests**: Maximum requests allowed per time window (range: 10-1000, default: 60)
- **Time Window**: Time window in seconds (range: 10-300, default: 60)
  - Example: Default settings allow 60 requests per 60 seconds per IP
  - Uses sliding window algorithm for accurate limiting
  - Exceeded IPs receive HTTP 429 Too Many Requests
  - Separate tracking per IP address

#### Advanced Limits
- **Max Concurrent Requests**: Maximum simultaneous requests (range: 5-50, default: 10)
  - Prevents resource exhaustion from too many concurrent scripts
  - Returns HTTP 429 when limit reached
- **Max Request Body Size**: Maximum request body size in MB (range: 1-50, default: 5)
  - Prevents memory issues from excessively large requests
  - Returns HTTP 413 Payload Too Large when exceeded
- **Max Script Text Length**: Maximum inline script size in KB (range: 100-10240, default: 1024)
  - Limits memory usage from large inline scripts
  - Use `scriptFile` instead of `script` for very large scripts

#### Monitoring
- **Active Requests**: Real-time counter showing current/max concurrent requests (e.g., "Active Requests: 2 / 10")
- **Request Log**: Detailed log with timestamps, client IPs, status codes, duration, request IDs, and script identifiers
  - Status codes: OK (success), ERR (error), WARN (warning), AUTH FAILED, BLOCKED, RATE LIMIT
  - Maximum 1000 lines displayed (older entries automatically removed)
  - "Clear Log" button to manually clear the log

**Important**: All configuration changes (except auto-start) require stopping and restarting the server to take effect. The server captures configuration values at startup and uses them throughout its lifecycle.

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
{ "running": true, "version": "1.2.0" }
```

#### `GET /health`

Returns detailed server health information (no authentication required).

```json
{
  "status": "ok",
  "version": "1.2.0",
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
Include your API token in the request header (if authentication is enabled):
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

**Request Parameters:**

| Field | Type | Required | Description |
|---|---|---|---|
| `scriptFile` | string | one of | Absolute path to a `.dsa` script file (must exist and be absolute) |
| `script` | string | one of | Inline DazScript code (configurable max, default 1MB) |
| `args` | object | no | Arguments accessible in the script via `getArguments()[0]` |

**Request Processing Order:**
1. Concurrent request limit check
2. IP whitelist check (if enabled)
3. Per-IP rate limit check (if enabled)
4. Request body size validation
5. Authentication check (if enabled)
6. JSON parsing and input validation
7. Script execution

**Validation & Limits:**
- **Request body size**: Configurable max (default 5MB, adjustable 1-50MB)
- **Script text length**: Configurable max (default 1MB, adjustable 100KB-10MB)
- **Concurrent requests**: Configurable max (default 10, adjustable 5-50)
- **Script file**: Must be an absolute path and exist
- **Either `scriptFile` or `script`** must be provided (not both)
- If both are provided, `scriptFile` takes precedence with a warning

**HTTP Status Codes:**

| Code | Condition | Description |
|---|---|---|
| `200 OK` | Success | Script executed (check `success` field in response body) |
| `400 Bad Request` | Validation failed | Malformed JSON, missing fields, or invalid parameters |
| `401 Unauthorized` | Auth failed | Missing or invalid API token (if auth enabled) |
| `403 Forbidden` | IP blocked | Client IP not in whitelist (if IP whitelist enabled) |
| `413 Payload Too Large` | Body too large | Request body exceeds configured max size |
| `429 Too Many Requests` | Rate limit exceeded | Concurrent limit reached or per-IP rate limit exceeded |
| `500 Internal Server Error` | Server error | Unexpected server-side error |

**Success Response:**

```json
{
  "success": true,
  "result": "My Node",
  "output": ["line printed by script"],
  "error": null,
  "request_id": "a3f2b891"
}
```

**Error Response:**

```json
{
  "success": false,
  "result": null,
  "output": [],
  "error": "Script execution failed at line 5: Undefined variable 'foo'",
  "request_id": "a3f2b891"
}
```

**Response Fields:**

| Field | Type | Description |
|---|---|---|
| `success` | boolean | `true` if the script executed without error |
| `result` | any | The script's return value (last evaluated expression), `null` on error |
| `output` | string[] | Array of strings printed via `print()` during execution (max 10,000 lines) |
| `error` | string\|null | Error message with line number if execution failed, otherwise `null` |
| `request_id` | string | Unique 8-character identifier for debugging and log correlation |

## Security Best Practices

### For Localhost-Only Access (Most Secure)
If you only need to control DAZ Studio from the same machine:
1. Keep host set to `127.0.0.1` (default)
2. Keep authentication enabled (default)
3. Protect your token file (`~/.daz3d/dazscriptserver_token.txt`)
4. IP whitelist and rate limiting are optional in this configuration

### For Network Access (Remote Clients)
If you need to control DAZ Studio from other machines on your network:
1. Change host to `0.0.0.0` to accept external connections
2. **Required**: Enable IP whitelist with specific allowed IPs
3. **Required**: Keep authentication enabled
4. **Recommended**: Enable rate limiting (e.g., 60 requests per 60 seconds)
5. **Recommended**: Use a firewall to restrict port access
6. **Never** expose to the public internet without additional security layers (VPN, reverse proxy with HTTPS)

### Token Security
- **Protect the token file**: Anyone with your token can execute arbitrary code in DAZ Studio
- **Never commit tokens to version control**: Add `dazscriptserver_token.txt` to `.gitignore`
- **Rotate tokens regularly**: Use the "Regenerate" button in the UI periodically
- **File permissions**: On Unix/macOS, the token file is automatically set to `chmod 600` (owner-only)
- **Windows**: Manually restrict file access to your user account only (Right-click → Properties → Security)
- **Disable authentication only on trusted networks**: If you disable auth, anyone who can reach the port can execute code

### Monitoring & Auditing
- **Check the request log regularly**: Monitor for unexpected authentication failures or blocked IPs
- **Use the `/metrics` endpoint**: Set up monitoring alerts for unusual patterns (high failure rates, auth failures)
- **Rate limiting logs**: Check for RATE LIMIT entries in the log to identify potential abuse

### What This Plugin Does NOT Provide
- **HTTPS/TLS encryption**: Requests are sent over plain HTTP (use a reverse proxy or VPN for encryption)
- **X-Forwarded-For support**: IP whitelist and rate limiting use direct TCP connection IP (not suitable for deployments behind proxies without modification)
- **User accounts or roles**: Single token for all authenticated access
- **Persistent session management**: Each request is independently authenticated

## Writing Scripts

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

## Troubleshooting

### Server Won't Start

**"Port already in use" or "Failed to bind":**
- Another application is using port 18811 (or your configured port)
- Check if another instance of DAZ Studio is running with the plugin active
- Try a different port number in the configuration
- On Windows: `netstat -ano | findstr :18811` to find what's using the port
- On macOS/Linux: `lsof -i :18811` or `netstat -an | grep 18811`

**Server starts but immediately stops:**
- Check the DAZ Studio log for error messages
- Verify you have permissions to bind to the configured host/port
- On Unix/macOS, ports < 1024 require root privileges (use ports > 1024)

### Connection Refused

**Cannot connect from localhost:**
- Verify the server is running (check UI status label)
- Verify you're using the correct port (default: 18811)
- Check host is set to `127.0.0.1` or `0.0.0.0`
- Firewall may be blocking connections (add exception for DAZ Studio)

**Cannot connect from remote machine:**
- Verify host is set to `0.0.0.0` (not `127.0.0.1`)
- Check IP whitelist includes the client IP address
- Verify firewall rules allow incoming connections on the port
- Verify network routing allows traffic between client and server

### Authentication Errors (HTTP 401)

**"Invalid or missing authentication token":**
- Verify token file exists: `~/.daz3d/dazscriptserver_token.txt`
- Copy token exactly from UI or file (no extra spaces or newlines)
- Use correct header: `X-API-Token: <token>` or `Authorization: Bearer <token>`
- If token file is corrupted, use "Regenerate" button in UI
- Check authentication is enabled in the UI

### HTTP 403 Forbidden

**"IP not whitelisted":**
- IP whitelist is enabled and your IP is not in the list
- Add your client IP to the whitelist (comma-separated)
- Check your actual IP (may be different from expected due to NAT/proxy)
- Temporarily disable IP whitelist for testing (re-enable for production)

### HTTP 429 Too Many Requests

**"Rate limit exceeded":**
- Per-IP rate limit is enabled and you've exceeded the limit
- Wait for the time window to expire (default: 60 seconds)
- Increase max requests or time window in configuration
- Temporarily disable rate limiting for testing

**"Maximum concurrent requests limit reached":**
- Too many scripts are running simultaneously
- Wait for some requests to complete
- Increase max concurrent requests in Advanced Limits
- Optimize scripts to run faster
- Add delays between requests in client code

### HTTP 413 Payload Too Large

**"Request body too large":**
- Request body exceeds configured max (default: 5MB)
- Reduce request size or increase max body size in Advanced Limits
- For large scripts, use `scriptFile` instead of inline `script`

### Script Execution Errors

**"Script execution failed" or error in response:**
- Check the `error` field in the response for details (includes line number)
- Verify script syntax is valid DazScript
- Check that referenced files/assets exist
- Review the `output` field for print statements that may indicate the issue
- Test script manually in DAZ Studio Script IDE first

**Script times out:**
- Script takes longer than configured timeout (default: 30 seconds)
- Increase timeout in configuration (max: 300 seconds)
- Optimize script for better performance
- Break long operations into multiple smaller requests

### Token File Issues

**Token file not created:**
- Plugin may not have write permissions to home directory
- Manually create `~/.daz3d/` directory
- On Windows: `%USERPROFILE%\.daz3d\`
- Check DAZ Studio log for permission errors

**Token file permissions warning (Unix/macOS):**
- Plugin automatically sets file to `chmod 600`
- If warning persists, manually run: `chmod 600 ~/.daz3d/dazscriptserver_token.txt`

## Frequently Asked Questions

### Is this safe to use?

The plugin is designed with security in mind:
- Cryptographically secure API tokens
- Optional IP whitelist and rate limiting
- Input validation and size limits
- Audit logging of all requests

However, **any client with a valid token can execute arbitrary DazScript code**, which has full access to your DAZ Studio scene, file system (within script permissions), and system resources. Treat your API token like a password and only share it with trusted applications.

### Can I use this in production?

Yes, this plugin is production-ready with enterprise features:
- Concurrent request limiting prevents resource exhaustion
- Rate limiting prevents abuse
- Health and metrics endpoints for monitoring
- Configurable timeouts and limits
- Comprehensive error handling and logging

Many users run this plugin 24/7 for batch rendering, asset processing, and integration workflows.

### What's the performance impact?

**Minimal when idle**: The HTTP server runs in a background thread and uses negligible CPU when not processing requests.

**Under load**: Performance depends on your scripts. The plugin itself adds < 10ms overhead per request. The limiting factor is usually the DazScript execution time and DAZ Studio's single-threaded scene graph operations.

### Can I run multiple instances?

No. Each DAZ Studio process can only load the plugin once. However, you can:
- Run multiple DAZ Studio instances on different ports (separate processes)
- Use the concurrent request limit to handle multiple simultaneous requests in a single instance

### Does this work with DAZ Studio CLI/headless mode?

The plugin requires the DAZ Studio GUI to be running (it's a pane plugin). For headless automation, you'll need to run DAZ Studio in a virtual display environment (Xvfb on Linux, hidden window on Windows).

### Can I execute multiple scripts in parallel?

Yes, up to the configured concurrent request limit (default: 10). However, note that:
- All scripts execute on DAZ Studio's main thread (required by the SDK)
- Scripts are executed serially, not truly in parallel
- The concurrent limit prevents too many requests from queuing up
- Heavy scene operations may block other requests

### What DazScript features are supported?

All standard DazScript features work:
- Scene graph manipulation (load, modify, render)
- File I/O operations
- Include/import of other scripts (use `scriptFile` not inline `script`)
- App objects and APIs
- Print statements (captured in `output` array)

The only difference from running scripts manually is that arguments are passed via the `args` JSON object instead of command-line parameters.

### How do I debug scripts?

1. **Use `print()` statements**: Captured in the response `output` array
2. **Check the `error` field**: Includes line numbers for errors
3. **Test scripts manually first**: Run in DAZ Studio Script IDE before automating
4. **Check the UI request log**: Shows all requests with status and duration
5. **Use the request_id**: Correlate requests between client logs and server logs

### Can I trigger renders?

Yes! You can execute any DazScript that renders:

```javascript
var args = getArguments()[0];
Scene.load(args.scenePath);
// Configure render settings
var renderMgr = App.getRenderMgr();
var renderOptions = renderMgr.getRenderOptions();
renderOptions.setImageFilename(args.outputPath);
// Trigger render
renderMgr.doRender(renderOptions);
return "Render complete";
```

Note: Renders block the request until complete. Use appropriate timeout settings (30-300 seconds).

### What about error handling and retries?

The plugin returns detailed error information in the response:
- `success: false` indicates script execution failed
- `error` field contains the error message and line number
- `output` field may contain print statements before the error

Implement retry logic in your client code for transient failures (429 rate limits, network errors). Don't retry 400 Bad Request or 401 Unauthorized errors.

### How do I upgrade to a new version?

1. Stop the server in DAZ Studio
2. Close DAZ Studio
3. Replace the plugin DLL/dylib in the plugins folder
4. Restart DAZ Studio
5. Start the server (your configuration is preserved via QSettings)

Your API token and all settings are stored separately and will persist across upgrades.

### Where are settings stored?

All settings are stored via Qt's QSettings:
- **Windows**: Registry key `HKEY_CURRENT_USER\Software\DAZ 3D\DazScriptServer`
- **macOS**: `~/Library/Preferences/com.daz3d.DazScriptServer.plist`
- **Linux**: `~/.config/DAZ 3D/DazScriptServer.conf`

The API token is stored separately in `~/.daz3d/dazscriptserver_token.txt`.

## Client Examples

The repository includes example clients in multiple languages:

**Python:**
- `test-simple.py` - Basic Python client demonstrating authentication and script execution
- `tests.py` - More comprehensive Python test suite

**JavaScript/Node.js:**
- `test-client.js` - Complete Node.js client with multiple examples
- Demonstrates async/await, error handling, and argument passing
- Requires: `npm install node-fetch` (or Node.js 18+ with built-in fetch)

**PowerShell:**
- `test-client.ps1` - PowerShell client for Windows automation
- Works with PowerShell 5.1+ and PowerShell Core 6+
- Demonstrates REST API calls, JSON handling, and error handling

**Usage:**
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

All examples include:
- API token authentication
- Error handling
- Argument passing
- Output capture
- Rate limiting demonstration

## Advanced Topics

### Thread Safety

The plugin uses a careful threading model to ensure thread safety:
- **HTTP handlers** run on `std::thread`s spawned by cpp-httplib (not Qt threads)
- **Script execution** happens on DAZ Studio's main Qt thread via `Qt::BlockingQueuedConnection`
- **Request metrics** are protected by `QMutex` for thread-safe access
- **Rate limit state** is protected by `QMutex` for concurrent access from HTTP threads

This design ensures:
- All DAZ Studio API calls happen on the main thread (required by DAZ SDK)
- HTTP threads only parse request data and validate auth/limits
- No race conditions in metrics, rate limiting, or request tracking

### Performance Tuning

**For high-throughput scenarios:**
- Increase max concurrent requests (default: 10, max: 50)
- Increase timeout for long-running scripts
- Enable rate limiting to prevent individual clients from monopolizing resources
- Monitor `/metrics` endpoint to identify bottlenecks

**For resource-constrained environments:**
- Decrease max concurrent requests to prevent memory exhaustion
- Decrease max body size and script length to reduce memory usage
- Decrease timeout to prevent long-running scripts from blocking

### Integration Patterns

**Polling Pattern:**
```python
# Check if server is ready before sending requests
while True:
    try:
        response = requests.get("http://localhost:18811/health")
        if response.json()["running"]:
            break
    except:
        time.sleep(1)
```

**Batch Processing:**
```python
# Process multiple items with error handling and retries
for item in items:
    max_retries = 3
    for attempt in range(max_retries):
        try:
            result = execute_script(item)
            break
        except requests.HTTPError as e:
            if e.response.status_code == 429:
                time.sleep(5)  # Wait for rate limit
            elif attempt == max_retries - 1:
                log_error(item, e)
```

**Health Check Integration:**
```bash
# Use in Docker/Kubernetes health probes
curl -f http://localhost:18811/health || exit 1
```

### Reverse Proxy Setup (HTTPS)

For production deployments with HTTPS, use a reverse proxy:

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
    }
}
```

**Note**: The current version does not parse `X-Forwarded-For` for IP whitelist/rate limiting. The IP whitelist will see the reverse proxy's IP, not the original client IP. This is a known limitation suitable for simple deployments.

### Deployment Checklist

When deploying to production:
- [ ] Enable authentication (default)
- [ ] Enable IP whitelist with specific allowed IPs
- [ ] Enable rate limiting (e.g., 60/60s)
- [ ] Set appropriate concurrent request limit for your workload
- [ ] Configure timeout based on expected script duration
- [ ] Secure token file permissions (chmod 600 on Unix/macOS)
- [ ] Set up monitoring on `/health` and `/metrics` endpoints
- [ ] Configure firewall rules to restrict port access
- [ ] Test failover behavior (what happens when DAZ Studio crashes/restarts)
- [ ] Document the token rotation procedure for your team
- [ ] Consider HTTPS via reverse proxy for network-exposed deployments

## Contributing

Contributions are welcome! Areas for improvement:

**Security:**
- X-Forwarded-For support for IP whitelist behind reverse proxies
- Wildcard IP matching (e.g., `192.168.1.*`)
- Per-endpoint authentication (allow `/health` and `/metrics` without auth)
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
- Request tracing with distributed trace IDs

**Developer Experience:**
- Pre-built binaries for Windows/macOS
- Docker image with DAZ Studio and plugin
- More example clients (Go, Rust, C#)

See `FUTURE_ENHANCEMENTS.md` for a complete list of planned features.

### Development Setup

For plugin development, see `CLAUDE.md` for detailed architecture notes and development guidelines.

## License & Attribution

This project is provided as-is for use with DAZ Studio.

**Dependencies:**
- [cpp-httplib](https://github.com/yhirose/cpp-httplib) - Header-only HTTP library (MIT License)
  - Used for embedding the HTTP server
  - No external dependencies, no compression enabled
- [DAZ Studio SDK](https://www.daz3d.com/daz-studio-4-5-sdk) - Required for building
  - Includes Qt 4.8 framework
  - Includes DAZ core libraries (`dzcore`, `dpc`)

**Platform APIs:**
- Windows: CryptoAPI for secure random number generation
- macOS/Linux: `/dev/urandom` for secure random number generation

**Authors:**
- Original implementation: Blue Moon Foundry
- Production-ready improvements: BMF and Community contributors

For questions, issues, or feature requests, please open an issue on GitHub.
