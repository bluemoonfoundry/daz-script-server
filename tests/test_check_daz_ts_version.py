"""Unit tests for scripts/check_daz_ts_version.py (no server needed)."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_daz_ts_version.py"
spec = importlib.util.spec_from_file_location("check_daz_ts_version", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

NAME = "@bluemoonfoundry/daz-ts"


@pytest.fixture
def pkg_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "PKG_DIR", tmp_path)
    return tmp_path


def write(pkg_dir: Path, version="0.2.0", lock_version="0.2.0", lock_name=NAME):
    (pkg_dir / "package.json").write_text(json.dumps({"name": NAME, "version": version}))
    (pkg_dir / "package-lock.json").write_text(json.dumps({
        "name": lock_name,
        "version": lock_version,
        "packages": {"": {"name": lock_name, "version": lock_version}},
    }))


def test_consistent_without_tag(pkg_dir):
    write(pkg_dir)
    assert mod.check(None) == []
    assert mod.main([]) == 0


def test_matching_tag(pkg_dir):
    write(pkg_dir)
    assert mod.check("daz-ts-v0.2.0") == []


def test_tag_version_mismatch(pkg_dir):
    write(pkg_dir)
    errors = mod.check("daz-ts-v0.2.1")
    assert len(errors) == 1 and "0.2.1" in errors[0]
    assert mod.main(["--tag", "daz-ts-v0.2.1"]) == 1


def test_plugin_tag_rejected(pkg_dir):
    write(pkg_dir)
    errors = mod.check("v0.2.0")
    assert errors and "daz-ts-v" in errors[0]


def test_stale_lockfile_version(pkg_dir):
    write(pkg_dir, lock_version="0.1.0")
    assert len(mod.check(None)) == 2


def test_stale_lockfile_name(pkg_dir):
    write(pkg_dir, lock_name="daz-ts")
    assert len(mod.check(None)) == 2


def test_repo_files_are_consistent():
    """The real daz-ts/package.json and lockfile agree."""
    assert mod.check(None) == []
