import json, requests


scriptFile = "y:/working/scripting/vangard-script-utils/vangard/scripts/CreateBasicCameraSU.dsa"

r = requests.post("http://127.0.0.1:18811/execute",
                    json={"scriptFile": scriptFile, 
                          "args": {
                              "cam_name": "test_cam",
                              "cam_class": "SCAM",
                              "focus": True
                          }})
print(r.json())
  