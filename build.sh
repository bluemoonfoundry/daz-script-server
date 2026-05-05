#!/usr/bin/env bash
# Build DazScriptServer plugin DLL.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="$SCRIPT_DIR/build"

usage() {
    cat <<EOF
Usage: ./build.sh [options]

Options:
  (none)           Configure (if needed) and build Release
  --install        Build Release and install DLL to DAZ Studio plugins folder
  --clean          Delete the build directory, reconfigure, and build
  --clean-only     Delete the build directory and exit (no build)
  --reconfigure    Force CMake configure even if a cache already exists
  --debug          Build Debug config instead of Release
  --verbose        Pass --verbose to the CMake build step
  --help           Show this help message and exit

Options can be combined, e.g.:
  ./build.sh --clean --install
  ./build.sh --reconfigure --debug --verbose

Required environment variables (loaded from .env if present):
  DAZ_SDK_DIR          Path to the DAZStudio4.5+ SDK

Optional environment variables:
  DAZ_STUDIO_EXE_DIR   Path to DAZ Studio executable folder (required for --install)
EOF
}

# Parse flags
OPT_INSTALL=0
OPT_CLEAN=0
OPT_CLEAN_ONLY=0
OPT_RECONFIGURE=0
OPT_DEBUG=0
OPT_VERBOSE=0

for arg in "$@"; do
    case "$arg" in
        --install)     OPT_INSTALL=1 ;;
        --clean)       OPT_CLEAN=1 ;;
        --clean-only)  OPT_CLEAN_ONLY=1 ;;
        --reconfigure) OPT_RECONFIGURE=1 ;;
        --debug)       OPT_DEBUG=1 ;;
        --verbose)     OPT_VERBOSE=1 ;;
        --help|-h)     usage; exit 0 ;;
        *)
            echo "Error: unknown option '$arg'" >&2
            echo "Run './build.sh --help' for usage." >&2
            exit 1
            ;;
    esac
done

# Load .env if present
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

# --clean-only: wipe build dir and exit
if [ "$OPT_CLEAN_ONLY" = 1 ]; then
    echo "Removing build directory: $BUILD_DIR"
    rm -rf "$BUILD_DIR"
    echo "Done."
    exit 0
fi

# --clean: wipe build dir before proceeding
if [ "$OPT_CLEAN" = 1 ]; then
    echo "Removing build directory: $BUILD_DIR"
    rm -rf "$BUILD_DIR"
fi

# Build up common cmake -D flags from environment variables
CMAKE_FLAGS=()
[ -n "$DAZ_SDK_DIR" ] && CMAKE_FLAGS+=("-DDAZ_SDK_DIR=$DAZ_SDK_DIR")
[ -n "$DAZ_STUDIO_EXE_DIR" ] && CMAKE_FLAGS+=("-DDAZ_STUDIO_EXE_DIR=$DAZ_STUDIO_EXE_DIR")
[ "$OPT_INSTALL" = 1 ] && CMAKE_FLAGS+=("-DINSTALL_TO_DAZ=ON")

# Determine build config
BUILD_CONFIG="Release"
[ "$OPT_DEBUG" = 1 ] && BUILD_CONFIG="Debug"

# Configure if needed: no cache, missing project files, --reconfigure, or --clean just wiped it
NEEDS_CONFIGURE=0
if [ "$PLATFORM" = "win" ]; then
    STALE_CHECK="$BUILD_DIR/ALL_BUILD.vcxproj"
else
    STALE_CHECK="$BUILD_DIR/Makefile"
fi
if [ ! -f "$BUILD_DIR/CMakeCache.txt" ] || [ ! -f "$STALE_CHECK" ]; then
    NEEDS_CONFIGURE=1
fi
# --install changes the output directory at configure time, so always reconfigure
[ "$OPT_RECONFIGURE" = 1 ] && NEEDS_CONFIGURE=1
[ "$OPT_INSTALL" = 1 ] && NEEDS_CONFIGURE=1

if [ "$NEEDS_CONFIGURE" = 1 ]; then
    echo "Running CMake configure..."
    "$CMAKE" -B "$BUILD_DIR" -S "$SCRIPT_DIR" "${CMAKE_FLAGS[@]}"
fi

# Build
BUILD_ARGS=("--build" "$BUILD_DIR" "--config" "$BUILD_CONFIG")
[ "$OPT_VERBOSE" = 1 ] && BUILD_ARGS+=("--verbose")

if [ "$OPT_INSTALL" = 1 ]; then
    # DAZ Studio locks the plugin while running — catch this before the linker does
    if [ "$PLATFORM" = "win" ]; then
        if tasklist //FI "IMAGENAME eq DAZStudio4.exe" 2>/dev/null | grep -qi "DAZStudio4.exe"; then
            echo "Error: DAZ Studio is currently running." >&2
            echo "Close DAZ Studio before installing, then re-run: ./build.sh --install" >&2
            exit 1
        fi
    else
        if pgrep -qx "DAZ Studio" 2>/dev/null; then
            echo "Error: DAZ Studio is currently running." >&2
            echo "Close DAZ Studio before installing, then re-run: ./build.sh --install" >&2
            exit 1
        fi
    fi
    echo "Building ($BUILD_CONFIG) and installing to DAZ Studio plugins folder..."
    "$CMAKE" "${BUILD_ARGS[@]}"
else
    echo "Building ($BUILD_CONFIG)..."
    "$CMAKE" "${BUILD_ARGS[@]}"
    if [ "$PLATFORM" = "win" ]; then
        echo "Output: $BUILD_DIR/lib/$BUILD_CONFIG/DazScriptServer.dll (copy to plugins/DazScriptServer/ in DAZ Studio folder)"
    else
        echo "Output: $BUILD_DIR/lib/DazScriptServer.dylib (copy to plugins/DazScriptServer/ in DAZ Studio folder)"
    fi
fi
