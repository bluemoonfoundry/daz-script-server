# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

DazScriptServer is a DAZ Studio plugin (`.dll`/`.dylib`) that embeds an HTTP server inside DAZ Studio, enabling remote execution of DazScript code via HTTP POST requests with JSON responses. It bridges external tools and the DAZ Studio environment.

## Build Commands

Requires the DAZ Studio 4.5+ SDK and CMake. The SDK provides Qt 4.8 and `dzcore`.

```bash
# Configure (set DAZ_SDK_DIR to your SDK path)
cmake -B build -S . -DDAZ_SDK_DIR="C:/path/to/DAZStudio4.5+ SDK"

# Build Release
cmake --build build --config Release

# Or use the convenience script (auto-detects cmake):
./build.sh
```

Output: `build/lib/Release/DazScriptServer.dll` (Windows) or `build/lib/DazScriptServer.dylib` (macOS).

To install directly into DAZ Studio's plugins folder:
```bash
cmake -B build -S . -DDAZ_SDK_DIR="..." -DINSTALL_TO_DAZ=ON -DDAZ_STUDIO_EXE_DIR="C:/Program Files/DAZ/Studio4"
cmake --build build --config Release --target install

# Or with build.sh:
./build.sh --install
```

Default install path: `C:\Program Files (x86)\DAZ\Studio4\plugins\`.

There are no unit tests — validation requires loading the plugin in DAZ Studio. A Python example client is provided in `test-simple.py` that demonstrates calling the `/execute` endpoint.

**Configuration settings** (persisted via QSettings):
- Host and port binding
- Request timeout (5-300 seconds, default 30)
- Authentication enabled/disabled state

## Architecture

### Threading Model (Critical)

The plugin runs two threads:
- **Main Qt thread**: GUI, script execution via `DzScript`, all Qt/DAZ API calls
- **HTTP thread**: `ServerListenThread` blocks on `httplib::Server::listen()`

HTTP handlers run on raw `std::thread`s spawned by cpp-httplib — **not** Qt threads. The handler must do minimal work (parse the raw `QByteArray` body only), then invoke `handleExecuteRequest()` on the main thread via `Qt::BlockingQueuedConnection`. All `QScriptEngine`, `DzScript`, and Qt operations must happen on the main thread.

### Request Flow

`POST /execute` → HTTP handler (HTTP thread) → validation & auth → emit signal → `handleExecuteRequest()` (main thread):
1. **Validates request body size** (max 10MB) - returns 413 if too large
2. **Validates API token** (if auth enabled) - returns 401 if invalid, logs failed attempts
3. **Parses JSON** with `QScriptEngine` - returns 400 with parse error if malformed
4. **Validates input:**
   - Script text length (max 1MB)
   - Either `scriptFile` or `script` is present
   - If `scriptFile`: path is absolute, file exists, is a file (not directory)
5. Wraps script in an IIFE; injects `args` as a JSON literal accessible inside the script
6. Captures `dzApp` debug output (print statements) via `onMessagePosted()` during execution
7. Runs script via `DzScript`, measuring execution duration
8. Logs request with timestamp, client IP, status, duration, and script identifier
9. Returns `{ success, result, output[], error }` as JSON

### Key Classes

| Class | File | Role |
|---|---|---|
| `DzScriptServerPane` | `src/DzScriptServerPane.cpp` | Main pane: GUI + server lifecycle + request handling |
| `ServerListenThread` | `src/DzScriptServerPane.cpp` | QThread wrapper that blocks on `httplib::Server::listen()` |
| `DzScriptServerPaneAction` | `src/pluginmain.cpp` | Registers the pane in DAZ Studio's Window → Panes menu |

### Plugin Registration

`include/dzscriptserver.h` provides two macros:
- `CPP_PLUGIN_DEFINITION(pluginName)` — generates the DLL entry point and `initPluginMetaData()`
- `NEW_PLUGIN_CUSTOM_CLASS_GUID(typeName, guid)` — factory for pane classes needing a `QWidget*` parent from variant args

Two GUIDs are registered in `pluginmain.cpp`: one for `DzScriptServerPane`, one for `DzScriptServerPaneAction`.

### HTTP API

| Endpoint | Method | Auth Required | Response |
|---|---|---|---|
| `/status` | GET | No | `{"running":true,"version":"1.0.0.0"}` |
| `/execute` | POST | Yes (if enabled) | `{"success":bool,"result":any,"output":[],"error":string\|null}` |

Default host: `127.0.0.1`, default port: `18811`.

**Authentication:** When enabled (default), clients must include API token via `X-API-Token` header or `Authorization: Bearer <token>`. Token is auto-generated on first start and stored in `~/.daz3d/dazscriptserver_token.txt`. Returns 401 Unauthorized if token is invalid/missing.

**POST /execute** accepts either:
- `scriptFile`: Absolute path to a `.dsa` file (required for scripts using `include()` or `getScriptFileName()`)
- `script`: Inline DazScript code as a string

Both accept optional `args` object, accessible in the script via `getArguments()[0]`.

### Dependencies

- **DAZ Studio SDK 4.5+**: provides `dzcore`, Qt 4.8, `dpc` pre-compiler
- **cpp-httplib**: embedded as `src/httplib.h` (header-only); compression disabled via `CPPHTTPLIB_NO_COMPRESS`
- **Platform**: Windows links `ws2_32` (Winsock); macOS uses system frameworks

### Compiler Flags

`/MD /U_DEBUG` (MSVC) — forces multi-threaded runtime DLL and disables debug macros regardless of build type. Release builds also use `/O2 /Ob2 /DNDEBUG`.

## Security & Reliability

### API Token Authentication

- **Token generation**: 32 hex characters (128-bit entropy) via `qrand()`
- **Storage**: `~/.daz3d/dazscriptserver_token.txt` (plaintext)
- **Validation**: HTTP thread checks `X-API-Token` header or `Authorization: Bearer <token>` before invoking main thread
- **Settings persistence**: `QSettings` stores host, port, timeout, and `authEnabled` flag
- **UI controls**: Token display (password-masked), copy to clipboard, regenerate, enable/disable checkbox
- **Thread safety**: Token is loaded once at startup and read-only during server operation (safe for HTTP thread to read)
- **Failed auth logging**: Auth failures logged with timestamp and client IP

### Input Validation

- **Request body size**: 10MB max (HTTP 413 if exceeded)
- **Script text length**: 1MB max
- **JSON parsing**: Error handling with line numbers for malformed JSON
- **Script file validation**: Must be absolute path, must exist, must be a file
- **Both fields warning**: If both `scriptFile` and `script` provided, warns and uses `scriptFile`

### Port Conflict Detection

- **Bind failure detection**: Checks if `httplib::Server` bound successfully after thread start
- **User-friendly errors**: Clear error messages suggesting port may be in use
- **Graceful cleanup**: Properly cleans up server objects on bind failure

### Request Logging

- **Format**: `[HH:mm:ss] [client_ip] [status] [duration_ms] script_identifier`
- **Status codes**: OK, ERR, WARN, AUTH FAILED
- **Duration tracking**: Uses `QTime` to measure execution time in milliseconds
- **Client IP logging**: Logs source IP for security auditing
- **Clear log button**: UI button to clear log view
