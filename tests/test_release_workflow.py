"""
release-tagged.yml job ordering (daz-script-server-yau7.7.1).

A PyPI upload can't be undone, so publish-pypi must run only after every
build job has passed and the GitHub release exists. Otherwise a failed
Windows/macOS build would still ship dazpy to PyPI with no matching release.
"""
from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "release-tagged.yml"


def _jobs():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]


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
    jobs = _jobs()
    builds = {n for n in jobs if n.startswith("build-")}
    assert builds, "no build-* jobs found"
    missing = builds - _ancestors(jobs, "publish-pypi")
    assert not missing, f"publish-pypi can run before: {sorted(missing)}"


def test_publish_pypi_waits_for_version_check_and_release():
    ancestors = _ancestors(_jobs(), "publish-pypi")
    assert {"check-version", "create-release"} <= ancestors


def test_create_release_does_not_depend_on_publish():
    # The irreversible step goes last; the reverse edge would be a cycle anyway.
    assert "publish-pypi" not in _ancestors(_jobs(), "create-release")
