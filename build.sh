#!/usr/bin/env bash
# Build DazScriptServer plugin DLL.
#
# Usage:
#   ./build.sh                  Build only
#   ./build.sh --install        Build and copy DLL to DAZ Studio plugins folder
#
# Required CMake variables (set in CMakeCache or passed via -D):
#   DAZ_SDK_DIR         Path to DAZStudio4.5+ SDK
#
# Optional:
#   DAZ_STUDIO_EXE_DIR  Path to DAZ Studio executable folder (needed for --install)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="$SCRIPT_DIR/build"

# Locate cmake — check PATH first, then known location
if command -v cmake &>/dev/null; then
    CMAKE=cmake
elif [ -f "/x/apps/CMake/bin/cmake.exe" ]; then
    CMAKE="/x/apps/CMake/bin/cmake"
else
    echo "Error: cmake not found. Add it to PATH or install it to X:/apps/CMake." >&2
    exit 1
fi

# Configure if no cache exists yet
if [ ! -f "$BUILD_DIR/CMakeCache.txt" ]; then
    echo "No build cache found — running CMake configure..."
    "$CMAKE" -B "$BUILD_DIR" -S "$SCRIPT_DIR"
fi

if [ "$1" = "--install" ]; then
    echo "Building and installing to DAZ Studio plugins folder..."
    "$CMAKE" -B "$BUILD_DIR" -S "$SCRIPT_DIR" -DINSTALL_TO_DAZ=ON
    "$CMAKE" --build "$BUILD_DIR" --config Release
else
    echo "Building..."
    "$CMAKE" --build "$BUILD_DIR" --config Release
    echo "Output: $BUILD_DIR/lib/Release/DazScriptServer.dll"
fi
