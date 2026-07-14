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

python -m pip install --upgrade pyinstaller pyinstaller-hooks-contrib
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller installation failed."
}

python -c "import PySide6, numpy, scipy, librosa, soundfile, reportlab"
if ($LASTEXITCODE -ne 0) {
    throw "Base dependencies are incomplete. Run .\install.ps1 first."
}

if ($AI) {
    python -c "import basic_pitch, tensorflow, torch, demucs; from demucs.api import Separator"
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
    "--collect-data", "librosa",
    "--collect-data", "reportlab",
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
    # Basic Pitch is imported dynamically, so declare the package and model data.
    $BuildArguments += @(
        "--collect-submodules", "basic_pitch",
        "--collect-data", "basic_pitch",
        "--hidden-import", "basic_pitch.inference",
        "--hidden-import", "tensorflow",
        "--hidden-import", "tensorflow.python.saved_model",
        "--hidden-import", "keras",
        "--hidden-import", "pretty_midi",
        "--hidden-import", "mir_eval",
        "--hidden-import", "resampy",
        "--copy-metadata", "basic-pitch",
        "--copy-metadata", "tensorflow",
        "--copy-metadata", "keras",
        "--copy-metadata", "pretty-midi",
        "--copy-metadata", "mir-eval",
        "--copy-metadata", "resampy"
    )

    # Demucs is also optional/dynamic. Collect Demucs itself, but let the
    # official PyInstaller torch hook collect the PyTorch runtime.
    $BuildArguments += @(
        "--collect-submodules", "demucs",
        "--collect-data", "demucs",
        "--hidden-import", "demucs.api",
        "--hidden-import", "demucs.apply",
        "--hidden-import", "demucs.audio",
        "--hidden-import", "demucs.pretrained",
        "--hidden-import", "demucs.repo",
        "--hidden-import", "torch",
        "--hidden-import", "sphn",
        "--copy-metadata", "demucs",
        "--copy-metadata", "torch"
    )

    # These large PyTorch areas are for training, distributed execution,
    # profiling, tests, and export. Bass Catcher only performs local inference.
    $BuildArguments += @(
        "--exclude-module", "torch.testing",
        "--exclude-module", "torch.distributed",
        "--exclude-module", "torch.onnx",
        "--exclude-module", "torch.profiler",
        "--exclude-module", "torch.quantization",
        "--exclude-module", "torch.package",
        "--exclude-module", "torch.utils.benchmark"
    )
}

$BuildArguments += "app\main.py"

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
    Write-Host "Demucs downloads the selected model on first use." -ForegroundColor Yellow
}
