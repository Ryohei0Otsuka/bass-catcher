param(
    [ValidateSet("onedir", "onefile")]
    [string]$Mode = "onedir",

    [switch]$AI
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

Write-Host ""
Write-Host "BASS CATCHER WINDOWS BUILD" -ForegroundColor Cyan
Write-Host "Project: $ProjectRoot"
Write-Host "Mode: $Mode"
Write-Host "AI: $AI"
Write-Host ""

$PythonVersion = python --version 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "Python was not found. Activate the Bass Catcher virtual environment."
}

if ($PythonVersion -notmatch "Python 3\.11") {
    throw "Python 3.11 is required. Current runtime: $PythonVersion"
}

if (-not (Test-Path "app\main.py")) {
    throw "app\main.py was not found."
}

if (-not (Test-Path "assets\bass_catcher.ico")) {
    throw "assets\bass_catcher.ico was not found."
}

Write-Host "Installing or updating PyInstaller..." -ForegroundColor Cyan
python -m pip install --upgrade pyinstaller
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller installation failed."
}

Write-Host "Checking required modules..." -ForegroundColor Cyan
python -c "import PySide6, numpy, scipy, librosa, soundfile, reportlab"
if ($LASTEXITCODE -ne 0) {
    throw "Base dependencies are incomplete. Run .\install.ps1 first."
}

if ($AI) {
    python -c "import basic_pitch, tensorflow, torch, demucs"
    if ($LASTEXITCODE -ne 0) {
        throw "AI dependencies are incomplete. Run .\install.ps1 -AI first."
    }
}

$BuildArguments = @(
    "--noconfirm",
    "--clean",
    "--windowed",
    "--noupx",
    "--name", "BassCatcher",
    "--paths", ".",
    "--icon", "assets\bass_catcher.ico",
    "--add-data", "assets;assets",
    "--collect-all", "librosa",
    "--collect-all", "soundfile",
    "--collect-all", "reportlab",
    "--copy-metadata", "librosa",
    "--copy-metadata", "soundfile",
    "--copy-metadata", "reportlab"
)

if ($Mode -eq "onefile") {
    $BuildArguments += "--onefile"
}
else {
    $BuildArguments += "--onedir"
}

if ($AI) {
    $BuildArguments += @(
        "--collect-all", "basic_pitch",
        "--collect-all", "tensorflow",
        "--collect-all", "keras",
        "--collect-all", "demucs",
        "--collect-all", "torch",
        "--collect-all", "pretty_midi",
        "--collect-all", "mir_eval",
        "--collect-all", "resampy",
        "--collect-all", "sphn",
        "--copy-metadata", "basic-pitch",
        "--copy-metadata", "tensorflow",
        "--copy-metadata", "keras",
        "--copy-metadata", "demucs",
        "--copy-metadata", "torch",
        "--copy-metadata", "pretty-midi",
        "--copy-metadata", "mir-eval",
        "--copy-metadata", "resampy"
    )
}

$BuildArguments += "app\main.py"

Write-Host ""
Write-Host "Starting PyInstaller..." -ForegroundColor Cyan
python -m PyInstaller @BuildArguments

if ($LASTEXITCODE -ne 0) {
    throw "EXE build failed."
}

Write-Host ""
Write-Host "BUILD COMPLETE" -ForegroundColor Green

if ($Mode -eq "onefile") {
    Write-Host "Output: dist\BassCatcher.exe" -ForegroundColor Green
}
else {
    Write-Host "Output: dist\BassCatcher\BassCatcher.exe" -ForegroundColor Green
}

if ($AI) {
    Write-Host "AI build includes TensorFlow and PyTorch and will be very large." -ForegroundColor Yellow
    Write-Host "Demucs may download its separation model on first use." -ForegroundColor Yellow
}
