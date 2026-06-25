# MCP Server Evaluation for DazScriptServer

## Executive Summary

This repository provides a **DAZ Studio plugin** that embeds an HTTP server enabling remote execution of DazScript code. An **MCP (Model Context Protocol) server** would be an ideal abstraction layer to expose these capabilities to LLMs, enabling users to create, manipulate, and render scenes in DAZ Studio using natural language.

---

## Current Architecture

**DazScriptServer provides:**
- HTTP REST API (default: `127.0.0.1:18811`)
- Endpoints for script execution (`/execute`, `/execute/async`)
- Script registry for reusable scripts
- Async request management
- Server-Sent Events (SSE) for real-time scene updates
- Authentication via secure tokens
- Python SDK (`dazpy`) that wraps the HTTP API

**Key capabilities:**
- Scene graph manipulation (nodes, skeletons, bones)
- Morph/property control (expressions, body shapes)
- Material and texture management
- Camera and lighting control
- Animation and timeline operations
- Rendering (sync and async)
- Geometry access (vertices, faces, normals, UVs)
- Real-time scene event monitoring

---

## Proposed MCP Server Architecture

### High-Level Design

```
┌─────────────────┐
│   LLM Client    │
│  (Claude Code)  │
└────────┬────────┘
         │ MCP Protocol
         ▼
┌─────────────────────┐
│   MCP Server        │
│  (daz-mcp-server)   │
│                     │
│  - Tool Definitions │
│  - Auth Management  │
│  - Error Handling   │
│  - Type Conversion  │
└─────────┬───────────┘
          │ HTTP/REST
          ▼
┌─────────────────────┐
│  DazScriptServer    │
│  (Plugin in DAZ)    │
│                     │
│  - Script Execution │
│  - Scene Management │
│  - Rendering Engine │
└─────────────────────┘
```

---

## MCP Tool Categories

### 1. **Scene Management Tools**

These tools manage the overall scene state:

| Tool Name | Description | Maps to Endpoint/SDK |
|-----------|-------------|----------------------|
| `daz_get_scene_info` | Get scene overview (node count, filename, needs save) | `DazScene.num_nodes()`, `.filename()`, `.needs_save()` |
| `daz_load_scene` | Load a .duf scene file | `DazScene.load(path)` |
| `daz_save_scene` | Save current scene | `DazScene.save(path)` |
| `daz_clear_scene` | Clear all scene content | `Scene.clear()` via execute |
| `daz_list_nodes` | List all nodes with types | `DazScene.nodes()` |
| `daz_get_node_tree` | Get hierarchical scene tree | `DazScene.node_tree()` |

**Example tool definition:**
```json
{
  "name": "daz_load_scene",
  "description": "Load a DAZ Studio scene file (.duf) into the current session",
  "input_schema": {
    "type": "object",
    "properties": {
      "file_path": {
        "type": "string",
        "description": "Absolute path to the .duf scene file"
      }
    },
    "required": ["file_path"]
  }
}
```

---

### 2. **Figure & Skeleton Tools**

Control characters and their bones:

| Tool Name | Description | Maps to SDK |
|-----------|-------------|-------------|
| `daz_find_figure` | Find a figure/character by label | `DazScene.find_skeleton_by_label()` |
| `daz_list_figures` | List all figures in scene | `DazScene.skeletons()` |
| `daz_list_bones` | List all bones in a figure | `DazSkeleton.bones()` |
| `daz_get_bone_rotation` | Get bone rotation (local Euler) | `DazBone.local_rotation()` |
| `daz_set_bone_rotation` | Set bone rotation | `DazBone.set_local_rotation(x, y, z)` |
| `daz_pose_figure` | Apply multiple bone rotations at once | Batch operation with undo |

**Example:**
```json
{
  "name": "daz_set_bone_rotation",
  "description": "Set the local rotation of a bone in a figure",
  "input_schema": {
    "type": "object",
    "properties": {
      "figure_label": {"type": "string", "description": "Figure label (e.g., 'Genesis 9')"},
      "bone_name": {"type": "string", "description": "Bone internal name (e.g., 'lShldrBend')"},
      "x_degrees": {"type": "number", "description": "X-axis rotation in degrees"},
      "y_degrees": {"type": "number", "description": "Y-axis rotation in degrees"},
      "z_degrees": {"type": "number", "description": "Z-axis rotation in degrees"}
    },
    "required": ["figure_label", "bone_name", "x_degrees", "y_degrees", "z_degrees"]
  }
}
```

---

### 3. **Morph & Expression Tools**

Control facial expressions and body shapes:

| Tool Name | Description | Maps to SDK |
|-----------|-------------|-------------|
| `daz_list_morphs` | List all morphs on a figure | `DazSkeleton.morphs()` |
| `daz_search_morphs` | Search morphs by name pattern | Filter `morphs()` results |
| `daz_get_morph_value` | Get current morph value | `DazMorph.value()` |
| `daz_set_morph_value` | Set morph value (0.0-1.0) | `DazMorph.set_value()` |
| `daz_set_expression` | Apply facial expression preset | Multiple morph operations |

**Example:**
```json
{
  "name": "daz_set_expression",
  "description": "Apply a facial expression to a figure using common morph names",
  "input_schema": {
    "type": "object",
    "properties": {
      "figure_label": {"type": "string"},
      "expression": {
        "type": "string",
        "enum": ["smile", "frown", "surprise", "angry", "neutral"],
        "description": "Predefined expression to apply"
      },
      "intensity": {
        "type": "number",
        "minimum": 0.0,
        "maximum": 1.0,
        "default": 1.0
      }
    },
    "required": ["figure_label", "expression"]
  }
}
```

---

### 4. **Object Manipulation Tools**

Transform and manage scene objects:

| Tool Name | Description | Maps to SDK |
|-----------|-------------|-------------|
| `daz_add_primitive` | Add primitive shape (cube, sphere, etc.) | DazScript `Scene.addNode()` |
| `daz_load_asset` | Load asset from content library | DazScript `AssetMgr.openFile()` |
| `daz_delete_node` | Remove node from scene | DazScript `Scene.removeNode()` |
| `daz_set_position` | Set node world position | `DazNode.set_position(x, y, z)` |
| `daz_set_rotation` | Set node world rotation | `DazNode.set_rotation(x, y, z)` |
| `daz_set_scale` | Set node scale | `DazNode.set_general_scale()` |
| `daz_get_transform` | Get node transform | `DazNode.position()`, `.rotation()`, `.scale()` |

---

### 5. **Material & Texture Tools**

| Tool Name | Description | Maps to SDK |
|-----------|-------------|-------------|
| `daz_list_materials` | List materials on a node | `DazNode.materials()` |
| `daz_get_material_color` | Get diffuse color | `DazMaterial.diffuse_color()` |
| `daz_set_material_color` | Set diffuse color | `DazMaterial.set_diffuse_color(r, g, b)` |
| `daz_set_material_property` | Set generic material property | `DazMaterial.set_property()` |

---

### 6. **Camera & Lighting Tools**

| Tool Name | Description | Maps to SDK |
|-----------|-------------|-------------|
| `daz_list_cameras` | List all cameras | `DazScene.cameras()` |
| `daz_list_lights` | List all lights | `DazScene.lights()` |
| `daz_find_camera` | Find camera by label | `DazScene.find_camera_by_label()` |
| `daz_set_camera_position` | Position camera | `DazCamera.set_position()` + `.aim_at()` |
| `daz_add_light` | Add new light to scene | DazScript light creation |
| `daz_set_light_color` | Set light color | `DazLight.set_color(r, g, b)` |
| `daz_configure_camera` | Set camera properties (focal length, etc.) | `DazCamera` properties |

---

### 7. **Rendering Tools**

| Tool Name | Description | Maps to SDK |
|-----------|-------------|-------------|
| `daz_render` | Trigger a render (async) | `POST /render` or `dazpy.render()` |
| `daz_render_variants` | Batch render with variations | `POST /render/batch` or `render_variants()` |
| `daz_get_render_progress` | Poll render progress | `GET /render/:id/progress` (SSE) |
| `daz_cancel_render` | Cancel running render | `POST /render/:id/cancel` |
| `daz_set_render_settings` | Configure render options | DazScript `RenderOptions` |
| `daz_capture_viewport` | Quick viewport screenshot | `dazpy` viewport capture |

**Example:**
```json
{
  "name": "daz_render",
  "description": "Render the current scene to an image file",
  "input_schema": {
    "type": "object",
    "properties": {
      "output_path": {"type": "string", "description": "Absolute path for output image"},
      "width": {"type": "integer", "default": 1920},
      "height": {"type": "integer", "default": 1080},
      "camera": {"type": "string", "description": "Camera label to use (optional)"},
      "wait": {"type": "boolean", "default": true, "description": "Wait for completion"}
    },
    "required": ["output_path"]
  }
}
```

---

### 8. **Animation Tools**

| Tool Name | Description | Maps to SDK |
|-----------|-------------|-------------|
| `daz_set_frame` | Jump to specific frame | `DazScene.set_frame()` |
| `daz_get_frame` | Get current frame | `DazScene.frame()` |
| `daz_set_play_range` | Set animation range | `DazScene.set_play_range()` |
| `daz_capture_pose` | Snapshot current pose | `DazPose.capture()` |
| `daz_apply_pose` | Apply saved pose | `DazPose.apply()` |
| `daz_set_keyframe` | Set animation keyframe | `DazAnimation` methods |

---

### 9. **Query & Inspection Tools**

| Tool Name | Description | Maps to SDK |
|-----------|-------------|-------------|
| `daz_get_selection` | Get selected nodes | `DazScene.selected_nodes()` |
| `daz_select_node` | Select a node | `DazNode.select()` |
| `daz_get_property` | Get any node property | `DazNode.get_property()` |
| `daz_search_assets` | Search content library | DazScript `AssetMgr` queries |
| `daz_get_server_status` | Check server health | `GET /health` |

---

### 10. **Advanced/Utility Tools**

| Tool Name | Description | Maps to SDK |
|-----------|-------------|-------------|
| `daz_execute_script` | Execute arbitrary DazScript | `POST /execute` |
| `daz_batch_execute` | Execute multiple scripts in one call | `dazpy.Batch` |
| `daz_undo` | Undo last operation | `DazScene.undo_last()` |
| `daz_redo` | Redo operation | `DazScene.redo_last()` |
| `daz_subscribe_events` | Subscribe to scene events (SSE) | `GET /scene/events` |

---

## MCP Server Implementation Details

### Technology Stack

**Language:** Python 3.10+ (matches dazpy SDK)

**MCP Framework:** Use `mcp` Python package from Anthropic

**Dependencies:**
- `dazpy` (the existing Python SDK)
- `mcp` (MCP protocol implementation)
- `requests` (HTTP client, already required by dazpy)
- `typing` (type hints)

### Project Structure

```
daz-mcp-server/
├── src/
│   ├── __init__.py
│   ├── server.py              # Main MCP server
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── scene.py           # Scene management tools
│   │   ├── figure.py          # Figure/skeleton tools
│   │   ├── morph.py           # Morph/expression tools
│   │   ├── transform.py       # Object manipulation tools
│   │   ├── material.py        # Material tools
│   │   ├── camera_light.py    # Camera/lighting tools
│   │   ├── render.py          # Rendering tools
│   │   ├── animation.py       # Animation tools
│   │   └── utility.py         # Query/utility tools
│   ├── auth.py                # Token management
│   ├── errors.py              # Error handling/mapping
│   └── utils.py               # Helper functions
├── tests/
│   ├── test_scene_tools.py
│   ├── test_figure_tools.py
│   └── ...
├── examples/
│   ├── natural_language_scene.md    # Example LLM interactions
│   └── workflow_examples.py
├── pyproject.toml
├── README.md
└── .env.example
```

### Authentication Flow

1. **Token Discovery:**
   - Check environment variable `DAZ_SERVER_TOKEN`
   - Fall back to reading `~/.daz3d/dazscriptserver_token.txt`
   - Allow explicit token in MCP server config

2. **Connection Validation:**
   - On startup, check `/health` endpoint
   - Fail fast if DAZ Studio is not running
   - Provide clear error messages to LLM

### Error Handling

Map DazScriptServer errors to LLM-friendly messages:

```python
ERROR_MESSAGES = {
    "NodeNotFoundError": "The specified node/figure '{name}' does not exist in the scene. Use daz_list_nodes or daz_list_figures to see available options.",
    "ConnectionError": "Cannot connect to DAZ Studio. Please ensure DAZ Studio is running and the DazScriptServer plugin is started (Window → Panes → Daz Script Server).",
    "AuthenticationError": "Authentication failed. Check that the API token is correct in ~/.daz3d/dazscriptserver_token.txt",
    "ScriptRuntimeError": "DazScript execution failed: {error}. This usually means the operation is not valid for the current scene state."
}
```

### Type Conversion

**DazScript → Python → MCP:**
- Vec3 → `{"x": float, "y": float, "z": float}`
- Quat → `{"x": float, "y": float, "z": float, "w": float}`
- Colors → `{"r": int, "g": int, "b": int}` (0-255)
- Rotations → degrees (not radians)

### Async Operation Handling

For long-running operations (renders, heavy scripts):
1. Submit async request
2. Return immediately with `request_id`
3. Provide separate polling tool if needed
4. Or use `wait=true` for simpler flow

---

## Natural Language Workflow Examples

### Example 1: Create a Simple Scene

**User:** "Create a scene with Genesis 9, add a smile expression, and position the camera to frame their face"

**LLM Tool Calls:**
1. `daz_clear_scene()` - Start fresh
2. `daz_load_asset(asset_path="Genesis 9")` - Load character
3. `daz_find_figure(label="Genesis 9")` - Get figure reference
4. `daz_set_expression(figure_label="Genesis 9", expression="smile", intensity=0.8)`
5. `daz_list_cameras()` - Find default camera
6. `daz_set_camera_position(camera_label="Camera 1", x=0, y=150, z=120, look_at_y=150)`

### Example 2: Batch Render Variations

**User:** "Render the current scene with 3 different expressions: happy, sad, and surprised"

**LLM Tool Calls:**
1. `daz_get_scene_info()` - Confirm scene is ready
2. `daz_list_figures()` - Get figure to modify
3. `daz_render_variants(variants=[
     {"label": "happy", "morphs": {"PHMSmileOpen": 1.0}},
     {"label": "sad", "morphs": {"PHMFrownSimple": 0.8}},
     {"label": "surprised", "morphs": {"eCTRLEyesWide": 1.0}}
   ], output_dir="/renders")`

### Example 3: Pose a Character

**User:** "Make the character wave with their right hand"

**LLM Tool Calls:**
1. `daz_find_figure(label="Genesis 9")`
2. `daz_list_bones(figure_label="Genesis 9")` - Find arm bones
3. `daz_set_bone_rotation(figure_label="Genesis 9", bone_name="rShldrBend", x=0, y=0, z=-90)` - Raise arm
4. `daz_set_bone_rotation(figure_label="Genesis 9", bone_name="rForeArm", x=0, y=0, z=-45)` - Bend elbow
5. `daz_set_bone_rotation(figure_label="Genesis 9", bone_name="rHand", x=0, y=0, z=-30)` - Wave

---

## Implementation Priorities

### Phase 1: Core MVP (Highest Priority)
- Scene management tools (load, save, clear, list nodes)
- Figure tools (find, list, basic pose)
- Morph tools (list, get, set - for expressions)
- Basic rendering (single render with default settings)
- Camera positioning
- Authentication and error handling

### Phase 2: Enhanced Control
- Advanced bone manipulation (full pose control)
- Material/texture tools
- Lighting tools
- Animation/timeline tools
- Batch rendering with variants

### Phase 3: Advanced Features
- Asset library search
- Geometry inspection
- Scene event monitoring (SSE integration)
- Custom script execution for edge cases
- Undo/redo support

---

## Benefits of MCP Abstraction

1. **Natural Language Interface**: Users describe intent, LLM translates to tool calls
2. **Type Safety**: Strong typing prevents invalid parameter combinations
3. **Error Recovery**: LLM can interpret errors and retry with corrections
4. **Discoverability**: Tools self-document capabilities via schema
5. **Composability**: Complex workflows built from simple tool chains
6. **Abstraction**: Hide DazScript complexity from end users
7. **Extensibility**: Easy to add new tools without changing server

---

## Challenges & Considerations

### 1. **Asset Path Discovery**
- DAZ Studio content library paths are user-specific
- MCP server needs strategy for asset discovery
- Options:
  - Provide `daz_search_assets()` tool
  - Maintain common asset name → path mapping
  - Let users provide full paths explicitly

### 2. **State Management**
- DAZ Studio is stateful (one active scene)
- Multiple concurrent LLM requests could conflict
- Consider request queuing or state locks

### 3. **Complex Poses**
- Natural language pose descriptions are ambiguous
- May need iterative refinement workflow
- Consider preset pose library (T-pose, A-pose, sitting, etc.)

### 4. **Rendering Time**
- High-quality renders can take minutes/hours
- Need async handling with progress updates
- Consider viewport capture for quick previews

### 5. **Figure-Specific Morphs**
- Morph names differ between Genesis 8, Genesis 9, etc.
- Tools should detect figure type and adapt
- Provide fallback error messages

---

## Recommended Next Steps

1. **Prototype Core Tools** (Week 1-2)
   - Implement Phase 1 tools
   - Test with simple LLM workflows
   - Validate error handling

2. **Documentation** (Week 2)
   - Write tool usage guide for LLMs
   - Create example prompts
   - Document common workflows

3. **Testing** (Week 3)
   - Unit tests for each tool
   - Integration tests with live DAZ Studio
   - LLM interaction testing (prompt engineering)

4. **Refinement** (Week 4)
   - Add Phase 2 tools based on usage patterns
   - Optimize tool granularity (too many small tools vs few large ones)
   - Improve error messages based on real LLM interactions

---

## Conclusion

An MCP server for DazScriptServer would provide a **powerful natural language interface** to DAZ Studio's 3D scene creation capabilities. The existing HTTP API and `dazpy` SDK provide a solid foundation, and the MCP abstraction layer would enable intuitive, conversational workflows for:

- Character posing and expression control
- Scene composition and lighting
- Material/texture management
- Batch rendering and variations
- Animation creation

The key to success is **thoughtful tool design** that balances granularity (specific operations) with usability (not overwhelming the LLM with 100+ tools). Starting with a focused MVP covering scene management, figure control, and basic rendering will validate the approach and inform further development.
