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

BASE_URL = "http://127.0.0.1:18811"
headers = {"X-API-Token": api_token}

# Example 1: Status endpoint (no auth required)
print("\n--- Example 1: Status ---")
r = requests.get(f"{BASE_URL}/status")
print(f"Status: {r.status_code}")
print(f"Response: {r.json()}")

# Example 2: Health endpoint (no auth required)
print("\n--- Example 2: Health ---")
r = requests.get(f"{BASE_URL}/health")
print(f"Status: {r.status_code}")
print(f"Response: {r.json()}")

# Example 3: Metrics endpoint (no auth required)
print("\n--- Example 3: Metrics ---")
r = requests.get(f"{BASE_URL}/metrics")
print(f"Status: {r.status_code}")
print(f"Response: {r.json()}")

# Example 4: Inline script using print() for output
print("\n--- Example 4: Inline Script (print output) ---")
r = requests.post(f"{BASE_URL}/execute",
                  headers=headers,
                  json={
                      "script": "print('Hello from DazScript!');",
                      "args": {}
                  })
print(f"Status: {r.status_code}")
print(f"Response: {r.json()}")

# Example 5: Inline script returning a value via variable
print("\n--- Example 5: Inline Script (return value) ---")
r = requests.post(f"{BASE_URL}/execute",
                  headers=headers,
                  json={
                      "script": "var result = 1 + 1; result;",
                      "args": {}
                  })
print(f"Status: {r.status_code}")
print(f"Response: {r.json()}")

# Example 6: Inline script using args
print("\n--- Example 6: Inline Script (with args) ---")
r = requests.post(f"{BASE_URL}/execute",
                  headers=headers,
                  json={
                      "script": "var args = getArguments()[0]; print('Hello, ' + args.name + '!');",
                      "args": {"name": "World"}
                  })
print(f"Status: {r.status_code}")
print(f"Response: {r.json()}")

# Example 7: Script file (update path to your script)
print("\n--- Example 7: Script File ---")
scriptFile = "y:/working/scripting/vangard-script-utils/vangard/scripts/CreateBasicCameraSU.dsa"

if os.path.exists(scriptFile):
    r = requests.post(f"{BASE_URL}/execute",
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

# Example 8: Auth failure test
print("\n--- Example 8: Auth Failure ---")
r = requests.post(f"{BASE_URL}/execute",
                  headers={"X-API-Token": "invalid-token"},
                  json={"script": "print('should not run');", "args": {}})
print(f"Status: {r.status_code}")
print(f"Response: {r.json()}")
