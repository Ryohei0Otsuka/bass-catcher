param(
    [switch]$AI
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

$Version = python --version 2>&1
if ($Version -notmatch "Python 3\.11") {
    throw "Bass CatcherはPython 3.11環境で実行してください。現在: $Version"
}

python -m pip install --upgrade pip
if ($AI) {
    python -m pip install -r requirements-ai.txt
}
else {
    python -m pip install -r requirements.txt
}

Write-Host ""
Write-Host "INSTALL COMPLETE" -ForegroundColor Green
if ($AI) {
    Write-Host "AI Hybrid + Demucs enabled" -ForegroundColor Magenta
}
