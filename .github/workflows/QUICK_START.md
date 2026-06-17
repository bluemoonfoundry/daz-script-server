# Quick Start Guide - CI/CD Workflows

This guide provides quick commands and common scenarios for working with the CI/CD workflows.

## Creating Releases

### Tagged Release (Official)

```bash
# 1. Ensure all changes are committed and pushed
git add .
git commit -m "Release v1.3.0"
git push origin master

# 2. Create and push tag
git tag v1.3.0
git push origin v1.3.0

# 3. GitHub Actions automatically creates release with all artifacts
```

The workflow will:
- Build Windows DLL
- Build macOS Intel, Apple Silicon, and Universal binaries
- Build dazpy wheel
- Generate commit summary since last release
- Create GitHub release with all artifacts

### Nightly Release

**Automatic:** Runs every night at 1 AM EST

**Manual trigger:**
```bash
# Via GitHub CLI
gh workflow run release-nightly.yml

# Or via GitHub web UI:
# 1. Go to Actions tab
# 2. Select "Nightly Release"
# 3. Click "Run workflow"
```

## Local Development

### Build Plugin Locally

```bash
# Windows
./build.sh build --platform win --clean

# macOS Intel
./build.sh build --platform mac --clean

# macOS with specific architecture
cmake -B build -S . \
  -DDAZ_SDK_DIR="/path/to/DAZStudio4.5+ SDK" \
  -DCMAKE_OSX_ARCHITECTURES="arm64"
cmake --build build --config Release
```

### Build dazpy Wheel Locally

```bash
python -m pip install build
python -m build --wheel --outdir dist
```

### Install to DAZ Studio

```bash
# Set DAZ_STUDIO_EXE_DIR in .env first
./build.sh install --clean
```

## Testing Before Release

### Pre-release Checklist

```bash
# 1. Run tests
python tests.py unit

# 2. Build all platforms (if possible)
./build.sh build --clean

# 3. Test build script with release
./build.sh release test-v1.3.0 --title "Test" --notes "Testing"

# 4. Verify artifacts
ls -lh build/plugin/Release/

# 5. Delete test release if successful
gh release delete test-v1.3.0 --yes
```

## Common Scenarios

### Update SDK Cache

If the DAZ SDK is updated, invalidate the cache:

1. Edit workflow files (`.github/workflows/build-*.yml`)
2. Change cache key version:
   ```yaml
   # Old
   key: daz-sdk-4.5-windows-v1

   # New
   key: daz-sdk-4.5-windows-v2
   ```
3. Commit and push

### Force Rebuild Without Cache

Temporarily disable cache in workflow:

```yaml
- name: Cache DAZ Studio SDK
  if: false  # Add this line
  id: cache-sdk
  uses: actions/cache@v4
```

### Debug Build in CI

Create a debug release:

```yaml
# In release-tagged.yml, change configuration
build-windows:
  uses: ./.github/workflows/build-windows.yml
  with:
    configuration: Debug  # Changed from Release
```

### Skip Nightly for Testing

Disable the schedule temporarily:

```yaml
on:
  schedule:
    # - cron: '0 6 * * *'  # Comment out
  workflow_dispatch:  # Keep manual trigger
```

## Workflow Status

### Check Workflow Status

```bash
# List recent workflow runs
gh run list --workflow=release-tagged.yml

# View specific run
gh run view <run-id>

# View logs
gh run view <run-id> --log

# Watch running workflow
gh run watch
```

### Cancel Running Workflow

```bash
# Cancel specific run
gh run cancel <run-id>

# Cancel all runs for a workflow
gh run list --workflow=release-nightly.yml --json databaseId -q '.[].databaseId' | \
  xargs -n1 gh run cancel
```

## Artifact Management

### Download Artifacts from CI

```bash
# Download all artifacts from latest run
gh run download

# Download specific artifact
gh run download --name DazScriptServer-windows-Release

# Download from specific run
gh run download <run-id>
```

### List Release Assets

```bash
# List all releases
gh release list

# View specific release
gh release view v1.3.0

# Download release assets
gh release download v1.3.0
```

## Troubleshooting Commands

### Check SDK Repository

```bash
# Verify SDK is accessible
curl -I https://github.com/3DBreww/DAZ-Studio-SDK/archive/refs/heads/main.zip

# Download SDK manually
curl -L -o daz-sdk.zip \
  https://github.com/3DBreww/DAZ-Studio-SDK/archive/refs/heads/main.zip
unzip daz-sdk.zip
```

### Verify Local Build Matches CI

```bash
# Download SDK same way CI does
curl -L -o daz-sdk.zip \
  https://github.com/3DBreww/DAZ-Studio-SDK/archive/refs/heads/main.zip
unzip daz-sdk.zip
mv DAZ-Studio-SDK-main "DAZStudio4.5+ SDK"

# Build with same configuration as CI
cmake -B build -S . \
  -DDAZ_SDK_DIR="${PWD}/DAZStudio4.5+ SDK" \
  -DCMAKE_BUILD_TYPE=Release

cmake --build build --config Release --verbose
```

### Check Build Output

```bash
# Windows
ls -lh build/plugin/Release/DazScriptServer.dll
file build/plugin/Release/DazScriptServer.dll

# macOS
ls -lh build/plugin/DazScriptServer.dylib
file build/plugin/DazScriptServer.dylib
lipo -info build/plugin/DazScriptServer.dylib
```

## Advanced Usage

### Modify Release Notes

Edit the workflow file to customize release notes:

```yaml
- name: Generate release notes
  run: |
    {
      echo "## Custom Header"
      echo ""
      echo "Your custom content here"
      echo ""
      # ... rest of release notes
    } > release_notes.md
```

### Add Additional Artifacts

```yaml
- name: Prepare release assets
  run: |
    # ... existing assets ...

    # Add custom asset
    cp path/to/custom/file release-assets/
```

### Custom Build Flags

```yaml
- name: Configure CMake
  run: |
    cmake -B build -S . \
      -DDAZ_SDK_DIR="${{ github.workspace }}/DAZStudio4.5+ SDK" \
      -DCMAKE_BUILD_TYPE=Release \
      -DCUSTOM_FLAG=ON  # Add custom flag
```

## Environment Setup

### GitHub CLI Setup

```bash
# Install gh CLI
# macOS
brew install gh

# Windows
winget install GitHub.cli

# Authenticate
gh auth login
```

### Required Permissions

The repository needs:
- Actions enabled
- Workflow permissions set to "Read and write"
- Allow GitHub Actions to create releases

Check in: Settings → Actions → General → Workflow permissions

## Useful Links

- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [GitHub CLI Documentation](https://cli.github.com/manual/)
- [CMake Documentation](https://cmake.org/documentation/)
- [DAZ Studio SDK](https://github.com/3DBreww/DAZ-Studio-SDK)

## Getting Help

1. **Check workflow logs:** Most issues show detailed error messages
2. **Review README.md:** Detailed troubleshooting guide
3. **Test locally:** Reproduce the issue on your machine
4. **GitHub Actions status:** Check https://www.githubstatus.com/
5. **Open issue:** Include workflow logs and error messages
