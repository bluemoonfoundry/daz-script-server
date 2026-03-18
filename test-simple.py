import json
import requests
import os

# Read API token from token file
token_file = os.path.expanduser("~/.daz3d/dazscriptserver_token.txt")
api_token = ""

if os.path.exists(token_file):
    with open(token_file, 'r') as f:
        api_token = f.read().strip()
    print(f"Loaded API token from {token_file}")
else:
    print(f"Warning: Token file not found at {token_file}")
    print("If authentication is enabled, this request will fail.")

# Set up headers with authentication
headers = {
    "X-API-Token": api_token
}

# Example 1: Execute an inline script
print("\n--- Example 1: Inline Script ---")
r = requests.post("http://127.0.0.1:18811/execute",
                  headers=headers,
                  json={
                      "script": "return 'Hello from DazScript!';",
                      "args": {}
                  })
print(f"Status: {r.status_code}")
print(f"Response: {r.json()}")

# Example 2: Execute a script file (update path to your script)
print("\n--- Example 2: Script File ---")
scriptFile = "y:/working/scripting/vangard-script-utils/vangard/scripts/CreateBasicCameraSU.dsa"

if os.path.exists(scriptFile):
    r = requests.post("http://127.0.0.1:18811/execute",
                      headers=headers,
                      json={
                          "scriptFile": scriptFile,
                          "args": {
                              "cam_name": "test_cam",
                              "cam_class": "SCAM",
                              "focus": True
                          }
                      })
    print(f"Status: {r.status_code}")
    print(f"Response: {r.json()}")
else:
    print(f"Skipping - script file not found: {scriptFile}")

# Example 3: Test authentication failure (uncomment to test)
# print("\n--- Example 3: Auth Failure Test ---")
# r = requests.post("http://127.0.0.1:18811/execute",
#                   headers={"X-API-Token": "invalid-token"},
#                   json={"script": "return 1+1;", "args": {}})
# print(f"Status: {r.status_code}")
# print(f"Response: {r.json()}")
  