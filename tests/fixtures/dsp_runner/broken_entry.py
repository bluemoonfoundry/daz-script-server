"""Fixture entry point for test_dsp_runner.py: deliberately raises."""


def run(inputs):
    raise RuntimeError("boom: this is a deliberate test failure")
