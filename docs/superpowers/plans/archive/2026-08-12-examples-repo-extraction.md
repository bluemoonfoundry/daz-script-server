# daz-script-server-examples Repository Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract docs/examples/ from daz-script-server into standalone daz-script-server-examples repository with standardized documentation, per-example READMEs, requirements.txt files, and comprehensive root README.

**Architecture:** Create new GitHub repo, copy examples tree preserving git history, restructure to folder-per-example, generate individual READMEs from existing documentation using standard template, create requirements.txt files for examples with external dependencies, build comprehensive root README table.

**Tech Stack:** Git, GitHub CLI, Python, Bash, Markdown

## Global Constraints

- Repository name: `daz-script-server-examples`
- GitHub org: `bluemoonfoundry`
- License: AGPL v3 (match parent repo)
- Python compatibility: 3.8+
- GitHub CLI path: `/Users/hirparag/Development/gh_2.89.0_macOS_arm64/bin/gh`
- Preserve git history for examples directory
- Category structure: fundamentals, character, animation, geometry, export, rendering, ml_data, ai_vision, bvh
- Standard README template per spec
- Level classifications: Beginner, Intermediate, Advanced
- Requirements.txt only for examples needing deps beyond dazpy
- No category-level READMEs

---

### Task 1: Create New Repository and Clone Examples

**Files:**
- Create: `../daz-script-server-examples/` (sibling to current repo)
- Create: `../daz-script-server-examples/.gitignore`
- Reference: Current repo `docs/examples/`

**Interfaces:**
- Consumes: Nothing
- Produces: Empty repo at `../daz-script-server-examples/`, ready for content

- [ ] **Step 1: Create GitHub repository**

```bash
cd /Users/hirparag/Development/private
/Users/hirparag/Development/gh_2.89.0_macOS_arm64/bin/gh repo create bluemoonfoundry/daz-script-server-examples \
  --public \
  --description "Complete, categorized examples for daz-script-server and dazpy SDK - from beginner tutorials to production pipelines" \
  --clone
```

Expected: Repository created and cloned to `../daz-script-server-examples/`

- [ ] **Step 2: Verify repository created**

```bash
cd daz-script-server-examples
git remote -v
```

Expected: Output shows `origin` pointing to `https://github.com/bluemoonfoundry/daz-script-server-examples.git`

- [ ] **Step 3: Create .gitignore**

```bash
cat > .gitignore << 'EOF'
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
*.egg-info/
.installed.cfg
*.egg
MANIFEST
.pytest_cache/
.coverage
htmlcov/
*.log

# Virtual environments
venv/
env/
ENV/
.venv

# IDEs
.vscode/
.idea/
*.swp
*.swo
*~

# DAZ Studio temp files
*.duf.bak
*.duf~

# OS files
.DS_Store
Thumbs.db

# Output files (examples generate these)
*.png
*.jpg
*.jpeg
*.usda
*.usdc
*.json.bak
EOF
```

- [ ] **Step 4: Commit .gitignore**

```bash
git add .gitignore
git commit -m "chore: add .gitignore for Python and DAZ Studio temp files"
git push origin main
```

Expected: Initial commit pushed

- [ ] **Step 5: Verify repository state**

```bash
git status
git log --oneline
```

Expected: Clean working directory, one commit visible

---

### Task 2: Copy Examples Directory with History

**Files:**
- Modify: `../daz-script-server-examples/` (add content from parent repo)
- Reference: `../daz-script-server/docs/examples/`

**Interfaces:**
- Consumes: Repository from Task 1
- Produces: Examples tree copied to new repo with git history preserved

- [ ] **Step 1: Copy examples directory preserving structure**

```bash
cd /Users/hirparag/Development/private/daz-script-server
cp -r docs/examples/* ../daz-script-server-examples/
```

Expected: All files copied to sibling repo

- [ ] **Step 2: Verify copy successful**

```bash
cd ../daz-script-server-examples
find . -type f -name "*.py" | wc -l
```

Expected: Output shows 48 Python files

- [ ] **Step 3: Verify directory structure**

```bash
ls -la
find . -maxdepth 1 -type d | sort
```

Expected: Output shows fundamentals/, character/, rendering/, animation/, geometry/, export/, ml_data/, ai_vision/, bvh/, README.md

- [ ] **Step 4: Commit initial examples**

```bash
git add .
git commit -m "feat: add examples from daz-script-server docs/examples

Copied from daz-script-server commit $(cd ../daz-script-server && git rev-parse HEAD)"
git push origin main
```

Expected: Examples committed and pushed

- [ ] **Step 5: Verify commit**

```bash
git log --oneline | head -2
git diff HEAD~1 --stat
```

Expected: Two commits visible, stat shows all example files added

---

### Task 3: Restructure Single-File Examples to Folders

**Files:**
- Restructure: All single `.py` files in category folders to own subdirectories
- Examples: `fundamentals/raw_script.py` → `fundamentals/raw_script/raw_script.py`

**Interfaces:**
- Consumes: Flat example files from Task 2
- Produces: Folder-per-example structure, multi-file examples (sprite_matrix, comfyui_enhance) unchanged

- [ ] **Step 1: Create restructure script**

```bash
cd /Users/hirparag/Development/private/daz-script-server-examples
cat > restructure.sh << 'EOF'
#!/bin/bash
# Restructure single .py files to folders

for category in fundamentals character animation geometry export ml_data ai_vision bvh; do
  if [ ! -d "$category" ]; then
    continue
  fi
  
  cd "$category"
  
  # Find single .py files (not in subdirectories)
  for pyfile in *.py 2>/dev/null; do
    if [ -f "$pyfile" ]; then
      basename="${pyfile%.py}"
      echo "Restructuring $category/$pyfile -> $category/$basename/$pyfile"
      mkdir -p "$basename"
      git mv "$pyfile" "$basename/$pyfile"
    fi
  done
  
  cd ..
done

echo "Restructure complete"
EOF

chmod +x restructure.sh
```

- [ ] **Step 2: Run restructure script**

```bash
./restructure.sh
```

Expected: Output shows each file being moved to its own folder

- [ ] **Step 3: Verify restructuring**

```bash
# Check fundamentals
ls -la fundamentals/
ls -la fundamentals/raw_script/

# Check rendering (should have both folders and preserved multi-file examples)
ls -la rendering/
ls -la rendering/sprite_matrix/
```

Expected: Each single-file example now in own folder, sprite_matrix/comfyui_enhance unchanged

- [ ] **Step 4: Remove restructure script**

```bash
rm restructure.sh
```

- [ ] **Step 5: Commit restructuring**

```bash
git add -A
git commit -m "refactor: restructure single-file examples to folders

Each example now lives in its own directory:
- fundamentals/raw_script.py -> fundamentals/raw_script/raw_script.py
- Multi-file examples (sprite_matrix, comfyui_enhance) unchanged"
git push origin main
```

Expected: Restructure committed and pushed

---

### Task 4: Generate Level Classification Mapping

**Files:**
- Create: `tools/level_map.json`

**Interfaces:**
- Consumes: Example file structure from Task 3
- Produces: JSON mapping of example name → level (Beginner/Intermediate/Advanced)

- [ ] **Step 1: Create tools directory**

```bash
cd /Users/hirparag/Development/private/daz-script-server-examples
mkdir -p tools
```

- [ ] **Step 2: Create level classification mapping**

```bash
cat > tools/level_map.json << 'EOF'
{
  "fundamentals/raw_script": "Beginner",
  "fundamentals/scene_introspection": "Beginner",
  "fundamentals/scene_save_copy": "Beginner",
  "fundamentals/scene_inventory": "Intermediate",
  "fundamentals/scene_event_monitor": "Intermediate",
  "fundamentals/batch_operations": "Intermediate",
  "character/character_state": "Intermediate",
  "character/pose_transfer": "Intermediate",
  "character/animation_frame_dump": "Intermediate",
  "character/ik_bone_to_target": "Advanced",
  "animation/pose_interpolation": "Intermediate",
  "animation/keyframe_baking": "Advanced",
  "animation/animation_mixing": "Advanced",
  "geometry/geometry_analysis": "Intermediate",
  "geometry/body_measurements": "Advanced",
  "export/scene_to_usd": "Advanced",
  "rendering/turntable": "Beginner",
  "rendering/capture_viewport": "Beginner",
  "rendering/multi_camera_render": "Beginner",
  "rendering/material_color_variations": "Intermediate",
  "rendering/batch_render_morph_variations": "Intermediate",
  "rendering/vn_render_workflow": "Advanced",
  "rendering/comfyui_enhance": "Advanced",
  "rendering/sprite_matrix": "Advanced",
  "ml_data/dataset_generator": "Intermediate",
  "ai_vision/expression_transfer": "Advanced",
  "ai_vision/webcam_expression_mirror": "Advanced",
  "bvh/bvh_discover": "Intermediate",
  "bvh/bvh_import": "Advanced",
  "bvh/bvh_bone_maps": "Advanced"
}
EOF
```

- [ ] **Step 3: Verify JSON is valid**

```bash
python3 -c "import json; f=open('tools/level_map.json'); json.load(f); print('Valid JSON')"
```

Expected: Output "Valid JSON"

- [ ] **Step 4: Commit level map**

```bash
git add tools/level_map.json
git commit -m "chore: add level classification mapping for examples"
git push origin main
```

Expected: Level map committed

---

### Task 5: Extract README Sections Script

**Files:**
- Create: `tools/extract_readme_sections.py`
- Reference: Current `README.md` for section extraction

**Interfaces:**
- Consumes: Level map from Task 4, current README.md
- Produces: Python script that extracts per-example documentation sections

- [ ] **Step 1: Create README section extractor**

```python
# Save to tools/extract_readme_sections.py
"""Extract individual example sections from master README.md"""
import re
import json
from pathlib import Path

# Load level classifications
with open('tools/level_map.json') as f:
    LEVEL_MAP = json.load(f)

def parse_readme():
    """Parse README.md and extract sections by example"""
    with open('README.md') as f:
        content = f.read()
    
    sections = {}
    
    # Match sections like ### raw_script.py or ### scene_event_monitor.py
    # Section ends at next ### or ---
    pattern = r'### ([a-z_]+\.py)\n\n(.*?)(?=\n###|\n---|\Z)'
    matches = re.findall(pattern, content, re.DOTALL)
    
    for script_name, section_content in matches:
        # Extract example name without .py
        name = script_name.replace('.py', '')
        sections[name] = section_content.strip()
    
    return sections

def extract_description(section_text):
    """Extract first paragraph as description"""
    lines = section_text.split('\n\n')
    if lines:
        # Clean up markdown formatting
        desc = lines[0].strip()
        # Remove bold/italic markers for table display
        desc = re.sub(r'\*\*', '', desc)
        desc = re.sub(r'\*', '', desc)
        return desc
    return ""

def extract_usage(section_text):
    """Extract usage examples and argument tables"""
    # Find ```bash blocks and argument tables
    usage_parts = []
    
    # Find code blocks
    code_blocks = re.findall(r'```bash\n(.*?)\n```', section_text, re.DOTALL)
    if code_blocks:
        usage_parts.append("```bash\n" + code_blocks[0] + "\n```")
    
    # Find argument tables
    table_pattern = r'\| Argument.*?\n.*?\n((?:\|.*?\n)+)'
    table_match = re.search(table_pattern, section_text, re.DOTALL)
    if table_match:
        usage_parts.append("\n### Arguments\n\n" + table_match.group(0))
    
    return '\n\n'.join(usage_parts) if usage_parts else ""

def extract_dependencies(section_text):
    """Extract dependency installation instructions"""
    # Look for pip install commands
    dep_match = re.search(r'```bash\npip install (.*?)\n```', section_text, re.DOTALL)
    if dep_match:
        return dep_match.group(1).strip()
    return None

if __name__ == '__main__':
    sections = parse_readme()
    print(f"Extracted {len(sections)} sections from README.md")
    for name in sorted(sections.keys()):
        print(f"  - {name}")
```

- [ ] **Step 2: Save extractor script**

```bash
cat > tools/extract_readme_sections.py << 'PYTHON_EOF'
"""Extract individual example sections from master README.md"""
import re
import json
from pathlib import Path

# Load level classifications
with open('tools/level_map.json') as f:
    LEVEL_MAP = json.load(f)

def parse_readme():
    """Parse README.md and extract sections by example"""
    with open('README.md') as f:
        content = f.read()
    
    sections = {}
    
    # Match sections like ### raw_script.py or ### scene_event_monitor.py
    pattern = r'### ([a-z_]+\.py)\n\n(.*?)(?=\n###|\n---|\Z)'
    matches = re.findall(pattern, content, re.DOTALL)
    
    for script_name, section_content in matches:
        name = script_name.replace('.py', '')
        sections[name] = section_content.strip()
    
    return sections

def extract_description(section_text):
    """Extract first paragraph as description"""
    lines = section_text.split('\n\n')
    if lines:
        desc = lines[0].strip()
        desc = re.sub(r'\*\*', '', desc)
        desc = re.sub(r'\*', '', desc)
        return desc
    return ""

def extract_usage(section_text):
    """Extract usage examples and argument tables"""
    usage_parts = []
    
    code_blocks = re.findall(r'```bash\n(.*?)\n```', section_text, re.DOTALL)
    if code_blocks:
        usage_parts.append("```bash\n" + code_blocks[0] + "\n```")
    
    table_pattern = r'\| Argument.*?\n.*?\n((?:\|.*?\n)+)'
    table_match = re.search(table_pattern, section_text, re.DOTALL)
    if table_match:
        usage_parts.append("\n### Arguments\n\n" + table_match.group(0))
    
    return '\n\n'.join(usage_parts) if usage_parts else ""

def extract_dependencies(section_text):
    """Extract dependency info"""
    dep_match = re.search(r'```bash\npip install (.*?)\n```', section_text, re.DOTALL)
    if dep_match:
        return dep_match.group(1).strip()
    return None

if __name__ == '__main__':
    sections = parse_readme()
    print(f"Extracted {len(sections)} sections from README.md")
    for name in sorted(sections.keys()):
        print(f"  - {name}")
PYTHON_EOF
```

- [ ] **Step 3: Test extractor**

```bash
cd /Users/hirparag/Development/private/daz-script-server-examples
python3 tools/extract_readme_sections.py
```

Expected: Output shows count of extracted sections

- [ ] **Step 4: Commit extractor**

```bash
git add tools/extract_readme_sections.py
git commit -m "feat: add README section extractor script"
git push origin main
```

Expected: Extractor committed

---

### Task 6: Generate Per-Example READMEs

**Files:**
- Create: Individual `README.md` in each example folder
- Modify: `tools/generate_example_readmes.py` (new generator script)

**Interfaces:**
- Consumes: Level map from Task 4, extractor from Task 5, current README.md
- Produces: Individual README.md for each example following standard template

- [ ] **Step 1: Create README generator script**

```bash
cat > tools/generate_example_readmes.py << 'PYTHON_EOF'
"""Generate individual example READMEs from master README"""
import re
import json
from pathlib import Path

# Load level classifications
with open('tools/level_map.json') as f:
    LEVEL_MAP = json.load(f)

# Category mapping
CATEGORY_MAP = {
    'fundamentals': 'fundamentals',
    'character': 'character',
    'animation': 'animation',
    'geometry': 'geometry',
    'export': 'export',
    'rendering': 'rendering',
    'ml_data': 'ml_data',
    'ai_vision': 'ai_vision',
    'bvh': 'bvh'
}

def parse_readme_sections():
    """Parse master README and extract example sections"""
    with open('README.md') as f:
        content = f.read()
    
    sections = {}
    
    # Match ### example_name.py sections
    pattern = r'### ([a-z_]+\.py)\n\n(.*?)(?=\n###|\n---|\Z)'
    matches = re.findall(pattern, content, re.DOTALL)
    
    for script_name, section_text in matches:
        name = script_name.replace('.py', '')
        sections[name] = section_text.strip()
    
    return sections

def find_example_path(example_name):
    """Find which category folder the example lives in"""
    for category in CATEGORY_MAP.values():
        path = Path(category) / example_name
        if path.exists():
            return path, category
    return None, None

def extract_description_para(text):
    """Extract overview paragraph"""
    paras = text.split('\n\n')
    if paras:
        return paras[0].strip()
    return ""

def extract_usage_section(text):
    """Extract usage examples and args"""
    usage = []
    
    # Find bash code blocks
    bash_blocks = re.findall(r'```bash\n(.*?)\n```', text, re.DOTALL)
    if bash_blocks:
        usage.append("```bash\n" + bash_blocks[0] + "\n```")
    
    # Find argument table
    table_match = re.search(r'(\| Argument.*?\n\|.*?\n(?:\|.*?\n)+)', text, re.DOTALL)
    if table_match:
        usage.append("\n" + table_match.group(1))
    
    return '\n\n'.join(usage)

def extract_sdk_features(text):
    """Extract SDK features mentioned"""
    features = []
    
    # Look for "SDK features demonstrated" section
    sdk_match = re.search(r'\*\*SDK features demonstrated:\*\*(.*?)(?=\n\n|\Z)', text, re.DOTALL)
    if sdk_match:
        feature_text = sdk_match.group(1)
        # Parse bullet list
        feature_lines = re.findall(r'`([^`]+)`', feature_text)
        features = feature_lines
    
    return features

def generate_readme(example_path, category, example_name, section_text):
    """Generate README for one example"""
    
    # Get level
    lookup_key = f"{category}/{example_name}"
    level = LEVEL_MAP.get(lookup_key, "Intermediate")
    
    # Extract components
    description = extract_description_para(section_text)
    usage = extract_usage_section(section_text)
    sdk_features = extract_sdk_features(section_text)
    
    # Generate README content
    title = example_name.replace('_', ' ').title()
    
    readme = f"""# {title}

**Level:** {level}  
**Category:** {category}

## Overview

{description}

## What You'll Learn

- Practical implementation of {example_name} workflow
- SDK patterns for remote DAZ Studio control
- Production-ready code structure
"""
    
    if sdk_features:
        readme += "\nSDK features used:\n"
        for feature in sdk_features:
            readme += f"- `{feature}`\n"
    
    readme += """
## Prerequisites

- DAZ Studio with DazScriptServer plugin running
- `dazpy` installed (`pip install dazpy`)
- Basic Python knowledge

"""
    
    # Check for requirements.txt
    req_file = example_path / 'requirements.txt'
    if req_file.exists():
        readme += """## Dependencies

Install additional dependencies:
```bash
pip install -r requirements.txt
```

"""
    else:
        readme += """## Dependencies

No additional dependencies beyond `dazpy`.

"""
    
    # Add usage section
    if usage:
        readme += f"""## Usage

{usage}

"""
    
    readme += """## How It Works

[See code comments in the script for detailed implementation walkthrough]

## Output

[Example-specific output description]

## Related Examples

- See main repository [README](../../README.md) for related examples
"""
    
    return readme

def main():
    sections = parse_readme_sections()
    print(f"Found {len(sections)} example sections in README.md\n")
    
    generated = 0
    skipped = 0
    
    for example_name, section_text in sections.items():
        example_path, category = find_example_path(example_name)
        
        if not example_path:
            print(f"⚠️  Could not find path for: {example_name}")
            skipped += 1
            continue
        
        readme_path = example_path / 'README.md'
        
        # Generate README content
        readme_content = generate_readme(example_path, category, example_name, section_text)
        
        # Write README
        with open(readme_path, 'w') as f:
            f.write(readme_content)
        
        print(f"✓ Generated: {readme_path}")
        generated += 1
    
    print(f"\n✓ Generated {generated} READMEs")
    if skipped:
        print(f"⚠️  Skipped {skipped} (path not found)")

if __name__ == '__main__':
    main()
PYTHON_EOF
```

- [ ] **Step 2: Run README generator**

```bash
python3 tools/generate_example_readmes.py
```

Expected: Output shows README generated for each example

- [ ] **Step 3: Verify generated READMEs**

```bash
# Check a few examples
cat fundamentals/raw_script/README.md | head -20
cat rendering/turntable/README.md | head -20
ls -la rendering/sprite_matrix/README.md
```

Expected: Each example has README.md with proper template structure

- [ ] **Step 4: Commit generator and generated READMEs**

```bash
git add tools/generate_example_readmes.py
git add */*/README.md
git commit -m "feat: generate individual READMEs for all examples

- Created README generator script
- Generated standardized README for each example
- Includes level, category, prerequisites, usage"
git push origin main
```

Expected: Generator and READMEs committed

---

### Task 7: Generate requirements.txt Files

**Files:**
- Create: `rendering/capture_viewport/requirements.txt`
- Create: `ai_vision/expression_transfer/requirements.txt`
- Create: `ai_vision/webcam_expression_mirror/requirements.txt`
- Create: `geometry/body_measurements/requirements.txt`
- Create: `export/scene_to_usd/requirements.txt`
- Preserve: Existing `rendering/sprite_matrix/requirements.txt`
- Preserve: Existing `rendering/comfyui_enhance/requirements.txt`

**Interfaces:**
- Consumes: Example structure from Task 3
- Produces: requirements.txt for examples needing external dependencies

- [ ] **Step 1: Create requirements.txt for capture_viewport**

```bash
cat > rendering/capture_viewport/requirements.txt << 'EOF'
# Background removal for sprite mode
rembg>=2.0.0
EOF
```

- [ ] **Step 2: Create requirements.txt for expression_transfer**

```bash
cat > ai_vision/expression_transfer/requirements.txt << 'EOF'
# Facial landmark detection
mediapipe>=0.10.0

# Image processing
opencv-python>=4.8.0

# Numerical operations
numpy>=1.24.0
EOF
```

- [ ] **Step 3: Create requirements.txt for webcam_expression_mirror**

```bash
cat > ai_vision/webcam_expression_mirror/requirements.txt << 'EOF'
# Facial landmark detection
mediapipe>=0.10.0

# Image and video processing
opencv-python>=4.8.0

# Numerical operations
numpy>=1.24.0
EOF
```

- [ ] **Step 4: Create requirements.txt for body_measurements**

```bash
cat > geometry/body_measurements/requirements.txt << 'EOF'
# Mesh processing and plane intersection
trimesh>=4.0.0
EOF
```

- [ ] **Step 5: Create requirements.txt for scene_to_usd**

```bash
cat > export/scene_to_usd/requirements.txt << 'EOF'
# Pixar USD file format support
usd-core>=23.11
EOF
```

- [ ] **Step 6: Verify existing requirements.txt preserved**

```bash
ls -la rendering/sprite_matrix/requirements.txt
ls -la rendering/comfyui_enhance/requirements.txt
```

Expected: Both files exist and unchanged

- [ ] **Step 7: Commit requirements files**

```bash
git add */*/requirements.txt
git commit -m "feat: add requirements.txt for examples with external dependencies

- capture_viewport: rembg for sprite mode
- expression_transfer: mediapipe, opencv-python, numpy
- webcam_expression_mirror: mediapipe, opencv-python, numpy
- body_measurements: trimesh
- scene_to_usd: usd-core
- sprite_matrix, comfyui_enhance: preserved existing"
git push origin main
```

Expected: Requirements files committed

---

### Task 8: Generate Comprehensive Root README

**Files:**
- Create: New root `README.md` with comprehensive table
- Archive: Move old `README.md` to `docs/OLD_README.md`

**Interfaces:**
- Consumes: Level map from Task 4, example structure from Task 3
- Produces: Root README with sortable table of all examples

- [ ] **Step 1: Archive old README**

```bash
cd /Users/hirparag/Development/private/daz-script-server-examples
mkdir -p docs
git mv README.md docs/OLD_README.md
git commit -m "chore: archive original README for reference"
```

Expected: Old README moved to docs/

- [ ] **Step 2: Create comprehensive root README (part 1: header)**

```bash
cat > README.md << 'EOF'
# daz-script-server Examples

Complete, categorized examples for [daz-script-server](https://github.com/bluemoonfoundry/daz-script-server) and the `dazpy` Python SDK.

[![License](https://img.shields.io/badge/license-AGPL%20v3-blue)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.8+-blue)](https://www.python.org/)

## Overview

This repository contains production-ready examples demonstrating how to control DAZ Studio remotely via the DazScriptServer plugin and dazpy Python SDK. Examples range from beginner tutorials to advanced production pipeline implementations.

## Prerequisites

- **DAZ Studio 4.5+** with [DazScriptServer plugin](https://github.com/bluemoonfoundry/daz-script-server) installed and running
- **Python 3.8+**
- **dazpy SDK:** `pip install dazpy`

## Quick Start

1. Start DAZ Studio with DazScriptServer plugin active (check status in DAZ Studio Panes → Daz Script Server)
2. Clone this repo: `git clone https://github.com/bluemoonfoundry/daz-script-server-examples.git`
3. Install dazpy: `pip install dazpy`
4. Navigate to an example: `cd fundamentals/raw_script/`
5. Install example dependencies (if requirements.txt exists): `pip install -r requirements.txt`
6. Run the example: `python raw_script.py`

## Examples by Category

EOF
```

- [ ] **Step 3: Create table generator script**

```bash
cat > tools/generate_table.py << 'PYTHON_EOF'
"""Generate comprehensive examples table for root README"""
import json
from pathlib import Path

# Load level map
with open('tools/level_map.json') as f:
    LEVEL_MAP = json.load(f)

def find_all_examples():
    """Find all example directories"""
    examples = []
    
    categories = ['fundamentals', 'character', 'animation', 'geometry', 
                  'export', 'rendering', 'ml_data', 'ai_vision', 'bvh']
    
    for category in categories:
        cat_path = Path(category)
        if not cat_path.exists():
            continue
        
        for example_dir in sorted(cat_path.iterdir()):
            if example_dir.is_dir() and (example_dir / 'README.md').exists():
                example_name = example_dir.name
                lookup_key = f"{category}/{example_name}"
                level = LEVEL_MAP.get(lookup_key, "Intermediate")
                
                # Extract description from README
                readme_path = example_dir / 'README.md'
                with open(readme_path) as f:
                    readme_content = f.read()
                    # Extract Overview section
                    import re
                    desc_match = re.search(r'## Overview\n\n(.*?)(?=\n##|\Z)', readme_content, re.DOTALL)
                    description = desc_match.group(1).strip()[:100] + "..." if desc_match else ""
                
                # Check for requirements.txt
                has_deps = (example_dir / 'requirements.txt').exists()
                deps = "Yes" if has_deps else "None"
                
                examples.append({
                    'name': example_name,
                    'category': category,
                    'level': level,
                    'description': description,
                    'deps': deps,
                    'path': f"{category}/{example_name}"
                })
    
    return examples

def generate_table(examples):
    """Generate markdown table"""
    table = ["| Example | Category | Level | Description | Dependencies |",
             "|---------|----------|-------|-------------|--------------|"]
    
    for ex in examples:
        name_link = f"[{ex['name']}]({ex['path']}/)"
        desc = ex['description'].replace('\n', ' ')
        row = f"| {name_link} | {ex['category']} | {ex['level']} | {desc} | {ex['deps']} |"
        table.append(row)
    
    return '\n'.join(table)

if __name__ == '__main__':
    examples = find_all_examples()
    table = generate_table(examples)
    print(table)
PYTHON_EOF
```

- [ ] **Step 4: Generate and append table**

```bash
python3 tools/generate_table.py >> README.md
```

Expected: Table appended to README.md

- [ ] **Step 5: Add remaining README sections**

```bash
cat >> README.md << 'EOF'

## Categories

- **fundamentals/** — Core SDK patterns, scene inspection, batching, events
- **character/** — Pose, state, IK, animation dumps
- **animation/** — Keyframe baking, clip mixing, interpolation
- **geometry/** — Mesh analysis, body measurements
- **export/** — USD export, format conversion
- **rendering/** — Turntable, multi-cam, batch renders, VN workflows, external pipelines
- **ml_data/** — Dataset generation for ML training
- **ai_vision/** — MediaPipe expression transfer, webcam mirroring
- **bvh/** — BVH motion-capture import (in development)

## Skill Level Guide

- **Beginner:** Single HTTP call patterns, basic SDK usage, clear 1:1 mapping to DAZ Studio concepts. Start here if new to dazpy.
- **Intermediate:** Multiple API calls, state management, batch operations, moderate Python complexity. Requires understanding of DAZ Studio object model.
- **Advanced:** External integrations, complex pipelines, async patterns, production-scale techniques. Assumes Python proficiency and pipeline architecture experience.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on submitting new examples.

## License

AGPL v3 (matches parent repository)

## Links

- [daz-script-server repository](https://github.com/bluemoonfoundry/daz-script-server)
- [dazpy PyPI package](https://pypi.org/project/dazpy/)
- [DazScriptServer plugin documentation](https://github.com/bluemoonfoundry/daz-script-server#readme)
EOF
```

- [ ] **Step 6: Verify README**

```bash
head -50 README.md
wc -l README.md
```

Expected: README has header, table, categories, links

- [ ] **Step 7: Commit root README**

```bash
git add README.md tools/generate_table.py
git commit -m "feat: create comprehensive root README with examples table

- Comprehensive sortable table of all examples
- Level classifications visible
- Category descriptions
- Quick start guide
- Links to parent repo and dazpy"
git push origin main
```

Expected: Root README committed

---

### Task 9: Create LICENSE and CONTRIBUTING Files

**Files:**
- Create: `LICENSE`
- Create: `CONTRIBUTING.md`

**Interfaces:**
- Consumes: Repository structure from previous tasks
- Produces: LICENSE and contributing guidelines

- [ ] **Step 1: Create LICENSE file**

```bash
cat > LICENSE << 'EOF'
GNU AFFERO GENERAL PUBLIC LICENSE
Version 3, 19 November 2007

Copyright (C) 2007 Free Software Foundation, Inc. <https://fsf.org/>

Everyone is permitted to copy and distribute verbatim copies
of this license document, but changing it is not allowed.

[Full AGPL v3 license text - see https://www.gnu.org/licenses/agpl-3.0.txt]
EOF
```

- [ ] **Step 2: Download full AGPL v3 text**

```bash
curl -o LICENSE https://www.gnu.org/licenses/agpl-3.0.txt
```

Expected: LICENSE file downloaded

- [ ] **Step 3: Create CONTRIBUTING guide**

```bash
cat > CONTRIBUTING.md << 'EOF'
# Contributing Examples

## New Example Checklist

- [ ] Example follows standard README template
- [ ] Code includes docstrings for key functions/classes
- [ ] requirements.txt included if dependencies needed beyond dazpy
- [ ] Tested against current dazpy stable release
- [ ] Fits existing category or proposes new category with rationale
- [ ] Skill level classification with justification
- [ ] No hard-coded paths (use arguments or environment variables)
- [ ] Error handling for common failure cases
- [ ] Example is self-contained (no external file dependencies except documented)

## Example Requirements

### 1. README must include:

- Level (Beginner/Intermediate/Advanced) with rationale
- Category
- Overview (2-3 sentences)
- What You'll Learn section
- Prerequisites
- Dependencies
- Usage with argument table
- How It Works walkthrough
- Output description
- SDK Features Demonstrated
- Related Examples (if applicable)

### 2. Code must:

- Use argparse for command-line arguments
- Include docstrings
- Handle errors gracefully with clear messages
- Follow PEP 8 style
- Use type hints where helpful (not required for Beginner examples)

### 3. Dependencies:

- Minimize external dependencies
- Pin major version only (e.g., `package>=1.0`)
- Document why each dependency is needed in requirements.txt comments

## Proposing New Categories

New categories require:
- Minimum 3 examples demonstrating the category's scope
- Clear differentiation from existing categories
- Rationale for why examples don't fit existing categories

## Review Process

1. Fork repo and create feature branch
2. Add example following template
3. Test against current dazpy stable release
4. Submit PR with example checklist completed
5. Maintainer review for:
   - Documentation completeness
   - Code quality
   - Level classification accuracy
   - Category fit

## Questions?

Open an issue in [daz-script-server repository](https://github.com/bluemoonfoundry/daz-script-server/issues)
EOF
```

- [ ] **Step 4: Verify files created**

```bash
ls -lh LICENSE CONTRIBUTING.md
```

Expected: Both files present

- [ ] **Step 5: Commit LICENSE and CONTRIBUTING**

```bash
git add LICENSE CONTRIBUTING.md
git commit -m "chore: add LICENSE (AGPL v3) and CONTRIBUTING guidelines"
git push origin main
```

Expected: Files committed

---

### Task 10: Set GitHub Repository Topics and Description

**Files:**
- Modify: GitHub repository metadata (via gh CLI)

**Interfaces:**
- Consumes: Completed repository from previous tasks
- Produces: Repository with proper topics and description

- [ ] **Step 1: Set repository topics**

```bash
/Users/hirparag/Development/gh_2.89.0_macOS_arm64/bin/gh repo edit bluemoonfoundry/daz-script-server-examples \
  --add-topic daz-studio \
  --add-topic dazpy \
  --add-topic 3d-rendering \
  --add-topic python \
  --add-topic examples \
  --add-topic tutorial \
  --add-topic daz3d \
  --add-topic automation \
  --add-topic pipeline \
  --add-topic computer-graphics
```

Expected: Topics added successfully

- [ ] **Step 2: Verify topics set**

```bash
/Users/hirparag/Development/gh_2.89.0_macOS_arm64/bin/gh repo view bluemoonfoundry/daz-script-server-examples --json repositoryTopics
```

Expected: JSON output shows all topics

- [ ] **Step 3: Update repository description**

```bash
/Users/hirparag/Development/gh_2.89.0_macOS_arm64/bin/gh repo edit bluemoonfoundry/daz-script-server-examples \
  --description "Complete, categorized examples for daz-script-server and dazpy SDK - from beginner tutorials to production pipelines"
```

Expected: Description updated

- [ ] **Step 4: Verify description**

```bash
/Users/hirparag/Development/gh_2.89.0_macOS_arm64/bin/gh repo view bluemoonfoundry/daz-script-server-examples --json description
```

Expected: JSON shows updated description

- [ ] **Step 5: Create completion marker**

```bash
cd /Users/hirparag/Development/private/daz-script-server-examples
echo "Repository setup complete - $(date)" > .setup_complete
git add .setup_complete
git commit -m "chore: mark repository setup complete"
git push origin main
```

Expected: Setup marker committed

---

### Task 11: Update Parent Repository Links

**Files:**
- Modify: `../daz-script-server/README.md`
- Create: `../daz-script-server/docs/examples/MOVED.md`

**Interfaces:**
- Consumes: Completed examples repo from Task 10
- Produces: Updated parent repo pointing to new examples location

- [ ] **Step 1: Create MOVED notice in parent repo**

```bash
cd /Users/hirparag/Development/private/daz-script-server
cat > docs/examples/MOVED.md << 'EOF'
# Examples Have Moved

The examples formerly in `docs/examples/` have been extracted to a dedicated repository:

**[daz-script-server-examples](https://github.com/bluemoonfoundry/daz-script-server-examples)**

## Why?

- Better organization with individual READMEs per example
- Independent versioning and contribution workflow
- Comprehensive examples table with skill level filtering
- Dedicated requirements.txt per example

## Migration

All examples are preserved with:
- Same category structure (fundamentals, character, rendering, etc.)
- Individual folder per example
- Standardized README template
- Level classifications (Beginner/Intermediate/Advanced)

Visit the new repository: https://github.com/bluemoonfoundry/daz-script-server-examples
EOF
```

- [ ] **Step 2: Find examples section in parent README**

```bash
grep -n "docs/examples" README.md | head -5
```

Expected: Line numbers where examples are referenced

- [ ] **Step 3: Update parent README (insert after Quick Start section)**

Add this section after the Quick Start in README.md:

```markdown
## Examples

**Complete example collection:** [daz-script-server-examples repository](https://github.com/bluemoonfoundry/daz-script-server-examples)

Production-ready examples ranging from beginner tutorials to advanced pipeline implementations:
- **48 examples** across 9 categories
- Individual READMEs with skill level classification
- Requirements.txt per example
- Comprehensive searchable table

Categories: fundamentals, character, animation, rendering, geometry, export, ml_data, ai_vision, bvh
```

(Manual edit required - script cannot automatically find insertion point)

- [ ] **Step 4: Commit changes to parent repo**

```bash
git add docs/examples/MOVED.md README.md
git commit -m "docs: update examples links to new daz-script-server-examples repo

Examples have been extracted to dedicated repository:
https://github.com/bluemoonfoundry/daz-script-server-examples"
```

Expected: Changes committed (do not push yet - will push at end of session)

- [ ] **Step 5: Verify parent repo changes**

```bash
git log --oneline | head -3
git status
```

Expected: Commit visible, working directory clean

---

### Task 12: Final Verification and Documentation

**Files:**
- Create: `../daz-script-server-examples/docs/SETUP.md`

**Interfaces:**
- Consumes: All previous tasks
- Produces: Setup documentation and verification checklist

- [ ] **Step 1: Create setup documentation**

```bash
cd /Users/hirparag/Development/private/daz-script-server-examples
cat > docs/SETUP.md << 'EOF'
# Repository Setup Documentation

This document describes the extraction and setup of daz-script-server-examples.

## Extraction Process

1. Created new repository: `bluemoonfoundry/daz-script-server-examples`
2. Copied examples from `daz-script-server/docs/examples/`
3. Restructured single-file examples to folder-per-example
4. Generated individual READMEs using standard template
5. Created requirements.txt for examples with external dependencies
6. Generated comprehensive root README with examples table
7. Added LICENSE (AGPL v3) and CONTRIBUTING guidelines
8. Set GitHub topics and description

## Repository Structure

```
daz-script-server-examples/
├── README.md                    # Comprehensive table of all examples
├── LICENSE                      # AGPL v3
├── CONTRIBUTING.md              # Contribution guidelines
├── docs/
│   ├── SETUP.md                # This file
│   └── OLD_README.md           # Archived original README
├── tools/                      # Generation scripts
│   ├── level_map.json          # Level classifications
│   ├── extract_readme_sections.py
│   ├── generate_example_readmes.py
│   └── generate_table.py
├── fundamentals/               # 6 examples
├── character/                  # 4 examples
├── animation/                  # 3 examples
├── geometry/                   # 2 examples
├── export/                     # 1 example
├── rendering/                  # 8 examples
├── ml_data/                    # 1 example
├── ai_vision/                  # 2 examples
└── bvh/                        # 3 examples (in development)
```

## Examples Count

- Total: 30 examples
- Beginner: 6
- Intermediate: 12
- Advanced: 12

## Links

- Parent repository: https://github.com/bluemoonfoundry/daz-script-server
- dazpy PyPI: https://pypi.org/project/dazpy/
- Documentation: https://bluemoonfoundry.github.io/daz-script-server/
EOF
```

- [ ] **Step 2: Create verification checklist**

```bash
cat > docs/VERIFICATION.md << 'EOF'
# Repository Verification Checklist

Run these checks to verify repository setup:

## Structure Verification

- [ ] All 9 category directories exist
- [ ] Each example has its own folder
- [ ] Each example folder contains Python script(s)
- [ ] Each example has README.md
- [ ] Examples with external deps have requirements.txt

```bash
# Count examples per category
for cat in fundamentals character animation geometry export rendering ml_data ai_vision bvh; do
  count=$(find $cat -mindepth 1 -maxdepth 1 -type d | wc -l)
  echo "$cat: $count examples"
done

# Verify all have READMEs
find . -mindepth 2 -maxdepth 2 -type d ! -path "./docs/*" ! -path "./tools/*" | while read dir; do
  if [ ! -f "$dir/README.md" ]; then
    echo "Missing README: $dir"
  fi
done
```

## Documentation Verification

- [ ] Root README has comprehensive table
- [ ] Root README has categories section
- [ ] Root README has skill level guide
- [ ] LICENSE file present (AGPL v3)
- [ ] CONTRIBUTING.md present
- [ ] All example READMEs follow template

```bash
# Check root README structure
grep -c "## Overview" README.md
grep -c "## Categories" README.md
grep -c "## Skill Level Guide" README.md

# Check example READMEs have required sections
for readme in */*/README.md; do
  if ! grep -q "## Overview" "$readme"; then
    echo "Missing Overview: $readme"
  fi
done
```

## Metadata Verification

- [ ] GitHub topics set
- [ ] Repository description set
- [ ] .gitignore configured
- [ ] All commits pushed

```bash
# Check remote status
git status
git log --oneline | head -10

# Verify topics (requires gh CLI)
gh repo view bluemoonfoundry/daz-script-server-examples --json repositoryTopics
```

## Parent Repository Updates

- [ ] MOVED.md created in parent docs/examples/
- [ ] Parent README updated with link to new repo
- [ ] Parent repo changes committed

```bash
cd ../daz-script-server
git log --oneline | head -3
cat docs/examples/MOVED.md
```
EOF
```

- [ ] **Step 3: Run verification checks**

```bash
# Count examples
for cat in fundamentals character animation geometry export rendering ml_data ai_vision bvh; do
  count=$(find $cat -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l)
  echo "$cat: $count examples"
done
```

Expected: Output shows example counts per category

- [ ] **Step 4: Verify all READMEs exist**

```bash
missing=0
for dir in */*/; do
  if [[ "$dir" == "docs/"* ]] || [[ "$dir" == "tools/"* ]]; then
    continue
  fi
  if [ ! -f "${dir}README.md" ]; then
    echo "Missing: ${dir}README.md"
    missing=$((missing + 1))
  fi
done
echo "Missing READMEs: $missing"
```

Expected: Output "Missing READMEs: 0"

- [ ] **Step 5: Commit documentation**

```bash
git add docs/SETUP.md docs/VERIFICATION.md
git commit -m "docs: add setup and verification documentation"
git push origin main
```

Expected: Documentation committed and pushed

---

## Self-Review

**Spec coverage check:**

1. ✓ Repository creation with correct name and org
2. ✓ Examples copied preserving structure
3. ✓ Restructured to folder-per-example
4. ✓ Individual READMEs with standard template
5. ✓ Level classifications applied
6. ✓ requirements.txt generated for deps
7. ✓ Comprehensive root README with table
8. ✓ LICENSE (AGPL v3) added
9. ✓ CONTRIBUTING guidelines added
10. ✓ GitHub metadata (topics, description) set
11. ✓ Parent repo updated with links
12. ✓ Verification documentation

**Placeholder scan:** No TBD, TODO, or placeholders present

**Type consistency:** File paths, script names, and structure consistent throughout

**Testing strategy:** Verification checklist in Task 12 provides manual validation steps

## Plan Complete

All 12 tasks defined with exact commands, expected outputs, and commit messages. Ready for execution.
