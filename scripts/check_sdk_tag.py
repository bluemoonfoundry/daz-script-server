#!/usr/bin/env python3
"""Verify a built DS6 plugin carries the SDK version tag Daz Studio 6.26+ requires.

Daz Studio 6.26 reads a ``DzPluginSDKVersionTag`` struct (emitted by the SDK's
``DZ_PLUGIN_SDK_VERSION_TAG()`` macro into a ``.dz_sdk`` / ``__TEXT,__dz_sdk``
section) *before* loading a plugin, and rejects plugins without one ("it has no
SDK version tag"). It also only loads plugins whose tagged SDK version falls in
``[DZ_MIN_SDK_VERSION, DZ_SDK_VERSION]`` of the running Studio.

This check fails the build when:
  * the tag is missing (e.g. our custom CPP_PLUGIN_DEFINITION dropped it, or CI
    restored a stale pre-6.26 SDK from cache), or
  * the tagged version does not match the SDK we compiled against.

Usage: check_sdk_tag.py <plugin.dll|plugin.dylib> <sdk-include-dir>
"""

import re
import struct
import sys
from pathlib import Path

MAGIC = b"DzPluginSDKTag"
# struct DzPluginSDKVersionTag { char magic[16]; quint32 layoutVersion;
#                                quint16 major, minor, revision, build; }
TAG_FORMAT = "<16sIHHHH"
TAG_SIZE = struct.calcsize(TAG_FORMAT)  # 28, static_assert'ed by the SDK


def read_sdk_versions(include_dir: Path):
    text = (include_dir / "dzversion.h").read_text(encoding="utf-8", errors="replace")

    def version(prefix):
        parts = []
        for field in ("MAJOR", "MINOR", "REV", "BUILD"):
            m = re.search(rf"#define\s+{prefix}_{field}\s+(\d+)", text)
            if not m:
                sys.exit(f"error: {prefix}_{field} not found in {include_dir / 'dzversion.h'}")
            parts.append(int(m.group(1)))
        return tuple(parts)

    return version("DZ_MIN_SDK_VERSION"), version("DZ_SDK_VERSION")


def find_tags(data: bytes):
    tags = []
    start = 0
    while True:
        idx = data.find(MAGIC + b"\0", start)
        if idx < 0:
            return tags
        chunk = data[idx : idx + TAG_SIZE]
        if len(chunk) == TAG_SIZE:
            magic, layout, *ver = struct.unpack(TAG_FORMAT, chunk)
            if magic.rstrip(b"\0") == MAGIC:
                tags.append((layout, tuple(ver)))
        start = idx + 1


def fmt(v):
    return ".".join(str(x) for x in v)


def main(argv):
    if len(argv) != 3:
        sys.exit(__doc__)
    plugin, include_dir = Path(argv[1]), Path(argv[2])
    min_sdk, sdk = read_sdk_versions(include_dir)
    print(f"SDK at {include_dir}: DZ_SDK_VERSION={fmt(sdk)} DZ_MIN_SDK_VERSION={fmt(min_sdk)}")

    tags = find_tags(plugin.read_bytes())
    if not tags:
        sys.exit(
            f"error: {plugin} has no DzPluginSDKVersionTag. Daz Studio 6.26+ will refuse "
            "to load it ('it has no SDK version tag'). Check that CPP_PLUGIN_DEFINITION "
            "invokes DZ_PLUGIN_SDK_VERSION_TAG() and that the SDK is 6.26.2026.27900 or newer."
        )
    if len(tags) > 1:
        sys.exit(f"error: {plugin} contains {len(tags)} SDK tags; expected exactly one")

    layout, version = tags[0]
    print(f"{plugin}: SDK tag layout={layout} version={fmt(version)}")
    if version != sdk:
        sys.exit(f"error: tag version {fmt(version)} != SDK version {fmt(sdk)}")
    if not (min_sdk <= version <= sdk):
        sys.exit(f"error: tag version {fmt(version)} outside [{fmt(min_sdk)}, {fmt(sdk)}]")
    print("SDK tag OK")


if __name__ == "__main__":
    main(sys.argv)
