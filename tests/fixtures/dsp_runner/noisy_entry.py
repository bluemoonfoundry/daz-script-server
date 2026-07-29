"""Fixture entry point for test_dsp_runner.py: exercises stdout capture."""


def run(inputs):
    print("noisy: starting")
    print("noisy: about to return", inputs.get("value"))
    return inputs.get("value")
