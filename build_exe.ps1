param(
    [ValidateSet("onedir", "onefile")]
    [string]$Mode = "onedir",

    [switch]$AI
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

$Version = python --version 2>&1
if ($Version -notmatch "Python 3\.11") {
    throw "Bass CatcherはPython 3.11環境でビルドしてください。現在: $Version"
}

python -m pip install --upgrade pyinstaller

$Arguments = @(
    "--noconfirm",
    "--clean",
    "--windowed",
    "--name", "BassCatcher",
    "--paths", ".",
    "--icon", "assets\bass_catcher.ico",
    "--add-data", "assets;assets",
    "--collect-all", "librosa",
    "--collect-all", "soundfile",
    "--collect-all", "reportlab"
)

if ($Mode -eq "onefile") {
    $Arguments += "--onefile"
}
else {
    $Arguments += "--onedir"
}

if ($AI) {
    $Arguments += @(
        "--collect-all", "basic_pitch",
        "--collect-all", "onnxruntime",
        "--collect-all", "demucs",
        "--collect-all", "torch",
        "--collect-all", "torchaudio"
    )
}

$Arguments += "app\main.py"

python -m PyInstaller @Arguments
if ($LASTEXITCODE -ne 0) {
    throw "EXEビルドに失敗しました。"
}

Write-Host ""
Write-Host "BUILD COMPLETE" -ForegroundColor Green
if ($Mode -eq "onefile") {
    Write-Host "dist\BassCatcher.exe"
}
else {
    Write-Host "dist\BassCatcher\BassCatcher.exe"
}
if ($AI) {
    Write-Host "AI build is very large because model runtimes are bundled." -ForegroundColor Yellow
}
