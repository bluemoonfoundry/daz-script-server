"""
Release workflow guards.

Job ordering (daz-script-server-yau7.7.1): a PyPI upload can't be undone, so
publish-pypi must run only after every build job has passed and the GitHub
release exists. Otherwise a failed Windows/macOS build would still ship dazpy
to PyPI with no matching release.

Token permissions (daz-script-server-yau7.7.2): every workflow defaults to
read-only, and write scopes appear only on the jobs that publish, so build and
CI jobs (including reusable workflows called from a release) can't write.
"""
from pathlib import Path

import yaml

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"
WORKFLOW = WORKFLOWS / "release-tagged.yml"

# Jobs allowed write scopes, and exactly which ones.
JOB_WRITE_SCOPES = {
    ("release-tagged.yml", "publish-pypi"): {"id-token"},
    ("release-tagged.yml", "create-release"): {"contents"},
    ("release-nightly.yml", "create-nightly-release"): {"contents"},
    ("publish-daz-ts.yml", "publish-npm"): {"id-token"},
    ("publish-daz-ts.yml", "github-release"): {"contents"},
}
# docs.yml deploys GitHub Pages from its only job, so its workflow-level block
# carries the Pages scopes.
WORKFLOW_WRITE_SCOPES = {"docs.yml": {"pages", "id-token"}}


def _load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _jobs():
    return _load(WORKFLOW)["jobs"]


def _write_scopes(perms):
    assert isinstance(perms, dict), f"permissions must be a mapping, got {perms!r}"
    return {scope for scope, level in perms.items() if level == "write"}


def _needs(job):
    needs = job.get("needs", [])
    return [needs] if isinstance(needs, str) else list(needs)


def _ancestors(jobs, name):
    seen, stack = set(), _needs(jobs[name])
    while stack:
        dep = stack.pop()
        if dep not in seen:
            seen.add(dep)
            stack.extend(_needs(jobs[dep]))
    return seen


def test_publish_pypi_waits_for_every_build_job():
    # The builds live in build-all.yml (S2); release-tagged calls it as one
    # `build` job with the defaults, which run every platform and SDK.
    jobs = _jobs()
    assert jobs["build"]["uses"] == "./.github/workflows/build-all.yml"
    assert "with" not in jobs["build"], "release must build everything (no filters)"
    assert "build" in _ancestors(jobs, "publish-pypi")

    build_all = _load(WORKFLOWS / "build-all.yml")
    trigger = build_all.get("on", build_all.get(True))  # PyYAML reads bare `on` as True
    inputs = trigger["workflow_call"]["inputs"]
    assert inputs["platform"]["default"] == "all"
    assert inputs["sdk-version"]["default"] == "both"
    builds = {n for n in build_all["jobs"] if n.startswith("build-")}
    assert len(builds) == 7, sorted(builds)
    # The summary fails the call when any requested build failed.
    assert set(_needs(build_all["jobs"]["summary"])) == builds


def test_release_workflows_share_build_all():
    for name in ("release-tagged.yml", "release-nightly.yml", "test-build.yml"):
        jobs = _load(WORKFLOWS / name)["jobs"]
        uses = {j.get("uses") for j in jobs.values()}
        assert "./.github/workflows/build-all.yml" in uses, name
        assert not {u for u in uses if u and u.endswith(("build-windows.yml", "build-macos.yml"))}, \
            f"{name} calls a platform build directly; go through build-all.yml"


def test_publish_pypi_waits_for_version_check_and_release():
    ancestors = _ancestors(_jobs(), "publish-pypi")
    assert {"check-version", "create-release"} <= ancestors


def test_create_release_does_not_depend_on_publish():
    # The irreversible step goes last; the reverse edge would be a cycle anyway.
    assert "publish-pypi" not in _ancestors(_jobs(), "create-release")


def _workflow_files():
    files = sorted(WORKFLOWS.glob("*.yml"))
    assert files
    return files


def test_every_workflow_declares_top_level_permissions():
    missing = [f.name for f in _workflow_files() if "permissions" not in _load(f)]
    assert not missing, f"no top-level permissions block (inherits repo default): {missing}"


def test_top_level_permissions_are_read_only():
    for f in _workflow_files():
        writes = _write_scopes(_load(f)["permissions"])
        assert writes == WORKFLOW_WRITE_SCOPES.get(f.name, set()), f"{f.name}: {sorted(writes)}"


def test_write_scopes_only_on_publishing_jobs():
    for f in _workflow_files():
        for name, job in _load(f)["jobs"].items():
            writes = _write_scopes(job["permissions"]) if "permissions" in job else set()
            expected = JOB_WRITE_SCOPES.get((f.name, name), set())
            assert writes == expected, f"{f.name}:{name} writes {sorted(writes)}, expected {sorted(expected)}"


def test_workflow_yaml_has_no_duplicate_keys():
    # GitHub rejects a workflow with a repeated mapping key; PyYAML keeps the
    # last one silently, so check explicitly.
    class Strict(yaml.SafeLoader):
        pass

    def mapping(loader, node, deep=False):
        keys = [loader.construct_object(k, deep=deep) for k, _ in node.value]
        dups = {k for k in keys if keys.count(k) > 1}
        assert not dups, f"duplicate keys {sorted(map(str, dups))} at line {node.start_mark.line + 1}"
        return yaml.SafeLoader.construct_mapping(loader, node, deep)

    Strict.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
    actions = WORKFLOWS.parent / "actions"
    for path in sorted(WORKFLOWS.glob("*.yml")) + sorted(actions.glob("*/action.yml")):
        yaml.load(path.read_text(encoding="utf-8"), Loader=Strict)
