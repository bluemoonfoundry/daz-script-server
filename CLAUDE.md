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
```

Output: `build/lib/DazScriptServer.dll` (Windows) or `.dylib` (macOS).

To install directly into DAZ Studio's plugins folder:
```bash
cmake -B build -S . -DDAZ_SDK_DIR="..." -DINSTALL_TO_DAZ=ON -DDAZ_STUDIO_EXE_DIR="C:/Program Files/DAZ/Studio4"
cmake --build build --config Release --target install
```

Default install path: `C:\Program Files (x86)\DAZ\Studio4\plugins\`.

There are no unit tests — validation requires loading the plugin in DAZ Studio.

## Architecture

### Threading Model (Critical)

The plugin runs two threads:
- **Main Qt thread**: GUI, script execution via `DzScript`, all Qt/DAZ API calls
- **HTTP thread**: `ServerListenThread` blocks on `httplib::Server::listen()`

HTTP handlers run on raw `std::thread`s spawned by cpp-httplib — **not** Qt threads. The handler must do minimal work (parse the raw `QByteArray` body only), then invoke `handleExecuteRequest()` on the main thread via `Qt::BlockingQueuedConnection`. All `QScriptEngine`, `DzScript`, and Qt operations must happen on the main thread.

### Request Flow

`POST /execute` → HTTP handler (HTTP thread) → emit signal → `handleExecuteRequest()` (main thread):
1. Parses JSON body with `QScriptEngine` to extract `"script"` and `"args"`
2. Wraps script in an IIFE; injects `args` as a JSON literal accessible inside the script
3. Captures `dzApp` debug output (print statements) via `onMessagePosted()` during execution
4. Runs script via `DzScript`
5. Returns `{ success, result, output[], error }` as JSON

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

| Endpoint | Method | Response |
|---|---|---|
| `/status` | GET | `{"running":true,"version":"1.0.0.0"}` |
| `/execute` | POST | `{"success":bool,"result":any,"output":[],"error":string\|null}` |

Default host: `127.0.0.1`, default port: `18811`.

### Dependencies

- **DAZ Studio SDK 4.5+**: provides `dzcore`, Qt 4.8, `dpc` pre-compiler
- **cpp-httplib**: embedded as `src/httplib.h` (header-only); compression disabled via `CPPHTTPLIB_NO_COMPRESS`
- **Platform**: Windows links `ws2_32` (Winsock); macOS uses system frameworks

### Compiler Flags

`/MD /U_DEBUG` (MSVC) — forces multi-threaded runtime DLL and disables debug macros regardless of build type. Release builds also use `/O2 /Ob2 /DNDEBUG`.
