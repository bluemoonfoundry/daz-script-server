import sys
import time
import os
import json
from dazpy import DazClient, DazScene, DazRenderSettings

scene  = DazScene()
render = DazRenderSettings()
figure = scene.find_skeleton_by_label("Genesis 9")

smile = figure.find_property_by_label("Smile Full Face")
brow  = figure.find_property_by_label("SO Fear Worry")

render.set_resolution(1920, 1080)

for i, (s, b) in enumerate([(0.0, 0.0), (0.5, 0.3), (1.0, 0.8)]):
    smile.value = s
    brow.value  = b
    render.output_path = f"y:/tmp/variant_{i:03d}.png"
    render.render()

