<#
Start backend for the AI Gym Coach project (Windows PowerShell)

Usage:
  - Edit the `GROQ_API_KEY` line below or set the env var in your session.
  - Run: `./start_backend.ps1` (you may need to unblock the script: `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`)

What it does:
  1. Creates/uses current Python environment's pip to install `requirements.txt` if packages are missing.
  2. Ensures `.env` is loaded by `python-dotenv` (server.py uses it).
  3. Starts the FastAPI app via `python server.py` (server.py already launches uvicorn).
#>

set -e

Write-Host "Checking Python..."
$python = (Get-Command python -ErrorAction SilentlyContinue)
if (-not $python) {
    Write-Error "Python not found in PATH. Please install Python 3.10+ and add it to PATH."
    exit 1
}

Write-Host "Installing required Python packages (if not already installed)..."
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

# Optionally set GROQ_API_KEY here, or export it in your environment before running this script.
# Replace the placeholder or comment out the line to use your existing environment variable.
$env:GROQ_API_KEY = "YOUR_GROQ_API_KEY_HERE"

Write-Host "Starting FastAPI backend (uvicorn via server.py)..."
python server.py
