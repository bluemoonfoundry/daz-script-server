#!/usr/bin/env pwsh
# Launch Jupyter notebook for dazpy interactive work.
# Installs required packages if missing.

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Test-PythonPackage {
    param([string]$Package)
    $result = python -c "import $Package" 2>$null
    return $?
}

Write-Host "==> Checking Python..." -ForegroundColor Cyan
try {
    $pyVersion = python --version 2>&1
    Write-Host "    $pyVersion"
} catch {
    Write-Error "Python not found. Install Python 3.9+ and ensure it is on PATH."
    exit 1
}

Write-Host "==> Installing/verifying dazpy SDK (editable)..." -ForegroundColor Cyan
pip install -e . --quiet
if (-not $?) { Write-Error "Failed to install dazpy"; exit 1 }

Write-Host "==> Checking for Jupyter..." -ForegroundColor Cyan
if (-not (Test-PythonPackage "jupyter_server")) {
    Write-Host "    Installing notebook..." -ForegroundColor Yellow
    pip install notebook --quiet
    if (-not $?) { Write-Error "Failed to install notebook"; exit 1 }
} else {
    Write-Host "    Jupyter already installed."
}

$notebooksDir = Join-Path $PSScriptRoot "notebooks"
if (-not (Test-Path $notebooksDir)) {
    New-Item -ItemType Directory -Path $notebooksDir | Out-Null
    Write-Host "==> Created notebooks/ directory."
}

Write-Host ""
Write-Host "==> Starting Jupyter Notebook..." -ForegroundColor Green
Write-Host "    DAZ Studio must be running with the DazScriptServer plugin active."
Write-Host "    Default server: http://127.0.0.1:18811"
Write-Host ""

jupyter notebook --notebook-dir="$notebooksDir"
