#!/usr/bin/env bash
# Build DazScriptServer plugin DLL.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="$SCRIPT_DIR/build"

usage() {
    cat <<EOF
Usage: ./build.sh [command] [options]

Commands:
  build              Configure (if needed) and build (default)
  install            Build and copy plugin to DAZ Studio plugins folder
  clean              Delete the build directory and exit
  release <tag>      Build, then create a GitHub release and attach the plugin

Options:
  --clean            Wipe the build directory before building
  --reconfigure      Force CMake configure even if a cache already exists
  --debug            Build Debug config instead of Release
  --verbose          Pass --verbose to the CMake build step
  --title <title>    Release title (release command only; defaults to <tag>)
  --notes <text>     Release notes text (release command only)
  --update           Update an existing release instead of creating a new one (release command only)
  --help             Show this help message and exit

Examples:
  ./build.sh
  ./build.sh build --clean --debug
  ./build.sh install --clean
  ./build.sh clean
  ./build.sh release v1.3.0 --title "v1.3.0" --notes "Bug fixes"

Required environment variables (loaded from .env if present):
  DAZ_SDK_DIR          Path to the DAZStudio4.5+ SDK

Optional environment variables:
  DAZ_STUDIO_EXE_DIR   Path to DAZ Studio executable folder (required for install)
EOF
}

# ── Parse command ─────────────────────────────────────────────────────────────
COMMAND="build"
RELEASE_TAG=""

if [[ $# -gt 0 && "$1" != --* && "$1" != "-h" ]]; then
    COMMAND="$1"
    shift
    if [ "$COMMAND" = "release" ]; then
        if [[ $# -eq 0 || "$1" == --* ]]; then
            echo "Error: 'release' requires a tag argument, e.g.: ./build.sh release v1.3.0" >&2
            exit 1
        fi
        RELEASE_TAG="$1"
        shift
    fi
fi

# ── Parse options ─────────────────────────────────────────────────────────────
OPT_CLEAN=0
OPT_RECONFIGURE=0
OPT_DEBUG=0
OPT_VERBOSE=0
OPT_UPDATE=0
OPT_TITLE=""
OPT_NOTES=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --clean)       OPT_CLEAN=1;                                      shift ;;
        --reconfigure) OPT_RECONFIGURE=1;                                shift ;;
        --debug)       OPT_DEBUG=1;                                      shift ;;
        --verbose)     OPT_VERBOSE=1;                                    shift ;;
        --update)      OPT_UPDATE=1;                                     shift ;;
        --title)       OPT_TITLE="${2:?'--title requires a value'}";     shift 2 ;;
        --notes)       OPT_NOTES="${2:?'--notes requires a value'}";     shift 2 ;;
        --help|-h)     usage; exit 0 ;;
        *)
            echo "Error: unknown option '$1'" >&2
            echo "Run './build.sh --help' for usage." >&2
            exit 1
            ;;
    esac
done

# Validate command
case "$COMMAND" in
    build|install|clean|release) ;;
    *)
        echo "Error: unknown command '$COMMAND'" >&2
        echo "Run './build.sh --help' for usage." >&2
        exit 1
        ;;
esac

# ── Environment ───────────────────────────────────────────────────────────────
if [ -f "$SCRIPT_DIR/.env" ]; then
    . "$SCRIPT_DIR/.env"
fi

echo "DAZ_SDK_DIR: ${DAZ_SDK_DIR:-<not set>}"
echo "DAZ_STUDIO_EXE_DIR: ${DAZ_STUDIO_EXE_DIR:-<not set>}"

# Detect platform
case "$(uname -s)" in
    Darwin*) PLATFORM=mac ;;
    *)       PLATFORM=win ;;
esac

# Locate cmake — check PATH first, then known Windows location
if command -v cmake &>/dev/null; then
    CMAKE=cmake
elif [ "$PLATFORM" = "win" ] && [ -f "/x/apps/CMake/bin/cmake.exe" ]; then
    CMAKE="/x/apps/CMake/bin/cmake"
else
    echo "Error: cmake not found. Add it to PATH or install it." >&2
    exit 1
fi

# Artifact path (used by build output message and release command)
if [ "$PLATFORM" = "win" ]; then
    BUILD_CONFIG="Release"
    [ "$OPT_DEBUG" = 1 ] && BUILD_CONFIG="Debug"
    ARTIFACT="$BUILD_DIR/lib/$BUILD_CONFIG/DazScriptServer.dll"
else
    BUILD_CONFIG="Release"
    [ "$OPT_DEBUG" = 1 ] && BUILD_CONFIG="Debug"
    ARTIFACT="$BUILD_DIR/lib/DazScriptServer.dylib"
fi

# ── clean command ─────────────────────────────────────────────────────────────
if [ "$COMMAND" = "clean" ]; then
    echo "Removing build directory: $BUILD_DIR"
    rm -rf "$BUILD_DIR"
    echo "Done."
    exit 0
fi

# ── Wipe before build (--clean option) ───────────────────────────────────────
if [ "$OPT_CLEAN" = 1 ]; then
    echo "Removing build directory: $BUILD_DIR"
    rm -rf "$BUILD_DIR"
fi

# ── CMake configure ───────────────────────────────────────────────────────────
CMAKE_FLAGS=()
[ -n "$DAZ_SDK_DIR" ]        && CMAKE_FLAGS+=("-DDAZ_SDK_DIR=$DAZ_SDK_DIR")
[ -n "$DAZ_STUDIO_EXE_DIR" ] && CMAKE_FLAGS+=("-DDAZ_STUDIO_EXE_DIR=$DAZ_STUDIO_EXE_DIR")
[ "$COMMAND" = "install" ]   && CMAKE_FLAGS+=("-DINSTALL_TO_DAZ=ON")

if [ "$PLATFORM" = "win" ]; then
    STALE_CHECK="$BUILD_DIR/ALL_BUILD.vcxproj"
else
    STALE_CHECK="$BUILD_DIR/Makefile"
fi

NEEDS_CONFIGURE=0
if [ ! -f "$BUILD_DIR/CMakeCache.txt" ] || [ ! -f "$STALE_CHECK" ]; then
    NEEDS_CONFIGURE=1
fi
# install changes the output directory at configure time, so always reconfigure
[ "$OPT_RECONFIGURE" = 1 ]   && NEEDS_CONFIGURE=1
[ "$COMMAND" = "install" ]   && NEEDS_CONFIGURE=1

if [ "$NEEDS_CONFIGURE" = 1 ]; then
    echo "Running CMake configure..."
    "$CMAKE" -B "$BUILD_DIR" -S "$SCRIPT_DIR" "${CMAKE_FLAGS[@]}"
fi

# ── Build ─────────────────────────────────────────────────────────────────────
BUILD_ARGS=("--build" "$BUILD_DIR" "--config" "$BUILD_CONFIG")
[ "$OPT_VERBOSE" = 1 ] && BUILD_ARGS+=("--verbose")

if [ "$COMMAND" = "install" ]; then
    # DAZ Studio locks the plugin while running — catch this before the linker does
    if [ "$PLATFORM" = "win" ]; then
        if tasklist //FI "IMAGENAME eq DAZStudio4.exe" 2>/dev/null | grep -qi "DAZStudio4.exe"; then
            echo "Error: DAZ Studio is currently running." >&2
            echo "Close DAZ Studio before installing, then re-run: ./build.sh install" >&2
            exit 1
        fi
    else
        if pgrep -qx "DAZ Studio" 2>/dev/null; then
            echo "Error: DAZ Studio is currently running." >&2
            echo "Close DAZ Studio before installing, then re-run: ./build.sh install" >&2
            exit 1
        fi
    fi
    echo "Building ($BUILD_CONFIG) and installing to DAZ Studio plugins folder..."
    "$CMAKE" "${BUILD_ARGS[@]}"
else
    echo "Building ($BUILD_CONFIG)..."
    "$CMAKE" "${BUILD_ARGS[@]}"
    echo "Output: $ARTIFACT"
fi

# ── release command ───────────────────────────────────────────────────────────
if [ "$COMMAND" = "release" ]; then
    if ! command -v gh &>/dev/null; then
        echo "Error: 'gh' CLI not found. Install it from https://cli.github.com" >&2
        exit 1
    fi

    if [ ! -f "$ARTIFACT" ]; then
        echo "Error: build artifact not found: $ARTIFACT" >&2
        exit 1
    fi

    if [ "$OPT_UPDATE" = 1 ]; then
        GH_ARGS=("release" "upload" "$RELEASE_TAG" "$ARTIFACT" "--clobber")
        echo "Updating GitHub release $RELEASE_TAG with $ARTIFACT..."
    else
        RELEASE_TITLE="${OPT_TITLE:-$RELEASE_TAG}"
        GH_ARGS=("release" "create" "$RELEASE_TAG" "$ARTIFACT" "--title" "$RELEASE_TITLE")
        [ -n "$OPT_NOTES" ] && GH_ARGS+=("--notes" "$OPT_NOTES")
        echo "Creating GitHub release $RELEASE_TAG and attaching $ARTIFACT..."
    fi
    gh "${GH_ARGS[@]}"
fi
