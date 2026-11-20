#!/usr/bin/env python3
"""Fail if the daz-ts version is not the same everywhere it is written.

daz-ts versions independently of the plugin and dazpy (see
scripts/check_version_consistency.py for those). daz-ts/package.json is the
source of truth; package-lock.json must agree with it.

    python scripts/check_daz_ts_version.py                       # CI: files agree
    python scripts/check_daz_ts_version.py --tag daz-ts-v0.1.0   # publish: tag too

The --tag check matters because npm versions are immutable: the publish
workflow skips a version that is already on the registry, so a tag pushed
without a package.json bump would "succeed" while publishing nothing.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG_DIR = ROOT / "daz-ts"
TAG_PREFIX = "daz-ts-v"


def load(name: str) -> dict:
    return json.loads((PKG_DIR / name).read_text(encoding="utf-8"))


def check(tag: str | None) -> list[str]:
    pkg = load("package.json")
    lock = load("package-lock.json")
    name, version = pkg.get("name"), pkg.get("version")
    if not version:
        return ["daz-ts/package.json: no version"]

    found = {
        "package-lock.json version": lock.get("version"),
        'package-lock.json packages[""].version':
            lock.get("packages", {}).get("", {}).get("version"),
    }
    errors = [
        f"{where}: {value!r} (expected {version!r})"
        for where, value in found.items()
        if value != version
    ]
    for where, value in (
        ("package-lock.json name", lock.get("name")),
        ('package-lock.json packages[""].name', lock.get("packages", {}).get("", {}).get("name")),
    ):
        if value != name:
            errors.append(f"{where}: {value!r} (expected {name!r})")

    if tag is not None:
        if not tag.startswith(TAG_PREFIX):
            errors.append(f"tag {tag!r} does not start with {TAG_PREFIX!r}")
        elif tag[len(TAG_PREFIX):] != version:
            errors.append(f"tag {tag!r}: {tag[len(TAG_PREFIX):]!r} (expected {version!r})")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tag", help=f"publish tag to check, e.g. {TAG_PREFIX}0.1.0")
    args = parser.parse_args(argv)

    version = load("package.json").get("version")
    errors = check(args.tag)
    if errors:
        print(f"daz-ts version {version} (daz-ts/package.json) is inconsistent:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print(f"daz-ts version {version} is consistent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
