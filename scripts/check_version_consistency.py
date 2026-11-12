#!/usr/bin/env python3
"""Fail if the release version is not the same everywhere it is written.

pyproject.toml is the source of truth. Every other place that names the
current version must agree with it, the README must have a "What's New"
section for it (the README is the PyPI project description, and PyPI
can't update an already-published version's page), and CHANGELOG.md's newest
entry must be for it.

    python scripts/check_version_consistency.py              # CI: files agree
    python scripts/check_version_consistency.py --tag v2.10.1  # release: tag too

The --tag check matters because the PyPI publish step uses skip-existing:
a tag pushed without a version bump would otherwise "succeed" while PyPI
keeps serving the previous upload and its README.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def find(rel: str, pattern: str) -> str | None:
    m = re.search(pattern, read(rel), re.MULTILINE)
    return m.group(1) if m else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tag", help="release tag to check, e.g. v2.10.1")
    args = parser.parse_args()

    version = find("pyproject.toml", r'^version\s*=\s*"([^"]+)"')
    if not version:
        print("pyproject.toml: no [project] version found")
        return 1

    header = read("include/common_version.h")
    parts = [
        re.search(rf"#define DZSRV_{k}\s+(\d+)", header)
        for k in ("MAJOR", "MINOR", "REV")
    ]
    header_triplet = ".".join(m.group(1) for m in parts) if all(parts) else None

    found = {
        "dazpy/__init__.py __version__":
            find("dazpy/__init__.py", r'^__version__\s*=\s*"([^"]+)"'),
        "docs/conf.py release": find("docs/conf.py", r'^release\s*=\s*"([^"]+)"'),
        "include/common_version.h DZSRV_VERSION_STR":
            find("include/common_version.h", r'DZSRV_VERSION_STR\s+"([^"]+)"'),
        "include/common_version.h MAJOR.MINOR.REV": header_triplet,
        "openapi.yaml info.version": find("openapi.yaml", r"^  version:\s*([\w.\-]+)"),
        "README.md version badge": find("README.md", r"\*\*Version ([^*]+)\*\*"),
        "CHANGELOG.md newest entry": find("CHANGELOG.md", r"^## \[(\d[^\]]*)\]"),
    }
    if args.tag:
        found["release tag"] = args.tag[1:] if args.tag.startswith("v") else args.tag

    errors = [
        f"{where}: {value!r} (expected {version!r})"
        for where, value in found.items()
        if value != version
    ]

    whats_new = re.findall(r"^## What's New in v([^\n]+)$", read("README.md"), re.MULTILINE)
    # A heading may cover a range, e.g. "v2.9.1 – v2.9.3"; the newest must name this version.
    if not whats_new or f"v{version}" not in f"v{whats_new[0]}":
        newest = whats_new[0] if whats_new else "none"
        errors.append(
            f"README.md: newest \"What's New\" section is v{newest}, "
            f"expected one for v{version}"
        )

    if errors:
        print(f"Version {version} (pyproject.toml) is inconsistent:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print(f"Version {version} is consistent across {len(found) + 2} locations.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
