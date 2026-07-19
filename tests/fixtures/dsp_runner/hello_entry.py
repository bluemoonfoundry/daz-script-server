"""Fixture entry point for test_dsp_runner.py."""


def run(inputs):
    return f"Hello, {inputs.get('name', 'world')}!"
