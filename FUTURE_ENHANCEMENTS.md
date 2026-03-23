# Future Enhancements - Script Library & Advanced Features

## Overview

This document outlines potential enhancements to make the DazScriptServer more powerful and efficient, particularly for MCP (Model Context Protocol) server integrations.

## Key Questions

1. **Where should script caching/library functionality live?**
   - Answer: **Hybrid approach** - Plugin provides primitives, MCP provides convenience

2. **What endpoints would be most useful?**
   - Script registry/library for reusable scripts
   - Common DAZ operations as dedicated endpoints
   - Batch execution for multiple operations

3. **How can results be more useful?**
   - Structured response formats for common types
   - Type metadata
   - Better error context

---

## Phase 1: Script Registry (High Value, Low Complexity)

### Concept

Allow registering named scripts that can be executed by ID instead of sending full script text each time.

### New Endpoints

#### POST /scripts/register
Register a script in the server's library.

**Request:**
```json
{
  "name": "get-selected-objects",
  "description": "Returns list of currently selected objects",
  "script": "var objs = Scene.getSelectedNodeList(); return objs.map(function(n) { return {name: n.name, type: n.className()}; });",
  "parameters": ["includeHidden"]
}
```

**Response:**
```json
{
  "success": true,
  "script_id": "get-selected-objects",
  "registered_at": "2026-03-20T14:23:45Z"
}
```

#### GET /scripts
List all registered scripts.

**Response:**
```json
{
  "scripts": [
    {
      "id": "get-selected-objects",
      "description": "Returns list of currently selected objects",
      "parameters": ["includeHidden"],
      "registered_at": "2026-03-20T14:23:45Z"
    }
  ]
}
```

#### POST /scripts/{id}/execute
Execute a registered script by ID.

**Request:**
```json
{
  "args": {
    "includeHidden": false
  }
}
```

**Response:**
```json
{
  "success": true,
  "result": [
    {"name": "Genesis 9", "type": "DzFigure"},
    {"name": "Camera 1", "type": "DzCamera"}
  ],
  "output": [],
  "error": null,
  "request_id": "b4f3c892"
}
```

#### DELETE /scripts/{id}
Remove a registered script.

### Benefits

- **Network efficiency**: Send script once, execute many times
- **Convenience**: Named operations instead of script text
- **Validation**: Script syntax checked once at registration
- **Documentation**: Self-documenting API with descriptions
- **Persistence**: Can save registry to disk

### Implementation Considerations

**Storage:**
```cpp
// In DzScriptServerPane.h
struct RegisteredScript {
    QString id;
    QString description;
    QString script;
    QStringList parameters;
    QDateTime registeredAt;
};

private:
    QMap<QString, RegisteredScript> m_registeredScripts;
    QMutex m_scriptRegistryMutex;
```

**Persistence:**
- Save registry to `~/.daz3d/dazscriptserver_scripts.json`
- Load on startup
- Optional: Sync across multiple DAZ instances

---

## Phase 2: Common DAZ Operations (Built on Registry)

### Concept

Pre-register commonly used DAZ operations as built-in endpoints.

### Built-in Scripts

These would be pre-registered on server start:

#### GET /daz/scene/info
Get basic scene information.

**Response:**
```json
{
  "scene_name": "Untitled",
  "node_count": 47,
  "selected_count": 2,
  "cameras": ["Camera 1", "Camera 2"],
  "lights": ["Distant Light 1", "Point Light 1"]
}
```

**Implementation:** Pre-registered script that gathers scene metadata.

#### GET /daz/scene/selection
Get currently selected objects with detailed info.

**Response:**
```json
{
  "selection": [
    {
      "name": "Genesis 9",
      "type": "DzFigure",
      "visible": true,
      "locked": false,
      "position": [0, 0, 0],
      "rotation": [0, 0, 0]
    }
  ]
}
```

#### POST /daz/scene/select
Select objects by name or pattern.

**Request:**
```json
{
  "names": ["Genesis 9", "Camera 1"],
  "pattern": "Light*",
  "clearExisting": true
}
```

#### GET /daz/scene/hierarchy
Get scene node hierarchy as tree.

**Response:**
```json
{
  "root": {
    "name": "Scene",
    "children": [
      {
        "name": "Genesis 9",
        "type": "DzFigure",
        "children": [
          {"name": "Head", "type": "DzBone"},
          {"name": "Body", "type": "DzBone"}
        ]
      }
    ]
  }
}
```

#### POST /daz/export
Export scene or objects to file.

**Request:**
```json
{
  "format": "obj",
  "path": "/path/to/output.obj",
  "selection_only": true,
  "options": {
    "scale": 1.0,
    "include_materials": true
  }
}
```

### Benefits

- **No script knowledge needed**: REST API for common operations
- **Type safety**: Structured requests/responses
- **MCP-friendly**: Easy to integrate into MCP tools
- **Performance**: Built-in scripts are pre-validated

### Implementation

```cpp
void DzScriptServerPane::registerBuiltinScripts() {
    // Scene info
    registerScript("builtin:scene-info",
        "Get basic scene information",
        "return {scene_name: Scene.getFilename(), node_count: Scene.getNumNodes(), ...};",
        QStringList());

    // Selection
    registerScript("builtin:get-selection",
        "Get selected objects",
        "var sel = Scene.getSelectedNodeList(); return sel.map(...);",
        QStringList());

    // ... more built-in scripts
}
```

---

## Phase 3: Enhanced Response Formats

### Problem

Current responses return raw QVariant which loses type information:

```json
{
  "result": [123, 456, 789]  // What do these numbers mean?
}
```

### Solution: Structured Response Types

#### Define Common Response Schemas

**Node Object:**
```json
{
  "name": "Genesis 9",
  "type": "DzFigure",
  "id": "uuid-string",
  "visible": true,
  "locked": false,
  "position": {"x": 0, "y": 0, "z": 0},
  "rotation": {"x": 0, "y": 0, "z": 0},
  "scale": {"x": 1, "y": 1, "z": 1}
}
```

**Property Object:**
```json
{
  "name": "Translate X",
  "value": 0.0,
  "min": -1000.0,
  "max": 1000.0,
  "type": "float",
  "animated": false
}
```

#### Script Annotations

Allow scripts to declare return type:

```javascript
// @returns {NodeInfo[]}
var objs = Scene.getSelectedNodeList();
return objs.map(function(n) {
  return {
    name: n.name,
    type: n.className(),
    // ...
  };
});
```

#### Response Metadata

Add type hints to responses:

```json
{
  "success": true,
  "result": [...],
  "result_type": "NodeInfo[]",
  "result_schema": "https://daz3d.com/schemas/NodeInfo.json",
  "output": [],
  "error": null
}
```

---

## Phase 4: Batch Operations

### Concept

Execute multiple operations in a single request.

### POST /batch

**Request:**
```json
{
  "operations": [
    {
      "id": "op1",
      "script_id": "get-selected-objects"
    },
    {
      "id": "op2",
      "script_id": "get-scene-info"
    },
    {
      "id": "op3",
      "script": "return Scene.getNumNodes();"
    }
  ],
  "atomic": false
}
```

**Response:**
```json
{
  "results": [
    {
      "id": "op1",
      "success": true,
      "result": [...]
    },
    {
      "id": "op2",
      "success": true,
      "result": {...}
    },
    {
      "id": "op3",
      "success": true,
      "result": 47
    }
  ]
}
```

**atomic: true** - All operations succeed or all fail (transaction).

### Benefits

- **Performance**: One round-trip for multiple operations
- **Consistency**: Atomic operations guarantee consistent state
- **Convenience**: Build complex workflows

---

## Phase 5: Script Templates

### Concept

Scripts with parameter placeholders.

### POST /scripts/register (with template)

**Request:**
```json
{
  "name": "set-property",
  "description": "Set a property value on an object",
  "template": true,
  "script": "var node = Scene.findNodeByLabel('{{nodeName}}'); node.setProperty('{{propertyName}}', {{value}});",
  "parameters": ["nodeName", "propertyName", "value"]
}
```

### POST /scripts/set-property/execute

**Request:**
```json
{
  "args": {
    "nodeName": "Genesis 9",
    "propertyName": "Translate X",
    "value": 100.0
  }
}
```

Server substitutes `{{nodeName}}` → `"Genesis 9"` before execution.

### Benefits

- **Reusability**: Generic scripts with parameters
- **Safety**: Parameter validation before substitution
- **Clarity**: Explicit parameters vs. args object

---

## Phase 6: Async Operations & Streaming

### Problem

Long-running operations (rendering, export) block HTTP threads.

### Solution: Async Job Queue

#### POST /execute (with async flag)

**Request:**
```json
{
  "script": "/* long-running operation */",
  "async": true
}
```

**Response (immediate):**
```json
{
  "job_id": "job-abc123",
  "status": "queued",
  "created_at": "2026-03-20T14:23:45Z"
}
```

#### GET /jobs/{id}

**Response:**
```json
{
  "job_id": "job-abc123",
  "status": "running",
  "progress": 0.45,
  "created_at": "2026-03-20T14:23:45Z",
  "started_at": "2026-03-20T14:23:46Z"
}
```

#### GET /jobs/{id}/result

**Response:**
```json
{
  "job_id": "job-abc123",
  "status": "completed",
  "result": {...},
  "output": [],
  "error": null,
  "duration_ms": 45230
}
```

### WebSocket Support

For real-time progress:

```javascript
ws://localhost:18811/jobs/{id}/stream

// Messages:
{"type": "progress", "value": 0.25, "message": "Processing textures..."}
{"type": "progress", "value": 0.50, "message": "Rendering frame 1..."}
{"type": "complete", "result": {...}}
```

---

## Recommended Implementation Order

### Phase 1 (Immediate Value) - Script Registry
**Effort:** Medium
**Value:** High
**Dependencies:** None

Implement:
- POST /scripts/register
- GET /scripts
- POST /scripts/{id}/execute
- DELETE /scripts/{id}

This alone provides huge value for MCP servers:
```python
# MCP server setup
client.register_script("get-selection", script_text)

# Later, repeatedly:
result = client.execute_script("get-selection")
```

### Phase 2 (MCP Convenience) - Built-in Operations
**Effort:** Medium
**Value:** High
**Dependencies:** Phase 1

Implement 5-10 most common operations:
- Scene info
- Selection management
- Object queries
- Basic manipulation

### Phase 3 (Better DX) - Enhanced Responses
**Effort:** Low-Medium
**Value:** Medium
**Dependencies:** None

Add structured response types and metadata.

### Phase 4 (Optimization) - Batch Operations
**Effort:** Medium
**Value:** Medium
**Dependencies:** Phase 1

Useful for complex workflows.

### Phase 5 (Advanced) - Templates
**Effort:** Low
**Value:** Low-Medium
**Dependencies:** Phase 1

Nice-to-have, not essential.

### Phase 6 (Complex) - Async/Streaming
**Effort:** High
**Value:** Medium
**Dependencies:** All above

Only if long-running operations are common.

---

## Architecture Decisions

### 1. Script Storage

**Recommendation:** Store in plugin, expose via API

```cpp
// Persistent storage
void DzScriptServerPane::saveScriptRegistry() {
    QFile file("~/.daz3d/dazscriptserver_scripts.json");
    // Write m_registeredScripts to JSON
}

void DzScriptServerPane::loadScriptRegistry() {
    // Load from JSON on startup
}
```

**Alternative:** MCP-side caching is still possible and complementary.

### 2. Built-in vs. User Scripts

**Recommendation:** Namespace separation

- `builtin:scene-info` - Cannot be deleted
- `user:my-script` - User-registered
- `system:import-preset` - System scripts

### 3. Security

**Considerations:**
- Validate script IDs (no path traversal)
- Limit registry size (max 100 scripts?)
- Rate-limit registration
- Optional: Require auth for registration

---

## MCP Server Integration Example

With Phase 1 implemented:

```python
# MCP Server (one-time setup)
from daz_script_client import DazScriptClient

client = DazScriptClient("http://localhost:18811", token="...")

# Register commonly used scripts
client.register_script(
    name="get-figure-morphs",
    script="""
    var fig = Scene.getSelectedNode(0);
    var morphs = fig.getModifierList();
    return morphs.map(function(m) {
        return {name: m.name, value: m.getValue()};
    });
    """
)

# Later, use repeatedly without resending script
@mcp_tool("daz_get_morphs")
def get_morphs():
    return client.execute_script("get-figure-morphs")
```

**Benefit:** Script sent once, executed many times.

---

## Summary & Recommendations

### Immediate Actions (v1.2.0)

Implement **Phase 1: Script Registry**
- Highest value/effort ratio
- Enables efficient MCP integration
- Foundation for future features
- ~300-400 lines of code

### Short Term (v1.3.0)

Add **Phase 2: Built-in Operations**
- Preregister 5-10 common operations
- Document in API reference
- Makes server immediately useful without script knowledge

### Medium Term (v1.4.0)

Add **Phase 3: Enhanced Responses** and **Phase 4: Batch Operations**
- Better developer experience
- Performance optimization

### Long Term (v2.0.0)

Consider **Phase 6: Async/Streaming** if use cases emerge.

---

## Conclusion

**Where should functionality live?**
→ **Plugin provides script registry/library primitives, MCP servers use them for convenience**

**Most valuable enhancement?**
→ **Script registry (Phase 1) - enables caching without coupling to specific use cases**

**MCP or Plugin?**
→ **Both:** Plugin provides efficient execution layer, MCP provides high-level abstractions

This hybrid approach gives maximum flexibility while optimizing network efficiency.
