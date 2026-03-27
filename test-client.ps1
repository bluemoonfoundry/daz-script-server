# DazScriptServer PowerShell Client Example
#
# This example demonstrates how to connect to DazScriptServer from PowerShell.
# Works with PowerShell 5.1+ on Windows, PowerShell Core 6+ on Windows/macOS/Linux.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File test-client.ps1
#   # Or on PowerShell Core:
#   pwsh test-client.ps1

# Server configuration
$ServerUrl = "http://127.0.0.1:18811"
$TokenPath = Join-Path $env:HOME ".daz3d/dazscriptserver_token.txt"

# Function to read API token
function Get-ApiToken {
    if (-not (Test-Path $TokenPath)) {
        Write-Host "Error: Token file not found at $TokenPath" -ForegroundColor Red
        Write-Host "Make sure DazScriptServer has been started at least once to generate the token." -ForegroundColor Yellow
        exit 1
    }

    try {
        $token = Get-Content $TokenPath -Raw
        return $token.Trim()
    }
    catch {
        Write-Host "Error reading token: $_" -ForegroundColor Red
        exit 1
    }
}

# Function to check server status
function Get-ServerStatus {
    try {
        $response = Invoke-RestMethod -Uri "$ServerUrl/status" -Method Get
        Write-Host "Server Status:" -ForegroundColor Green
        Write-Host ($response | ConvertTo-Json -Depth 10)
        return $response.running
    }
    catch {
        Write-Host "Error connecting to server: $_" -ForegroundColor Red
        Write-Host "Make sure DazScriptServer is running in DAZ Studio." -ForegroundColor Yellow
        return $false
    }
}

# Function to check server health
function Get-ServerHealth {
    try {
        $response = Invoke-RestMethod -Uri "$ServerUrl/health" -Method Get
        Write-Host "`nServer Health:" -ForegroundColor Green
        Write-Host ($response | ConvertTo-Json -Depth 10)
    }
    catch {
        Write-Host "Error getting health: $_" -ForegroundColor Red
    }
}

# Function to execute a DazScript
function Invoke-DazScript {
    param(
        [Parameter(Mandatory=$true)]
        [string]$Token,

        [Parameter(Mandatory=$true)]
        [string]$Script,

        [Parameter(Mandatory=$false)]
        [hashtable]$Arguments = @{}
    )

    $headers = @{
        "Content-Type" = "application/json"
        "X-API-Token" = $Token
    }

    $body = @{
        script = $Script
        args = $Arguments
    } | ConvertTo-Json -Depth 10

    try {
        $response = Invoke-RestMethod -Uri "$ServerUrl/execute" -Method Post -Headers $headers -Body $body
        return $response
    }
    catch {
        $statusCode = $_.Exception.Response.StatusCode.value__
        Write-Host "HTTP $statusCode Error: $_" -ForegroundColor Red

        # Try to parse error response
        try {
            $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
            $errorBody = $reader.ReadToEnd() | ConvertFrom-Json
            Write-Host "Server Error: $($errorBody.error)" -ForegroundColor Red
        }
        catch {
            # Ignore parsing errors
        }

        return $null
    }
}

# Main script
Write-Host "=== DazScriptServer PowerShell Client Example ===`n" -ForegroundColor Cyan

# Check if server is running
$isRunning = Get-ServerStatus
if (-not $isRunning) {
    exit 1
}

# Check server health
Get-ServerHealth

# Read API token
$token = Get-ApiToken
$tokenPreview = $token.Substring(0, 8) + "..." + $token.Substring($token.Length - 8)
Write-Host "`nAPI Token: $tokenPreview" -ForegroundColor Cyan

# Example 1: Simple script
Write-Host "`n--- Example 1: Simple Script ---" -ForegroundColor Yellow
$result = Invoke-DazScript -Token $token -Script 'return "Hello from DazScript!";'
if ($result) {
    Write-Host "Success: $($result.success)"
    Write-Host "Result: $($result.result)"
    Write-Host "Request ID: $($result.request_id)"
}

# Example 2: Script with arguments
Write-Host "`n--- Example 2: Script with Arguments ---" -ForegroundColor Yellow
$script = @"
var args = getArguments()[0];
var message = args.message || "default";
var count = args.count || 1;
return message + " (x" + count + ")";
"@

$result = Invoke-DazScript -Token $token -Script $script -Arguments @{
    message = "PowerShell calling DAZ"
    count = 5
}
if ($result) {
    Write-Host "Success: $($result.success)"
    Write-Host "Result: $($result.result)"
}

# Example 3: Get scene information
Write-Host "`n--- Example 3: Get Scene Info ---" -ForegroundColor Yellow
$script = @"
var scene = Scene.getPrimarySelection();
if (scene) {
    return {
        name: scene.name,
        type: scene.className(),
        visible: scene.isVisible()
    };
} else {
    return "No selection";
}
"@

$result = Invoke-DazScript -Token $token -Script $script
if ($result) {
    Write-Host "Success: $($result.success)"
    Write-Host "Result:"
    Write-Host ($result.result | ConvertTo-Json -Depth 10)
}

# Example 4: Script with output (print statements)
Write-Host "`n--- Example 4: Script with Output ---" -ForegroundColor Yellow
$script = @"
print("Starting calculation...");
var sum = 0;
for (var i = 1; i <= 5; i++) {
    sum += i;
    print("Step " + i + ": sum = " + sum);
}
print("Calculation complete!");
return sum;
"@

$result = Invoke-DazScript -Token $token -Script $script
if ($result) {
    Write-Host "Success: $($result.success)"
    Write-Host "Result: $($result.result)"
    Write-Host "Output:"
    $result.output | ForEach-Object { Write-Host "  $_" }
}

# Example 5: Error handling
Write-Host "`n--- Example 5: Error Handling ---" -ForegroundColor Yellow
$result = Invoke-DazScript -Token $token -Script 'return nonExistentVariable;'
if ($result) {
    Write-Host "Success: $($result.success)"
    if (-not $result.success) {
        Write-Host "Error: $($result.error)" -ForegroundColor Red
    }
}

# Example 6: Using scriptFile instead of inline script
Write-Host "`n--- Example 6: Execute Script File ---" -ForegroundColor Yellow
Write-Host "(This requires a .dsa file path - skipping in this example)"

# Example 7: Rate limiting demonstration
Write-Host "`n--- Example 7: Rate Limiting Test ---" -ForegroundColor Yellow
Write-Host "Sending 15 rapid requests to test rate limiting..."

$successCount = 0
$rateLimitedCount = 0

for ($i = 1; $i -le 15; $i++) {
    Write-Host "Request $i..." -NoNewline

    try {
        $headers = @{
            "Content-Type" = "application/json"
            "X-API-Token" = $token
        }
        $body = @{ script = "return $i;" } | ConvertTo-Json

        $response = Invoke-RestMethod -Uri "$ServerUrl/execute" -Method Post -Headers $headers -Body $body
        Write-Host " OK" -ForegroundColor Green
        $successCount++
    }
    catch {
        $statusCode = $_.Exception.Response.StatusCode.value__
        if ($statusCode -eq 429) {
            Write-Host " RATE LIMITED" -ForegroundColor Yellow
            $rateLimitedCount++
        }
        else {
            Write-Host " ERROR ($statusCode)" -ForegroundColor Red
        }
    }

    # Small delay between requests
    Start-Sleep -Milliseconds 50
}

Write-Host "`nResults:"
Write-Host "  Successful: $successCount" -ForegroundColor Green
Write-Host "  Rate Limited: $rateLimitedCount" -ForegroundColor Yellow
Write-Host "  (Enable rate limiting in DAZ Studio to see 429 responses)"

Write-Host "`n=== All examples completed ===" -ForegroundColor Cyan
